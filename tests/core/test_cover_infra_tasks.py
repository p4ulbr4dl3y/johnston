"""Coverage tests for core/infrastructure/tasks/shell_task.py and output.py edge paths.

Uses lightweight mocks / Monaco'd readers so these run quickly and in isolation
(no real long-running subprocesses except where trivially safe). Mirrors the
existing tasks/test_task_core.py style.
"""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

import core.infrastructure.tasks.output as _out
from core.infrastructure.tasks.output import OutputBuffer, process_carriage_returns
from core.infrastructure.tasks.shell_task import ShellTask

# ---------------------------------------------------------------------------
# output.py
# ---------------------------------------------------------------------------


def test_process_carriage_returns_spinner_collapse():
    text = process_carriage_returns("-\n/\n")
    assert text == "/\n"


def test_output_buffer_empty_chunk_and_len():
    buf = OutputBuffer()
    buf.append("")
    assert len(buf) == 0
    buf.append("abc")
    assert len(buf) == 3


def test_make_log_path_makedirs_failure(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise OSError("no dir")

    monkeypatch.setattr(_out.os, "makedirs", _boom)
    assert _out.make_log_path("x") is None


def test_output_log_constructor_open_failure(tmp_path):
    log = _out.OutputLog(str(tmp_path))  # opening a directory as a file fails
    assert not log.opened
    log.append("ignored")
    log.close()


def test_output_log_worker_swallows_write_flush_close_errors(monkeypatch, tmp_path):
    class BadFile:
        def __init__(self):
            self.closed = False

        def write(self, item):
            raise OSError("write fail")

        def flush(self):
            raise OSError("flush fail")

        def close(self):
            raise OSError("close fail")

    fake_open = MagicMock()
    fake_open.return_value = BadFile()
    monkeypatch.setattr("builtins.open", fake_open)

    log = _out.OutputLog(str(tmp_path / "x.log"))
    assert log.opened
    log.append("a\n")  # worker write path -> raises -> swallowed
    log.close()  # sentinel -> flush/close raise -> swallowed
    assert not log.opened


def test_output_log_append_none_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    log = _out.OutputLog.create("nl")
    try:
        with pytest.raises(TypeError):
            log.append(None)
    finally:
        log.close()


def test_output_log_flush_now_noop_when_closed(tmp_path):
    log = _out.OutputLog("")  # no file/thread -> flush_now returns
    log.flush_now()
    assert not log.opened


def test_output_log_context_manager(monkeypatch, tmp_path):
    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    with _out.OutputLog.create("ctx") as log:
        log.append("x\n")
    assert not log.opened


# ---------------------------------------------------------------------------
# shell_task.py
# ---------------------------------------------------------------------------


def test_shell_task_repr_and_open_log_failure(monkeypatch):
    task = ShellTask(task_id="t0", command="echo hi")
    assert repr(task).startswith("ShellTask(")

    class Closed:
        opened = False
        path = ""

    monkeypatch.setattr("core.infrastructure.tasks.shell_task.OutputLog.create", lambda _tid: Closed())
    assert task.open_log() is None
    assert task._log is None


def test_notify_listeners_swallows_callback_errors():
    task = ShellTask(task_id="t3", command="echo")

    def bad(text):
        raise RuntimeError("listener fail")

    calls = []
    task._listeners = [bad, lambda t: calls.append(t)]
    task._notify_listeners("hi")
    assert calls == ["hi"]


@pytest.mark.asyncio
async def test_read_no_source_breaks_immediately():
    task = ShellTask(task_id="t4", command="echo", process=None)
    task.start_reading()
    await task.wait()
    assert task._status.value == "completed"  # _mark_terminated ran via finally


@pytest.mark.asyncio
async def test_read_bad_chunk_type_hits_outer_except():
    class FakeProc:
        def __init__(self):
            self.stdout = AsyncMock()
            self.stdout.read = AsyncMock(return_value="not-bytes")  # decode_output raises -> outer except swallows
            self.returncode = 0

    task = ShellTask(task_id="t5", command="echo", process=FakeProc())
    task.start_reading()
    await task.wait()
    assert task._status.value == "completed"

@pytest.mark.asyncio
async def test_read_process_returncode_access_raises():
    class FakeProcess:
        def __init__(self):
            self.stdout = AsyncMock()
            self.stdout.read = AsyncMock(return_value=b"")

        @property
        def returncode(self):
            raise OSError("rc boom")

    proc = FakeProcess()
    task = ShellTask(task_id="t6", command="echo", process=proc)
    task.start_reading()
    await task.wait()
    assert task._status.value == "completed"


@pytest.mark.asyncio
async def test_read_on_completed_raises_is_swallowed():
    proc = MagicMock()
    proc.stdout.read = AsyncMock(return_value=b"")
    proc.returncode = None
    proc.wait = AsyncMock(return_value=0)

    def on_completed(*a):
        raise RuntimeError("on_completed fail")

    task = ShellTask(task_id="t7", command="echo", process=proc)
    task.is_background = True
    task.start_reading(on_completed=on_completed)
    await task.wait()
    assert task._status.value == "completed"


@pytest.mark.asyncio
async def test_tail_returns_buffered_output():
    task = ShellTask(task_id="t8", command="echo")
    task.output.append("abcdefghij")
    assert await task.tail(5) == "fghij"


@pytest.mark.asyncio
async def test_send_input_stdin_not_writable():
    task = ShellTask(task_id="t10", command="echo")
    task.process = None
    res = await task.send_input("x")
    assert "stdin not writable" in res


@pytest.mark.asyncio
async def test_send_input_stdin_write_raises():
    task = ShellTask(task_id="t11", command="echo")
    proc = MagicMock()
    proc.stdin.write = MagicMock(side_effect=OSError("write fail"))
    task.process = proc
    res = await task.send_input("x")
    assert "send input" in res


@pytest.mark.asyncio
async def test_kill_sync_process_kill_raises_and_cancels_read_task():
    task = ShellTask(task_id="t12", command="echo")
    proc = MagicMock()
    proc.pid = None  # skip killpg
    proc.kill.side_effect = AttributeError("no kill")
    task.process = proc
    task.read_task = asyncio.create_task(asyncio.sleep(5))
    task.kill_sync()
    await asyncio.sleep(0)  # let the cancellation be observed
    assert task.read_task.cancelled()
    assert task._status.value == "killed"


@pytest.mark.skipif(sys.platform == "win32", reason="os.killpg is POSIX-only")
@pytest.mark.asyncio
async def test_kill_sync_killpg_raises(monkeypatch):
    task = ShellTask(task_id="t13", command="echo")
    proc = MagicMock()
    proc.pid = 99999
    task.process = proc

    def _boom(pgid, sig):
        raise OSError("killpg fail")

    monkeypatch.setattr("core.infrastructure.tasks.shell_task.os.killpg", _boom)
    task.kill_sync()
    assert task._status.value == "killed"


if __name__ == "__main__":
    pytest.main([__file__])
