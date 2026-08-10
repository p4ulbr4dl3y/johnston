"""
Stdio JSON-RPC 2.0 client for MCP servers.
"""

import asyncio
import json
import logging
import os
import select
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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
        self._stopped = False
        self._buffer = ""
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._pending_responses: Dict[int, Dict[str, Any]] = {}
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None

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
            self._read_task = loop.create_task(self._async_read_loop())
        except RuntimeError:
            logger.debug("No running loop; skipping async reader for MCP server '%s'", self.name)

    async def _async_read_loop(self):
        """Background async loop reading stdio JSON-RPC lines and fulfilling futures by request ID."""
        loop = asyncio.get_running_loop()
        while not self._stopped and self.process and self.process.stdout:
            try:
                # Read directly on the loop. A single buffered readline() is cheap
                # and avoids switching to a worker thread per JSON-RPC line; the
                # async reader is the only stdout consumer in this path (the sync
                # path uses _read_response with select/os.read).
                line_bytes = self.process.stdout.readline()
                if not line_bytes:
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
                        loop.call_soon_threadsafe(fut.set_result, data)
                    # Cache the response for the sync _read_response path. Bound the
                    # cache so long-running async sessions don't leak entries that
                    # were already consumed by their matching future.
                    if len(self._pending_responses) >= self.MAX_PENDING_RESPONSES:
                        self._pending_responses.pop(next(iter(self._pending_responses)), None)
                    self._pending_responses[res_id] = data
            except asyncio.CancelledError:
                break
            except Exception:
                logger.debug("Error in async read loop for MCP server '%s'", self.name, exc_info=True)
                await asyncio.sleep(0.05)

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
        self._start_async_reader()
        self.req_id += 1
        current_id = self.req_id
        req = {"jsonrpc": "2.0", "id": current_id, "method": method}
        if params is not None:
            req["params"] = params

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self._send_request_sync(method, params=params, timeout=timeout)

        fut = loop.create_future()
        self._pending_futures[current_id] = fut

        line = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            if self.process and self.process.stdin:
                with self._write_lock:
                    self.process.stdin.write(line)
                    self.process.stdin.flush()
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
        return {
            "args": self.cmd,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "cwd": self.cwd or os.getcwd(),
            "env": run_env,
            "text": True,
            "bufsize": 1,
        }

    def start(self) -> bool:
        self._stopped = False
        if self.process and self.process.poll() is None:
            self._start_async_reader()
            return True

        self.last_error = None
        try:
            self.process = subprocess.Popen(**self._build_popen_kwargs())
            self._buffer = ""
            init_ok = self._initialize()
            if not init_ok:
                if not self.last_error:
                    self.last_error = "Server initialization timed out or returned error"
                self.stop()
            return init_ok
        except Exception as e:
            self.last_error = f"Process start failed: {e}"
            self.stop()
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
            self._start_async_reader()
            init_ok = await self._initialize_async()
            if not init_ok:
                if not self.last_error:
                    self.last_error = "Server initialization timed out or returned error"
                self.stop()
            return init_ok
        except Exception as e:
            self.last_error = f"Process start failed: {e}"
            self.stop()
            return False

    def stop(self):
        self._stopped = True
        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
        for fut in list(self._pending_futures.values()):
            if not fut.done():
                fut.set_exception(RuntimeError(f"MCP server '{self.name}' stopped"))
        self._pending_futures.clear()

        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                if self.process.stdout:
                    self.process.stdout.close()
                if self.process.stderr:
                    self.process.stderr.close()
            except Exception:
                logger.debug("Error closing MCP server '%s' stdio streams", self.name, exc_info=True)

            try:
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    logger.debug("Failed to kill MCP server '%s'", self.name, exc_info=True)
            self.process = None

    def _send(self, message: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        line = json.dumps(message, ensure_ascii=False) + "\n"
        with self._write_lock:
            self.process.stdin.write(line)
            self.process.stdin.flush()

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
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "johnston", "version": "1.0.0"},
            },
        }
        self._send(init_req)
        res = self._read_response(req_id=self.req_id, timeout=5.0)
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
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "johnston", "version": "1.0.0"},
            },
            timeout=5.0,
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

        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await self.fetch_tools_async()
        return True

    def fetch_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            self.req_id += 1
            current_id = self.req_id
            req = {"jsonrpc": "2.0", "id": current_id, "method": "tools/list"}
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=5.0)
            if res and "result" in res:
                self.tools = res["result"].get("tools", [])
            return self.tools

    async def fetch_tools_async(self) -> List[Dict[str, Any]]:
        res = await self._send_request_async("tools/list", timeout=5.0)
        if res and "result" in res:
            self.tools = res["result"].get("tools", [])
        return self.tools

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
            res = self._read_response(req_id=current_id, timeout=timeout)
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
        current_id, req = self._build_call_payload(tool_name, arguments)

        fut = loop.create_future()
        self._pending_futures[current_id] = fut

        line = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            if self.process and self.process.stdin:
                with self._write_lock:
                    self.process.stdin.write(line)
                    self.process.stdin.flush()
        except Exception as e:
            self._pending_futures.pop(current_id, None)
            return f"Error writing to MCP server '{self.name}': {e}"

        try:
            if timeout is not None:
                res = await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            else:
                res = await fut
        except asyncio.TimeoutError:
            self._pending_futures.pop(current_id, None)
            return f"Error: No response from MCP server '{self.name}'"
        except asyncio.CancelledError:
            self._pending_futures.pop(current_id, None)
            raise

        try:
            await self.fetch_tools_async()
        except Exception:
            logger.debug("Failed to refresh tools after async MCP tool call", exc_info=True)

        return self._parse_tool_response(tool_name, res)
