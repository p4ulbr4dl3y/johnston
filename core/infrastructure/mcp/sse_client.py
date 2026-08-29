"""
SSE and HTTP JSON-RPC 2.0 client for remote MCP servers.
"""

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from core.domain.defaults.config import DEFAULT_MCP_CALL_TIMEOUT, DEFAULT_MCP_INIT_TIMEOUT
from core.domain.defaults.errors import format_tool_error

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "johnston"
CLIENT_VERSION = "1.0.0"

DEFAULT_TOOLS_CALL_TIMEOUT = DEFAULT_MCP_CALL_TIMEOUT
INIT_TIMEOUT = DEFAULT_MCP_INIT_TIMEOUT


def _config_init_timeout() -> float:
    """Return the configured MCP init timeout (tools.mcp_init_timeout)."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools.mcp_init_timeout
    except Exception:
        return INIT_TIMEOUT


class MCPSSEClient:
    """HTTP/SSE JSON-RPC 2.0 client for remote MCP servers."""

    def __init__(
        self,
        name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.url = url.rstrip("/")
        self.post_url = self.url
        self.headers = dict(headers or {})
        self.cwd = cwd
        self.env = env
        self.req_id = 0
        self.tools: List[Dict[str, Any]] = []
        self.resources: List[Dict[str, Any]] = []
        self.prompts: List[Dict[str, Any]] = []
        self.server_capabilities: Dict[str, Any] = {}
        self.last_error: Optional[str] = None
        self._stopped = False
        self._http_client: Optional[httpx.AsyncClient] = None
        self._sse_task: Optional[asyncio.Task] = None
        self._endpoint_ready = asyncio.Event()
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._call_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._tools_fetch_time = 0.0
        self.on_tools_changed: Optional[Any] = None
        self.on_resources_changed: Optional[Any] = None
        self.on_prompts_changed: Optional[Any] = None

    def _next_req_id(self) -> int:
        self.req_id += 1
        return self.req_id

    def is_alive(self) -> bool:
        return not self._stopped and self._http_client is not None

    def is_tools_stale(self, ttl: float = 300.0) -> bool:
        if self._tools_fetch_time <= 0.0:
            return True
        return (time.monotonic() - self._tools_fetch_time) >= ttl

    async def start_async(self, timeout: float | None = None) -> bool:
        if timeout is None:
            timeout = _config_init_timeout()
        async with self._start_lock:
            if self.is_alive():
                return True
            self._stopped = False
            self.last_error = None
            self._endpoint_ready.clear()

            req_headers = {
                "Accept": "text/event-stream, application/json, text/plain",
                "User-Agent": f"{CLIENT_NAME}/{CLIENT_VERSION}",
            }
            req_headers.update(self.headers)
            self._http_client = httpx.AsyncClient(
                headers=req_headers,
                timeout=httpx.Timeout(timeout, read=None),
                trust_env=False,
            )

            # Start SSE background connection
            self._sse_task = asyncio.create_task(self._sse_listen_loop())

            # Wait briefly for endpoint event or fallback to base url
            try:
                await asyncio.wait_for(self._endpoint_ready.wait(), timeout=min(5.0, timeout))
            except asyncio.TimeoutError:
                self.post_url = self.url

            try:
                ok = await asyncio.wait_for(self._initialize_async(), timeout=timeout)
                if not ok:
                    await self.stop_async()
                    return False
                return True
            except Exception as e:
                self.last_error = f"MCP SSE start failed: {e}"
                await self.stop_async()
                return False

    def start(self, timeout: float | None = None) -> bool:
        if timeout is None:
            timeout = _config_init_timeout()
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(lambda: asyncio.run(self.start_async(timeout=timeout))).result(timeout=timeout)
        except RuntimeError:
            return asyncio.run(self.start_async(timeout=timeout))

    async def stop_async(self) -> None:
        self._stopped = True
        if self._sse_task and not self._sse_task.done():
            self._sse_task.cancel()
            try:
                await self._sse_task
            except (asyncio.CancelledError, Exception):
                pass
        self._sse_task = None

        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        for fut in list(self._pending_futures.values()):
            if not fut.done():
                fut.set_exception(RuntimeError("MCP SSE client stopped"))
        self._pending_futures.clear()

    def stop(self) -> None:
        try:
            asyncio.get_running_loop()
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(lambda: asyncio.run(self.stop_async())).result(timeout=5.0)
        except RuntimeError:
            asyncio.run(self.stop_async())

    async def _sse_listen_loop(self) -> None:
        """Stream SSE events from the server."""
        if not self._http_client:
            return
        try:
            sse_url = self.url
            async with self._http_client.stream(
                "GET",
                sse_url,
                headers={"Accept": "text/event-stream"},
                timeout=httpx.Timeout(connect=10.0, read=None, write=10.0, pool=None),
            ) as response:
                if response.status_code >= 400:
                    self.last_error = f"SSE connection failed HTTP {response.status_code}"
                    self._endpoint_ready.set()
                    return

                event_type = "message"
                data_lines: List[str] = []

                async for line in response.aiter_lines():
                    if self._stopped:
                        break
                    line = line.strip()
                    if not line:
                        if data_lines:
                            full_data = "\n".join(data_lines)
                            await self._handle_sse_event(event_type, full_data)
                            data_lines = []
                            event_type = "message"
                        continue

                    if line.startswith("event:"):
                        event_type = line[len("event:") :].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[len("data:") :].strip())
                    elif line.startswith(":"):
                        continue
        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not self._stopped:
                logger.debug("SSE listen loop ended for '%s': %s", self.name, e)
        finally:
            self._endpoint_ready.set()

    async def _handle_sse_event(self, event_type: str, data: str) -> None:
        """Process incoming SSE event."""
        if event_type == "endpoint":
            raw_endpoint = data.strip()
            if raw_endpoint.startswith("http://") or raw_endpoint.startswith("https://"):
                self.post_url = raw_endpoint
            else:
                self.post_url = urljoin(self.url, raw_endpoint)
            self._endpoint_ready.set()
            return

        if not data.startswith("{"):
            return

        try:
            msg = json.loads(data)
        except Exception:
            return

        if not isinstance(msg, dict):
            return

        if "method" in msg and "id" not in msg:
            method = msg.get("method", "")
            if method in ("notifications/tools/list_changed", "tools/list_changed") or method.endswith("tools/list_changed"):
                asyncio.create_task(self.fetch_tools_async())
                if callable(self.on_tools_changed):
                    try:
                        self.on_tools_changed()
                    except Exception:
                        pass
            elif method in ("notifications/resources/list_changed", "resources/list_changed") or method.endswith("resources/list_changed"):
                asyncio.create_task(self.fetch_resources_async())
                if callable(self.on_resources_changed):
                    try:
                        self.on_resources_changed()
                    except Exception:
                        pass
            elif method in ("notifications/prompts/list_changed", "prompts/list_changed") or method.endswith("prompts/list_changed"):
                asyncio.create_task(self.fetch_prompts_async())
                if callable(self.on_prompts_changed):
                    try:
                        self.on_prompts_changed()
                    except Exception:
                        pass
            return

        if "method" in msg and "id" in msg:
            asyncio.create_task(self._handle_server_request_async(msg))
            return

        res_id = msg.get("id")
        if res_id is not None:
            fut = self._pending_futures.pop(res_id, None)
            if fut and not fut.done():
                fut.set_result(msg)

    async def _handle_server_request_async(self, data: Dict[str, Any]) -> None:
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
            await self._send_post_async({"jsonrpc": "2.0", "id": req_id, "result": {"roots": roots}})
        elif method == "ping":
            await self._send_post_async({"jsonrpc": "2.0", "id": req_id, "result": {}})
        else:
            await self._send_post_async({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method {method!r} not found"},
            })

    async def _send_post_async(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self._http_client or self._stopped:
            return None
        try:
            resp = await self._http_client.post(
                self.post_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code == 200 and resp.text:
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        return data
                except Exception:
                    pass
            return None
        except Exception as e:
            logger.debug("POST failed to %s: %s", self.post_url, e)
            return None

    async def _send_request_async(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = DEFAULT_TOOLS_CALL_TIMEOUT
    ) -> Optional[Dict[str, Any]]:
        if not self._http_client or self._stopped:
            return None

        current_id = self._next_req_id()
        req = {"jsonrpc": "2.0", "id": current_id, "method": method}
        if params is not None:
            req["params"] = params

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending_futures[current_id] = fut

        try:
            post_result = await self._send_post_async(req)
            if post_result and (post_result.get("id") == current_id or "result" in post_result or "error" in post_result):
                self._pending_futures.pop(current_id, None)
                return post_result

            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending_futures.pop(current_id, None)
            return None
        except Exception:
            self._pending_futures.pop(current_id, None)
            return None

    async def _initialize_async(self) -> bool:
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
            err_msg = res["error"].get("message", str(res["error"])) if isinstance(res["error"], dict) else str(res["error"])
            self.last_error = f"MCP init error: {err_msg}"
            return False

        self.server_capabilities = res.get("result", {}).get("capabilities", {})
        await self._send_post_async({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await self.fetch_tools_async()
        if "resources" in self.server_capabilities:
            await self.fetch_resources_async()
        if "prompts" in self.server_capabilities:
            await self.fetch_prompts_async()
        return True

    async def fetch_tools_async(self) -> List[Dict[str, Any]]:
        res = await self._send_request_async("tools/list", timeout=_config_init_timeout())
        if res and "result" in res:
            self.tools = res["result"].get("tools", [])
            self._tools_fetch_time = time.monotonic()
        return self.tools

    async def call_tool_async(
        self, tool_name: str, arguments: Dict[str, Any], timeout: float = DEFAULT_TOOLS_CALL_TIMEOUT
    ) -> Optional[str]:
        res = await self._send_request_async(
            "tools/call",
            params={"name": tool_name, "arguments": arguments},
            timeout=timeout,
        )
        if not res:
            return format_tool_error(f"Timeout: MCP server '{self.name}' did not respond within {timeout}s")
        if "error" in res:
            err = res["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return format_tool_error(f"MCP error: {msg}")

        result = res.get("result", {})
        if isinstance(result, dict) and result.get("isError"):
            err_content = self._format_content(result)
            return format_tool_error(err_content or "Tool returned an error")
        return self._format_content(result)

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

    @staticmethod
    def _format_content(result: Any) -> str:
        content_items = result.get("content", []) if isinstance(result, dict) else []
        output_parts = []
        for item in content_items:
            if isinstance(item, dict) and item.get("type") == "text":
                output_parts.append(item.get("text", ""))
            else:
                output_parts.append(json.dumps(item, ensure_ascii=False))
        return "\n".join(output_parts).strip()
