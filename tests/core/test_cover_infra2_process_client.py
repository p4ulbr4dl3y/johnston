"""Coverage-focused tests for MCPProcessClient. All mocks, no real processes."""

import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.infrastructure.mcp.process_client as core_infra_process_client
from core.infrastructure.mcp.process_client import MCPProcessClient


async def _make_client():
    client = MCPProcessClient("cov", "echo")
    return client


class TestCoverReaderMisc:
    def test_reader_thread_target_no_loop_or_stdout(self):
        client = MCPProcessClient("t", "echo")
        client._reader_loop = None
        client.process = None
        client._reader_thread_target()  # must not raise

    def test_spawn_reader_thread_when_alive(self):
        client = MCPProcessClient("t", "echo")
        thread = MagicMock()
        thread.is_alive.return_value = True
        client._reader_thread = thread
        client._spawn_reader_thread(MagicMock())
        thread.start.assert_not_called()

    def test_spawn_stderr_drain_no_process(self):
        client = MCPProcessClient("t", "echo")
        client._spawn_stderr_drain()

    def test_spawn_stderr_drain_thread_alive(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        client.process = proc
        thread = MagicMock()
        thread.is_alive.return_value = True
        client._stderr_thread = thread
        client._spawn_stderr_drain()
        thread.start.assert_not_called()

    def test_spawn_stderr_drain_stream_none(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stderr = None
        client.process = proc
        client._spawn_stderr_drain()

    def test_spawn_stderr_drain_fileno_raises(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stderr.fileno.side_effect = OSError("no fd")
        client.process = proc
        client._spawn_stderr_drain()
        assert client._stderr_thread is None

    def test_drain_stderr_stream_none(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stderr = None
        client.process = proc
        client._drain_stderr()

    def test_drain_stderr_readline_raises(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stderr.readline.side_effect = OSError("boom")
        client.process = proc
        client._drain_stderr()

    def test_join_stderr_thread_alive_logs(self):
        client = MCPProcessClient("t", "echo")
        thread = MagicMock()
        thread.is_alive.return_value = True
        client._stderr_thread = thread
        with patch("core.infrastructure.mcp.process_client.logger") as mock_logger:
            client._join_stderr_thread()
        mock_logger.debug.assert_called()
        assert client._stderr_thread is None

    def test_maybe_append_stderr_tail_with_tail(self):
        client = MCPProcessClient("t", "echo")
        client._stderr_tail.append("boom at runtime")
        client.last_error = "init failed"
        client._maybe_append_stderr_tail()
        assert "server stderr" in client.last_error


class TestCoverReadLoopCache:
    async def test_async_read_loop_caches_response_over_cap(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        resp = json.dumps({"jsonrpc": "2.0", "id": 900, "result": {"ok": True}}).encode("utf-8")
        proc.stdout.readline = MagicMock(side_effect=[resp, b""])
        client.process = proc
        client._pending_responses = {i: {"fake": i} for i in range(MCPProcessClient.MAX_PENDING_RESPONSES)}
        await client._async_read_loop()
        assert 900 in client._pending_responses
        assert len(client._pending_responses) == MCPProcessClient.MAX_PENDING_RESPONSES


class TestCoverPopenKwargs:
    def test_build_popen_kwargs_win32_creationflags(self):
        client = MCPProcessClient("t", ["node", "srv.js"], cwd="/tmp", env={"A": "1"})
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "win32"),
            patch.object(
                core_infra_process_client.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x08000000, create=True
            ),
        ):
            kwargs = client._build_popen_kwargs()
        assert kwargs["creationflags"] == 0x08000000
        assert kwargs["cwd"] == "/tmp"
        assert kwargs["env"]["A"] == "1"


class TestCoverCancelReadTask:
    def test_cancel_read_task_threadsafe_runtime_error(self):
        client = MCPProcessClient("t", "echo")
        task = MagicMock()
        task.done.return_value = False
        client._read_task = task
        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
        client._reader_loop = loop
        client._cancel_read_task_threadsafe()
        task.cancel.assert_called_once()


class TestCoverFailPendingFutures:
    async def test_fail_pending_futures_done_skipped_and_loop_error(self):
        client = MCPProcessClient("t", "echo")
        loop = asyncio.get_running_loop()
        done_fut = loop.create_future()
        done_fut.set_result(None)
        pending_fut = loop.create_future()
        client._pending_futures = {1: done_fut, 2: pending_fut}
        with patch.object(loop, "call_soon_threadsafe", side_effect=RuntimeError("closed")):
            client._fail_pending_futures()
        assert done_fut.done()
        assert pending_fut.done()
        assert isinstance(pending_fut.exception(), RuntimeError)


class TestCoverTerminate:
    def _base(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.pid = 12345
        client.process = proc
        return client, proc

    @pytest.mark.skipif(sys.platform == "win32", reason="os.killpg is POSIX-only")
    def test_terminate_posix_killpg_and_wait_fail(self):
        client, proc = self._base()
        proc.wait.side_effect = [OSError("w1"), OSError("w2")]
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch(
                "core.infrastructure.mcp.process_client.os.killpg", side_effect=[None, OSError("kill fail")]
            ) as killpg,
        ):
            client._terminate_process_group()
        assert killpg.call_count == 2

    def test_terminate_win32_kill_and_wait_fail(self):
        client, proc = self._base()
        proc.wait.side_effect = [OSError("w1"), OSError("w2")]
        proc.kill.side_effect = OSError("kill fail")
        with patch("core.infrastructure.mcp.process_client.sys.platform", "win32"):
            client._terminate_process_group()
        proc.kill.assert_called_once()

    @pytest.mark.skipif(sys.platform == "win32", reason="os.killpg is POSIX-only")
    def test_terminate_stream_none_skipped(self):
        client, proc = self._base()
        proc.stdout = None
        with (
            patch("core.infrastructure.mcp.process_client.sys.platform", "linux"),
            patch("core.infrastructure.mcp.process_client.os.killpg"),
        ):
            client._terminate_process_group()
        assert client.process is None

    def test_join_reader_thread_alive_logs(self):
        client = MCPProcessClient("t", "echo")
        thread = MagicMock()
        thread.is_alive.return_value = True
        client._reader_thread = thread
        with patch("core.infrastructure.mcp.process_client.logger") as mock_logger:
            client._join_reader_thread()
        mock_logger.debug.assert_called()
        assert client._reader_thread is None


class TestCoverSendAsync:
    async def test_send_async_no_process(self):
        client = MCPProcessClient("t", "echo")
        await client._send_async({"jsonrpc": "2.0", "id": 1})

    async def test_send_async_no_stdin(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.stdin = None
        client.process = proc
        await client._send_async({"jsonrpc": "2.0", "id": 1})


class TestCoverFetchAndStale:
    async def test_fetch_tools_async_sets_tools(self):
        client = MCPProcessClient("t", "echo")
        res = {"result": {"tools": [{"name": "x"}, {"name": "y"}]}}
        client._send_request_async = AsyncMock(return_value=res)
        tools = await client.fetch_tools_async()
        assert tools == [{"name": "x"}, {"name": "y"}]
        assert client.tools == tools

    def test_is_tools_stale(self):
        client = MCPProcessClient("t", "echo")
        client._tools_fetch_time = 90.0
        with patch("core.infrastructure.mcp.process_client.time.monotonic", return_value=100.0):
            assert client.is_tools_stale(ttl=5.0)


class TestCoverCallToolAsyncGenericError:
    async def test_call_tool_async_generic_exception(self):
        client = MCPProcessClient("t", "echo")
        proc = MagicMock()
        proc.poll.return_value = None
        client.process = proc
        client._start_async_reader = MagicMock()

        def on_write(line):
            req = json.loads(line)
            fut = client._pending_futures.get(req["id"])
            if fut and not fut.done():
                fut.set_exception(ValueError("bad thing"))

        client.process.stdin.write.side_effect = on_write
        out = await client.call_tool_async("foo", {}, timeout=2.0)
        assert "Error:" in out
