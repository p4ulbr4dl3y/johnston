"""
Shared base for MCP JSON-RPC 2.0 clients (stdio and SSE transports).
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from core.domain.defaults.config import DEFAULT_MCP_CALL_TIMEOUT, DEFAULT_MCP_INIT_TIMEOUT
from core.domain.defaults.errors import format_tool_error

logger = logging.getLogger(__name__)

# ── Protocol constants (shared by both transports) ────────────────────────
MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "johnston"
CLIENT_VERSION = "1.0.0"

# Default upper bound for a tools/call round-trip. A hanging server must never
# hold an agent turn forever; both the manager and direct callers get this
# default when no explicit timeout is passed.
DEFAULT_TOOLS_CALL_TIMEOUT = DEFAULT_MCP_CALL_TIMEOUT
INIT_TIMEOUT = DEFAULT_MCP_INIT_TIMEOUT


def _config_init_timeout() -> float:
    """Return the configured MCP init timeout (tools.mcp_init_timeout)."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools.mcp_init_timeout
    except Exception:
        return INIT_TIMEOUT


class MCPClientBase:
    """Abstract base for MCP JSON-RPC 2.0 clients.

    Holds all shared state, constants, and transport-agnostic protocol logic
    (initialize handshake, tools/resources/prompts fetching, tool invocation,
    server request handling, notification dispatch).

    Subclasses must implement only the transport layer:
    ``_send_request_async``, ``_send_notification_async``, ``start``,
    ``start_async``, ``stop``, ``stop_async``.
    """

    def __init__(self, name: str, cwd: Optional[str] = None, env: Optional[Dict[str, Any]] = None) -> None:
        self.name = name
        self.cwd = cwd
        self.env = env
        self.req_id = 0
        self.tools: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []
        self.prompts: List[Dict[str, Any]] = []
        self.server_capabilities: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self._stopped = False
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._call_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._tools_fetch_time = 0.0
        self.on_tools_changed: Optional[Any] = None
        self.on_resources_changed: Optional[Any] = None
        self.on_prompts_changed: Optional[Any] = None

    # ── Request ID generation ─────────────────────────────────────────────

    def _next_req_id(self) -> int:
        self.req_id += 1
        return self.req_id

    # ── Tools freshness check ─────────────────────────────────────────────

    def is_tools_stale(self, ttl: float = 300.0) -> bool:
        if self._tools_fetch_time <= 0.0:
            return True
        return (time.monotonic() - self._tools_fetch_time) >= ttl

    # ── Server request handling (roots/list, ping) ────────────────────────

    async def _handle_server_request_async(self, data: Dict[str, Any]) -> None:
        """Handle an incoming server-initiated JSON-RPC request (roots/list, ping)."""
        req_id = data.get("id")
        method = data.get("method", "")
        if method == "roots/list":
            roots = []
            if self.cwd:
                real_cwd = os.path.realpath(self.cwd)
                roots.append({
                    "uri": f"file://{real_cwd}",
                    "name": os.path.basename(real_cwd) or "workspace",
                })
            await self._send_notification_async({"jsonrpc": "2.0", "id": req_id, "result": {"roots": roots}})
        elif method == "ping":
            await self._send_notification_async({"jsonrpc": "2.0", "id": req_id, "result": {}})
        else:
            await self._send_notification_async({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method {method!r} not found"},
            })

    # ── Notification dispatch helpers ──────────────────────────────────────

    async def _handle_tools_list_changed_async(self) -> None:
        try:
            await self.fetch_tools_async()
            if callable(self.on_tools_changed):
                cb = self.on_tools_changed
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
        except Exception:
            logger.debug("Failed to refresh tools on list_changed notification for '%s'", self.name, exc_info=True)

    async def _handle_resources_list_changed_async(self) -> None:
        try:
            await self.fetch_resources_async()
            if callable(self.on_resources_changed):
                cb = self.on_resources_changed
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
        except Exception:
            logger.debug("Failed to refresh resources on list_changed notification for '%s'", self.name, exc_info=True)

    async def _handle_prompts_list_changed_async(self) -> None:
        try:
            await self.fetch_prompts_async()
            if callable(self.on_prompts_changed):
                cb = self.on_prompts_changed
                if asyncio.iscoroutinefunction(cb):
                    await cb()
                else:
                    cb()
        except Exception:
            logger.debug("Failed to refresh prompts on list_changed notification for '%s'", self.name, exc_info=True)

    def _dispatch_notification_sync(self, method: str) -> None:
        """Handle a server notification in a sync context (used by stdio reader)."""
        if "tools/list_changed" in method:
            try:
                self.fetch_tools()
                if callable(self.on_tools_changed):
                    self.on_tools_changed()
            except Exception:
                logger.debug("Failed to refresh tools on list_changed notification", exc_info=True)
        elif "resources/list_changed" in method:
            try:
                self.fetch_resources()
                if callable(self.on_resources_changed):
                    self.on_resources_changed()
            except Exception:
                logger.debug("Failed to refresh resources on list_changed notification", exc_info=True)
        elif "prompts/list_changed" in method:
            try:
                self.fetch_prompts()
                if callable(self.on_prompts_changed):
                    self.on_prompts_changed()
            except Exception:
                logger.debug("Failed to refresh prompts on list_changed notification", exc_info=True)

    # ── Initialize handshake ───────────────────────────────────────────────

    async def _initialize_async(self) -> bool:
        """Perform the MCP initialize handshake (shared by both transports)."""
        res = await self._send_request_async(
            "initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "roots": {"listChanged": True},
                },
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
            timeout=_config_init_timeout(),
        )
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
        await self._send_notification_async({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await self.fetch_tools_async()
        if "resources" in self.server_capabilities:
            await self.fetch_resources_async()
        if "prompts" in self.server_capabilities:
            await self.fetch_prompts_async()
        return True

    # ── Tools / Resources / Prompts fetching ───────────────────────────────

    async def fetch_tools_async(self) -> List[Dict[str, Any]]:
        res = await self._send_request_async("tools/list", timeout=_config_init_timeout())
        if res and "result" in res:
            self.tools = res["result"].get("tools", [])
            self._tools_fetch_time = time.monotonic()
        return self.tools

    async def fetch_resources_async(self) -> List[Dict[str, Any]]:
        res = await self._send_request_async("resources/list", timeout=_config_init_timeout())
        if res and "result" in res:
            self.resources = res["result"].get("resources", [])
        return self.resources

    async def read_resource_async(self, uri: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        res = await self._send_request_async(
            "resources/read",
            params={"uri": uri},
            timeout=timeout or DEFAULT_TOOLS_CALL_TIMEOUT,
        )
        if res and "result" in res:
            return res["result"]
        return None

    async def fetch_prompts_async(self) -> List[Dict[str, Any]]:
        res = await self._send_request_async("prompts/list", timeout=_config_init_timeout())
        if res and "result" in res:
            self.prompts = res["result"].get("prompts", [])
        return self.prompts

    async def get_prompt_async(
        self, name: str, arguments: Optional[Dict[str, str]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        res = await self._send_request_async(
            "prompts/get",
            params={"name": name, "arguments": arguments or {}},
            timeout=timeout or DEFAULT_TOOLS_CALL_TIMEOUT,
        )
        if res and "result" in res:
            return res["result"]
        return None

    # ── Tool call ──────────────────────────────────────────────────────────

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        effective_timeout = timeout if timeout is not None else DEFAULT_TOOLS_CALL_TIMEOUT
        res = await self._send_request_async(
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            timeout=effective_timeout,
        )
        return self._parse_tool_response(tool_name, res)

    # ── Response / content parsing helpers ─────────────────────────────────

    @staticmethod
    def _format_content(result: Any) -> str:
        """Serialize a tools/call result ``content`` list into one output string."""
        content_items = result.get("content", []) if isinstance(result, dict) else []
        output_parts = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                output_parts.append(item.get("text", ""))
            else:
                output_parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(output_parts).strip()

    def _parse_tool_response(self, tool_name: str, res: Optional[Dict[str, Any]]) -> str:
        """Parse MCP tool call JSON-RPC response or error dict into string output.

        Every failure path returns an ``ERR:``-prefixed string so upper layers
        (``normalize_tool_result`` in the registry and agent loop) classify it
        as an error just like native-tool failures. Per the MCP spec, a result
        with ``isError: true`` is a tool-level failure even though the JSON-RPC
        round-trip itself succeeded.
        """
        if not res:
            return format_tool_error("mcp", detail=f"No response from MCP server '{self.name}'", name=tool_name)
        if "error" in res:
            err_val = res["error"]
            err_msg = err_val.get("message", str(err_val)) if isinstance(err_val, dict) else str(err_val)
            return format_tool_error("mcp", detail=err_msg, name=tool_name)

        result = res.get("result", {})
        if isinstance(result, dict) and result.get("isError"):
            detail = self._format_content(result) or "Tool reported isError without content"
            return format_tool_error("mcp", detail=detail, name=tool_name)

        output_text = self._format_content(result)
        if output_text:
            return output_text

        return f"MCP tool '{tool_name}' from server '{self.name}' executed successfully."

    # ── Abstract transport interface ───────────────────────────────────────

    async def _send_request_async(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """Send a JSON-RPC request and return the response dict.

        Subclasses must implement this with their transport (stdin/stdout or HTTP POST + SSE).
        """
        raise NotImplementedError

    async def _send_notification_async(self, message: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification or response (no return value expected).

        Subclasses must implement this with their transport.
        """
        raise NotImplementedError

    def start(self) -> bool:
        """Start the client synchronously. Subclasses implement transport-specific startup."""
        raise NotImplementedError

    async def start_async(self) -> bool:
        """Start the client asynchronously. Subclasses implement transport-specific startup."""
        raise NotImplementedError

    def stop(self) -> None:
        """Stop the client synchronously. Subclasses implement transport-specific teardown."""
        raise NotImplementedError

    async def stop_async(self) -> None:
        """Stop the client asynchronously. Subclasses implement transport-specific teardown."""
        raise NotImplementedError
