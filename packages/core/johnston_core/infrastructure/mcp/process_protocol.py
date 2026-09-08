"""MCP protocol operations for stdio process client."""

import asyncio
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from johnston_core.domain.defaults.errors import format_tool_error
from johnston_core.infrastructure.mcp.base import (
    CLIENT_NAME,
    CLIENT_VERSION,
    DEFAULT_TOOLS_CALL_TIMEOUT,
    MCP_PROTOCOL_VERSION,
    _config_init_timeout,
)


class MCPProcessProtocolMixin:
    """High-level MCP JSON-RPC protocol methods (init, list, call) for stdio clients."""

    name: str
    process: Optional[Any]
    tools: List[Dict[str, Any]]
    resources: List[Dict[str, Any]]
    prompts: List[Dict[str, Any]]
    server_capabilities: Dict[str, Any]
    last_error: Optional[str]
    _lock: threading.RLock
    _call_lock: asyncio.Lock
    _pending_futures: Dict[int, asyncio.Future]
    _tools_fetch_time: float

    # ── Sync tools/resources/prompts/init (stdio-only) ─────────────────────

    def _initialize(self) -> bool:
        current_id = self._next_req_id()
        init_req = {
            "jsonrpc": "2.0",
            "id": current_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "roots": {"listChanged": True},
                },
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
        self._send(init_req)
        res = self._read_response(req_id=current_id, timeout=_config_init_timeout())
        if not res:
            self.last_error = "Server did not respond to initialize request (timeout)"
            return False
        if "error" in res:
            err_msg = (
                res["error"].get("message", str(res["error"])) if isinstance(res["error"], dict) else str(res["error"])
            )
            self.last_error = f"MCP init error: {err_msg}"
            return False

        self.server_capabilities = res.get("result", {}).get("capabilities", {})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.fetch_tools()
        if "resources" in self.server_capabilities:
            self.fetch_resources()
        if "prompts" in self.server_capabilities:
            self.fetch_prompts()
        return True

    def fetch_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            current_id = self._next_req_id()
            req = {"jsonrpc": "2.0", "id": current_id, "method": "tools/list"}
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=_config_init_timeout())
            if res and "result" in res:
                self.tools = res["result"].get("tools", [])
                self._tools_fetch_time = time.monotonic()
            return self.tools

    def fetch_resources(self) -> List[Dict[str, Any]]:
        with self._lock:
            current_id = self._next_req_id()
            req = {"jsonrpc": "2.0", "id": current_id, "method": "resources/list"}
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=_config_init_timeout())
            if res and "result" in res:
                self.resources = res["result"].get("resources", [])
            return self.resources

    def fetch_prompts(self) -> List[Dict[str, Any]]:
        with self._lock:
            current_id = self._next_req_id()
            req = {"jsonrpc": "2.0", "id": current_id, "method": "prompts/list"}
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=_config_init_timeout())
            if res and "result" in res:
                self.prompts = res["result"].get("prompts", [])
            return self.prompts

    # ── Tool call (stdio transport) ────────────────────────────────────────

    def _build_call_payload(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Helper to create JSON-RPC tool call payload with incremented request id."""
        current_id = self._next_req_id()
        req = {
            "jsonrpc": "2.0",
            "id": current_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        return current_id, req

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                if not self.start():
                    return format_tool_error(
                        "mcp", detail=f"MCP server '{self.name}' process is not running", name=tool_name
                    )

            current_id, req = self._build_call_payload(tool_name, arguments)
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=timeout or DEFAULT_TOOLS_CALL_TIMEOUT)
            return self._parse_tool_response(tool_name, res)

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self.call_tool(tool_name, arguments, timeout=timeout)

        if not self.process or self.process.poll() is not None:
            if not await self.start_async():
                return format_tool_error(
                    "mcp", detail=f"MCP server '{self.name}' process is not running", name=tool_name
                )

        self._start_async_reader()
        async with self._call_lock:
            current_id, req = self._build_call_payload(tool_name, arguments)

            fut = loop.create_future()
            self._pending_futures[current_id] = fut

            try:
                await self._send_async(req)
            except asyncio.CancelledError:
                # Dropped while the write was in flight: remove the pending
                # future so a cancelled call can never leave a dangling entry
                # (the outer finally only covers the read phase).
                self._pending_futures.pop(current_id, None)
                fut.cancel()
                raise
            except Exception as e:
                self._pending_futures.pop(current_id, None)
                return format_tool_error(
                    "mcp", detail=f"failed to write to MCP server '{self.name}': {e}", name=tool_name
                )

        try:
            effective_timeout = timeout if timeout is not None else DEFAULT_TOOLS_CALL_TIMEOUT
            res = await asyncio.wait_for(asyncio.shield(fut), timeout=effective_timeout)
        except asyncio.TimeoutError:
            return format_tool_error("mcp", detail=f"No response from MCP server '{self.name}'", name=tool_name)
        except asyncio.CancelledError:
            raise
        except RuntimeError as e:
            # Server stopped while we awaited; surface gracefully instead of crashing.
            return format_tool_error("mcp", detail=str(e), name=tool_name)
        except Exception as e:
            return format_tool_error("mcp", detail=str(e), name=tool_name)
        finally:
            self._pending_futures.pop(current_id, None)

        return self._parse_tool_response(tool_name, res)
