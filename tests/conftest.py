"""Shared pytest fixtures and builders for the Johnston test suite.

Home for reusable building blocks (mock app / agent / orchestrator / ToolContext)
so individual test clusters can stop hand-rolling MagicMock boilers. Consumers get
the builders via factory fixtures (e.g. ``app = make_app_mock()``) — no import needed.
The private ``_make_*`` functions back them and are importable directly if a test
cluster prefers ``from tests.conftest import ...``.
"""

import tempfile
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.context import ToolContext

DEFAULT_TOOLS: List[Dict[str, Any]] = [
    {"function": {"name": "read"}},
    {"function": {"name": "shell"}},
    {"function": {"name": "edit"}},
    {"function": {"name": "create"}},
]


# --------------------------------------------------------------------------- #
# Builders (private functions — exposed via factory fixtures below)
# --------------------------------------------------------------------------- #

def _make_agent_mock(
    role: str = "worker",
    model: str = "deepseek-v4-flash",
    provider_key: str = "openai",
    tools: List[Dict[str, Any]] | None = None,
    **overrides: Any,
) -> MagicMock:
    """Build a MagicMock agent with the standard fields tests rely on.

    ``stream_steps`` is an ``AsyncMock``; ``tools``/``system_prompt`` default to
    sensible values so tools like invoke_subagent can inspect them. Pass any extra
    kwargs to override or extend the mock (e.g. ``app=...``, ``is_subagent=True``).
    """
    agent = MagicMock()
    agent.role = role
    agent.model = model
    agent.provider_key = provider_key
    agent.stream_steps = AsyncMock()
    agent.tools = list(tools) if tools is not None else list(DEFAULT_TOOLS)
    agent.system_prompt = ""
    for key, value in overrides.items():
        setattr(agent, key, value)
    return agent


def _make_orchestrator_mock(**overrides: Any) -> MagicMock:
    """Build a MagicMock orchestrator agent (an agent with role='orchestrator')."""
    return _make_agent_mock(role="orchestrator", **overrides)


def _make_pm_mock(agent: MagicMock | None = None, **overrides: Any) -> MagicMock:
    """Build a MagicMock provider manager with the standard wiring."""
    pm = MagicMock()
    pm.get_active_provider_key.return_value = "openai"
    pm.create_active_agent.return_value = agent if agent is not None else MagicMock()
    for key, value in overrides.items():
        setattr(pm, key, value)
    return pm


def _make_app_mock(
    project_dir: str | None = None,
    current_session_id: str = "pytest-session-id",
    role: str = "worker",
    agent: MagicMock | None = None,
    **overrides: Any,
) -> MagicMock:
    """Build a fully-wired MagicMock JohnstonApp instance.

    Populates the fields shared by most tests: project dir, session id, role,
    notify/refresh stubs, a provider manager, a bound agent and a real
    ``ToolContext`` delegating to the mock app.
    """
    app = MagicMock()
    app.project_dir = project_dir
    app.current_session_id = current_session_id
    app.role = role
    app.is_app_active = True
    app.notify = MagicMock()
    app.refresh_status_footer = MagicMock()

    resolved_agent = agent if agent is not None else _make_agent_mock(role=role)
    app.agent = resolved_agent
    app.pm = _make_pm_mock(agent=resolved_agent)
    app.tool_context = ToolContext(app)

    for key, value in overrides.items():
        setattr(app, key, value)
    return app


def _make_tool_context(
    app: Any = None,
    is_subagent: bool = False,
    cwd: str | None = None,
    **overrides: Any,
) -> ToolContext:
    """Build a real ``ToolContext`` over a host (defaults to a fresh mock app)."""
    host = app if app is not None else _make_app_mock()
    ctx = ToolContext(host, is_subagent=is_subagent, cwd=cwd)
    for key, value in overrides.items():
        setattr(ctx, key, value)
    return ctx


# --------------------------------------------------------------------------- #
# Factory fixtures (tests request these by name, then call them)
# --------------------------------------------------------------------------- #

@pytest.fixture
def make_agent_mock():
    return _make_agent_mock


@pytest.fixture
def make_orchestrator_mock():
    return _make_orchestrator_mock


@pytest.fixture
def make_pm_mock():
    return _make_pm_mock


@pytest.fixture
def make_app_mock():
    return _make_app_mock


@pytest.fixture
def make_tool_context():
    return _make_tool_context


# --------------------------------------------------------------------------- #
# Instance fixtures (pre-built mocks)
# --------------------------------------------------------------------------- #

@pytest.fixture
def mock_app(tmp_path):
    """Pytest fixture providing a mock JohnstonApp instance."""
    return _make_app_mock(project_dir=str(tmp_path))


@pytest.fixture
def mock_agent():
    """A pre-built worker agent mock."""
    return _make_agent_mock()


@pytest.fixture
def mock_orchestrator():
    """A pre-built orchestrator agent mock."""
    return _make_orchestrator_mock()


@pytest.fixture
def mock_pm():
    """A pre-built provider manager mock."""
    return _make_pm_mock()


@pytest.fixture
def mock_tool_context():
    """A real ToolContext over a mock app, pre-built."""
    return _make_tool_context()


class WindowsSafeTemporaryDirectory(tempfile.TemporaryDirectory):
    """TemporaryDirectory whose cleanup retries on Windows sharing violations.

    git/CI Windows runners routinely hit `PermissionError: [WinError 32]` when
    deleting a freshly written temp dir because Defender is still scanning the
    files. Retry briefly before propagating so teardown stays green.
    """

    def cleanup(self) -> None:
        import time

        for _ in range(8):
            try:
                return super().cleanup()
            except PermissionError:
                time.sleep(0.25)
        super().cleanup()
