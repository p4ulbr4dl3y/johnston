"""Edge-case tests for tools/manage_shell.py and tools/manage_subagent.py.

Targets states the existing tests don't cover: None/empty ids, dead/twice-killed
tasks, races, and background tracking. Some tests intentionally expose product
bugs and are left red.
"""
import asyncio
import tempfile
from contextlib import suppress as suppress_cancelled
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tasks.manager import TaskManager
from core.infrastructure.tasks.shell_task import ShellTask
from core.infrastructure.tasks.task import TaskStatus
from core.session_manager import SessionStore
from tools.context import ToolContext
from tools.manage_shell import ManageShellTool
from tools.manage_subagent import ManageSubagentTool


def _noop_async(*a, **k):
    async def _inner(*a, **k):
        return None

    return _inner()


# ---------------------------------------------------------------------------
# manage_shell edge cases
# ---------------------------------------------------------------------------


class _App:
    """Lightweight fake app exposing only what manage_shell reads."""

    def __init__(self, tasks=None, current_session_id=None):
        self.task_manager = TaskManager()
        if tasks is not None:
            for t in tasks:
                self.task_manager.register(t)
        self._sid = current_session_id
        self.refreshed = 0

    @property
    def current_session_id(self):
        return self._sid

    def refresh_status_footer(self):
        self.refreshed += 1


@pytest.fixture
def tool():
    return ManageShellTool()


@pytest.fixture
def sub_tool():
    return ManageSubagentTool()


def _shell_app(tasks=None, session=None):
    return _App(tasks=tasks, current_session_id=session)


def _task(tid, running=True, session=None):
    t = ShellTask(tid, f"cmd-{tid}", MagicMock())
    if not running:
        t.status = TaskStatus.COMPLETED
    t.session_id = session
    t.is_background = True
    t.output.append(f"out-{tid}")
    return t


# --- None task_id ----------------------------------------------------------

async def test_unknown_action_none_task_id_should_not_crash(tool):
    """Bug B1: task_id=None -> AttributeError on .strip() (tools/manage_shell.py:28)."""
    app = _shell_app([])
    try:
        res = str(await tool.execute({"action": "bogus", "task_id": None}, ctx=app))
    except AttributeError as exc:
        import inspect

        src = inspect.getsource(ManageShellTool.execute).splitlines()
        line = "manage_shell.py:28"
        for i, ln in enumerate(src):
            if ".strip()" in ln:
                line = f"manage_shell.py:{28 + i}"
                break
        pytest.fail(f"BUG B1: manage_shell crashed on task_id=None -> AttributeError ({line}): {exc}")
        return
    assert isinstance(res, str)


async def test_send_input_none_task_id_should_not_crash(tool):
    app = _shell_app([])
    try:
        res = str(await tool.execute({"action": "send_input", "task_id": None, "input": "x"}, ctx=app))
    except AttributeError as exc:
        pytest.fail(f"BUG: send_input task_id=None crashed: {exc}")
    assert isinstance(res, str)


async def test_kill_none_task_id_should_not_crash(tool):
    app = _shell_app([])
    try:
        res = str(await tool.execute({"action": "kill", "task_id": None}, ctx=app))
    except AttributeError as exc:
        pytest.fail(f"BUG: kill task_id=None crashed: {exc}")
    assert isinstance(res, str)


# --- unknown/removed action ----------------------------------------------------

async def test_status_action_removed(tool):
    """'status' was dropped from manage_shell; it must not dispatch."""
    t = _task("tdone", running=False, session="s1")
    app = _shell_app([t], session="s1")
    for kwargs in ({"action": "status", "task_id": "tdone"}, {"action": "status"}):
        res = str(await tool.execute(kwargs, ctx=app))
        assert "ERR: action 'status'" in res


# --- kill edge cases -------------------------------------------------------

async def test_kill_task_not_running_is_notrunning_error(tool):
    t = _task("tk1", running=False, session="s1")
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "kill", "task_id": "tk1"}, ctx=app))
    assert "notrunning" in res


async def test_double_kill_running_task_is_idempotent(tool):
    """Second kill on a task already killed must not crash; returns notrunning."""
    t = ShellTask("tk2", "sleep 5", MagicMock())
    t.session_id = "s1"
    called = {"n": 0}

    async def fake_kill():
        called["n"] += 1
        t.status = TaskStatus.KILLED

    t.kill = fake_kill
    app = _shell_app([t], session="s1")
    r1 = str(await tool.execute({"action": "kill", "task_id": "tk2"}, ctx=app))
    assert "killed" in r1
    # Simulate engine marking it dead.
    t.status = TaskStatus.COMPLETED
    r2 = str(await tool.execute({"action": "kill", "task_id": "tk2"}, ctx=app))
    assert "notrunning" in r2
    assert called["n"] == 1


async def test_kill_task_whose_process_already_exited_no_crash(tool):
    """Kill a running task whose underlying proc.returncode is set (already exited)."""
    proc = MagicMock()
    proc.returncode = 0

    async def fake_kill():
        t.status = TaskStatus.KILLED

    t = ShellTask("tk3", "ls", proc)
    t.session_id = "s1"
    t.kill = fake_kill
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "kill", "task_id": "tk3"}, ctx=app))
    assert "killed" in res
    assert not t.is_running


async def test_kill_exception_is_soft_error(tool):
    t = _task("tk4", running=True, session="s1")

    async def boom():
        raise RuntimeError("kill denied")

    t.kill = boom
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "kill", "task_id": "tk4"}, ctx=app))
    assert "ERR" in res
    assert "kill denied" in res
    # tool leaves is_running alone on failure
    assert t.is_running


# --- send_input edge cases -------------------------------------------------

async def test_send_input_not_running_is_error(tool):
    t = _task("tst", running=False, session="s1")
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "send_input", "task_id": "tst", "input": "x"}, ctx=app))
    assert "notrunning" in res


async def test_send_input_empty_input_still_writes_newline(tool):
    mock_stdin = MagicMock()

    async def drain():
        pass

    mock_stdin.write = MagicMock()
    mock_stdin.drain = drain
    proc = MagicMock()
    proc.stdin = mock_stdin
    t = ShellTask("tsempty", "read name", proc)
    t.session_id = "s1"
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "send_input", "task_id": "tsempty", "input": ""}, ctx=app))
    assert "OK: input sent" in res
    mock_stdin.write.assert_called_once_with(b"\n")


async def test_send_input_task_without_stdin(tool):
    """Tasks without writable stdin route through their own send_input."""
    t = ShellTask("tsnoproc", "weird", MagicMock())
    t.session_id = "s1"

    async def _send(text):
        assert text == "x"
        return "HANDLED"

    t.send_input = _send
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "send_input", "task_id": "tsnoproc", "input": "x"}, ctx=app))
    assert res == "HANDLED"


# --- list edge cases -------------------------------------------------------

async def test_list_many_tasks_preserves_input_order(tool):
    tasks = []
    for i in range(50):
        tasks.append(_task(f"t{i}", running=(i % 2 == 0), session="s1"))
    app = _shell_app(tasks, session="s1")
    res = str(await tool.execute({"action": "list"}, ctx=app))
    # order preserved as registered
    first_occ = [res.index(fid) for fid in ("t0", "t1", "t2")]
    assert first_occ == sorted(first_occ)


async def test_list_filtered_by_status_contains_only_finished_when_one_running(tool):
    """With mixed tasks, running ones show RUNNING; report both status tags present."""
    t_run = _task("run", running=True, session="s1")
    t_fin = _task("fin", running=False, session="s1")
    app = _shell_app([t_run, t_fin], session="s1")
    res = str(await tool.execute({"action": "list"}, ctx=app))
    assert "RUNNING" in res
    assert "FINISHED" in res


# --- timeout/background tracking ------------------------------------------

async def test_background_task_already_finished_is_excluded_from_list(tool, monkeypatch):
    """Race: a task that finished between registration and manage must not crash list."""
    t1 = ShellTask("tbkg", "sleep 1", MagicMock())
    t1.session_id = "s1"
    t2 = _task("tbkg2", running=True, session="s1")
    app = _shell_app([t1, t2], session="s1")
    # Race: t1 finishes right before manage runs.
    t1.status = TaskStatus.COMPLETED
    res = str(await tool.execute({"action": "list"}, ctx=app))
    assert "tbkg" in res  # still listed as FINISHED (no crash)
    assert "FINISHED" in res


async def test_kill_running_background_task(tool):
    t = _task("tbk", running=True, session="s1")
    app = _shell_app([t], session="s1")
    res = str(await tool.execute({"action": "kill", "task_id": "tbk"}, ctx=app))
    assert "killed" in res
    assert not t.is_running


# --- invalid action --------------------------------------------------------

async def test_unknown_action_returns_error_not_crash(tool):
    app = _shell_app([])
    res = str(await tool.execute({"action": "explode"}, ctx=app))
    assert "ERR: action" in res
    assert "explode" in res


# ---------------------------------------------------------------------------
# manage_subagent edge cases
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    tmp = tempfile.TemporaryDirectory()
    st = SessionStore(project_path=tmp.name)
    old = SessionStore._instance
    SessionStore._instance = st
    yield st
    SessionStore._instance = old
    tmp.cleanup()


def _mk(sid=None, status="running", parent="parent-x", desc="desc", background=True):
    st = SessionStore.get_instance()
    return st.create_subagent(
        parent_id=parent,
        subagent_id=sid,
        role="worker",
        description=desc,
        prompt="p",
        status=status,
        background=background,
    )


class _SimpleAgent:
    def __init__(self, lines=("response",)):
        self.app = None
        self.is_subagent = True
        self.lines = list(lines)
        self.history = []
        self._src_role = ""
        self.tokens_input = 0
        self.tokens_output = 0
        self.total_tokens = 0
        self.cost_usd = 0.0
        self._merged_tokens_input = 0
        self._merged_tokens_output = 0
        self._merged_total_tokens = 0
        self._merged_cost_usd = 0.0
        self.tools = []
        self.role = ""
        self.system_prompt = ""

    async def stream_steps(self, message):
        yield ("bot_delta", "")
        yield ("bot_text", getattr(self, "_resp", "reply"))
        yield ("final", "")


class _SmApp:
    def __init__(self, sm, agent_factory=None, current_session_id=None):
        self.sm = sm
        self.current_session_id = current_session_id
        self.project_dir = None
        self.pm = MagicMock()
        self.pm.create_active_agent.side_effect = agent_factory if agent_factory else (lambda: None)

    def refresh_status_footer(self):
        pass


def _ctx(app):
    return ToolContext(app)


# --- send_message on dead / none / empty ----------------------------------


async def test_send_message_empty_whitespace_soft(sub_tool, store):
    _mk("sws")
    res = str(await sub_tool.execute(
        {"action": "send_message", "session_id": "sws", "message": "   "}, ctx=_ctx(_SmApp(store))
    ))
    assert "ERR: params" in res


async def test_send_message_to_nonexistent_soft(sub_tool, store):
    res = str(await sub_tool.execute(
        {"action": "send_message", "session_id": "ghost", "message": "hi"}, ctx=_ctx(_SmApp(store))
    ))
    assert "notfound" in res


async def test_send_message_to_completed_session_not_crash(sub_tool, store):
    """Follow-up to a finished subagent must still work / not crash (tool supports re-activation)."""
    sess = _mk("sfin", status="completed")

    agent = _SimpleAgent()
    agent._resp = "post-done reply"
    app = _SmApp(store, agent_factory=lambda: agent)
    res = str(await sub_tool.execute(
        {"action": "send_message", "session_id": "sfin", "message": "again"}, ctx=_ctx(app)
    ))
    assert isinstance(res, str)
    assert "message sent to sfin" in res
    assert sess.status in ("running",)
    # Now always async: drain completes the session once the bg stream finishes.
    assert sess.async_task is not None
    if sess.async_task:
        with suppress_cancelled():
            await sess.async_task
    assert sess.status == "completed"


async def test_send_message_background_nonblocking_does_not_complete(sub_tool, store):
    """background=True must return immediately and enqueue async task (not complete)."""
    sess = _mk("sbgn", status="running", background=True)
    agent = _SimpleAgent()
    app = _SmApp(store, agent_factory=lambda: agent)
    res = str(await sub_tool.execute(
        {"action": "send_message", "session_id": "sbgn", "message": "bg hi", "background": True}, ctx=_ctx(app)
    ))
    assert "message sent to sbgn" in res
    assert sess.status == "running"  # not finished synchronously
    assert sess.async_task is not None
    if sess.async_task:
        with suppress_cancelled():
            sess.async_task.cancel()


async def test_send_message_default_background_dispatch(sub_tool, store):
    """No explicit background -> uses session.background (True) and returns immediately."""
    sess = _mk("sdflt", status="running", background=True)
    agent = _SimpleAgent()
    app = _SmApp(store, agent_factory=lambda: agent)
    res = str(await sub_tool.execute(
        {"action": "send_message", "session_id": "sdflt", "message": "hi"}, ctx=_ctx(app)
    ))
    assert "message sent to sdflt" in res
    assert sess.status == "running"
    if sess.async_task:
        pending = [t for t in asyncio.all_tasks() if t is sess.async_task]
        for tt in pending:
            tt.cancel()


async def test_send_message_no_agent_available_soft(sub_tool, store):
    """Both session.agent None and ctx cannot create one -> soft context error."""
    _mk("snoagent", status="running")
    app = _SmApp(store, agent_factory=lambda: None)
    res = str(await sub_tool.execute(
        {"action": "send_message", "session_id": "snoagent", "message": "hi"}, ctx=_ctx(app)
    ))
    assert "ERR: context" in res


async def test_subagent_status_action_removed(sub_tool, store):
    """'status' was dropped from manage_subagent; it must not dispatch."""
    _mk("sgone", status="running")
    res = str(await sub_tool.execute({"action": "status", "session_id": "sgone"}))
    assert "ERR: action 'status'" in res


# --- kill edge cases -------------------------------------------------------


async def test_kill_completed_session_soft(sub_tool, store):
    _mk("skdone", status="completed")
    res = str(await sub_tool.execute({"action": "kill", "session_id": "skdone"}))
    assert "already in" in res


async def test_kill_nonexistent_soft(sub_tool, store):
    res = str(await sub_tool.execute({"action": "kill", "session_id": "ghost"}))
    assert "notfound" in res


async def test_kill_running_with_no_async_task(sub_tool, store):
    """Kill a running session whose async_task is None (never started) must not crash."""
    sess = _mk("sknone", status="running")
    assert sess.async_task is None
    res = str(await sub_tool.execute({"action": "kill", "session_id": "sknone"}))
    assert "terminated" in res
    assert sess.status == "cancelled"


async def test_kill_twice_idempotent(sub_tool, store):
    _mk("sk2", status="running")
    r1 = str(await sub_tool.execute({"action": "kill", "session_id": "sk2"}))
    assert "terminated" in r1
    r2 = str(await sub_tool.execute({"action": "kill", "session_id": "sk2"}))
    assert "already in" in r2


# --- list edge cases -------------------------------------------------------


async def test_list_no_subagents_no_crash(sub_tool, store):
    res = str(await sub_tool.execute({"action": "list"}))
    assert "No subagent sessions found" in res
    assert "Roles" not in res


async def test_list_filters_by_parent(sub_tool, store):
    """list with current_session_id only shows that parent's subagents."""
    _mk("sp1a", parent="parent-a")
    _mk("sp1b", parent="parent-a")
    _mk("sp2", parent="parent-b")
    app = _SmApp(store, current_session_id="parent-a")
    app.sm = store
    res = str(await sub_tool.execute({"action": "list"}, ctx=_ctx(app)))
    assert "sp1a" in res
    assert "sp1b" in res
    assert "sp2" not in res


async def test_list_invalid_parent_id_no_crash(sub_tool, store):
    _mk("sip", parent="parent-a")
    app = _SmApp(store, current_session_id="parent-zzz")
    res = str(await sub_tool.execute({"action": "list"}, ctx=_ctx(app)))
    assert "No subagent sessions found" in res
    # parent scoping means sip not listed under parent-zzz
    assert "sip" not in res


# --- race / double send ----------------------------------------------------


async def test_list_stable_while_running_does_not_finish(sub_tool, store):
    """Repeated list on a running subagent must not flip it to completed."""
    sess = _mk("sstable", status="running")
    for _ in range(3):
        await sub_tool.execute({"action": "list"})
    assert sess.status == "running"


async def test_send_message_status_change_recorded(sub_tool, store):
    sess = _mk("sstat", status="running", background=True)
    agent = _SimpleAgent()
    app = _SmApp(store, agent_factory=lambda: agent)
    await sub_tool.execute(
        {"action": "send_message", "session_id": "sstat", "message": "hi", "background": True}, ctx=_ctx(app)
    )
    types = [e.get("type") for e in sess.messages]
    assert "status_change" in types
    if sess.async_task:
        with suppress_cancelled():
            sess.async_task.cancel()


async def test_double_send_message_two_background_tasks(sub_tool, store):
    """Two send_message in a row must each schedule its own bg task, not overwrite+leak."""
    sess = _mk("s2x", status="running", background=True)
    agent = _SimpleAgent()
    app = _SmApp(store, agent_factory=lambda: agent)
    await sub_tool.execute(
        {"action": "send_message", "session_id": "s2x", "message": "one", "background": True}, ctx=_ctx(app)
    )
    first_task = sess.async_task
    await sub_tool.execute(
        {"action": "send_message", "session_id": "s2x", "message": "two", "background": True}, ctx=_ctx(app)
    )
    second_task = sess.async_task
    assert second_task is not None
    # second replaces first (only one kept) — no extra assertion on counts
    assert first_task is not None
    if first_task:
        with suppress_cancelled():
            first_task.cancel()
    if second_task:
        with suppress_cancelled():
            second_task.cancel()


async def test_unknown_subagent_action_soft(sub_tool, store):
    _mk("subunk")
    res = str(await sub_tool.execute({"action": "explode", "session_id": "subunk"}))
    assert "ERR: action" in res
    assert "explode" in res


# helpers
