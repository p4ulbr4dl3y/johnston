"""
Stdio JSON-RPC 2.0 client for MCP servers.
"""

import asyncio
import collections
import json
import logging
import os
import select
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "johnston"
CLIENT_VERSION = "1.0.0"

# Default upper bound for a tools/call round-trip. A hanging server must never
# hold an agent turn forever; both the manager and direct callers get this
# default when no explicit timeout is passed.
DEFAULT_TOOLS_CALL_TIMEOUT = 120.0
INIT_TIMEOUT = 5.0
STDERR_TAIL_LINES = 200


class MCPProcessClient:
    """Stdio JSON-RPC 2.0 client for MCP servers with Async Multiplexing support."""

    # Upper bound on cached responses kept for the sync read path. The async path
    # resolves futures directly and only caches responses so that sync
    # _read_response calls can still pick them up; without a cap this dict grows
    # unboundedly for long-running async-only sessions.
    MAX_PENDING_RESPONSES = 256

    def __init__(
        self, name: str, command: str | List[str], cwd: Optional[str] = None, env: Optional[Dict[str, Any]] = None
    ):
        self.name = name
        if isinstance(command, str):
            self.cmd = [command]
        else:
            self.cmd = list(command)
        self.cwd = cwd
        self.env = env
        self.process: Optional[subprocess.Popen] = None
        self.req_id = 0
        self.tools: List[Dict[str, Any]] = []
        self.last_error: Optional[str] = None
        self._stopped = False
        self._buffer = ""
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_responses: Dict[int, Dict[str, Any]] = {}
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # Bounded tail of server stderr (drained off the event loop) so a chatty
        # server can never deadlock on a full pipe; also available as diagnostics.
        self._stderr_tail: Deque[str] = collections.deque(maxlen=STDERR_TAIL_LINES)
        self._queue: Optional[asyncio.Queue] = None
        # Guards the async request critical section (id generation, future
        # registration and stdin write) so concurrent callers never pick a
        # duplicate req_id or leave an unregistered future behind.
        self._call_lock = asyncio.Lock()
        # Monotonic timestamp of the last successful tools/list fetch, used to
        # rate-limit the per-call post-call refresh (avoids a duplicate fetch).
        self._tools_fetch_time = 0.0

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

    def _start_async_reader(self):
        if self._read_task and not self._read_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("No running loop; skipping async reader for MCP server '%s'", self.name)
            return
        self._read_task = loop.create_task(self._async_read_loop())

    def _reader_thread_target(self):
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

    def _spawn_reader_thread(self, loop) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._reader_loop = loop
        self._reader_thread = threading.Thread(
            target=self._reader_thread_target, name=f"mcp-reader-{self.name}", daemon=True
        )
        self._reader_thread.start()

    def _spawn_stderr_drain(self) -> None:
        """Drain the server's stderr pipe in a daemon thread.

        Without this, a server writing more than the OS pipe buffer (~64KB) of
        logs to stderr blocks on ``write(2)`` and stops answering stdin, which
        looks exactly like a hung server. The tail is kept in a bounded ring
        buffer for diagnostics. Only spawned for real stream objects (mocked
        test doubles are skipped via the ``fileno`` check).
        """
        if not self.process or self._stderr_thread and self._stderr_thread.is_alive():
            return
        stream = getattr(self.process, "stderr", None)
        if stream is None:
            return
        try:
            fd = stream.fileno()
        except Exception:
            return
        if not isinstance(fd, int):
            return
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, name=f"mcp-stderr-{self.name}", daemon=True
        )
        self._stderr_thread.start()

    def _drain_stderr(self) -> None:
        stream = getattr(self.process, "stderr", None) if self.process else None
        if stream is None:
            return
        while not self._stopped:
            try:
                line = stream.readline()
            except Exception:
                return
            if not line:
                return
            line = line.rstrip("\n")
            if line:
                self._stderr_tail.append(line)

    def _join_stderr_thread(self, timeout: float = 1.0) -> None:
        thread = self._stderr_thread
        if thread is None:
            return
        thread.join(timeout=timeout)
        if thread.is_alive():
            logger.debug("stderr thread for MCP server '%s' did not exit in time", self.name)
        self._stderr_thread = None

    def stderr_tail(self, max_lines: int = 30) -> str:
        """Return the last captured stderr lines (for diagnostics on failures)."""
        return "\n".join(list(self._stderr_tail)[-max_lines:])

    def _maybe_append_stderr_tail(self) -> None:
        tail = self.stderr_tail(max_lines=15)
        if tail:
            self.last_error = f"{self.last_error}; server stderr: {tail[-300:]}"

    async def _async_read_loop(self):
        """Background async loop reading stdio JSON-RPC lines and fulfilling futures by request ID.

        Blocking ``readline`` runs in one long-lived daemon thread (see
        :meth:`_reader_thread_target`); this coroutine only consumes a queue and does
        all JSON-RPC parsing/future fulfillment on the event loop.
        """
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._spawn_reader_thread(loop)
        while not self._stopped:
            try:
                line_bytes = await self._queue.get()
            except asyncio.CancelledError:
                break
            if line_bytes is None:
                # Reader thread signaled EOF/termination.
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
                if data.get("method") == "notifications/tools/list_changed":
                    try:
                        await self.fetch_tools_async()
                    except Exception:
                        logger.debug("Failed to refresh tools on list_changed notification", exc_info=True)
                continue

            res_id = data.get("id")
            if res_id is not None:
                fut = self._pending_futures.pop(res_id, None)
                if fut and not fut.done():
                    fut.set_result(data)
                # Cache the response for the sync _read_response path. Bound the
                # cache so long-running async sessions don't leak entries that
                # were already consumed by their matching future.
                if len(self._pending_responses) >= self.MAX_PENDING_RESPONSES:
                    self._pending_responses.pop(next(iter(self._pending_responses)), None)
                self._pending_responses[res_id] = data

    def _send_request_sync(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        self.req_id += 1
        current_id = self.req_id
        req = {"jsonrpc": "2.0", "id": current_id, "method": method}
        if params is not None:
            req["params"] = params
        self._send(req)
        return self._read_response(req_id=current_id, timeout=timeout)

    async def _send_request_async(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._send_request_sync(method, params=params, timeout=timeout)

        self._start_async_reader()
        async with self._call_lock:
            self.req_id += 1
            current_id = self.req_id
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

    def _build_popen_kwargs(self) -> Dict[str, Any]:
        """Helper to assemble standard Popen keyword arguments for MCP server process."""
        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)
        kwargs: Dict[str, Any] = {
            "args": self.cmd,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": self.cwd or os.getcwd(),
            "env": run_env,
            "text": True,
            "bufsize": 1,
        }
        if sys.platform == "win32":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            if creationflags:
                kwargs["creationflags"] = creationflags
        else:
            # Own process group so stop() can kill the whole tree (npx/uvx
            # spawn children that would otherwise be orphaned).
            kwargs["start_new_session"] = True
        return kwargs

    def start(self) -> bool:
        self._stopped = False
        if self.process and self.process.poll() is None:
            self._start_async_reader()
            return True

        self.last_error = None
        try:
            self.process = subprocess.Popen(**self._build_popen_kwargs())
            self._spawn_stderr_drain()
            self._buffer = ""
            init_ok = self._initialize()
            if not init_ok:
                if not self.last_error:
                    self.last_error = "Server initialization timed out or returned error"
                self.stop()
                self._maybe_append_stderr_tail()
            return init_ok
        except Exception as e:
            self.last_error = f"Process start failed: {e}"
            self.stop()
            self._maybe_append_stderr_tail()
            return False

    async def start_async(self) -> bool:
        self._stopped = False
        if self.process and self.process.poll() is None:
            self._start_async_reader()
            return True

        self.last_error = None
        try:
            kwargs = self._build_popen_kwargs()
            args = kwargs.pop("args")
            self.process = await asyncio.to_thread(subprocess.Popen, args, **kwargs)
            self._spawn_stderr_drain()
            self._start_async_reader()
            init_ok = await self._initialize_async()
            if not init_ok:
                if not self.last_error:
                    self.last_error = "Server initialization timed out or returned error"
                self.stop()
                self._maybe_append_stderr_tail()
            return init_ok
        except Exception as e:
            self.last_error = f"Process start failed: {e}"
            self.stop()
            self._maybe_append_stderr_tail()
            return False

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

    def _terminate_process_group(self) -> None:
        """Terminate the server process and its whole process group (POSIX)."""
        proc = self.process
        if proc is None:
            return
        pid = getattr(proc, "pid", None)
        use_pg = sys.platform != "win32" and isinstance(pid, int) and pid > 0

        for name in ("stdin", "stdout", "stderr"):
            stream = getattr(proc, name, None)
            if stream is None:
                continue
            try:
                stream.close()
            except Exception:
                logger.debug("Error closing MCP server '%s' %s stream", self.name, name, exc_info=True)

        try:
            try:
                if use_pg:
                    os.killpg(pid, signal.SIGTERM)
                else:
                    proc.terminate()
                try:
                    proc.wait(timeout=1)
                except Exception:
                    if use_pg:
                        try:
                            os.killpg(pid, signal.SIGKILL)
                        except Exception:
                            pass
                    else:
                        proc.kill()
            except Exception:
                if use_pg:
                    try:
                        os.killpg(pid, signal.SIGKILL)
                    except Exception:
                        logger.debug("Failed to kill MCP server group '%s'", self.name, exc_info=True)
                else:
                    try:
                        proc.kill()
                    except Exception:
                        logger.debug("Failed to kill MCP server '%s'", self.name, exc_info=True)
        finally:
            self.process = None

    def stop(self):
        self._stopped = True
        self._cancel_read_task_threadsafe()
        self._fail_pending_futures()
        self._terminate_process_group()
        self._join_reader_thread()
        self._join_stderr_thread()

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

    async def stop_async(self) -> None:
        """Async variant of ``stop`` for use on the event loop.

        Runs blocking subprocess teardown (terminate + wait + stream close) in a
        worker thread so async callers (e.g. ``_cleanup_if_created`` / timeout
        teardown) never stall the loop.
        """
        await asyncio.to_thread(self.stop)

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
                if timeout is not None and elapsed >= timeout:
                    return None
                time.sleep(0.01)
                continue

            while "\n" in self._buffer:
                line_str, self._buffer = self._buffer.split("\n", 1)
                line_str = line_str.strip()
                data = self._parse_line(line_str)
                if data is None:
                    continue
                if "method" in data and "id" not in data:
                    if data.get("method") == "notifications/tools/list_changed":
                        # Reentrant by design: _lock is an RLock and fetch_tools
                        # only mutates the same reader-critical sections guarded
                        # here; the GIL keeps _pending_responses consistent
                        # between sync and async read paths.
                        try:
                            self.fetch_tools()
                        except Exception:
                            logger.debug("Failed to refresh tools on list_changed notification", exc_info=True)
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

    def _initialize(self) -> bool:
        self.req_id += 1
        init_req = {
            "jsonrpc": "2.0",
            "id": self.req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
        self._send(init_req)
        res = self._read_response(req_id=self.req_id, timeout=INIT_TIMEOUT)
        if not res:
            self.last_error = "Server did not respond to initialize request (timeout)"
            return False
        if "error" in res:
            err_msg = (
                res["error"].get("message", str(res["error"])) if isinstance(res["error"], dict) else str(res["error"])
            )
            self.last_error = f"MCP init error: {err_msg}"
            return False

        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.fetch_tools()
        return True

    async def _initialize_async(self) -> bool:
        res = await self._send_request_async(
            "initialize",
            params={
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
            timeout=INIT_TIMEOUT,
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

        await self._send_async({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await self.fetch_tools_async()
        return True

    def fetch_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            self.req_id += 1
            current_id = self.req_id
            req = {"jsonrpc": "2.0", "id": current_id, "method": "tools/list"}
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=INIT_TIMEOUT)
            if res and "result" in res:
                self.tools = res["result"].get("tools", [])
                self._tools_fetch_time = time.monotonic()
            return self.tools

    async def fetch_tools_async(self) -> List[Dict[str, Any]]:
        res = await self._send_request_async("tools/list", timeout=INIT_TIMEOUT)
        if res and "result" in res:
            self.tools = res["result"].get("tools", [])
            self._tools_fetch_time = time.monotonic()
        return self.tools

    def is_tools_stale(self, ttl: float = 5.0) -> bool:
        """True if the cached tools list is stale (based on last fetch time)."""
        return (time.monotonic() - self._tools_fetch_time) >= ttl

    def _build_call_payload(self, tool_name: str, arguments: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """Helper to create JSON-RPC tool call payload with incremented request id."""
        self.req_id += 1
        current_id = self.req_id
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

    def _parse_tool_response(self, tool_name: str, res: Optional[Dict[str, Any]]) -> str:
        """Helper to parse MCP tool call JSON-RPC response or error dict into string output."""
        if not res:
            return f"Error: No response from MCP server '{self.name}'"
        if "error" in res:
            err_val = res["error"]
            err_msg = err_val.get("message", str(err_val)) if isinstance(err_val, dict) else str(err_val)
            return f"MCP Error: {err_msg}"

        result = res.get("result", {})
        content_items = result.get("content", [])
        output_parts = []
        for item in content_items:
            if item.get("type") == "text":
                output_parts.append(item.get("text", ""))
            else:
                output_parts.append(json.dumps(item, ensure_ascii=False))

        output_text = "\n".join(output_parts).strip()
        if output_text:
            return output_text

        return f"MCP tool '{tool_name}' from server '{self.name}' executed successfully."

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                if not self.start():
                    return f"Error: MCP server '{self.name}' process is not running"

            current_id, req = self._build_call_payload(tool_name, arguments)
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=timeout or DEFAULT_TOOLS_CALL_TIMEOUT)
            if self.is_tools_stale():
                try:
                    self.fetch_tools()
                except Exception:
                    logger.debug("Failed to refresh tools after MCP tool call", exc_info=True)
            return self._parse_tool_response(tool_name, res)

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self.call_tool(tool_name, arguments, timeout=timeout)

        if not self.process or self.process.poll() is not None:
            if not await self.start_async():
                return f"Error: MCP server '{self.name}' process is not running"

        self._start_async_reader()
        async with self._call_lock:
            current_id, req = self._build_call_payload(tool_name, arguments)

            fut = loop.create_future()
            self._pending_futures[current_id] = fut

            try:
                await self._send_async(req)
            except Exception as e:
                self._pending_futures.pop(current_id, None)
                return f"Error writing to MCP server '{self.name}': {e}"

        try:
            if timeout is not None:
                res = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            else:
                res = await asyncio.wait_for(asyncio.shield(fut), timeout=DEFAULT_TOOLS_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending_futures.pop(current_id, None)
            return f"Error: No response from MCP server '{self.name}'"
        except asyncio.CancelledError:
            self._pending_futures.pop(current_id, None)
            raise
        except RuntimeError as e:
            # Server stopped while we awaited; surface gracefully instead of crashing.
            self._pending_futures.pop(current_id, None)
            return f"Error: {e}"
        except Exception as e:
            self._pending_futures.pop(current_id, None)
            return f"Error: {e}"

        # Refresh tools only if the list may have changed since the last fetch
        # (e.g. a server reporting new tools). Without this rate limit every call
        # would trigger a redundant tools/list right after get_active_tools_async
        # already fetched it.
        if self.is_tools_stale():
            try:
                await self.fetch_tools_async()
            except Exception:
                logger.debug("Failed to refresh tools after async MCP tool call", exc_info=True)

        return self._parse_tool_response(tool_name, res)
