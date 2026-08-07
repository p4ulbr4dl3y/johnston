"""
Stdio JSON-RPC 2.0 client for MCP servers.
"""
import asyncio
import json
import os
import select
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional


class MCPProcessClient:
    """Stdio JSON-RPC 2.0 client for MCP servers with Async Multiplexing support."""

    def __init__(self, name: str, command: str | List[str], cwd: Optional[str] = None, env: Optional[Dict[str, str]] = None):
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
        self._pending_responses: Dict[int, Dict[str, Any]] = {}
        self._pending_futures: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None

    def _start_async_reader(self):
        if self._read_task and not self._read_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._read_task = loop.create_task(self._async_read_loop())
        except RuntimeError:
            pass

    async def _async_read_loop(self):
        """Background async loop reading stdio JSON-RPC lines and fulfilling futures by request ID."""
        loop = asyncio.get_running_loop()
        while not self._stopped and self.process and self.process.stdout:
            try:
                line_bytes = await asyncio.to_thread(self.process.stdout.readline)
                if not line_bytes:
                    break
                line_str = line_bytes.decode("utf-8", errors="replace").strip() if isinstance(line_bytes, bytes) else str(line_bytes).strip()
                if not line_str.startswith("{"):
                    continue
                try:
                    data = json.loads(line_str)
                except Exception:
                    continue

                if "method" in data and "id" not in data:
                    if data.get("method") == "notifications/tools/list_changed":
                        try:
                            await self.fetch_tools_async()
                        except Exception:
                            pass
                    continue

                res_id = data.get("id")
                if res_id is not None:
                    fut = self._pending_futures.pop(res_id, None)
                    if fut and not fut.done():
                        loop.call_soon_threadsafe(fut.set_result, data)
                    self._pending_responses[res_id] = data
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.05)

    def _send_request_sync(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        self.req_id += 1
        current_id = self.req_id
        req = {
            "jsonrpc": "2.0",
            "id": current_id,
            "method": method
        }
        if params is not None:
            req["params"] = params
        self._send(req)
        return self._read_response(req_id=current_id, timeout=timeout)

    async def _send_request_async(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Optional[Dict[str, Any]]:
        self._start_async_reader()
        self.req_id += 1
        current_id = self.req_id
        req = {
            "jsonrpc": "2.0",
            "id": current_id,
            "method": method
        }
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
                self.process.stdin.write(line)
                self.process.stdin.flush()
        except Exception:
            self._pending_futures.pop(current_id, None)
            return None

        try:
            if timeout is not None:
                return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
            return await fut
        except Exception:
            return None
        finally:
            self._pending_futures.pop(current_id, None)

    def start(self) -> bool:
        self._stopped = False
        if self.process and self.process.poll() is None:
            self._start_async_reader()
            return True

        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)

        self.last_error = None
        try:
            self.process = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd or os.getcwd(),
                env=run_env,
                text=True,
                bufsize=1
            )
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

        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)

        self.last_error = None
        try:
            self.process = await asyncio.to_thread(
                subprocess.Popen,
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd or os.getcwd(),
                env=run_env,
                text=True,
                bufsize=1,
            )
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
                pass

            try:
                self.process.terminate()
                self.process.wait(timeout=1)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None

    def _send(self, message: Dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            return
        line = json.dumps(message, ensure_ascii=False) + "\n"
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
                if not line_str.startswith("{"):
                    continue
                try:
                    data = json.loads(line_str)
                    if "method" in data and "id" not in data:
                        if data.get("method") == "notifications/tools/list_changed":
                            try:
                                self.fetch_tools()
                            except Exception:
                                pass
                        continue

                    res_id = data.get("id")
                    if req_id is not None and res_id != req_id:
                        if res_id is not None:
                            self._pending_responses[res_id] = data
                        continue

                    return data
                except Exception:
                    continue

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
                    return None
            else:
                try:
                    rlist, _, _ = select.select([self.process.stdout], [], [], wait_time)
                except Exception:
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
                "clientInfo": {"name": "johnston", "version": "1.0.0"}
            }
        }
        self._send(init_req)
        res = self._read_response(req_id=self.req_id, timeout=5.0)
        if not res:
            self.last_error = "Server did not respond to initialize request (timeout)"
            return False
        if "error" in res:
            err_msg = res["error"].get("message", str(res["error"])) if isinstance(res["error"], dict) else str(res["error"])
            self.last_error = f"MCP init error: {err_msg}"
            return False

        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.fetch_tools()
        return True

    async def _initialize_async(self) -> bool:
        res = await self._send_request_async("initialize", params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "johnston", "version": "1.0.0"}
        }, timeout=5.0)
        if not res:
            self.last_error = "Server did not respond to initialize request (timeout)"
            return False
        if "error" in res:
            err_msg = res["error"].get("message", str(res["error"])) if isinstance(res["error"], dict) else str(res["error"])
            self.last_error = f"MCP init error: {err_msg}"
            return False

        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await self.fetch_tools_async()
        return True

    def fetch_tools(self) -> List[Dict[str, Any]]:
        with self._lock:
            self.req_id += 1
            current_id = self.req_id
            req = {
                "jsonrpc": "2.0",
                "id": current_id,
                "method": "tools/list"
            }
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

    def call_tool(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        with self._lock:
            if not self.process or self.process.poll() is not None:
                if not self.start():
                    return f"Error: MCP server '{self.name}' process is not running"

            self.req_id += 1
            current_id = self.req_id
            req = {
                "jsonrpc": "2.0",
                "id": current_id,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            self._send(req)
            res = self._read_response(req_id=current_id, timeout=timeout)
            if not res:
                return f"Error: No response from MCP server '{self.name}'"
            if "error" in res:
                return f"MCP Error: {res['error'].get('message', res['error'])}"

            result = res.get("result", {})
            content_items = result.get("content", [])
            output_parts = []
            for item in content_items:
                if item.get("type") == "text":
                    output_parts.append(item.get("text", ""))
                else:
                    output_parts.append(json.dumps(item, ensure_ascii=False))

            try:
                self.fetch_tools()
            except Exception:
                pass

            output_text = "\n".join(output_parts).strip()
            if output_text:
                return output_text

            return f"MCP tool '{tool_name}' from server '{self.name}' executed successfully."

    async def call_tool_async(self, tool_name: str, arguments: Dict[str, Any], timeout: Optional[float] = None) -> str:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self.call_tool(tool_name, arguments, timeout=timeout)

        if not self.process or self.process.poll() is not None:
            if not await self.start_async():
                return f"Error: MCP server '{self.name}' process is not running"

        self._start_async_reader()
        self.req_id += 1
        current_id = self.req_id
        req = {
            "jsonrpc": "2.0",
            "id": current_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }

        fut = loop.create_future()
        self._pending_futures[current_id] = fut

        line = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            if self.process and self.process.stdin:
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

        try:
            await self.fetch_tools_async()
        except Exception:
            pass

        output_text = "\n".join(output_parts).strip()
        if output_text:
            return output_text

        return f"MCP tool '{tool_name}' from server '{self.name}' executed successfully."
