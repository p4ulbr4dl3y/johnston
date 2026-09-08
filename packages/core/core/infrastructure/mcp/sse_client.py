"""
SSE and HTTP JSON-RPC 2.0 client for remote MCP servers.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from core.infrastructure.mcp.base import (
    CLIENT_NAME,
    CLIENT_VERSION,
    DEFAULT_TOOLS_CALL_TIMEOUT,
    MCPClientBase,
    _config_init_timeout,
)

logger = logging.getLogger(__name__)


class MCPSSEClient(MCPClientBase):
    """HTTP/SSE JSON-RPC 2.0 client for remote MCP servers."""

    def __init__(
        self,
        name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, cwd=cwd, env=env)
        self.url = url.rstrip("/")
        self.post_url = self.url
        self.headers = dict(headers or {})
        self._http_client: Optional[httpx.AsyncClient] = None
        self._sse_task: Optional[asyncio.Task] = None
        self._endpoint_ready = asyncio.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def is_alive(self) -> bool:
        return not self._stopped and self._http_client is not None

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

    # ── SSE listener ───────────────────────────────────────────────────────

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

    # ── Transport: HTTP POST + SSE ─────────────────────────────────────────

    async def _send_notification_async(self, payload: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification or response via HTTP POST."""
        await self._send_post_async(payload)

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
