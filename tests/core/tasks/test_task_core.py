"""Unit tests for the task-core module (core/tasks/).

Covers OutputBuffer formatting/streaming, ShellTask basic read/kill against a
real short subprocess, and SubagentTask mapping/kill over a mock AgentSession.
"""

import asyncio

import pytest

from core.tasks.events import TaskEvents
from core.tasks.manager import TaskManager
from core.tasks.output import OutputBuffer, process_carriage_returns, strip_ansi
from core.tasks.shell_task import ShellTask
from core.tasks.subagent_task import SubagentTask
from core.tasks.task import TASK_KINDS, TaskSnapshot, TaskStatus

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


@pytest.mark.asyncio
async def test_output_buffer_stream_yields_new_chunks():
    buf = OutputBuffer()
    received = []

    async def consume():
        async for chunk in buf.stream():
            received.append(chunk)

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    buf.append("chunk1")
    await asyncio.sleep(0)
    buf.append("chunk2")
    await asyncio.sleep(0)
    buf.close_stream()
    await consumer
    assert received == ["chunk1", "chunk2"]


# ---------------------------------------------------------------------------
# ShellTask
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shell_task_reads_real_echo():
    proc = await asyncio.create_subprocess_exec(
        "echo", "hello from shell",
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
        "sleep", "30", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    task = ShellTask(task_id="t2", command="sleep 30", process=proc)
    # No reading loop: the process is simply killed to check the terminal status.
    await task.kill()
    assert task.status == TaskStatus.KILLED
    assert not task.is_running


@pytest.mark.asyncio
async def test_shell_task_send_input_missing_stdin_reports_error():
    proc = await asyncio.create_subprocess_exec(
        "echo", "hi", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    task = ShellTask(task_id="t3", command="echo hi", process=proc)
    task.start_reading()
    await task.wait()
    res = await task.send_input("nope")
    assert "not running" in res


# ---------------------------------------------------------------------------
# SubagentTask
# ---------------------------------------------------------------------------


def make_session(status="running", messages=None):
    class _Sess:
        def __init__(self):
            self.id = "sub-1"
            self.kind = "subagent"
            self.status = status
            self.description = "test subagent"
            self.prompt = ""
            self.messages = messages or []
            self.async_task = None

        def finish(self, status, error_msg=""):
            self.status = status

        def to_dict(self):
            return {}

    return _Sess()


class _Store:
    def __init__(self):
        self.saved = []

    def save(self, sess):
        self.saved.append(sess)


def test_subagent_task_status_mapping():
    assert SubagentTask("s1", make_session(status="running")).status == TaskStatus.RUNNING
    assert SubagentTask("s2", make_session(status="completed")).status == TaskStatus.COMPLETED
    assert SubagentTask("s3", make_session(status="cancelled")).status == TaskStatus.KILLED
    assert SubagentTask("s4", make_session(status="error")).status == TaskStatus.ERROR


@pytest.mark.asyncio
async def test_subagent_task_kill_cancels_and_finishes():
    session = make_session(status="running")
    calls = []

    async def fake_task():
        calls.append("start")
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            calls.append("cancelled")
            raise

    task_obj = asyncio.create_task(fake_task())
    await asyncio.sleep(0)  # let fake_task reach its sleep point
    assert calls == ["start"]
    session.async_task = task_obj
    store = _Store()
    sub = SubagentTask("s5", session, store)
    assert sub.status == TaskStatus.RUNNING

    await sub.kill()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert task_obj.cancelled()
    assert "cancelled" in calls
    assert session.status == "cancelled"
    assert sub.status == TaskStatus.KILLED
    assert store.saved == [session]


@pytest.mark.asyncio
async def test_subagent_task_send_input_unsupported():
    sub = SubagentTask("s6", make_session(status="running"))
    assert "not supported" in await sub.send_input("x")


# ---------------------------------------------------------------------------
# TaskSnapshot / manager / events
# ---------------------------------------------------------------------------


def test_snapshot_fields():
    snap = TaskSnapshot(id="a", kind="shell", status_str="running", command="ls", is_running=True)
    assert snap.id == "a"
    assert snap.status_str == "running"
    assert snap.is_running is True


def test_task_kind_literals():
    assert ("shell", "subagent") == TASK_KINDS
    assert TaskStatus.RUNNING.value == "running"


@pytest.mark.asyncio
async def test_manager_register_drop_find():
    mgr = TaskManager()
    task = ShellTask(task_id="t1", command="echo hi")
    mgr.register(task)
    assert await mgr.find("t1") is task
    assert len(mgr.list()) == 1
    snap = mgr.list()[0]
    assert snap.id == "t1"


@pytest.mark.asyncio
async def test_manager_kill_all():
    proc = await asyncio.create_subprocess_exec(
        "sleep", "30", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    task = ShellTask(task_id="t9", command="sleep 30", process=proc)
    mgr = TaskManager()
    mgr.register(task)
    await mgr.kill_all()
    assert task.status == TaskStatus.KILLED


def test_events_on_completed_dispatches_handlers():
    events = TaskEvents()
    seen = []

    def h(task, result, error):
        seen.append((task, result, error))

    events.add_handler(h)
    events.on_completed("task", result="out", error=None)
    assert seen == [("task", "out", None)]
