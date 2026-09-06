"""Stdio transport and asynchronous multiplexing for MCP process client."""

import asyncio
import json
import logging
import os
import select
import sys
import threading
import time
from typing import Any, Dict, Optional

_default_logger = logging.getLogger("core.infrastructure.mcp.process_client")


class _ProcessClientLoggerProxy:
    """Proxy delegating to core.infrastructure.mcp.process_client.logger if available."""

    def __getattr__(self, name: str) -> Any:
        mod = sys.modules.get("core.infrastructure.mcp.process_client")
        if mod is not None and hasattr(mod, "logger"):
            return getattr(mod.logger, name)
        return getattr(_default_logger, name)


logger: Any = _ProcessClientLoggerProxy()


class MCPProcessTransportMixin:
    """Stdio JSON-RPC transport and async response reader multiplexing."""

    MAX_PENDING_RESPONSES = 256

    name: str
    cwd: Optional[str]
    process: Optional[Any]
    _stopped: bool
    _buffer: str
    _lock: threading.RLock
    _write_lock: threading.Lock
    _call_lock: asyncio.Lock
    _pending_responses: Dict[int, Dict[str, Any]]
    _pending_futures: Dict[int, asyncio.Future]
    _read_task: Optional[asyncio.Task]
    _reader_thread: Optional[threading.Thread]
    _reader_loop: Optional[asyncio.AbstractEventLoop]
    _queue: Optional[asyncio.Queue]
    _response_event: threading.Event

    # ── Stdio line parsing ─────────────────────────────────────────────────

    @staticmethod
    def _parse_line(line_str: str) -> Optional[Dict[str, Any]]:
        """Parses a single JSON-RPC line into a dict, or None if it is not valid JSON."""
        if not line_str or not line_str.startswith("{"):
            return None
        try:
            data = json.loads(line_str)
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    # ── Async reader lifecycle ─────────────────────────────────────────────

    def _start_async_reader(self) -> None:
        if self._read_task and not self._read_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running loop; skipping async reader for MCP server '%s'", self.name)
            return
        self._read_task = loop.create_task(self._async_read_loop())

    def _reader_thread_target(self) -> None:
        """Long-lived daemon thread that blocks on process stdout and hands lines to the event loop.

        All blocking I/O happens here (off the event loop). Each line is shipped to
        the running loop via ``loop.call_soon_threadsafe`` so JSON-RPC parsing and
        future fulfillment stay on the loop. The thread exits as soon as the process
        hits EOF, the client is stopped, or the stdout stream is gone/closed.
        """
        loop = self._reader_loop
        stdout = None
        if self.process:
            stdout = getattr(self.process, "stdout", None)
        if loop is None or stdout is None:
            return
        while not self._stopped:
            try:
                line = stdout.readline()
            except Exception:
                logger.debug("Reader thread error for MCP server '%s'", self.name, exc_info=True)
                break
            if not line:
                break
            try:
                loop.call_soon_threadsafe(self._queue.put_nowait, line)
            except RuntimeError:
                # Loop is closed; nothing more to deliver.
                break
        # Signal EOF/termination to the consuming loop so it can exit too.
        try:
            loop.call_soon_threadsafe(self._queue.put_nowait, None)
        except RuntimeError:
            pass

    def _spawn_reader_thread(self, loop: asyncio.AbstractEventLoop) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_loop = loop
        self._reader_thread = threading.Thread(
            target=self._reader_thread_target, name=f"mcp-reader-{self.name}", daemon=True
        )
        self._reader_thread.start()

    def _cancel_read_task_threadsafe(self) -> None:
        """Cancel the async reader without touching the task from a foreign thread."""
        task = self._read_task
        if task is None or task.done():
            self._read_task = None
            return
        loop = self._reader_loop
        if loop is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                task.cancel()
        else:
            task.cancel()
        self._read_task = None

    @staticmethod
    def _set_future_exception(fut: asyncio.Future, exc: Exception) -> None:
        if not fut.done():
            fut.set_exception(exc)

    def _fail_pending_futures(self) -> None:
        """Fail all in-flight async requests, scheduling the exception on their loop."""
        self._response_event.set()
        futs = list(self._pending_futures.values())
        self._pending_futures.clear()
        exc = RuntimeError(f"MCP server '{self.name}' stopped")
        for fut in futs:
            if fut.done():
                continue
            try:
                loop = fut.get_loop()
                loop.call_soon_threadsafe(self._set_future_exception, fut, exc)
            except RuntimeError:
                self._set_future_exception(fut, exc)

    def _join_reader_thread(self, timeout: float = 1.0) -> None:
        """Wait for the background reader thread to finish so we don't leak it.

        The thread exits on EOF/termination once the process is gone or the
        stdout stream is closed; we only bound the join so stop() never hangs.
        """
        thread = self._reader_thread
        if thread is None:
            return
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.debug("Reader thread for MCP server '%s' did not exit in time", self.name)
        self._reader_thread = None

    # ── Async read loop (stdio transport) ──────────────────────────────────

    async def _async_read_loop(self) -> None:
        """Background async loop reading stdio JSON-RPC lines and fulfilling futures by request ID.

        Blocking ``readline`` runs in one long-lived daemon thread (see
        :meth:`_reader_thread_target`); this coroutine only consumes a queue and does
        all JSON-RPC parsing/future fulfillment on the event loop.
        """
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._spawn_reader_thread(loop)
        try:
            while not self._stopped:
                try:
                    line_bytes = await self._queue.get()
                except asyncio.CancelledError:
                    break
                if line_bytes is None:
                    # Reader thread signaled EOF/termination.
                    self._fail_pending_futures()
                    break
                line_str = (
                    line_bytes.decode("utf-8", errors="replace").strip()
                    if isinstance(line_bytes, bytes)
                    else str(line_bytes).strip()
                )
                data = self._parse_line(line_str)
                if data is None:
                    continue

                if "method" in data and "id" not in data:
                    method = data.get("method", "")
                    if method in ("notifications/tools/list_changed", "tools/list_changed") or method.endswith("tools/list_changed"):
                        asyncio.create_task(self._handle_tools_list_changed_async())
                    elif method in ("notifications/resources/list_changed", "resources/list_changed") or method.endswith("resources/list_changed"):
                        asyncio.create_task(self._handle_resources_list_changed_async())
                    elif method in ("notifications/prompts/list_changed", "prompts/list_changed") or method.endswith("prompts/list_changed"):
                        asyncio.create_task(self._handle_prompts_list_changed_async())
                    continue

                if "method" in data and "id" in data:
                    asyncio.create_task(self._handle_server_request_async(data))
                    continue

                res_id = data.get("id")
                if res_id is not None:
                    fut = self._pending_futures.pop(res_id, None)
                    if fut and not fut.done():
                        fut.set_result(data)
                    else:
                        # Cache response for sync _read_response path only if no future handled it
                        if len(self._pending_responses) >= self.MAX_PENDING_RESPONSES:
                            self._pending_responses.pop(next(iter(self._pending_responses)), None)
                        self._pending_responses[res_id] = data
                        self._response_event.set()
        finally:
            self._fail_pending_futures()

    # ── Transport: send messages over stdin ────────────────────────────────

    def _send(self, message: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            self.process.stdin.write(line)
            self.process.stdin.flush()

    async def _send_async(self, message: Dict[str, Any]) -> None:
        """Send a JSON-RPC message without blocking the event loop.

        ``_write_lock`` (threading) still guards the write; the actual blocking
        write+flush runs in a worker thread so it never stalls the loop.
        """
        if not self.process or not self.process.stdin:
            return
        await asyncio.to_thread(self._send, message)

    async def _send_notification_async(self, message: Dict[str, Any]) -> None:
        """Send a JSON-RPC notification or response over stdin."""
        await self._send_async(message)

    # ── Transport: read responses from stdout (sync fallback) ──────────────

    def _read_response(self, req_id: Optional[int] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        if not self.process or not self.process.stdout or self._stopped:
            return None

        if req_id is not None and req_id in self._pending_responses:
            return self._pending_responses.pop(req_id)

        start_time = time.time()
        while not self._stopped:
            if req_id is not None and req_id in self._pending_responses:
                return self._pending_responses.pop(req_id)

            if self._read_task and not self._read_task.done():
                elapsed = time.time() - start_time
                if timeout is not None:
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        return None
                    wait_time = min(1.0, remaining)
                else:
                    wait_time = 1.0
                self._response_event.wait(timeout=wait_time)
                self._response_event.clear()
                continue

            while "\n" in self._buffer:
                line_str, self._buffer = self._buffer.split("\n", 1)
                line_str = line_str.strip()
                data = self._parse_line(line_str)
                if data is None:
                    continue
                if "method" in data and "id" not in data:
                    method = data.get("method", "")
                    self._dispatch_notification_sync(method)
                    continue

                if "method" in data and "id" in data:
                    self._handle_server_request_sync(data)
                    continue

                res_id = data.get("id")
                if req_id is not None and res_id != req_id:
                    if res_id is not None:
                        self._pending_responses[res_id] = data
                    continue

                return data

            wait_time = 1.0
            if timeout is not None:
                elapsed = time.time() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    return None
                wait_time = min(1.0, max(0.05, remaining))

            if sys.platform == "win32":
                try:
                    line_str = self.process.stdout.readline()
                    if not line_str:
                        return None
                    self._buffer += line_str
                except Exception:
                    logger.debug("Error reading from MCP server stdout (win32)", exc_info=True)
                    return None
            else:
                try:
                    rlist, _, _ = select.select([self.process.stdout], [], [], wait_time)
                except Exception:
                    logger.debug("select failed on MCP server stdout", exc_info=True)
                    return None

                if self._stopped:
                    return None

                if not rlist:
                    continue

                try:
                    raw_chunk = os.read(self.process.stdout.fileno(), 8192)
                    if not raw_chunk:
                        return None
                    self._buffer += raw_chunk.decode("utf-8", errors="replace")
                except (OSError, BlockingIOError):
                    continue
                except Exception:
                    logger.debug("Unexpected error reading MCP server stdout", exc_info=True)
                    return None

        return None

    def _handle_server_request_sync(self, data: Dict[str, Any]) -> None:
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
            self._send({"jsonrpc": "2.0", "id": req_id, "result": {"roots": roots}})
        elif method == "ping":
            self._send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        else:
            self._send({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method {method!r} not found"},
            })

    # ── Transport: async request/response over stdin ───────────────────────

    async def _send_request_async(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._send_request_sync(method, params=params, timeout=timeout)

        self._start_async_reader()
        async with self._call_lock:
            current_id = self._next_req_id()
            req = {"jsonrpc": "2.0", "id": current_id, "method": method}
            if params is not None:
                req["params"] = params

            fut = loop.create_future()
            self._pending_futures[current_id] = fut

            try:
                await self._send_async(req)
            except Exception:
                logger.debug("Failed to write request to MCP server '%s'", self.name, exc_info=True)
                self._pending_futures.pop(current_id, None)
                return None

        try:
            if timeout is not None:
                return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            return await fut
        except Exception:
            logger.debug("MCP request '%s' failed for server '%s'", method, self.name, exc_info=True)
            return None
        finally:
            self._pending_futures.pop(current_id, None)

    def _send_request_sync(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        current_id = self._next_req_id()
        req = {"jsonrpc": "2.0", "id": current_id, "method": method}
        if params is not None:
            req["params"] = params
        self._send(req)
        return self._read_response(req_id=current_id, timeout=timeout)
