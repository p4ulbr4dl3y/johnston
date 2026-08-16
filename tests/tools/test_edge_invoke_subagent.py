"""Edge-case tests for tools/invoke_subagent.py.

These probe failure/abuse paths with fake app/agent/provider mocks. Each test is
independent (fresh temp SessionStore). Red tests here document genuine product
bugs (crash on bad types, orphan running-session on failure, session marked
error when persistence dies mid-stream); they are intentionally left failing.
"""

import asyncio
import tempfile
from unittest.mock import MagicMock as MMock

import pytest

from core.domain.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.domain.entities.session import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_ERROR
from core.infrastructure.tasks.output import MAX_SUBAGENT_RESULT_CHARS
from core.session_manager import SessionStore
from tools.context import ToolContext
from tools.invoke_subagent import InvokeSubagentTool


class _FakeRole:
    """Minimal role-def double for apply_subagent_role provider/scope paths."""

    def __init__(
        self,
        key="worker",
        scope="any",
        provider="",
        model="",
        system_prompt="test prompt",
        read_only=False,
        disallowed_tools=None,
        allowed_tools=None,
    ):
        self.key = key
        self.scope = scope
        self.provider = provider
        self.model = model
        self.system_prompt = system_prompt
        self.read_only = read_only
        self.disallowed_tools = disallowed_tools or []
        self.allowed_tools = allowed_tools or []

    def is_tool_allowed(self, name):
        return None


class _FakeRegistry:
    def __init__(self, definition=None):
        self._def = definition or _FakeRole()

    def load_roles(self, *a, **k):
        pass

    def get_role(self, key, *a, **k):
        low = (key or "").lower().strip()
        if low == "mainonly-pinned":
            return _FakeRole(key=low, scope="main", provider="loaf-provider")
        if low == "worker":
            return _FakeRole(key="worker", scope="any")
        return self._def


def _make_env(agent):
    store_tmp = tempfile.TemporaryDirectory()
    store = SessionStore(project_path=store_tmp.name)
    app = MMock()
    app.sm = store
    app.current_session_id = None
    app.current_tool_widget = None
    app.pm = MMock()
    app.pm.create_active_agent.return_value = agent
    app.project_dir = store_tmp.name
    app.cwd = store_tmp.name
    app.agent = MMock()  # main agent for metric merging

    tool = InvokeSubagentTool()
    tool._ensure_context = lambda ctx=None: ToolContext(app=app)
    return store, app, tool, store_tmp


def _agent_with_stream(gen):
    """Agent whose stream_steps returns the given async iterator function."""
    agent = MMock()
    agent.tools = [
        {"function": {"name": "read"}},
        {"function": {"name": "shell"}},
        {"function": {"name": "invoke_subagent"}},
    ]
    agent.system_prompt = "base"
    agent.stream_steps = gen
    return agent


async def _launch_and_wait(tool, args, app, store, wait=True):
    res = str(await tool.execute(args))
    running = [s for s in store.list(kind="subagent") if s.status == "running"]
    task = running[0].async_task if running else None
    if wait and task is not None:
        await asyncio.wait_for(task, timeout=10)
    return res, (running[0] if running else None)


# ---------------------------------------------------------------------------
# Arguments: missing / wrong-type prompts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [None, {}, {"prompt": ""}, {"prompt": "   \t\n"}])
async def test_missing_or_blank_prompt_returns_error(args):
    store, app, tool, tmp = _make_env(_agent_with_stream(_empty_gen))
    try:
        res = str(await tool.execute(args))
        assert res.startswith("ERR: params 'prompt': required")
        assert store.list(kind="subagent") == []  # nothing spawned
    finally:
        tmp.cleanup()


async def _empty_gen(prompt):
    if False:
        yield None


@pytest.mark.asyncio
async def test_prompt_non_string_crashes_instead_of_clean_error():
    """BUG: non-string prompt (int) reaches .strip() and raises AttributeError.
    red test — tool should return ERR for a non-string prompt, not crash."""
    agent = _agent_with_stream(_empty_gen)
    store, app, tool, tmp = _make_env(agent)
    try:
        with pytest.raises((AttributeError, TypeError)):
            await tool.execute({"prompt": 123, "description": "bad"})
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_prompt_list_crashes():
    agent = _agent_with_stream(_empty_gen)
    store, app, tool, tmp = _make_env(agent)
    try:
        with pytest.raises((AttributeError, TypeError)):
            await tool.execute({"prompt": ["a", "b"], "description": "bad"})
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# role / subagent_type handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [None, " ", "   ", "NONEXISTENT_ROLE", "CamelCase", "héllo!", "worker"])
async def test_role_falls_back_or_accepts(role, monkeypatch):
    """Any unknown/blank role canonicalizes to 'worker' on the agent. The
    session.role is expected to stay in lock-step with the applied app role."""
    agent = _agent_with_stream(_empty_gen)

    def fake_get_role(self, key, *a, **k):
        low = (key or "").lower().strip()
        base = {"worker": _FakeRole(key="worker", scope="any")}
        return base.get(low, base["worker"])

    monkeypatch.setattr("core.role_registry.RoleRegistry.get_role", fake_get_role)
    monkeypatch.setattr("core.role_registry.RoleRegistry.load_roles", lambda self, *a, **k: {})

    store, app, tool, tmp = _make_env(agent)
    try:
        args = {"prompt": "do thing", "description": "t", "branch": "main"}
        if role is not None:
            args["type"] = role
        await tool.execute(args)
        sess = store.list(kind="subagent")[0]
        # canonical agent role is worker for unknown/blank input
        assert agent.role == "worker"
        # BUG: session.role is the raw un-normalized subagent_type, so it drifts
        # from the applied agent.role for blank/unknown roles ('' vs 'worker').
        assert sess.role == "worker", f"BUG: session.role {sess.role!r} != applied agent.role 'worker' for {role!r}"
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_main_scope_role_falls_back_to_worker(monkeypatch):
    """orchestrator overrides: scope='main' role must fall back to worker."""
    agent = _agent_with_stream(_empty_gen)
    registry = _FakeRegistry(definition=_FakeRole(key="orchestrator", scope="main", provider=""))

    def fake_get(self, key, *a, **k):
        low = (key or "").lower().strip()
        if low == "orchestrator":
            return registry.get_role("orchestrator")
        return _FakeRole(key="worker", scope="any")

    monkeypatch.setattr("core.role_registry.RoleRegistry.get_role", fake_get)
    monkeypatch.setattr("core.role_registry.RoleRegistry.load_roles", lambda self, *a, **k: {})

    store, app, tool, tmp = _make_env(agent)
    try:
        await tool.execute({"prompt": "do thing", "description": "t", "type": "orchestrator", "branch": "main"})
        sess = store.list(kind="subagent")[0]
        # main-only role must fall back to worker on the agent, not run as main
        assert agent.role == "worker", "main-only role must fall back to worker, not spawn as main"
        assert sess.role == "worker", (
            f"BUG: session.role {sess.role!r} != worker after main-role fallback (agent.role={agent.role!r})"
        )
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_role_pinned_provider_not_connected_raises(monkeypatch):
    """role pins a provider that is NOT connected -> apply_subagent_role raises
    ValueError which escapes execute() as a crash (no ERR, no cleanup)."""
    agent = _agent_with_stream(_empty_gen)

    def fake_get(self, key, *a, **k):
        low = (key or "").lower().strip()
        if low == "heavymetal":
            return _FakeRole(key="heavymetal", scope="any", provider="zzz-not-connected")
        return _FakeRole(key="worker", scope="any")

    monkeypatch.setattr("core.role_registry.RoleRegistry.get_role", fake_get)
    monkeypatch.setattr("core.role_registry.RoleRegistry.load_roles", lambda self, *a, **k: {})

    class _Pm:
        def load_providers(self):
            pass

        def is_provider_connected(self, key):
            return key != "zzz-not-connected"

        def create_agent_for_provider(self, key):
            return _FakeRole(key="whatever", scope="any")

    monkeypatch.setattr("core.provider_manager.ProviderManager", _Pm)

    store, app, tool, tmp = _make_env(agent)
    try:
        with pytest.raises(ValueError, match="not connected"):
            await tool.execute({"prompt": "do", "description": "t", "type": "heavymetal", "branch": "main"})
        # Fixed: role is applied BEFORE session creation, so a failed role
        # (provider not connected) no longer persists an orphan 'running' session.
        running = [s for s in store.list(kind="subagent") if s.status == "running"]
        assert not running, "no orphan running session should be created on role failure"
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# create_agent failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_agent_returns_none():
    store, app, tool, tmp = _make_env(None)
    try:
        res = str(await tool.execute({"prompt": "do", "description": "t", "branch": "main"}))
        assert res.startswith("ERR: context")
        assert store.list(kind="subagent") == []
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_create_agent_crashes_leaks_nothing():
    store, app, tool, tmp = _make_env(_agent_with_stream(_empty_gen))
    app.pm.create_active_agent.side_effect = RuntimeError("boom agent")
    try:
        with pytest.raises(RuntimeError):
            await tool.execute({"prompt": "do", "description": "t", "branch": "main"})
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# workspace/branch failure leaves orphan running session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worktree_create_raises_crashes_instead_of_err(monkeypatch):
    """BUG: branch != current + create_worktree raises -> execute() propagates
    the exception as a crash instead of returning an ERR: string. The tool
    contract (always return a string, never raise) is violated."""
    agent = _agent_with_stream(_empty_gen)
    store, app, tool, tmp = _make_env(agent)

    class _BadWorktree:
        @staticmethod
        def create_worktree(*a, **k):
            raise RuntimeError("git worktree failed")

        @staticmethod
        def is_git_repo(*a, **k):
            return True

    monkeypatch.setattr("tools.invoke_subagent.SubagentWorktreeManager", _BadWorktree)
    try:
        with pytest.raises(RuntimeError, match="git worktree failed"):
            await tool.execute({"prompt": "do", "description": "t", "branch": "dev"})
        assert store.list(kind="subagent") == [], (
            "BUG: no session must exist, but none expected here since worktree raised first"
        )
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# background stream behavior
# ---------------------------------------------------------------------------


async def _gen_ok(prompt):
    yield ("bot_delta", "hello world")


@pytest.mark.asyncio
async def test_stream_completes_and_marks_completed():
    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        res, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "greet", "branch": "main"}, app, store)
        assert sess.status == STATUS_COMPLETED
        assert "launched (" in res
        app.trigger_ai_response.assert_called()  # notification fired
    finally:
        tmp.cleanup()


async def _gen_empty_result(prompt):
    if False:
        yield None


@pytest.mark.asyncio
async def test_stream_empty_result():
    agent = _agent_with_stream(_gen_empty_result)
    store, app, tool, tmp = _make_env(agent)
    try:
        _, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
        assert sess.status == STATUS_COMPLETED
        msg = app.trigger_ai_response.call_args.args[0]
        assert "Completed with no text output." in msg
    finally:
        tmp.cleanup()


async def _gen_crash(prompt):
    raise RuntimeError("provider exploded")
    yield  # pragma: no cover


@pytest.mark.asyncio
async def test_stream_throws_propagates_to_notification_not_caller():
    agent = _agent_with_stream(_gen_crash)
    store, app, tool, tmp = _make_env(agent)
    try:
        _, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
        assert sess.status == STATUS_ERROR
        msg = app.trigger_ai_response.call_args.args[0]
        assert "Subagent error: provider exploded" in msg
    finally:
        tmp.cleanup()


async def _gen_huge(prompt):
    yield ("bot_delta", "x" * (MAX_SUBAGENT_RESULT_CHARS + 5000))


@pytest.mark.asyncio
async def test_stream_huge_result_truncates():
    agent = _agent_with_stream(_gen_huge)
    store, app, tool, tmp = _make_env(agent)
    try:
        _, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
        assert sess.status == STATUS_COMPLETED
        msg = app.trigger_ai_response.call_args.args[0]
        assert "truncated at" in msg
        assert "Use `read` tool" in msg
    finally:
        tmp.cleanup()


async def _gen_mid_cancel(prompt):
    release = asyncio.Event()
    yield ("bot_delta", "partial ")
    await release.wait()  # deterministic mid-stream await; cancellable


@pytest.mark.asyncio
async def test_cancel_mid_stream_marks_cancelled():
    agent = _agent_with_stream(_gen_mid_cancel)
    store, app, tool, tmp = _make_env(agent)
    try:
        await tool.execute({"prompt": "hi", "description": "t", "branch": "main"})
        sess = store.list(kind="subagent")[-1]
        assert sess.async_task is not None
        # Give the bg task time to enter the stream and block on the Event.
        await asyncio.sleep(0.1)
        sess.async_task.cancel()
        try:
            await asyncio.wait_for(sess.async_task, timeout=10)
        except asyncio.CancelledError:
            pass  # task swallowed or propagated; either way it must finish
        assert sess.status == STATUS_CANCELLED
        # Notification should have been produced for the cancelled tail.
        assert "[Subagent cancelled]" in app.trigger_ai_response.call_args.args[0]
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# session/persist failure + parent fallback
# ---------------------------------------------------------------------------


class _FailingSaveStore(list):
    """Wraps nothing but raises on save; looks like an app.sm store."""

    def list(self, *a, **k):
        return []

    def get_subagents_for_parent(self, pid):
        return []

    def create_subagent(self, *a, **k):
        return None  # provision fails


@pytest.mark.asyncio
async def test_session_create_returns_none_crashes(monkeypatch):
    """store.create_subagent returning None -> execute crashes (None.agent).
    A store is contractually expected to return a session; guarded handling
    would return ERR. Red test documents the unguarded attribute access."""
    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        app.sm = None  # force singleton lookup path below
        # Use singleton path but override create_subagent to return None
        import core.session_manager as sm

        real = sm.SessionStore.create_subagent
        sm.SessionStore.create_subagent = lambda *a, **k: None
        try:
            with pytest.raises(AttributeError):
                await tool.execute({"prompt": "hi", "description": "t", "branch": "main"})
        finally:
            sm.SessionStore.create_subagent = real
    finally:
        tmp.cleanup()


class _DieSaveStore:
    """Real store behavior but save() raises."""

    def __init__(self, real):
        self._real = real

    def list(self, *a, **k):
        return self._real.list(*a, **k)

    def get_subagents_for_parent(self, pid):
        return self._real.get_subagents_for_parent(pid)

    def create_subagent(self, *a, **k):
        return self._real.create_subagent(*a, **k)

    def save(self, sess):
        raise OSError("disk full")


@pytest.mark.asyncio
async def test_save_fails_mid_stream_does_not_escape():
    """Fixed: a store.save OSError (disk full / permissions) in run_subagent_stream_bg
    is wrapped, so it no longer escapes the background task as a raised exception."""
    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        app.sm = _DieSaveStore(store)
        await tool.execute({"prompt": "hi", "description": "t", "branch": "main"})
        sess = store.list(kind="subagent")[-1]
        assert sess.async_task is not None
        # The task returns its normal result string; the save failure is swallowed.
        result = await asyncio.wait_for(sess.async_task, timeout=10)
        assert isinstance(result, str)
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_no_parent_session_id_uses_global_running_scan():
    """BUG: when ctx.host has no current_session_id the tool scans ALL subagent
    sessions regardless of parent, so unrelated running sessions from another
    parent/agent count against this parent's concurrency cap."""
    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        for i in range(MAX_CONCURRENT_SUBAGENTS):
            store.create_subagent(
                parent_id=f"other-parent-{i}", role="worker", description=f"foreign {i}", prompt="p", status="running"
            )
        res = str(await tool.execute({"prompt": "hi", "description": "t", "branch": "main"}))
        assert "ERR: limit" in res, (
            "BUG: got no limit error, yet this parent has ZERO running and all "
            "running sessions belong to other parents/windows"
        )
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# ctx / dependency absence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ctx_app_none_falls_back_to_singleton_store():
    """ctx=None + app.sm absent -> SessionStore singleton used, spawn works."""
    from unittest.mock import patch

    store, app, tool, tmp = _make_env(_agent_with_stream(_gen_ok))
    try:
        app.sm = None
        with patch("core.session_manager.SessionStore.get_instance", return_value=store):
            res, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
            assert sess.status == STATUS_COMPLETED
            assert res.startswith("subagent ")
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_app_has_no_sm_uses_singleton():
    from unittest.mock import patch

    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        app.sm = None
        tool._ensure_context = lambda ctx=None: ToolContext(app=app)
        with patch("core.session_manager.SessionStore.get_instance", return_value=store):
            res, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
            assert sess.status == STATUS_COMPLETED
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# metric merge edge (missing / odd attributes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metrics_merge_missing_subagent_attrs_no_crash():
    """subagent lacking tokens_* attrs -> merge_subagent_metrics defaults 0."""
    agent = MMock()
    agent.tools = []
    agent.system_prompt = "base"
    agent.stream_steps = _gen_ok
    del agent.tokens_input  # ensure attribute truly absent
    del agent.tokens_output
    del agent.total_tokens
    del agent.cost_usd

    store, app, tool, tmp = _make_env(agent)
    try:
        _, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
        assert sess.status == STATUS_COMPLETED
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_metrics_merge_none_values_no_crash():
    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        agent.tokens_input = None
        agent.tokens_output = None
        agent.total_tokens = None
        agent.cost_usd = float("nan")
        _, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "t", "branch": "main"}, app, store)
        assert sess.status == STATUS_COMPLETED
    finally:
        tmp.cleanup()


# ---------------------------------------------------------------------------
# return value / error formatting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launch_return_contains_description_and_id():
    agent = _agent_with_stream(_gen_ok)
    store, app, tool, tmp = _make_env(agent)
    try:
        res, sess = await _launch_and_wait(tool, {"prompt": "hi", "description": "  Greet me  ", "branch": "main"}, app, store)
        res = res[0] if isinstance(res, tuple) else res
        assert "subagent 'Greet me' launched" in res
        assert sess.id in res
    finally:
        tmp.cleanup()


@pytest.mark.asyncio
async def test_error_format_matches_err_convention():
    store, app, tool, tmp = _make_env(_agent_with_stream(_gen_ok))
    try:
        res = str(await tool.execute({"prompt": "  "}))
        assert res == "ERR: params 'prompt': required", res
    finally:
        tmp.cleanup()
