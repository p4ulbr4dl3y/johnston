import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from tools.context import ToolContext


@pytest.fixture
def temp_workspace():
    """Pytest fixture providing an isolated temporary directory."""
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def mock_app(temp_workspace):
    """Pytest fixture providing a mock JohnstonApp instance."""
    app = MagicMock()
    app.project_dir = temp_workspace
    app.current_session_id = "pytest-session-id"
    app.mode = "action"
    app.is_app_active = True
    app.tool_context = ToolContext(app)
    app.notify = MagicMock()
    app.refresh_status_footer = MagicMock()

    agent = MagicMock()
    agent.mode = "action"
    agent.model = "deepseek-v4-flash"
    agent.provider_key = "openai"
    agent.stream_steps = AsyncMock()

    pm = MagicMock()
    pm.get_active_provider_key.return_value = "openai"
    pm.create_active_agent.return_value = agent
    app.pm = pm
    app.agent = agent

    return app
