import unittest
from unittest.mock import MagicMock, patch

from core.domain.entities.session import AgentSession
from widgets.app.role_service import toggle_agent_role
from widgets.app.session_state import collect_session_data
from widgets.mixins.session_persistence import SessionPersistenceMixin


class DummyApp(SessionPersistenceMixin):
    def __init__(self):
        self.current_session_id = "test-session"
        self.role = "worker"
        self.agent = MagicMock()
        self.agent.role = "worker"
        self.agent.history = []
        self.agent.tokens_input = 0
        self.agent.tokens_output = 0
        self.agent.total_tokens = 0
        self.agent.cost_usd = 0.0
        self.agent.tokens_cache_read = 0
        self.agent.last_context_tokens = 0
        self.sm = MagicMock()
        self.refresh_status_footer = MagicMock()
        self.run_worker = MagicMock()
        self.query_one = MagicMock()


class TestSessionRolePersistence(unittest.TestCase):
    def test_collect_session_data_includes_role(self):
        app = DummyApp()
        session = AgentSession(
            session_id="test-session",
            role="explorer",
        )
        session.messages = [{"type": "user", "text": "Hello world", "show_in_ui": True}]
        app.sm.get.return_value = session
        app.agent.role = "explorer"

        data = collect_session_data(app)
        self.assertIsNotNone(data)
        self.assertEqual(data["role"], "explorer")

    def test_write_session_data_persists_role(self):
        app = DummyApp()
        session = AgentSession(session_id="test-session", role="worker")
        app.sm.get.return_value = session

        session_data = {
            "title": "Test Title",
            "role": "researcher",
            "messages": [],
            "agent_history": [],
        }
        app._write_session_data(session_data)

        self.assertEqual(session.role, "researcher")
        app.sm.save.assert_called_once_with(session)

    def test_toggle_agent_role_updates_session_and_saves(self):
        app = DummyApp()
        session = AgentSession(session_id="test-session", role="worker")
        app.sm.get.return_value = session
        app.save_current_session = MagicMock()

        with patch("widgets.app.role_service.RoleRegistry.get_instance") as mock_reg_inst:
            reg = MagicMock()
            reg.list_roles.return_value = {"worker": MagicMock(), "explorer": MagicMock()}
            mock_reg_inst.return_value = reg

            res = toggle_agent_role(app)

        self.assertTrue(res)
        self.assertEqual(app.agent.role, "explorer")
        self.assertEqual(app.role, "explorer")
        self.assertEqual(session.role, "explorer")
        app.save_current_session.assert_called_once()

    def test_write_session_data_skips_save_and_touch_when_unchanged(self):
        app = DummyApp()
        orig_ts = 1000.0
        session = AgentSession(
            session_id="test-session",
            role="worker",
            title="My Session",
            updated_at=orig_ts,
        )
        session.messages = [{"type": "user", "text": "hi"}]
        app.sm.get.return_value = session

        session_data = {
            "title": "My Session",
            "role": "worker",
            "messages": [{"type": "user", "text": "hi"}],
            "agent_history": [],
            "tokens_input": 0,
            "tokens_output": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "last_context_tokens": 0,
            "tokens_cache_read": 0,
        }
        app._write_session_data(session_data)

        app.sm.save.assert_not_called()
        self.assertEqual(session.updated_at, orig_ts)

