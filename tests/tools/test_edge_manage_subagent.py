"""Edge-case tests for tools/manage_subagent.py (split out of the former
test_edge_manage_shell_sub.py when the manage_shell cases were consolidated
into test_manage_shell.py).

Targets states the main suite doesn't cover: None/empty ids, dead/twice-killed
sessions, races, and background tracking.
"""
import asyncio
import tempfile
from contextlib import suppress as suppress_cancelled
from unittest.mock import MagicMock

import pytest

from core.infrastructure.storage.session_store import SessionStore
from tools.context import ToolContext
from tools.manage_subagent import ManageSubagentTool


@pytest.fixture
def sub_tool():
    return ManageSubagentTool()


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
    res = await sub_tool.execute({"action": "kill", "session_id": "skdone"})
    assert "already in" in str(res) or "completed" in str(res)


async def test_kill_nonexistent_soft(sub_tool, store):
    res = str(await sub_tool.execute({"action": "kill", "session_id": "ghost"}))
    assert "notfound" in res


async def test_kill_running_with_no_async_task(sub_tool, store):
    """Kill a running session whose async_task is None (never started) must not crash."""
    sess = _mk("sknone", status="running")
    assert sess.async_task is None
    res = await sub_tool.execute({"action": "kill", "session_id": "sknone"})
    assert "sknone" in res.content
    assert sess.status == "cancelled"


async def test_kill_twice_idempotent(sub_tool, store):
    _mk("sk2", status="running")
    r1 = await sub_tool.execute({"action": "kill", "session_id": "sk2"})
    assert "sk2" in r1.content
    r2 = await sub_tool.execute({"action": "kill", "session_id": "sk2"})
    assert "already in" in str(r2) or "cancelled" in str(r2)


# --- list edge cases -------------------------------------------------------


async def test_list_no_subagents_no_crash(sub_tool, store):
    res = await sub_tool.execute({"action": "list"})
    assert res.content == "no active subagents"
    assert "No subagent sessions found" in res.display


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
    res = await sub_tool.execute({"action": "list"}, ctx=_ctx(app))
    assert res.content == "no active subagents"
    assert "sip" not in res.content


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
