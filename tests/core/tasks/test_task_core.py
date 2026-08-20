"""Unit tests for the task-core module (core/tasks/).

Covers OutputBuffer formatting/streaming, ShellTask basic read/kill against a
real short subprocess, and SubagentTask mapping/kill over a mock AgentSession.
"""

import asyncio
import os
import sys

import pytest

from core.infrastructure.tasks.manager import TaskManager
from core.infrastructure.tasks.output import OutputBuffer, process_carriage_returns, strip_ansi
from core.infrastructure.tasks.shell_task import ShellTask
from core.infrastructure.tasks.task import TASK_KINDS, TaskStatus

# ---------------------------------------------------------------------------
# OutputBuffer
# ---------------------------------------------------------------------------


def test_strip_ansi():
    text = "\x1b[31mred\x1b[0m \x1b[1mgreen\x1b[0m"
    assert strip_ansi(text) == "red green"


def test_process_carriage_returns_collapse():
    assert process_carriage_returns("a\rb\nc") == "b\nc"
    assert process_carriage_returns("") == ""


def test_output_buffer_formatted_caps_at_300kb():
    buf = OutputBuffer(byte_limit=300 * 1024)
    # Push chunks beyond the 300KB retained budget.
    big = "x" * 200 * 1024
    for _ in range(3):
        buf.append(big)
    text = buf.formatted()
    assert text.startswith("[Output truncated: showing recent output]\n")
    assert "x" in text
    # Retained size is bounded at the cap.
    assert buf.size_bytes <= 300 * 1024


def test_output_buffer_strips_ansi_and_collapses_cr():
    buf = OutputBuffer()
    buf.append("\x1b[32mline one\r\x1b[0mfinal\r\n")
    assert buf.formatted() == "final\n"


def test_output_buffer_tail():
    buf = OutputBuffer()
    buf.append("abcdefghij")
    assert buf.tail(5) == "fghij"


def test_output_buffer_history():
    buf = OutputBuffer()
    buf.append("a")
    buf.append("b")
    assert buf.history == ["a", "b"]


# ---------------------------------------------------------------------------
# ShellTask
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
async def test_shell_task_reads_real_echo():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('hello from shell')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    task = ShellTask(task_id="t1", command="echo hello", process=proc)
    task.start_reading()
    await task.wait()
    text = await task.read()
    assert "hello from shell" in text
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_shell_task_kill_sets_killed_status():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    task = ShellTask(task_id="t2", command="sleep 30", process=proc)
    # No reading loop: the process is simply killed to check the terminal status.
    await task.kill()
    assert task.status == TaskStatus.KILLED
    assert not task.is_running


@pytest.mark.slow
@pytest.mark.asyncio
async def test_shell_task_send_input_missing_stdin_reports_error():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('hi')", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    task = ShellTask(task_id="t3", command="echo hi", process=proc)
    task.start_reading()
    await task.wait()
    res = await task.send_input("nope")
    assert "not running" in res


@pytest.mark.asyncio
async def test_shell_task_move_to_background_sets_flag_and_event():
    task = ShellTask(task_id="t4", command="sleep 1", process=None)
    assert not task.is_background
    assert not task.background_event.is_set()

    task.move_to_background()

    assert task.is_background is True
    assert task.background_event.is_set()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_shell_task_on_completed_only_when_background():
    completed_calls = []

    def on_completed(tid, cmd, out):
        completed_calls.append((tid, cmd, out))

    # Foreground task: on_completed must NOT be called
    proc1 = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('foreground')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    task1 = ShellTask(task_id="fg_task", command="echo foreground", process=proc1)
    task1.start_reading(on_completed=on_completed)
    await task1.wait()
    assert len(completed_calls) == 0

    # Background task: on_completed MUST be called
    proc2 = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('background')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    task2 = ShellTask(task_id="bg_task", command="echo background", process=proc2)
    task2.is_background = True
    task2.start_reading(on_completed=on_completed)
    await task2.wait()
    assert len(completed_calls) == 1
    assert completed_calls[0][0] == "bg_task"
    assert "background" in completed_calls[0][2]


@pytest.mark.asyncio
async def test_shell_task_widget_streaming_appends_output():
    class DummyWidget:
        def __init__(self):
            self.received = []
            self.is_mounted = True

        def append_shell_output(self, text: str) -> None:
            self.received.append(text)

    widget = DummyWidget()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('widget hello')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    task = ShellTask(task_id="t5", command="echo widget hello", process=proc)
    task.add_listener(widget.append_shell_output)
    task.start_reading()
    await task.wait()

    chunks = "".join(widget.received)
    assert "widget hello" in chunks
    # Final empty flush signal is delivered after completion.
    assert "" in widget.received
    # ANSI-free output landed in the buffer too.
    text = await task.read()
    assert "widget hello" in text


@pytest.mark.asyncio
async def test_shell_task_widget_streaming_strips_ansi():
    class DummyWidget:
        def __init__(self):
            self.received = []
            self.is_mounted = True

        def append_shell_output(self, text: str) -> None:
            self.received.append(text)

    widget = DummyWidget()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", r"print('\x1b[31mcolored\x1b[0m text')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    task = ShellTask(task_id="t6", command="print ansi", process=proc)
    task.add_listener(widget.append_shell_output)
    task.start_reading()
    await task.wait()

    received = "".join(widget.received)
    assert "colored text" in received
    assert "\x1b" not in received
    # The buffer itself is ANSI-free too.
    text = await task.read()
    assert "colored text" in text
    assert "\x1b" not in text


@pytest.mark.asyncio
async def test_shell_task_listeners_are_isolated_and_removable():
    """Multiple listeners each get chunks; removal stops delivery to one only."""

    class DummyWidget:
        def __init__(self):
            self.received = []

        def append_shell_output(self, text: str) -> None:
            self.received.append(text)

    a, b = DummyWidget(), DummyWidget()
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('fanout')",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    task = ShellTask(task_id="t7", command="echo fanout", process=proc)
    task.add_listener(a.append_shell_output)
    task.add_listener(b.append_shell_output)
    task.add_listener(b.append_shell_output)  # idempotent
    task.remove_listener(a.append_shell_output)
    task.start_reading()
    await task.wait()

    assert "fanout" not in "".join(a.received)
    assert "fanout" in "".join(b.received)


# ---------------------------------------------------------------------------
# TaskStatus / manager / events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_task_file_log_writes_full_output(monkeypatch, tmp_path):
    """Background file log captures full output beyond the memory cap."""
    # Point the log helper into a tmp dir via its own module constant.
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))

    task = ShellTask(task_id="tlog", command="echo hi", process=None)
    path = task.open_log()
    assert path is not None
    # Log while "running"
    task.is_background = True
    task._log.append("hello from file log\n")
    task._log.append("line2\n")
    task._log.flush_now()
    content = open(task.log_path).read()
    assert "hello from file log" in content
    assert "line2" in content
    task.close_log()
    assert task.log_path is not None
    # file persists on disk after close
    assert "line2" in open(task.log_path).read()


@pytest.mark.asyncio
async def test_shell_task_open_log_twice_is_idempotent(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    task = ShellTask(task_id="tlog2", command="echo", process=None)
    p1 = task.open_log()
    p2 = task.open_log()
    assert p1 == p2
    task.close_log()


@pytest.mark.asyncio
async def test_shell_task_open_log_backfills_buffered_output(monkeypatch, tmp_path):
    """Late-opened log (e.g. timeout -> background) is not missing leading output."""
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    task = ShellTask(task_id="tlog3", command="echo", process=None)
    # Buffered output arrives before the log is opened.
    task.output.append("early line\n")
    task.output.append("mid line\n")

    path = task.open_log()
    assert path is not None
    content = open(task.log_path).read()
    assert "early line" in content
    assert "mid line" in content
    task.close_log()


# ---------------------------------------------------------------------------
# OutputLog
# ---------------------------------------------------------------------------


def test_output_log_streams_and_closes(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    log = _out.OutputLog.create("build")
    assert log.opened
    assert log.path and os.path.exists(log.path)
    log.append("chunk1\n")
    log.append("chunk2\n")
    log.close()
    assert not log.opened
    content = open(log.path).read()
    assert "chunk1\nchunk2\n" in content


def test_output_log_append_after_close_is_noop(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    log = _out.OutputLog.create("x")
    log.append("a\n")
    log.close()
    log.append("b\n")
    log.close()  # idempotent
    assert "a\n" in open(log.path).read()
    assert "b\n" not in open(log.path).read()


def test_output_log_create_failure_returns_closed_noop(monkeypatch):
    import core.infrastructure.tasks.output as _out

    def _boom(*_a, **_k):
        raise OSError("no permissions")

    monkeypatch.setattr(_out, "make_log_path", _boom)
    log = _out.OutputLog.create("x")
    assert not log.opened
    log.append("ignored")
    log.close()


def test_make_log_path_sanitizes_prefix(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    path = _out.make_log_path("some/project\\name")
    assert path is not None
    assert os.path.dirname(path) == str(tmp_path)
    assert "/" not in os.path.basename(path)
    assert "\\" not in os.path.basename(path)
    assert path.endswith(".log")


def test_make_log_path_non_unique_keeps_bare_prefix(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    path = _out.make_log_path("shell_1", unique=False)
    assert path == os.path.join(str(tmp_path), "shell_1.log")


def test_make_log_path_unique_adds_short_suffix(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    path = _out.make_log_path("shell", unique=True)
    base = os.path.basename(path)
    # {prefix}-{hex4}.log
    assert len(base) == len("shell") + 1 + 4 + len(".log")
    assert base.startswith("shell-")
    assert path.endswith(".log")


def test_make_log_path_caps_long_prefix(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    path = _out.make_log_path("x" * 200, unique=False)
    base = os.path.basename(path)
    assert len(base) == _out.MAX_LOG_PREFIX_CHARS + len(".log")


def test_make_log_path_custom_extension(monkeypatch, tmp_path):
    import core.infrastructure.tasks.output as _out

    monkeypatch.setattr(_out, "LOGS_DIR", str(tmp_path))
    path_md = _out.make_log_path("doc", ext=".md")
    assert path_md.endswith(".md")
    path_json = _out.make_log_path("data", unique=False, ext="json")
    assert path_json == os.path.join(str(tmp_path), "data.json")


@pytest.mark.asyncio
async def test_task_kind_literals():
    assert ("shell",) == TASK_KINDS
    assert TaskStatus.RUNNING.value == "running"


@pytest.mark.asyncio
async def test_manager_register_iterate_drop():
    mgr = TaskManager()
    task = ShellTask(task_id="t1", command="echo hi")
    mgr.register(task)
    assert len(list(mgr)) == 1
    assert list(mgr)[0].task_id == "t1"
    mgr.drop("t1")
    assert len(list(mgr)) == 0


@pytest.mark.asyncio
async def test_manager_kill_all():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "import time; time.sleep(30)", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    task = ShellTask(task_id="t9", command="sleep 30", process=proc)
    mgr = TaskManager()
    mgr.register(task)
    await mgr.kill_all()
    assert task.status == TaskStatus.KILLED
