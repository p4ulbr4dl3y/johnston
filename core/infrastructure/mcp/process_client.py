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

from core.domain.defaults.errors import format_tool_error
from core.infrastructure.mcp.base import (
    CLIENT_NAME,
    CLIENT_VERSION,
    DEFAULT_TOOLS_CALL_TIMEOUT,
    MCP_PROTOCOL_VERSION,
    MCPClientBase,
    _config_init_timeout,
)

logger = logging.getLogger(__name__)

STDERR_TAIL_LINES = 200


class MCPProcessClient(MCPClientBase):
    """Stdio JSON-RPC 2.0 client for MCP servers with Async Multiplexing support."""

    # Upper bound on cached responses kept for the sync read path. The async path
    # resolves futures directly and only caches responses so that sync
    # _read_response calls can still pick them up; without a cap this dict grows
    # unboundedly for long-running async-only sessions.
    MAX_PENDING_RESPONSES = 256

    # Used to serialize _next_req_id in thread-safe sync paths.
    _id_lock = threading.RLock()

    def __init__(
        self, name: str, command: str | List[str], cwd: Optional[str] = None, env: Optional[Dict[str, Any]] = None
    ):
        super().__init__(name, cwd=cwd, env=env)
        if isinstance(command, str):
            self.cmd = [command]
        else:
            self.cmd = list(command)
        self.process: Optional[subprocess.Popen] = None
        self._buffer = ""
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_responses: Dict[int, Dict[str, Any]] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._reader_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stderr_thread: Optional[threading.Thread] = None
        # Bounded tail of server stderr (drained off the event loop) so a chatty
        # server can never deadlock on a full pipe; also available as diagnostics.
        self._stderr_tail: Deque[str] = collections.deque(maxlen=STDERR_TAIL_LINES)
        self._queue: Optional[asyncio.Queue] = None
        self._response_event = threading.Event()

    # ── Request ID generation (thread-safe) ────────────────────────────────

    def _next_req_id(self) -> int:
        with self._id_lock:
            self.req_id += 1
            return self.req_id

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

    # ── Async read loop (stdio transport) ──────────────────────────────────

    async def _async_read_loop(self):
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

    # ── Process management ─────────────────────────────────────────────────

    def _build_popen_kwargs(self) -> Dict[str, Any]:
        """Helper to assemble standard Popen keyword arguments for MCP server process."""
        from core.infrastructure.secrets import interpolate_secrets

        run_env = os.environ.copy()
        if self.env:
            for k, v in self.env.items():
                run_env[k] = interpolate_secrets(str(v))

        if isinstance(self.cmd, list):
            resolved_args = [interpolate_secrets(str(a)) for a in self.cmd]
        else:
            resolved_args = interpolate_secrets(str(self.cmd))

        kwargs: Dict[str, Any] = {
            "args": resolved_args,
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
        async with self._start_lock:
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

    def _terminate_process_group(self) -> None:
        """Terminate the server process and its whole process group (POSIX)."""
        proc = self.process
        if proc is None:
            return
        pid = getattr(proc, "pid", None)
        use_pg = sys.platform != "win32" and isinstance(pid, int) and pid > 0

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
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    try:
                        proc.wait(timeout=1)
                    except Exception:
                        pass
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
                try:
                    proc.wait(timeout=1)
                except Exception:
                    pass
        finally:
            for name in ("stdin", "stdout", "stderr"):
                stream = getattr(proc, name, None)
                if stream is None:
                    continue
                try:
                    stream.close()
                except Exception:
                    logger.debug("Error closing MCP server '%s' %s stream", self.name, name, exc_info=True)
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

    def read_resource(self, uri: str, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        with self._lock:
            current_id = self._next_req_id()
            req = {
                "jsonrpc": "2.0",
                "id": current_id,
                "method": "resources/read",
                "params": {"uri": uri},
            }
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=timeout or DEFAULT_TOOLS_CALL_TIMEOUT)
            if res and "result" in res:
                return res["result"]
            return None

    def fetch_prompts(self) -> List[Dict[str, Any]]:
        with self._lock:
            current_id = self._next_req_id()
            req = {"jsonrpc": "2.0", "id": current_id, "method": "prompts/list"}
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=_config_init_timeout())
            if res and "result" in res:
                self.prompts = res["result"].get("prompts", [])
            return self.prompts

    def get_prompt(
        self, name: str, arguments: Optional[Dict[str, str]] = None, timeout: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            current_id = self._next_req_id()
            req = {
                "jsonrpc": "2.0",
                "id": current_id,
                "method": "prompts/get",
                "params": {"name": name, "arguments": arguments or {}},
            }
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=timeout or DEFAULT_TOOLS_CALL_TIMEOUT)
            if res and "result" in res:
                return res["result"]
            return None

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
