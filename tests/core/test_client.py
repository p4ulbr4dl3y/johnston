from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from johnston.core.client import JohnstonClient
from johnston.core.dto import (
    CompactionResultDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    GitStateDTO,
    MessageDTO,
    ModelInfoDTO,
    ProviderDTO,
    RewindPointDTO,
    RuleDTO,
    SessionDTO,
    SessionSummaryDTO,
    SkillDTO,
    StreamEventDTO,
    ToolCallDTO,
    ToolResultDTO,
    TurnCompletedDTO,
)


class MockAgent:
    def __init__(self, steps: list[Any] | None = None) -> None:
        self.steps = steps or []
        self.model = "test-model"
        self.thinking_effort = "auto"
        self.reasoning_effort = "auto"
        self.sandbox_enabled = False
        self.worktree_branch = ""
        self.history: list[dict[str, Any]] = []
        self.tokens_input = 10
        self.tokens_output = 20
        self.total_tokens = 30
        self.cost_usd = 0.001

    async def stream_steps(self, prompt: str, attachments: list[Any] | None = None) -> AsyncIterator[Any]:
        for s in self.steps:
            yield s

    async def compact_history(self) -> tuple[bool, str]:
        return True, "History compacted (1,000 → 200 tokens)"


@pytest.fixture
def mock_pm() -> MagicMock:
    pm = MagicMock()
    pm.get_active_provider_key.return_value = "mock_provider"
    pm.get_provider_model.return_value = "mock-model"
    pm.create_agent_for_provider.return_value = MockAgent()
    pm.load_providers.return_value = {
        "mock_provider": {
            "name": "Mock Provider",
            "models": ["mock-model", "mock-model-2"],
            "enabled": True,
            "api_key": "secret",
        }
    }
    pdef = MagicMock()
    pdef.models = ["mock-model", "mock-model-2"]
    pm.load_provider_def.return_value = pdef
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
    store.list_main_sessions.return_value = [
        {
            "id": "session-test-123",
            "title": "Test Session",
            "created_at": 1000.0,
            "updated_at": 1100.0,
            "message_count": 2,
            "total_tokens": 150,
        }
    ]
    return store


def test_client_init_defaults(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    assert client.provider == "mock_provider"
    assert client.model == "mock-model"
    assert client.role == "worker"
    assert client.session_id == "session-test-123"
    assert client.agent is not None
    assert client.agent.model == "mock-model"


def test_client_init_explicit(mock_pm: MagicMock, mock_store: MagicMock):
    agent = MockAgent()
    client = JohnstonClient(
        provider="anthropic",
        model="claude-3-5-sonnet",
        role="reviewer",
        effort="high",
        sandbox=True,
        session_id="custom-sess-456",
        branch="feature/client",
        pm=mock_pm,
        store=mock_store,
        agent=agent,
    )
    assert client.provider == "anthropic"
    assert client.model == "claude-3-5-sonnet"
    assert client.role == "reviewer"
    assert client.session_id == "custom-sess-456"
    assert client.agent is agent
    assert agent.model == "claude-3-5-sonnet"
    assert agent.thinking_effort == "high"
    assert agent.reasoning_effort == "high"
    assert agent.sandbox_enabled is True
    assert agent.worktree_branch == "feature/client"


@pytest.mark.asyncio
async def test_client_stream_synthetic_steps(mock_pm: MagicMock, mock_store: MagicMock):
    steps = [
        ("content", "Hello "),
        ("content", "world!"),
        ("tool_call", "bash", {"cmd": "ls"}, "call_1"),
        ("tool_result", "file.txt", "bash", False, "done", 0),
    ]
    agent = MockAgent(steps=steps)
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)

    events: list[StreamEventDTO] = []
    async for evt in client.stream("hi"):
        events.append(evt)

    assert len(events) == 5
    assert isinstance(events[0], ContentDeltaDTO)
    assert events[0].text == "Hello "

    assert isinstance(events[1], ContentDeltaDTO)
    assert events[1].text == "world!"

    assert isinstance(events[2], ToolCallDTO)
    assert events[2].tool_name == "bash"
    assert events[2].args == {"cmd": "ls"}
    assert events[2].call_id == "call_1"

    assert isinstance(events[3], ToolResultDTO)
    assert events[3].tool_name == "bash"
    assert events[3].content == "file.txt"
    assert events[3].is_error is False
    assert events[3].returncode == 0

    assert isinstance(events[4], TurnCompletedDTO)
    assert events[4].usage["tokens_input"] == 10
    assert events[4].usage["tokens_output"] == 20


@pytest.mark.asyncio
async def test_client_stream_error_handling(mock_pm: MagicMock, mock_store: MagicMock):
    class ExplodingAgent:
        async def stream_steps(self, prompt: str):
            yield ("content", "starting...")
            raise RuntimeError("LLM exploded")

    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=ExplodingAgent())
    events = []
    async for evt in client.stream("test"):
        events.append(evt)

    assert len(events) == 2
    assert isinstance(events[0], ContentDeltaDTO)
    assert isinstance(events[1], ErrorEventDTO)
    assert "LLM exploded" in events[1].message


@pytest.mark.asyncio
async def test_client_stream_no_agent(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=None)
    client.agent = None

    events = []
    async for evt in client.stream("test"):
        events.append(evt)

    assert len(events) == 1
    assert isinstance(events[0], ErrorEventDTO)
    assert events[0].fatal is True


@pytest.mark.asyncio
async def test_client_prompt_accumulation(mock_pm: MagicMock, mock_store: MagicMock):
    steps = [
        ("content", "Hello "),
        ("content", "world!"),
        ("tool_call", "bash", {"cmd": "echo 123"}, "call_99"),
        ("tool_result", "123", "bash", False, "done", 0),
    ]
    agent = MockAgent(steps=steps)
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)

    turn = await client.prompt("test prompt")
    assert isinstance(turn, TurnCompletedDTO)
    assert turn.text == "Hello world!"
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].tool_name == "bash"
    assert turn.tool_calls[0].call_id == "call_99"
    assert turn.usage["tokens_input"] == 10


def test_client_get_sessions(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    sessions = client.get_sessions()
    assert len(sessions) == 1
    s = sessions[0]
    assert isinstance(s, SessionSummaryDTO)
    assert s.id == "session-test-123"
    assert s.title == "Test Session"
    assert s.message_count == 2
    assert s.token_count == 150


def test_client_get_session(mock_pm: MagicMock, mock_store: MagicMock):
    sess_mock = MagicMock()
    sess_mock.id = "session-test-123"
    sess_mock.title = "Detailed Session"
    sess_mock.created_at = 1000.0
    sess_mock.updated_at = 1100.0
    sess_mock.messages = [
        {"role": "user", "content": "Hello", "timestamp": 1001.0},
        {"role": "assistant", "content": "Hi there", "timestamp": 1002.0, "tool_calls": [{"name": "read_file"}]},
    ]
    mock_store.get.return_value = sess_mock

    client = JohnstonClient(pm=mock_pm, store=mock_store)
    dto = client.get_session("session-test-123")
    assert dto is not None
    assert isinstance(dto, SessionDTO)
    assert dto.id == "session-test-123"
    assert dto.title == "Detailed Session"
    assert len(dto.messages) == 2
    assert isinstance(dto.messages[0], MessageDTO)
    assert dto.messages[0].role == "user"
    assert dto.messages[0].content == "Hello"
    assert isinstance(dto.messages[1], MessageDTO)
    assert dto.messages[1].role == "assistant"
    assert len(dto.messages[1].tool_calls) == 1


@pytest.mark.asyncio
async def test_client_compact(mock_pm: MagicMock, mock_store: MagicMock):
    agent = MockAgent()
    client = JohnstonClient(pm=mock_pm, store=mock_store, agent=agent)

    res = await client.compact()
    assert isinstance(res, CompactionResultDTO)
    assert res.success is True
    assert res.tokens_before == 1000
    assert res.tokens_after == 200
    assert "compacted" in res.summary.lower()


@pytest.mark.asyncio
async def test_client_get_rewind_points(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    client.session.messages = [
        {"type": "user", "role": "user", "display_text": "First query"},
        {"type": "bot", "role": "assistant", "text": "Answer 1"},
        {"type": "user", "role": "user", "display_text": "Second query"},
    ]

    mock_entry_1 = MagicMock(index=0, text="First query", git_stats="+10 / -2", changed_files=["a.py"])
    mock_entry_2 = MagicMock(index=2, text="Second query", git_stats="diff unavailable", changed_files=[])

    with patch(
        "johnston.core.client.get_rewind_git_stats",
        new=AsyncMock(return_value=[mock_entry_1, mock_entry_2]),
    ):
        points = await client.get_rewind_points()

    assert len(points) == 2
    assert isinstance(points[0], RewindPointDTO)
    assert points[0].index == 0
    assert points[0].insertions == 10
    assert points[0].deletions == 2
    assert points[0].changed_files == ("a.py",)
    assert points[0].is_checkpoint_available is True

    assert points[1].index == 2
    assert points[1].insertions == 0
    assert points[1].deletions == 0
    assert points[1].is_checkpoint_available is False


def test_client_get_skills(mock_pm: MagicMock, mock_store: MagicMock):
    mock_sm = MagicMock()
    mock_skill_1 = MagicMock()
    mock_skill_1.name = "review"
    mock_skill_1.description = "Review code"
    mock_skill_1.location = "/skills/review/SKILL.md"
    mock_skill_1.hidden = False
    mock_skill_1.scope = MagicMock(value="project")
    mock_sm.list_skills.return_value = [mock_skill_1]

    with patch("johnston.core.client.get_skill_manager", return_value=mock_sm):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        skills = client.get_skills()

    assert len(skills) == 1
    assert isinstance(skills[0], SkillDTO)
    assert skills[0].name == "review"
    assert skills[0].description == "Review code"
    assert skills[0].path == "/skills/review/SKILL.md"
    assert skills[0].enabled is True
    assert skills[0].is_project is True


def test_client_get_rules(mock_pm: MagicMock, mock_store: MagicMock):
    mock_rm = MagicMock()
    mock_rule = MagicMock()
    mock_rule.name = "caveman"
    mock_rule.path = "/rules/caveman.md"
    mock_rule.content = "Speak like caveman."
    mock_rule.source = "global"
    mock_rm.load_rules.return_value = [mock_rule]

    with patch("johnston.core.client.RulesManager.get_instance", return_value=mock_rm):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        rules = client.get_rules()

    assert len(rules) == 1
    assert isinstance(rules[0], RuleDTO)
    assert rules[0].title == "caveman"
    assert rules[0].content_preview == "Speak like caveman."
    assert rules[0].scope == "global"


def test_client_get_providers(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    providers = client.get_providers()

    assert len(providers) == 1
    p = providers[0]
    assert isinstance(p, ProviderDTO)
    assert p.name == "Mock Provider"
    assert p.key == "mock_provider"
    assert p.is_configured is True
    assert len(p.models) == 2
    assert isinstance(p.models[0], ModelInfoDTO)
    assert p.models[0].name == "mock-model"
    assert p.models[0].provider == "mock_provider"


def test_client_get_git_state(mock_pm: MagicMock, mock_store: MagicMock):
    with patch("johnston.core.client.get_branch_info", return_value="main"), patch(
        "johnston.core.client.get_diff_stats", return_value="+5 / -1"
    ), patch(
        "subprocess.run",
        return_value=MagicMock(returncode=0, stdout=" M file1.py\n M file2.py\n"),
    ):
        client = JohnstonClient(pm=mock_pm, store=mock_store)
        git_state = client.get_git_state()
        assert isinstance(git_state, GitStateDTO)
        assert git_state.branch == "main"
        assert git_state.is_dirty is True
        assert git_state.changed_files == 2


def test_client_get_model_info(mock_pm: MagicMock, mock_store: MagicMock):
    client = JohnstonClient(pm=mock_pm, store=mock_store)
    info = client.get_model_info("openai", "gpt-4o")
    assert isinstance(info, ModelInfoDTO)
    assert info.name == "gpt-4o"
    assert info.provider == "openai"
    assert isinstance(info.supports_vision, bool)
    assert isinstance(info.supports_thinking, bool)


def test_architecture_zero_textual_imports():
    """Verify strictly 0 imports from textual or johnston.tui in client.py."""
    client_path = Path(__file__).resolve().parents[2] / "src" / "johnston" / "core" / "client.py"
    assert client_path.is_file(), f"File {client_path} does not exist"

    code = client_path.read_text(encoding="utf-8")
    tree = ast.parse(code, filename=str(client_path))

    forbidden_prefixes = ("textual", "johnston.tui")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                for prefix in forbidden_prefixes:
                    assert not alias.name.startswith(
                        prefix
                    ), f"Forbidden import found in client.py: import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for prefix in forbidden_prefixes:
                assert not mod.startswith(
                    prefix
                ), f"Forbidden import found in client.py: from {mod} import ..."
