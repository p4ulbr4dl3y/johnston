"""Subprocess lifecycle management for MCP stdio client."""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from typing import Any, Deque, Dict, Optional

_default_logger = logging.getLogger("johnston.core.infrastructure.mcp.process_client")


class _ProcessClientLoggerProxy:
    """Proxy delegating to johnston.core.infrastructure.mcp.process_client.logger if available."""

    def __getattr__(self, name: str) -> Any:
        mod = sys.modules.get("johnston.core.infrastructure.mcp.process_client")
        if mod is not None and hasattr(mod, "logger"):
            return getattr(mod.logger, name)
        return getattr(_default_logger, name)


logger: Any = _ProcessClientLoggerProxy()

STDERR_TAIL_LINES = 200


class MCPProcessLifecycleMixin:
    """Subprocess lifecycle management for MCP stdio client (start, stop, stderr draining)."""

    name: str
    process: Optional[subprocess.Popen]
    cmd: Any
    cwd: Optional[str]
    env: Optional[Dict[str, Any]]
    last_error: Optional[str]
    _stopped: bool
    _start_lock: asyncio.Lock
    _stderr_thread: Optional[Any]
    _stderr_tail: Deque[str]

    def _build_popen_kwargs(self) -> Dict[str, Any]:
        """Helper to assemble standard Popen keyword arguments for MCP server process."""
        from johnston.core.infrastructure.secrets import interpolate_secrets

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

    def stop(self) -> None:
        self._stopped = True
        self._cancel_read_task_threadsafe()
        self._fail_pending_futures()
        self._terminate_process_group()
        self._join_reader_thread()
        self._join_stderr_thread()

    async def stop_async(self) -> None:
        """Async variant of ``stop`` for use on the event loop.

        Runs blocking subprocess teardown (terminate + wait + stream close) in a
        worker thread so async callers (e.g. ``_cleanup_if_created`` / timeout
        teardown) never stall the loop.
        """
        await asyncio.to_thread(self.stop)

    def _spawn_stderr_drain(self) -> None:
        """Drain the server's stderr pipe in a daemon thread.

        Without this, a server writing more than the OS pipe buffer (~64KB) of
        logs to stderr blocks on ``write(2)`` and stops answering stdin, which
        looks exactly like a hung server. The tail is kept in a bounded ring
        buffer for diagnostics. Only spawned for real stream objects (mocked
        test doubles are skipped via the ``fileno`` check).
        """
        import threading

        if not self.process or (self._stderr_thread and self._stderr_thread.is_alive()):
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
