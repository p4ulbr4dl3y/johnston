import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from tools.context import ToolContext


class BaseTestCase(unittest.TestCase):
    """Base test case providing clean isolated workspace & app mocks."""

    def setUp(self):
        super().setUp()
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_temp_dir)

    def _cleanup_temp_dir(self):
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_app(self, project_dir: str | None = None) -> MagicMock:
        """Create a fully configured mock JohnstonApp instance."""
        p_dir = project_dir or self.temp_dir
        mock_app = MagicMock()
        mock_app.project_dir = p_dir
        mock_app.current_session_id = "test-session-id"
        mock_app.mode = "action"
        mock_app.is_app_active = True
        mock_app.tool_context = ToolContext(mock_app)
        mock_app.notify = MagicMock()
        mock_app.refresh_status_footer = MagicMock()
        mock_app.save_current_session = MagicMock()

        # Mock ProviderManager & Agent
        mock_agent = MagicMock()
        mock_agent.mode = "action"
        mock_agent.model = "deepseek-v4-flash"
        mock_agent.provider_key = "openai"
        mock_agent.tokens_input = 0
        mock_agent.tokens_output = 0
        mock_agent.cost_usd = 0.0
        mock_agent.stream_steps = AsyncMock()

        mock_pm = MagicMock()
        mock_pm.get_active_provider_key.return_value = "openai"
        mock_pm.create_active_agent.return_value = mock_agent
        mock_app.pm = mock_pm
        mock_app.agent = mock_agent

        return mock_app


class AsyncBaseTestCase(unittest.IsolatedAsyncioTestCase, BaseTestCase):
    """Base test case for asynchronous tests with isolated workspace & app mocks."""

    pass
