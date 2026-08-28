"""
Unit tests for core.infrastructure.mcp.process_client.MCPProcessClient.

All tests use mocks only; no real subprocesses are spawned.
"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.infrastructure.mcp.process_client import MCPProcessClient


class TestStartAsyncReader(unittest.TestCase):
    def test_start_async_reader_without_running_loop(self):
        client = MCPProcessClient("t", "echo")
        client._start_async_reader()
        self.assertIsNone(client._read_task)

    def test_start_async_reader_existing_task_returns_early(self):
        client = MCPProcessClient("t", "echo")
        task = MagicMock()
        task.done.return_value = False
        client._read_task = task
        client._start_async_reader()
        self.assertIs(client._read_task, task)


class TestAsyncReadLoop(unittest.IsolatedAsyncioTestCase):
    async def test_async_read_loop_breaks_on_eof(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stdout.readline = MagicMock(side_effect=[b"", b""])
        client.process = proc
        await client._async_read_loop()

    async def test_async_read_loop_skips_invalid_json(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stdout.readline = MagicMock(side_effect=[b"{broken json}\n", b""])
        client.process = proc
        await client._async_read_loop()

    async def test_async_read_loop_handles_list_changed_notification(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        proc.stdout.readline = MagicMock(side_effect=[notification.encode("utf-8"), b""])
        client.process = proc
        fetch_called = asyncio.Event()

        async def _fetch():
            fetch_called.set()

        client.fetch_tools_async = AsyncMock(side_effect=_fetch)
        await client._async_read_loop()
        await asyncio.wait_for(fetch_called.wait(), timeout=1.0)
        client.fetch_tools_async.assert_awaited_once()

    async def test_async_read_loop_notification_fetch_error_ignored(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        proc.stdout.readline = MagicMock(side_effect=[notification.encode("utf-8"), b""])
        client.process = proc
        fetch_called = asyncio.Event()

        async def _fetch():
            fetch_called.set()
            raise RuntimeError("boom")

        client.fetch_tools_async = AsyncMock(side_effect=_fetch)
        await client._async_read_loop()  # must not raise
        await asyncio.wait_for(fetch_called.wait(), timeout=1.0)
        client.fetch_tools_async.assert_awaited_once()

    async def test_async_read_loop_fulfills_pending_future(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        resp = json.dumps({"jsonrpc": "2.0", "id": 5, "result": {"ok": True}})
        proc.stdout.readline = MagicMock(side_effect=[resp.encode("utf-8"), b""])
        client.process = proc

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending_futures[5] = fut

        await client._async_read_loop()
        result = await asyncio.wait_for(fut, 0.5)
        self.assertEqual(result["id"], 5)
        self.assertNotIn(5, client._pending_futures)
        self.assertNotIn(5, client._pending_responses)

    async def test_async_read_loop_survives_reader_errors(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stdout.readline = MagicMock(side_effect=[RuntimeError("boom"), b""])
        client.process = proc
        await client._async_read_loop()


class TestSendRequestSync(unittest.TestCase):
    def test_send_request_sync_with_params(self):
        client = MCPProcessClient("t", "echo")
        resp = {"jsonrpc": "2.0", "id": 1, "result": {}}
        with patch.object(client, "_send") as mock_send:
            with patch.object(client, "_read_response", return_value=resp) as mock_read:
                result = client._send_request_sync("ping", params={"a": 1}, timeout=2.0)
        self.assertEqual(result, resp)
        mock_read.assert_called_once_with(req_id=1, timeout=2.0)
        req = mock_send.call_args[0][0]
        self.assertEqual(req["method"], "ping")
        self.assertEqual(req["params"], {"a": 1})

    def test_send_request_sync_without_params(self):
        client = MCPProcessClient("t", "echo")
        with patch.object(client, "_send") as mock_send:
            with patch.object(client, "_read_response", return_value=None):
                result = client._send_request_sync("ping")
        self.assertIsNone(result)
        req = mock_send.call_args[0][0]
        self.assertNotIn("params", req)


class TestSendRequestAsync(unittest.IsolatedAsyncioTestCase):
    async def test_send_request_async_success_with_timeout(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin = MagicMock()
        client._start_async_reader = MagicMock()

        resp = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write

        result = await client._send_request_async("ping", params={"x": 1}, timeout=2.0)
        self.assertEqual(result, resp)
        self.assertNotIn(1, client._pending_futures)

    async def test_send_request_async_success_without_timeout(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin = MagicMock()
        client._start_async_reader = MagicMock()

        resp = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write

        result = await client._send_request_async("ping")
        self.assertEqual(result, resp)
        self.assertNotIn(1, client._pending_futures)

    async def test_send_request_async_write_error_returns_none(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin.write.side_effect = OSError("pipe closed")
        client._start_async_reader = MagicMock()
        result = await client._send_request_async("ping", timeout=2.0)
        self.assertIsNone(result)
        self.assertNotIn(1, client._pending_futures)

    async def test_send_request_async_future_error_returns_none(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin = MagicMock()
        client._start_async_reader = MagicMock()

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_exception(RuntimeError("boom"))

        client.process.stdin.write.side_effect = on_write
        result = await client._send_request_async("ping", timeout=2.0)
        self.assertIsNone(result)
        self.assertNotIn(1, client._pending_futures)


class TestSendRequestAsyncNoLoop(unittest.TestCase):
    def test_send_request_async_falls_back_to_sync_without_loop(self):
        client = MCPProcessClient("t", "echo")
        client._send_request_sync = MagicMock(return_value={"jsonrpc": "2.0", "id": 1, "result": {}})
        coro = client._send_request_async("ping", params={"x": 1}, timeout=2.0)
        try:
            coro.send(None)
            self.fail("expected StopIteration")
        except StopIteration as exc:
            result = exc.value
        self.assertEqual(result["id"], 1)
        client._send_request_sync.assert_called_once_with("ping", params={"x": 1}, timeout=2.0)


class TestStart(unittest.TestCase):
    def test_start_returns_true_when_already_running(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.poll.return_value = None
        client.process = proc
        with patch.object(client, "_start_async_reader") as mock_reader:
            result = client.start()
        self.assertTrue(result)
        mock_reader.assert_called_once()

    def test_start_sets_last_error_when_init_fails(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        with patch("subprocess.Popen", return_value=proc):
            with patch.object(client, "_initialize", return_value=False):
                with patch.object(client, "stop") as mock_stop:
                    result = client.start()
        self.assertFalse(result)
        self.assertEqual(client.last_error, "Server initialization timed out or returned error")
        mock_stop.assert_called_once()

    def test_start_handles_popen_failure(self):
        client = MCPProcessClient("t", "echo")
        with patch("subprocess.Popen", side_effect=OSError("spawn failed")):
            with patch.object(client, "stop") as mock_stop:
                result = client.start()
        self.assertFalse(result)
        self.assertIn("Process start failed", client.last_error)
        mock_stop.assert_called_once()


class TestStartAsync(unittest.IsolatedAsyncioTestCase):
    async def test_start_async_success(self):
        client = MCPProcessClient("t", "echo", cwd=".", env={"A": "B"})
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin = MagicMock()
        proc.stdout = MagicMock()
        with patch("subprocess.Popen", return_value=proc):
            with patch.object(client, "_start_async_reader") as mock_reader:
                with patch.object(client, "_initialize_async", new=AsyncMock(return_value=True)):
                    result = await client.start_async()
        self.assertTrue(result)
        mock_reader.assert_called_once()

    async def test_start_async_already_running(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.poll.return_value = None
        client.process = proc
        with patch.object(client, "_start_async_reader") as mock_reader:
            result = await client.start_async()
        self.assertTrue(result)
        mock_reader.assert_called_once()

    async def test_start_async_init_failure_sets_last_error(self):
        client = MCPProcessClient("t", "echo")
        with patch("subprocess.Popen", return_value=MagicMock()):
            with patch.object(client, "_start_async_reader"):
                with patch.object(client, "_initialize_async", new=AsyncMock(return_value=False)):
                    with patch.object(client, "stop") as mock_stop:
                        result = await client.start_async()
        self.assertFalse(result)
        self.assertEqual(client.last_error, "Server initialization timed out or returned error")
        mock_stop.assert_called_once()

    async def test_start_async_handles_popen_failure(self):
        client = MCPProcessClient("t", "echo")
        with patch("subprocess.Popen", side_effect=OSError("spawn failed")):
            with patch.object(client, "stop") as mock_stop:
                result = await client.start_async()
        self.assertFalse(result)
        self.assertIn("Process start failed", client.last_error)
        mock_stop.assert_called_once()


class TestStop(unittest.TestCase):
    def test_stop_cancels_read_task_and_fails_pending_futures(self):
        client = MCPProcessClient("t", "echo")
        read_task = MagicMock()
        read_task.done.return_value = False
        client._read_task = read_task

        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            client._pending_futures = {1: fut}
            proc = MagicMock()
            client.process = proc
            client.stop()
            # stop() defers task-cancel/future-failure onto the loop via
            # call_soon_threadsafe; run a tick so those callbacks execute.
            loop.run_until_complete(asyncio.sleep(0))
        finally:
            loop.close()

        self.assertTrue(client._stopped)
        read_task.cancel.assert_called_once()
        self.assertTrue(fut.done())
        self.assertIsInstance(fut.exception(), RuntimeError)
        self.assertEqual(client._pending_futures, {})
        proc.terminate.assert_called_once()
        self.assertIsNone(client.process)

    def test_stop_terminates_process(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        client.process = proc
        client.stop()
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once_with(timeout=1)
        self.assertIsNone(client.process)

    def test_stop_handles_terminate_failure_with_kill(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stdin.close.side_effect = OSError("close failed")
        proc.terminate.side_effect = OSError("term failed")
        proc.wait.side_effect = OSError("wait failed")
        client.process = proc
        client.stop()
        proc.kill.assert_called_once()
        self.assertIsNone(client.process)

    def test_stop_handles_kill_failure(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.terminate.side_effect = OSError("term failed")
        proc.kill.side_effect = OSError("kill failed")
        client.process = proc
        client.stop()  # must not raise
        proc.kill.assert_called_once()
        self.assertIsNone(client.process)


class TestSend(unittest.TestCase):
    def test_send_without_process_is_noop(self):
        client = MCPProcessClient("t", "echo")
        client._send({"jsonrpc": "2.0", "id": 1})

    def test_send_without_stdin_is_noop(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin = None
        client._send({"jsonrpc": "2.0", "id": 1})


class TestReadResponse(unittest.TestCase):
    def test_read_response_without_process_returns_none(self):
        client = MCPProcessClient("t", "echo")
        self.assertIsNone(client._read_response(req_id=1, timeout=0.1))
        # _stopped -> immediate None
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._stopped = True
        self.assertIsNone(client._read_response(req_id=1, timeout=0.1))

    def test_read_response_returns_pending_response(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._pending_responses[1] = {"jsonrpc": "2.0", "id": 1, "result": {}}
        res = client._read_response(req_id=1)
        self.assertEqual(res["id"], 1)
        self.assertNotIn(1, client._pending_responses)

    def test_read_response_returns_pending_response_inside_loop(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        read_task = MagicMock()
        read_task.done.return_value = False
        client._read_task = read_task

        def fake_wait(timeout=None):
            client._pending_responses[1] = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
            return True

        with patch.object(client._response_event, "wait", side_effect=fake_wait):
            with patch("core.infrastructure.mcp.process_client.time.time", side_effect=[100.0, 100.0]):
                res = client._read_response(req_id=1, timeout=5.0)
        self.assertEqual(res["id"], 1)

    def test_read_response_read_task_timeout(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        read_task = MagicMock()
        read_task.done.return_value = False
        client._read_task = read_task
        with patch("core.infrastructure.mcp.process_client.time.time", side_effect=[100.0, 101.0]):
            res = client._read_response(req_id=1, timeout=1.0)
        self.assertIsNone(res)

    def test_read_response_loop_exits_when_stopped(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        read_task = MagicMock()
        read_task.done.return_value = False
        client._read_task = read_task

        def fake_wait(timeout=None):
            client._stopped = True
            return True

        with patch.object(client._response_event, "wait", side_effect=fake_wait):
            with patch("core.infrastructure.mcp.process_client.time.time", side_effect=[100.0, 100.0]):
                res = client._read_response(req_id=1, timeout=5.0)
        self.assertIsNone(res)

    def test_read_response_skips_non_json_buffer_lines(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._buffer = "some log line\n" + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"
        res = client._read_response(req_id=1, timeout=0.1)
        self.assertEqual(res["id"], 1)

    def test_read_response_notification_fetch_error_ignored(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._buffer = (
            json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
            + "\n"
        )
        with patch.object(client, "fetch_tools", side_effect=RuntimeError("boom")):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertEqual(res["id"], 1)

    def test_read_response_invalid_json_buffer_times_out(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._buffer = "{not json}\n"
        with patch("core.infrastructure.mcp.process_client.time.time", side_effect=[100.0, 100.6]):
            with patch("select.select", return_value=([], [], [])):
                res = client._read_response(req_id=1, timeout=0.5)
        self.assertIsNone(res)

    def test_read_response_select_error(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch("select.select", side_effect=OSError("select failed")),
        ):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)

    def test_read_response_stopped_after_select(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.fileno.return_value = 42

        def fake_select(*args, **kwargs):
            client._stopped = True
            return ([client.process.stdout], [], [])

        with patch("select.select", side_effect=fake_select):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)

    def test_read_response_select_empty_continues(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.fileno.return_value = 42
        data_line = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode() + b"\n"
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch("core.infrastructure.mcp.process_client.time.time", side_effect=[100.0, 100.0, 100.1]),
            patch("select.select", side_effect=[([], [], []), ([client.process.stdout], [], [])]),
            patch("os.read", return_value=data_line),
        ):
            res = client._read_response(req_id=1, timeout=5.0)
        self.assertEqual(res["id"], 1)

    def test_read_response_os_read_eof(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.fileno.return_value = 42
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch("select.select", return_value=([client.process.stdout], [], [])),
            patch("os.read", return_value=b""),
        ):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)

    def test_read_response_os_read_blocking_error_continues(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.fileno.return_value = 42
        data_line = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}).encode() + b"\n"
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch("select.select", return_value=([client.process.stdout], [], [])),
            patch("os.read", side_effect=[BlockingIOError(11, "again"), data_line]),
        ):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertEqual(res["id"], 1)

    def test_read_response_os_read_other_error(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.fileno.return_value = 42
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch("select.select", return_value=([client.process.stdout], [], [])),
            patch("os.read", side_effect=ValueError("weird")),
        ):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)

    def test_read_response_win32_readline(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.readline.return_value = json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n"
        with patch("core.infrastructure.mcp.process_client.sys.platform", "win32"):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertEqual(res["id"], 1)

    def test_read_response_win32_eof(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.readline.return_value = ""
        with patch("core.infrastructure.mcp.process_client.sys.platform", "win32"):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)

    def test_read_response_win32_error(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.readline.side_effect = OSError("boom")
        with patch("core.infrastructure.mcp.process_client.sys.platform", "win32"):
            res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)


class TestInitialize(unittest.TestCase):
    def _client_with_stdin(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin = MagicMock()
        return client

    def test_initialize_timeout(self):
        client = self._client_with_stdin()
        with patch.object(client, "_read_response", return_value=None):
            ok = client._initialize()
        self.assertFalse(ok)
        self.assertEqual(client.last_error, "Server did not respond to initialize request (timeout)")

    def test_initialize_error_response(self):
        client = self._client_with_stdin()
        res = {"jsonrpc": "2.0", "id": 1, "error": {"message": "bad protocol"}}
        with patch.object(client, "_read_response", return_value=res):
            ok = client._initialize()
        self.assertFalse(ok)
        self.assertEqual(client.last_error, "MCP init error: bad protocol")

    def test_initialize_error_response_non_dict(self):
        client = self._client_with_stdin()
        res = {"jsonrpc": "2.0", "id": 1, "error": "oops"}
        with patch.object(client, "_read_response", return_value=res):
            ok = client._initialize()
        self.assertFalse(ok)
        self.assertEqual(client.last_error, "MCP init error: oops")


class TestInitializeAsync(unittest.IsolatedAsyncioTestCase):
    async def _client_with_stdin(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.stdin = MagicMock()
        return client

    async def test_initialize_async_success(self):
        client = await self._client_with_stdin()
        res = {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
        with patch.object(client, "_send_request_async", new=AsyncMock(return_value=res)):
            with patch.object(client, "fetch_tools_async", new=AsyncMock()) as mock_fetch:
                ok = await client._initialize_async()
        self.assertTrue(ok)
        mock_fetch.assert_awaited_once()

    async def test_initialize_async_timeout(self):
        client = await self._client_with_stdin()
        with patch.object(client, "_send_request_async", new=AsyncMock(return_value=None)):
            ok = await client._initialize_async()
        self.assertFalse(ok)
        self.assertEqual(client.last_error, "Server did not respond to initialize request (timeout)")

    async def test_initialize_async_error(self):
        client = await self._client_with_stdin()
        res = {"jsonrpc": "2.0", "id": 1, "error": {"message": "nope"}}
        with patch.object(client, "_send_request_async", new=AsyncMock(return_value=res)):
            ok = await client._initialize_async()
        self.assertFalse(ok)
        self.assertEqual(client.last_error, "MCP init error: nope")


class TestCallTool(unittest.TestCase):
    def _client_with_process(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.poll.return_value = None
        client.process.stdin = MagicMock()
        return client

    def test_call_tool_non_text_content(self):
        client = self._client_with_process()
        res = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "image", "data": "abc"}]}}
        with patch.object(client, "_read_response", return_value=res):
            with patch.object(client, "fetch_tools"):
                out = client.call_tool("img", {})
        self.assertIn('"data": "abc"', out)

    def test_call_tool_fetch_tools_error_ignored(self):
        client = self._client_with_process()
        res = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}}
        with patch.object(client, "_read_response", return_value=res):
            with patch.object(client, "fetch_tools", side_effect=RuntimeError("boom")):
                out = client.call_tool("foo", {})
        self.assertEqual(out, "ok")

    def test_call_tool_empty_output_success_message(self):
        client = self._client_with_process()
        res = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}
        with patch.object(client, "_read_response", return_value=res):
            with patch.object(client, "fetch_tools"):
                out = client.call_tool("foo", {})
        self.assertEqual(out, "MCP tool 'foo' from server 't' executed successfully.")


class TestCallToolAsyncNoLoop(unittest.TestCase):
    def test_call_tool_async_falls_back_to_sync_without_loop(self):
        client = MCPProcessClient("t", "echo")
        client.call_tool = MagicMock(return_value="sync result")
        coro = client.call_tool_async("foo", {"a": 1}, timeout=2.0)
        try:
            coro.send(None)
            self.fail("expected StopIteration")
        except StopIteration as exc:
            result = exc.value
        self.assertEqual(result, "sync result")
        client.call_tool.assert_called_once_with("foo", {"a": 1}, timeout=2.0)


class TestCallToolAsync(unittest.IsolatedAsyncioTestCase):
    async def _client_with_process(self):
        client = MCPProcessClient("t", "echo")
        client.process = MagicMock()
        client.process.poll.return_value = None
        client.process.stdin = MagicMock()
        client._start_async_reader = MagicMock()
        return client

    async def test_call_tool_async_start_failure(self):
        client = MCPProcessClient("t", "echo")
        client.process = None
        with patch.object(client, "start_async", new=AsyncMock(return_value=False)):
            out = await client.call_tool_async("foo", {})
        self.assertIn("ERR: mcp 'foo': MCP server 't' process is not running", out)

    async def test_call_tool_async_success(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "hello"}]}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {"a": 1})
        self.assertEqual(out, "hello")

    async def test_call_tool_async_timeout(self):
        client = await self._client_with_process()
        out = await client.call_tool_async("foo", {}, timeout=0.01)
        self.assertIn("ERR: mcp 'foo': No response from MCP server 't'", out)
        self.assertNotIn(1, client._pending_futures)

    async def test_call_tool_async_write_error(self):
        client = await self._client_with_process()
        client.process.stdin.write.side_effect = OSError("pipe closed")
        out = await client.call_tool_async("foo", {})
        self.assertIn("ERR: mcp 'foo': failed to write to MCP server 't': pipe closed", out)

    async def test_call_tool_async_no_response(self):
        client = await self._client_with_process()

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(None)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {})
        self.assertIn("ERR: mcp 'foo': No response from MCP server 't'", out)

    async def test_call_tool_async_error_response(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "error": {"message": "bad args"}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {})
        self.assertIn("ERR: mcp 'foo': bad args", out)

    async def test_call_tool_async_error_response_non_dict(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "error": "oops"}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {})
        self.assertIn("ERR: mcp 'foo': oops", out)

    async def test_call_tool_async_result_is_error(self):
        # Per MCP spec, a result with isError: true is a tool-level failure even
        # though the JSON-RPC round-trip succeeded; it must be surfaced as ERR:.
        client = await self._client_with_process()
        resp = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"isError": True, "content": [{"type": "text", "text": "permission denied"}]},
        }

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {})
        self.assertEqual(out, "ERR: mcp 'foo': permission denied")

    async def test_call_tool_async_result_is_error_without_content(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": []}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {})
        self.assertEqual(out, "ERR: mcp 'foo': Tool reported isError without content")

    async def test_call_tool_async_non_text_content(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "image", "data": "img1"}]}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("img", {})
        self.assertIn('"data": "img1"', out)

    async def test_call_tool_async_fetch_tools_error_ignored(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": "ok"}]}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        with patch.object(client, "fetch_tools_async", new=AsyncMock(side_effect=RuntimeError("boom"))):
            out = await client.call_tool_async("foo", {})
        self.assertEqual(out, "ok")

    async def test_call_tool_async_empty_output_success_message(self):
        client = await self._client_with_process()
        resp = {"jsonrpc": "2.0", "id": 1, "result": {"content": []}}

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_result(resp)

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {})
        self.assertEqual(out, "MCP tool 'foo' from server 't' executed successfully.")


class TestProcessClientAsyncRegression(unittest.IsolatedAsyncioTestCase):
    async def test_async_read_loop_fails_pending_futures_on_eof(self):
        client = MCPProcessClient("test_srv", "echo")
        proc = MagicMock()
        proc.stdout.readline = MagicMock(side_effect=[b""])  # Immediate EOF
        client.process = proc

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending_futures[99] = fut

        read_task = asyncio.create_task(client._async_read_loop())
        with self.assertRaises(RuntimeError):
            await asyncio.wait_for(fut, timeout=2.0)
        self.assertTrue(fut.done())
        await read_task

    async def test_call_tool_async_cleans_pending_futures_on_cancellation(self):
        client = MCPProcessClient("test_srv", "echo")
        proc = MagicMock()
        proc.poll.return_value = None
        proc.stdin.write = MagicMock()
        proc.stdin.flush = MagicMock()
        client.process = proc

        # Force infinite wait on future to trigger cancellation
        with patch.object(client, "_start_async_reader"):
            task = asyncio.create_task(client.call_tool_async("tool1", {}, timeout=10.0))
            while not client._pending_futures:
                await asyncio.sleep(0)
            self.assertEqual(len(client._pending_futures), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(len(client._pending_futures), 0)

    async def test_stop_async(self):
        client = MCPProcessClient("test_srv", "echo")
        proc = MagicMock()
        proc.poll.return_value = None
        proc.pid = 12345
        proc.wait.return_value = 0
        client.process = proc

        await client.stop_async()
        self.assertTrue(client._stopped)
        self.assertIsNone(client.process)

    async def test_terminate_process_group_waits_after_kill(self):
        client = MCPProcessClient("test_srv", "echo")
        proc = MagicMock()
        proc.pid = 12345
        proc.terminate = MagicMock()
        proc.wait = MagicMock(side_effect=[Exception("timeout"), 0])
        proc.kill = MagicMock()
        client.process = proc

        with patch("sys.platform", "win32"):
            client._terminate_process_group()
            proc.kill.assert_called_once()
            self.assertEqual(proc.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
