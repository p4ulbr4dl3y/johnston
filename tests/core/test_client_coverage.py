"""Coverage-boost tests for johnston.core.client (error branches, edge cases).

Complements tests/core/test_client.py — focuses on previously uncovered
branches: lazy module helpers, init edge cases, stream fallbacks, session
sync/error paths, provider fallback branches, worktree forms, task statuses,
subagent kill paths and git-state exception handling. All mock-based.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from johnston.core.client import JohnstonClient
from johnston.core.dto import (
    ContentDeltaDTO,
    ErrorEventDTO,
    MessageDTO,
    TaskDTO,
    TurnCompletedDTO,
)
from johnston.core.infrastructure.platform.git_metrics import clear_git_metrics_cache
from johnston.core.infrastructure.tasks.task import TaskStatus


class MockAgent:
    def __init__(self, steps: list[Any] | None = None) -> None:
        self.steps = steps or []
        self.model = "test-model"
        self.thinking_effort = "auto"
        self.reasoning_effort = "auto"
        self.sandbox_enabled = False
        self.history: list[Any] = []
        self.tokens_input = 10
        self.tokens_output = 20
        self.total_tokens = 30
        self.cost_usd = 0.001

    async def stream_steps(self, prompt: str, attachments: list[Any] | None = None) -> AsyncIterator[Any]:
        for s in self.steps:
            yield s


@pytest.fixture
def mock_pm() -> MagicMock:
    pm = MagicMock()
    pm.get_active_provider_key.return_value = "mock_provider"
    pm.get_provider_model.return_value = "mock-model"
    pm.create_agent_for_provider.return_value = MockAgent()
    pm.load_providers.return_value = {}
    pm.load_provider_def.return_value = None
    pm.provider_needs_key.return_value = True
    pm.get_api_key.return_value = "secret"
    return pm


@pytest.fixture
def mock_store() -> MagicMock:
    store = MagicMock()
    store.generate_session_id.return_value = "session-test-123"
    sess = MagicMock()
    sess.id = "session-test-123"
    sess.title = "Test Session"
    sess.created_at = 1000.0
    sess.updated_at = 1100.0
    sess.messages = []
    sess.agent_history = []
    store.create_main.return_value = sess
    store.get.return_value = sess
    store.project_path = "/proj"
    return store


# ── Module-level helpers ─────────────────────────────────────────────────


def test_module_level_helpers():
    from johnston.core import client as cmod

    assert cmod.normalize_thinking_effort("HIGH") == "high"
    assert cmod.normalize_thinking_effort(None) is None
    assert cmod.display_thinking_effort("bogus") == "auto"
    assert cmod.process_carriage_returns("a\rline2\n") == "line2\n"
    assert cmod.strip_ansi("\x1b[31mred\x1b[0m") == "red"
    assert cmod.is_windows() is False
    assert cmod._parse_rewind_stat_numbers("") == (0, 0, True)

    with patch("johnston.core.application.session.facade.kill_subagent", return_value=True) as mkill:
        assert cmod.kill_subagent(MagicMock()) is True
        mkill.assert_called_once()
    with patch("johnston.core.application.session.facade._get_store", return_value="st") as mstore:
        assert cmod._get_store(None) == "st"
        mstore.assert_called_once()
    with patch("johnston.core.application.mcp.mcp_service.McpService", return_value="svc") as msvc:
        assert cmod.McpService("n", k=1) == "svc"
        msvc.assert_called_once_with("n", k=1)


# ── Init branches ────────────────────────────────────────────────────────


def test_client_init_without_provider_methods(mock_store: MagicMock):
    pm = MagicMock(spec=["load_providers"])
    client = JohnstonClient(pm=pm, store=mock_store)
    assert client.provider == ""
    assert client.model == ""
    assert client.agent is None


def test_client_init_non_string_model(mock_store: MagicMock):
    pm = MagicMock()
    pm.get_provider_model.return_value = {"name": "weird"}
    pm.create_agent_for_provider.return_value = MockAgent()
    client = JohnstonClient(provider="anthropic", pm=pm, store=mock_store)
    assert client.provider == "anthropic"
    assert client.model == ""
    assert client.agent is not None


def test_client_init_apply_role_failure(mock_pm: MagicMock, mock_store: MagicMock):
    with patch("johnston.core.client.apply_role", side_effect=RuntimeError("no such role")):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
    assert client.agent is not None  # role failure is swallowed with a debug log


def test_client_init_session_create_fallback(mock_pm: MagicMock, mock_store: MagicMock):
    mock_store.get.return_value = None
    client = JohnstonClient(pm=mock_pm, store=mock_store, session_id="custom")
    assert client.session is not None
    mock_store.create_main.assert_called_with(session_id="custom", role="worker")


def test_client_init_resumes_session_state(mock_pm: MagicMock, mock_store: MagicMock):
    sess = MagicMock()
    sess.id = "resume-1"
    sess.agent_history = [{"role": "user", "content": "hi"}]
    sess.messages = [{"role": "user", "content": "hi"}]
    sess.tokens_input = 100
    sess.tokens_output = 50
    sess.total_tokens = 150
    sess.cost_usd = 0.01
    mock_store.get.return_value = sess

    agent = MockAgent()
    agent.messages = []
    client = JohnstonClient(pm=mock_pm, store=mock_store, session_id="resume-1", agent=agent)
    assert client.agent.history == [{"role": "user", "content": "hi"}]
    assert client.agent.messages == [{"role": "user", "content": "hi"}]
    assert client.agent.tokens_input == 100
    assert client.agent.cost_usd == 0.01


# ── stream() edge cases ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_stream_no_stream_steps(mock_pm: MagicMock, mock_store: MagicMock):
    class NoStreamAgent:
        pass

    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=NoStreamAgent())
    events = [e async for e in client.stream("hi")]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEventDTO)
    assert events[0].fatal is True


@pytest.mark.asyncio
async def test_client_stream_attachments_typeerror_fallback(mock_pm: MagicMock, mock_store: MagicMock):
    class LegacyAgent:
        # Signature without the `attachments` kwarg: calling with attachments
        # raises TypeError at the call site, then fallback retries without.
        async def stream_steps(self, prompt: str):
            yield ("content", "fallback-ok")

    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=LegacyAgent())
    events = [e async for e in client.stream("hi", attachments=["a.txt"])]
    assert len(events) == 2
    assert isinstance(events[0], ContentDeltaDTO)
    assert events[0].text == "fallback-ok"
    assert isinstance(events[1], TurnCompletedDTO)


@pytest.mark.asyncio
async def test_client_stream_records_attachments(mock_pm: MagicMock, mock_store: MagicMock):
    agent = MockAgent(steps=[("content", "hi")])
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)
    events = [e async for e in client.stream("hello", attachments=["f1.txt"])]
    assert events
    last = client.session.messages[-1]
    assert last["attachments"] == ["f1.txt"]
    assert last["text"] == "hello"


@pytest.mark.asyncio
async def test_client_stream_dto_passthrough_and_sync(mock_pm: MagicMock, mock_store: MagicMock):
    class DtoAgent:
        async def stream_steps(self, prompt: str, attachments: list[Any] | None = None):
            yield ContentDeltaDTO(text="direct")
            yield TurnCompletedDTO(duration_s=2.5, usage={"total_tokens": 1})

    agent = DtoAgent()
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)
    client.agent.history = [{"role": "assistant", "content": "direct"}]
    client.agent.messages = [{"role": "assistant", "content": "direct"}]
    events = [e async for e in client.stream("hi")]
    # DTO steps pass through untouched; no synthetic TurnCompleted appended.
    assert len(events) == 2
    assert isinstance(events[0], ContentDeltaDTO)
    assert isinstance(events[1], TurnCompletedDTO)
    assert events[1].duration_s == 2.5
    assert client.session.agent_history == [{"role": "assistant", "content": "direct"}]
    assert client.session.messages == [{"role": "assistant", "content": "direct"}]


@pytest.mark.asyncio
async def test_client_stream_store_save_failure(mock_pm: MagicMock, mock_store: MagicMock):
    mock_store.save.side_effect = RuntimeError("disk full")
    agent = MockAgent(steps=[("content", "ok")])
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)
    events = [e async for e in client.stream("hi")]
    assert len(events) == 2  # content + synthetic completion; save failure swallowed


@pytest.mark.asyncio
async def test_client_stream_skips_duplicate_user_prompt(mock_pm: MagicMock, mock_store: MagicMock):
    agent = MockAgent(steps=[("content", "x")])
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)
    client.session.messages = [{"role": "user", "text": "same prompt"}]
    _ = [e async for e in client.stream("same prompt")]
    assert len(client.session.messages) == 1


# ── compact() edge cases ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_compact_no_agent(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    client.agent = None
    res = await client.compact()
    assert res.success is False
    assert res.error == "No active agent configured"


@pytest.mark.asyncio
async def test_client_compact_save_failure_and_error(mock_pm: MagicMock, mock_store: MagicMock):
    agent = MockAgent()
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)
    mock_store.save.side_effect = RuntimeError("disk full")

    outcome = SimpleNamespace(
        success=True,
        tokens=SimpleNamespace(before=10, after=4),
        title="Compacted",
        message="done",
    )

    async def fake_compact(agent, *, save_session_cb=None, **_kw):
        save_session_cb()  # triggers store.save which raises -> swallowed
        return outcome

    with patch("johnston.core.client.compact_session", new=fake_compact):
        res = await client.compact()
    assert res.success is True
    assert res.tokens_before == 10
    assert res.tokens_after == 4
    assert res.summary == "Compacted"

    async def bad_compact(agent, **kw):
        raise RuntimeError("compaction exploded")

    with patch("johnston.core.client.compact_session", new=bad_compact):
        res2 = await client.compact()
    assert res2.success is False
    assert res2.error == "compaction exploded"


@pytest.mark.asyncio
async def test_client_get_rewind_points_error(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch(
        "johnston.core.client.get_rewind_git_stats",
        new=AsyncMock(side_effect=RuntimeError("git unavailable")),
    ):
        points = await client.get_rewind_points()
    assert points == []


# ── Sessions ──────────────────────────────────────────────────────────────


def test_client_get_sessions_without_store():
    with patch("johnston.core.infrastructure.storage.session_store.SessionStore.get_instance", return_value=None):
        client = JohnstonClient(pm=MagicMock(spec=["load_providers"]), store=None)
    assert client.get_sessions() == []
    assert client.get_session("x") is None


def test_client_get_sessions_list_fallback_and_objects(mock_pm: MagicMock, mock_store: MagicMock):
    store = MagicMock()
    del store.list_main_sessions  # force the `list` fallback
    store.list.return_value = [
        {"id": "d1", "title": "Dict", "created_at": 1.0},
        SimpleNamespace(id="o1", title="Obj", created_at=2.0, updated_at=3.0, message_count=None, turn_count=5),
        SimpleNamespace(id="o2", title="", created_at=0.0, updated_at=0.0, message_count=0, token_count=7),
    ]
    client = JohnstonClient(pm=mock_pm, store=store)
    sessions = client.get_sessions()
    assert [s.id for s in sessions] == ["d1", "o1", "o2"]
    assert sessions[0].message_count == 0
    assert sessions[1].message_count == 5
    assert sessions[2].token_count == 7


def test_client_get_session_edge_cases(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    client.session_id = ""
    assert client.get_session() is None  # no target id

    mock_store.get.return_value = None
    assert client.get_session("missing") is None


def test_client_get_session_message_dto(mock_pm: MagicMock, mock_store: MagicMock):
    sess = MagicMock()
    sess.id = "s1"
    sess.title = "T"
    sess.created_at = 1.0
    sess.updated_at = 2.0
    sess.messages = [MessageDTO(role="user", content="hi", timestamp=1.5), {"role": "bot", "text": "yo"}]
    mock_store.get.return_value = sess
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    dto = client.get_session("s1")
    assert dto is not None
    assert dto.messages[0].content == "hi"
    assert dto.messages[1].content == "yo"


# ── Skills / rules / sandbox ─────────────────────────────────────────────


def test_client_toggle_skill(mock_pm: MagicMock, mock_store: MagicMock):
    sm = MagicMock()
    sm.toggle_hidden.return_value = True
    with patch("johnston.core.client.get_skill_manager", return_value=sm):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.toggle_skill("review") is True
    sm.toggle_hidden.assert_called_once_with("review")


def test_client_get_rules_long_preview(mock_pm: MagicMock, mock_store: MagicMock):
    rm = MagicMock()
    rule = MagicMock()
    rule.name = "long"
    rule.path = "/rules/long.md"
    rule.content = "x" * 150
    rule.source = "project"
    rm.load_rules.return_value = [rule]
    with patch("johnston.core.client.RulesManager.get_instance", return_value=rm):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        rules = client.get_rules()
    assert rules[0].content_preview == ("x" * 100) + "..."


def test_client_toggle_sandbox(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=MockAgent())
    with patch(
        "johnston.core.infrastructure.config.config_helpers.save_sandbox_config",
        side_effect=RuntimeError("config locked"),
    ):
        assert client.toggle_sandbox() is True
        assert client.sandbox is True
        assert client.agent.sandbox_enabled is True
        assert client.toggle_sandbox() is False
        assert client.agent.sandbox_enabled is False


# ── Providers ─────────────────────────────────────────────────────────────


def test_client_estimate_cost(mock_pm: MagicMock, mock_store: MagicMock):
    cat = MagicMock()
    cat.estimate_cost_from_totals.return_value = 2.5
    with patch("johnston.core.domain.policies.models_catalog.catalog", cat):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.estimate_cost("openai", "gpt-4o", 1000) == 2.5
    with patch("johnston.core.domain.policies.models_catalog.catalog", SimpleNamespace()):
        assert client.estimate_cost("openai", "gpt-4o", 1000) == 0.0


def test_client_get_providers_fallback_branches(mock_store: MagicMock):
    pm = MagicMock()
    pm.get_api_key.return_value = ""
    pm.load_providers.return_value = {
        "info_provider": {"name": "Info", "models": ["i1", "i2"], "api_key": "key-from-info"},
        "fallback_provider": {"name": "Fb"},
        "no_models": {"name": "Empty", "api_key": "k"},
        "anon": {},
    }
    pdef_fb = MagicMock()
    pdef_fb.name = "Fb"
    pdef_fb.enabled = False
    pdef_fb.models = None
    pdef_fb.models_fallback = MagicMock(return_value=["f1"])

    def load_def(key):
        return pdef_fb if key == "fallback_provider" else None

    pm.load_provider_def.side_effect = load_def

    client = JohnstonClient(provider="x", pm=pm, store=mock_store)
    providers = client.get_providers()
    by_key = {p.key: p for p in providers}

    assert [m.name for m in by_key["info_provider"].models] == ["i1", "i2"]
    assert by_key["info_provider"].is_configured is True  # api_key came from info dict

    assert [m.name for m in by_key["fallback_provider"].models] == ["f1"]
    assert by_key["fallback_provider"].is_disabled is True

    assert by_key["no_models"].models == []
    assert by_key["anon"].name == "anon"  # display name falls back to key


def test_client_get_providers_cache_hit(mock_store: MagicMock):
    pm = MagicMock()
    pm.get_api_key.return_value = ""
    pm.load_providers.return_value = {"cached_p": {"name": "C"}}
    pm.load_provider_def.return_value = None
    client = JohnstonClient(provider="x", pm=pm, store=mock_store)

    with patch("os.path.exists", return_value=True), patch(
        "johnston.core.infrastructure.platform.platform_utils.cached_json_read",
        return_value={"models": ["c1"]},
    ) as mread:
        providers = client.get_providers()
    assert [m.name for m in providers[0].models] == ["c1"]
    mread.assert_called_once()


def test_client_get_providers_cache_and_catalog_failures(mock_store: MagicMock):
    pm = MagicMock()
    pm.get_api_key.return_value = ""
    pm.load_providers.return_value = {
        "cache_bad": {"name": "CB"},
        "cat_ok": {"name": "CO"},
        "cat_bad": {"name": "CBad"},
    }
    pm.load_provider_def.return_value = None
    client = JohnstonClient(provider="x", pm=pm, store=mock_store)

    cat_models = {"cat_ok": {"models": ["cm1"]}}

    def get_cp(key):
        if key in cat_models:
            return cat_models[key]
        raise RuntimeError("no catalog entry")

    catalog_mock = SimpleNamespace(get_catalog_provider=get_cp)

    def fake_read(path, default):
        raise RuntimeError("no cache")

    with patch("os.path.exists", return_value=True), patch(
        "johnston.core.infrastructure.platform.platform_utils.cached_json_read", side_effect=fake_read
    ), patch("johnston.core.domain.policies.models_catalog.catalog", catalog_mock):
        providers = client.get_providers()

    by_key = {p.key: p for p in providers}
    assert by_key["cache_bad"].models == []
    assert [m.name for m in by_key["cat_ok"].models] == ["cm1"]
    assert by_key["cat_bad"].models == []


# ── Workspace roots / permissions ────────────────────────────────────────


def test_client_workspace_roots(mock_pm: MagicMock, mock_store: MagicMock):
    perm = MagicMock()
    perm.get_workspace_roots.return_value = ["/root/a", "/root/b"]
    with patch("johnston.core.application.permission.interactor.get_root_scope", return_value="primary"):
        client = JohnstonClient(pm=mock_pm, store=mock_store, perm_manager=perm)
        roots = client.get_workspace_roots()
    assert [r.path for r in roots] == ["/root/a", "/root/b"]
    assert all(r.scope == "primary" for r in roots)

    fallback_pm = MagicMock()
    fallback_pm.get_workspace_roots.return_value = ["/c"]
    with patch(
        "johnston.core.application.permission.permission_manager.PermissionManager.get_instance",
        return_value=fallback_pm,
    ), patch("johnston.core.application.permission.interactor.get_root_scope", return_value="session"):
        client2 = JohnstonClient(pm=mock_pm, store=mock_store)
        assert [r.path for r in client2.get_workspace_roots()] == ["/c"]


def test_client_permission_helpers(mock_pm: MagicMock, mock_store: MagicMock):
    with patch("johnston.core.application.permission.interactor.add_workspace_root") as m_add, patch(
        "johnston.core.application.permission.interactor.remove_workspace_root", return_value=True
    ), patch(
        "johnston.core.application.permission.interactor.get_root_scope", return_value="local"
    ), patch(
        "johnston.core.application.permission.interactor.build_permission_options",
        return_value=([("allow", "allow once")], "shell: *"),
    ) as m_build:
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        client.add_workspace_root("/x", scope="session")
        m_add.assert_called_with("/x", scope="session")
        assert client.remove_workspace_root("/x") is True
        assert client.get_root_scope("/x") == "local"
        opts, pat = client.build_permission_options("shell", {"cmd": "ls"}, server_name="srv")
        assert opts == [("allow", "allow once")]
        assert pat == "shell: *"
        m_build.assert_called_with("shell", {"cmd": "ls"}, "srv")


# ── Worktrees / merge ────────────────────────────────────────────────────


def test_client_list_worktrees(mock_pm: MagicMock, mock_store: MagicMock):
    items = [
        {"name": "main", "is_current": True, "is_worktree": False, "is_root": True, "path": "/repo"},
        {"name": "dev", "is_current": False, "is_worktree": True, "is_root": False, "path": "/repo/dev"},
        {"name": "feature", "is_current": False, "is_worktree": False, "is_root": False, "path": ""},
    ]
    with patch(
        "johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.list_branches_and_worktrees",
        return_value=items,
    ):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        dtos = client.list_worktrees("/proj")
    assert len(dtos) == 3
    assert dtos[0].name == "main" and dtos[0].is_root is True and dtos[0].is_current is True
    assert dtos[1].is_worktree is True
    assert dtos[2].path == ""


@pytest.mark.asyncio
async def test_client_list_worktrees_async(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch("johnston.core.client.JohnstonClient.list_worktrees", return_value=["x"]):
        assert await client.list_worktrees_async("/p") == ["x"]


def test_client_create_worktree_branches(mock_pm: MagicMock, mock_store: MagicMock):
    with patch(
        "johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.create_worktree",
        return_value=("/wt", "b"),
    ) as m_create, patch("os.path.exists", return_value=False):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        client.create_worktree(branch_name="feat", project_dir="/proj")
        client.create_worktree("/proj", "feat2")
        client.create_worktree("feat3", "/other/path")
        client.create_worktree("feat4", "feat5")
        client.create_worktree("solo")  # store.project_path fallback

    calls = m_create.call_args_list
    assert calls[0] == call("/proj", "feat", base_branch="HEAD")
    assert calls[1] == call("/proj", "feat2", base_branch="HEAD")
    assert calls[2] == call("/other/path", "feat3", base_branch="HEAD")
    assert calls[3] == call("feat4", "feat5", base_branch="HEAD")
    assert calls[4] == call("/proj", "solo", base_branch="HEAD")


@pytest.mark.asyncio
async def test_client_create_worktree_async(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch.object(client, "create_worktree", return_value=("/wt", "b")) as mc:
        assert await client.create_worktree_async("a", "b", branch_name="x") == ("/wt", "b")
    mc.assert_called_once()


def test_client_check_merge_conflicts_branches(mock_pm: MagicMock, mock_store: MagicMock):
    with patch(
        "johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.check_merge_conflicts",
        return_value=(True, ["a.py"]),
    ) as m_ck:
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.check_merge_conflicts(source="s", target="t", project_dir="/proj") == (True, ["a.py"])
        client.check_merge_conflicts("/proj", "s2", "t2")
        client.check_merge_conflicts("s3", "t3", "/proj2")
        client.check_merge_conflicts("s4", "t4")

    calls = m_ck.call_args_list
    assert calls[0] == call("/proj", "s", "t")
    assert calls[1] == call("/proj", "s2", "t2")
    assert calls[2] == call("/proj2", "s3", "t3")
    assert calls[3] == call("/proj", "s4", "t4")


@pytest.mark.asyncio
async def test_client_check_merge_conflicts_async(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch.object(client, "check_merge_conflicts", return_value=(False, [])):
        assert await client.check_merge_conflicts_async("a", "b") == (False, [])


def test_client_merge_branch_branches(mock_pm: MagicMock, mock_store: MagicMock):
    with patch(
        "johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.merge_branch",
        return_value=(True, "merged"),
    ) as m_merge:
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.merge_branch(source="s", target="t", project_dir="/proj") == (True, "merged")
        client.merge_branch("/proj", "s2", "t2")
        client.merge_branch("s3", "t3", "/proj2")
        client.merge_branch("s4", "t4")

    calls = m_merge.call_args_list
    assert calls[0] == call("/proj", "s", "t")
    assert calls[1] == call("/proj", "s2", "t2")
    assert calls[2] == call("/proj2", "s3", "t3")
    assert calls[3] == call("/proj", "s4", "t4")


@pytest.mark.asyncio
async def test_client_merge_branch_async(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch.object(client, "merge_branch", return_value=(True, "ok")):
        assert await client.merge_branch_async("a", "b") == (True, "ok")


def test_client_remove_worktree(mock_pm: MagicMock, mock_store: MagicMock):
    with patch(
        "johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.remove_worktree",
        return_value=True,
    ) as m_rm:
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.remove_worktree("/wt", "b", project_dir="/proj", delete_branch=True) is True
        client.remove_worktree("/wt2")  # store.project_path fallback
    assert m_rm.call_args_list[0] == call("/proj", "/wt", branch_name="b", delete_branch=True)
    assert m_rm.call_args_list[1] == call("/proj", "/wt2", branch_name="", delete_branch=False)


@pytest.mark.asyncio
async def test_client_remove_worktree_async(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch.object(client, "remove_worktree", return_value=True):
        assert await client.remove_worktree_async("/wt") is True


# ── Background tasks ─────────────────────────────────────────────────────


def _task(**kw) -> SimpleNamespace:
    base = dict(
        is_background=True,
        session_id="session-test-123",
        is_running=False,
        status=None,
        task_id="t",
        command="cmd",
        returncode=None,
        log_path="/tmp/l",
        created_at=None,
        completed_at=None,
        exit_code=None,
        was_killed=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_client_get_tasks(mock_pm: MagicMock, mock_store: MagicMock):
    now = time.time()
    tasks = [
        _task(task_id="running", is_running=True, created_at=now - 5),
        _task(task_id="killed", was_killed=True, exit_code=9, created_at=now - 10, completed_at=now - 1),
        _task(task_id="timeout", status=TaskStatus.TIMEOUT),
        _task(task_id="exited", exit_code=42),
        _task(task_id="exited_dur", status=TaskStatus.COMPLETED, exit_code=1, created_at=now - 10, completed_at=now - 1),
        _task(task_id="queued", status=TaskStatus.QUEUED),
        _task(task_id="other_sess", session_id="other"),
        _task(task_id="non_bg", is_background=False),
        _task(task_id="bad_ts", created_at="not-a-number"),
        _task(task_id="str_ts", created_at="123.5"),
    ]
    tm = MagicMock()
    tm.list.return_value = tasks
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    client.task_manager = tm

    dtos = client.get_tasks()
    assert len(dtos) == 8  # non_bg and other_sess filtered out
    by_id = {d.task_id: d for d in dtos}
    assert isinstance(by_id["running"], TaskDTO)
    assert by_id["running"].status == "RUNNING"
    assert by_id["running"].is_running is True
    assert by_id["running"].progress_badge != "running..."

    assert by_id["killed"].status == "FINISHED"
    assert by_id["killed"].progress_badge == "killed"
    assert by_id["timeout"].progress_badge == "timeout"
    assert by_id["exited"].progress_badge == "exit 42"
    assert by_id["exited_dur"].progress_badge.startswith("exit 1")
    assert by_id["queued"].progress_badge == "queued"

    assert by_id["bad_ts"].created_at == 0.0  # unparseable timestamp -> 0
    assert by_id["str_ts"].created_at == 123.5


def test_client_get_tasks_no_manager(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    assert client.get_tasks() == []


def test_client_get_task(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    assert client.get_task("x") is None  # no task manager

    tm = MagicMock()
    task = MagicMock(task_id="t1")
    tm.get.return_value = task
    client.task_manager = tm
    assert client.get_task("t1") is task

    client.task_manager = [SimpleNamespace(task_id="a"), SimpleNamespace(id="b")]
    assert client.get_task("b").id == "b"
    assert client.get_task("zzz") is None


@pytest.mark.asyncio
async def test_client_kill_task(mock_pm: MagicMock, mock_store: MagicMock):
    tm = MagicMock()
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    client.task_manager = tm

    awaitable_task = MagicMock()
    awaitable_task.is_running = True
    awaitable_task.kill = AsyncMock(return_value=True)
    tm.get.return_value = awaitable_task
    assert await client.kill_task("a") is True
    awaitable_task.kill.assert_awaited_once()

    sync_task = MagicMock()
    sync_task.is_running = True
    sync_task.kill = MagicMock(return_value=None)
    tm.get.return_value = sync_task
    assert await client.kill_task("b") is True

    idle_task = MagicMock()
    idle_task.is_running = False
    tm.get.return_value = idle_task
    assert await client.kill_task("c") is False


# ── Subagents ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_kill_subagent_non_string(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    sess_obj = MagicMock()
    with patch("johnston.core.application.session.facade.kill_subagent", return_value=True) as mkill:
        assert await client.kill_subagent(sess_obj) is True
    mkill.assert_called_with(sess_obj, app=None)


@pytest.mark.asyncio
async def test_client_kill_subagent_by_id(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch("johnston.core.application.session.facade.kill_subagent", return_value=True) as mkill, patch(
        "johnston.core.application.session.facade.list_subagent_sessions"
    ) as mlist:
        # found in parent-scoped list
        mlist.side_effect = [[MagicMock(id="s1"), MagicMock(id="s2")], []]
        assert await client.kill_subagent("s2") is True

        # found only in the global list
        mlist.side_effect = [[MagicMock(id="s1")], [MagicMock(id="s3")]]
        assert await client.kill_subagent("s3") is True

        # not found anywhere
        mlist.side_effect = [[], []]
        assert await client.kill_subagent("s9") is False

    assert mkill.call_count == 2


def test_client_list_subagent_sessions(mock_pm: MagicMock, mock_store: MagicMock):
    with patch("johnston.core.application.session.facade.list_subagent_sessions", return_value=["s1"]) as ml:
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.list_subagent_sessions() == ["s1"]
        ml.assert_called_with(parent_id="session-test-123", app=None)
        assert client.list_subagent_sessions("custom-pid") == ["s1"]
        ml.assert_called_with(parent_id="custom-pid", app=None)


def test_client_get_config_dir(mock_pm: MagicMock, mock_store: MagicMock):
    with patch("johnston.core.infrastructure.platform.paths.CONFIG_DIR", "/cfg"):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        assert client.get_config_dir() == "/cfg"


# ── Git state ────────────────────────────────────────────────────────────


def test_client_get_git_state_count_raises(mock_pm: MagicMock, mock_store: MagicMock):
    clear_git_metrics_cache()
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch("johnston.core.client.get_branch_info", return_value="main"), patch(
        "johnston.core.client.get_diff_metrics", return_value=SimpleNamespace(insertions=3, deletions=1)
    ), patch("johnston.core.client.get_diff_stats", return_value=""), patch(
        "johnston.core.client.get_changed_file_count", side_effect=RuntimeError("boom")
    ):
        st = client.get_git_state()
    assert st.is_dirty is True
    assert st.changed_files == 1
    clear_git_metrics_cache()


def test_client_get_git_state_zero_count(mock_pm: MagicMock, mock_store: MagicMock):
    clear_git_metrics_cache()
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch("johnston.core.client.get_branch_info", return_value="main"), patch(
        "johnston.core.client.get_diff_metrics", return_value=SimpleNamespace(insertions=2, deletions=0)
    ), patch("johnston.core.client.get_diff_stats", return_value=""), patch(
        "johnston.core.client.get_changed_file_count", return_value=0
    ):
        st = client.get_git_state()
    assert st.is_dirty is True
    assert st.changed_files == 1  # dirty with zero reported files -> 1
    assert st.insertions == 2
    clear_git_metrics_cache()


# ── Thinking effort ──────────────────────────────────────────────────────


def test_client_set_thinking_effort_with_app(mock_pm: MagicMock, mock_store: MagicMock):
    app = SimpleNamespace(agent=SimpleNamespace())
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    client.set_thinking_effort("Medium", app=app)
    assert app.agent.thinking_effort == "medium"
    assert app.agent.reasoning_effort == "medium"
    assert client.agent.thinking_effort == "medium"
    mock_pm.set_provider_thinking_effort.assert_called_with("mock_provider", "mock-model", "Medium")


# ── Lookups / checkpoints ────────────────────────────────────────────────


def test_client_resolve_session_by_title_global_fallback(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    mock_store.find_session_by_title_or_id.side_effect = [None, MagicMock(id="second")]
    with patch("johnston.core.application.session.facade.resolve_session_by_title", return_value=None):
        found = client.resolve_session_by_title("Some Title")
    assert found is not None
    assert found.id == "second"


def test_client_get_checkpoint_diff_no_manager(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    with patch("johnston.core.domain.ports.checkpoint.get_checkpoint_manager", return_value=None):
        assert client.get_checkpoint_diff("s1", 0) == []


def test_client_rewind_to_save_failure(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    mock_store.save.side_effect = RuntimeError("nope")

    def fake_rewind(agent, sid, pdir, user_msgs, idx, **kwargs):
        kwargs["save_session_cb"]()
        return True

    with patch("johnston.core.application.session.actions.rewind_session", new=fake_rewind):
        assert client.rewind_to(0) is True
