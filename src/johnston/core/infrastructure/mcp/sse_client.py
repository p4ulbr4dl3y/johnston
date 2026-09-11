"""
SSE and HTTP JSON-RPC 2.0 client for remote MCP servers.
"""

import asyncio
import atexit
import json
import logging
import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx

from johnston.core.infrastructure.mcp.base import (
    CLIENT_NAME,
    CLIENT_VERSION,
    DEFAULT_TOOLS_CALL_TIMEOUT,
    MCPClientBase,
    _config_init_timeout,
)

logger = logging.getLogger(__name__)

# ── Sync-lifecycle resource pooling ────────────────────────────────────────
# Perf audit finding #14: the old start()/stop() built a fresh single-worker
# ThreadPoolExecutor and ran ``asyncio.run`` (a fresh event loop) on every sync
# lifecycle call, churning threads and loops under MCP SSE-heavy workloads.
# Now one shared, bounded executor plus one persistent per-client loop thread
# are reused across all calls and released on stop/exit.

_SSE_EXECUTOR_MAX_WORKERS = 4
_SSE_EXECUTOR: Optional[ThreadPoolExecutor] = None
_SSE_EXECUTOR_LOCK = threading.Lock()


def _get_sse_executor() -> ThreadPoolExecutor:
    """Shared, lazily-created executor for sync calls made from a running loop.

    Module-level (no owning client) so the bounded pool is shared by every
    ``MCPSSEClient``; it is shut down once at interpreter exit via ``atexit``.
    Created lazily so processes that never use SSE spawn no extra threads.
    """
    global _SSE_EXECUTOR
    if _SSE_EXECUTOR is None:
        with _SSE_EXECUTOR_LOCK:
            if _SSE_EXECUTOR is None:
                _SSE_EXECUTOR = ThreadPoolExecutor(
                    max_workers=_SSE_EXECUTOR_MAX_WORKERS,
                    thread_name_prefix="johnston-mcp-sse",
                )
                atexit.register(_SSE_EXECUTOR.shutdown, wait=True)
    return _SSE_EXECUTOR


def _run_loop_forever(loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
    """Body of the per-client loop thread: run one loop until ``stop`` is requested."""
    asyncio.set_event_loop(loop)
    ready.set()
    try:
        loop.run_forever()
    finally:
        try:
            loop.close()
        except RuntimeError:
            pass


def _finalize_loop_state(state: Dict[str, Any]) -> None:
    """Backstop for clients GC'd without ``stop()``: stop + join the loop thread."""
    thread = state.get("thread")
    loop = state.get("loop")
    if thread is not None and loop is not None and not loop.is_closed():
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            pass
        if thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=1.0)
    state.clear()


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
        # Persistent event loop used by sync lifecycle calls (see _ensure_loop).
        self._loop_state: Dict[str, Any] = {"loop": None, "thread": None, "stopping": False}
        self._loop_lock = threading.Lock()
        weakref.finalize(self, _finalize_loop_state, self._loop_state)

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
        return self._run_sync_lifecycle(lambda: self.start_async(timeout=timeout), timeout)

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

        # Release the persistent loop thread (no-op for async-only usage).
        self._shutdown_loop()

    def stop(self) -> None:
        loop_thread = self._loop_state.get("thread")
        try:
            self._run_sync_lifecycle(self.stop_async, 5.0)
        except Exception:
            # Teardown must never raise: log and let the loop thread finish
            # tearing down state on its own.
            logger.debug("MCP SSE stop failed for '%s'", self.name, exc_info=True)
        finally:
            if (
                loop_thread is not None
                and loop_thread.is_alive()
                and loop_thread is not threading.current_thread()
            ):
                loop_thread.join(timeout=1.0)

    # ── Sync loop/executor reuse ──────────────────────────────────────────

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """Create (or reuse) this client's persistent event-loop thread.

        Sync lifecycle calls schedule their coroutines on this one loop via
        ``asyncio.run_coroutine_threadsafe`` instead of paying for a fresh
        event loop per call (``asyncio.run``). All async state for the client
        stays on this single loop for its lifetime; the loop is recreated after
        ``stop``/restart cycles.
        """
        with self._loop_lock:
            state = self._loop_state
            thread = state["thread"]
            if state["stopping"]:
                # A shutdown is in flight (stop_async ran on the loop and
                # scheduled stop): never schedule new work on that loop.
                if thread is not None and thread is not threading.current_thread() and thread.is_alive():
                    thread.join(timeout=1.0)
                state["stopping"] = False
                state["loop"] = None
                state["thread"] = None
                thread = None
            if thread is not None and thread.is_alive() and not state["loop"].is_closed():
                return state["loop"]
            loop = asyncio.new_event_loop()
            ready = threading.Event()
            thread = threading.Thread(
                target=_run_loop_forever,
                args=(loop, ready),
                name=f"johnston-mcp-sse-{self.name}",
                daemon=True,
            )
            thread.start()
            ready.wait(timeout=2.0)
            state["loop"] = loop
            state["thread"] = thread
            return loop

    def _shutdown_loop(self) -> None:
        """Stop the persistent loop thread (idempotent; safe from any thread)."""
        with self._loop_lock:
            state = self._loop_state
            thread = state["thread"]
            loop = state["loop"]
            if thread is None or loop is None:
                return
            state["stopping"] = True
            if not loop.is_closed():
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except RuntimeError:
                    pass
            if thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=1.0)
            state["loop"] = None
            state["thread"] = None

    def _run_coro_blocking(self, coro_factory: Any, timeout: Optional[float]) -> Any:
        """Schedule ``coro_factory()`` on the persistent loop and block for the result."""
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro_factory(), loop)
        if timeout is None:
            return fut.result()
        return fut.result(timeout=timeout)

    def _run_sync_lifecycle(self, coro_factory: Any, timeout: Optional[float]) -> Any:
        """Run a lifecycle coroutine synchronously with pooled resources.

        No loop in this thread (plain sync caller): schedule on this client's
        persistent loop and block — replaces the old per-call ``asyncio.run``.
        A loop IS running (async caller using the sync API): offload to the
        shared ``_get_sse_executor`` pool so the caller's loop is never
        blocked; the worker still runs on the client's persistent loop —
        replaces the old per-call ``ThreadPoolExecutor`` + fresh loop combo.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return self._run_coro_blocking(coro_factory, None)
        return _get_sse_executor().submit(self._run_coro_blocking, coro_factory, timeout).result(timeout=timeout)

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
