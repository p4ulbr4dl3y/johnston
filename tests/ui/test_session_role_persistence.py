import unittest
from unittest.mock import MagicMock, patch

from johnston.core.domain.entities.session import AgentSession
from johnston.tui.app.role_service import toggle_agent_role
from johnston.tui.app.session_state import collect_session_data
from johnston.tui.mixins.session_persistence import SessionPersistenceMixin


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
        self.query = MagicMock(return_value=[])


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

        with patch("johnston.tui.app.role_service.RoleRegistry.get_instance") as mock_reg_inst:
            reg = MagicMock()
            reg.list_roles.return_value = {"worker": MagicMock(), "explorer": MagicMock()}
            mock_reg_inst.return_value = reg

            res = toggle_agent_role(app)

        self.assertTrue(res)
        self.assertEqual(app.agent.role, "explorer")
        self.assertEqual(app.role, "explorer")
        self.assertEqual(session.role, "explorer")
        app.save_current_session.assert_called_once()

    def test_toggle_agent_role_empty_registry_returns_false(self):
        app = DummyApp()
        with patch("johnston.tui.app.role_service.RoleRegistry.get_instance") as mock_reg_inst:
            reg = MagicMock()
            reg.list_roles.return_value = {}
            mock_reg_inst.return_value = reg

            res = toggle_agent_role(app)

        self.assertFalse(res)

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

    def test_collect_session_data_includes_project_dir_and_branch(self):
        app = DummyApp()
        app.project_dir = "/tmp/fake-dir"
        app.agent.worktree_branch = "feat/new-ui"
        session = AgentSession(session_id="test-session", role="worker")
        session.messages = [{"type": "user", "text": "test", "show_in_ui": True}]
        app.sm.get.return_value = session

        data = collect_session_data(app)
        self.assertIsNotNone(data)
        self.assertEqual(data["project_dir"], "/tmp/fake-dir")
        self.assertEqual(data["branch_name"], "feat/new-ui")

    def test_write_session_data_persists_branch_and_dir(self):
        app = DummyApp()
        session = AgentSession(session_id="test-session", role="worker")
        app.sm.get.return_value = session

        session_data = {
            "title": "Branch Session",
            "role": "worker",
            "messages": [],
            "agent_history": [],
            "project_dir": "/tmp/custom-worktree",
            "branch_name": "feat/worktree-branch",
        }
        app._write_session_data(session_data)

        self.assertEqual(session.project_dir, "/tmp/custom-worktree")
        self.assertEqual(session.branch_name, "feat/worktree-branch")
        app.sm.save.assert_called_once_with(session)

    def test_restore_session_state_switches_project_dir_and_branch(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = DummyApp()
            app.project_dir = "/other/path"
            app.switch_project_dir = MagicMock()
            session = AgentSession(session_id="test-session", role="worker")
            session.project_dir = tmp_dir
            session.branch_name = "feat/restored-branch"
            app.sm.get.return_value = session
            app.load_session_ui("test-session")

            app.switch_project_dir.assert_called_once_with(tmp_dir, "feat/restored-branch")
            app.refresh_status_footer.assert_called_once()

    def test_restore_session_state_handles_missing_worktree_dir(self):
        app = DummyApp()
        app.project_dir = "/repo/main"
        app.switch_project_dir = MagicMock()
        app.notify = MagicMock()
        app.agent.worktree_branch = "feat/old"
        session = AgentSession(session_id="test-session", role="worker")
        session.project_dir = "/nonexistent/deleted/worktree"
        session.branch_name = "feat/deleted"
        app.sm.get.return_value = session
        app.load_session_ui("test-session")

        app.switch_project_dir.assert_not_called()
        self.assertEqual(session.project_dir, "/repo/main")
        self.assertEqual(session.branch_name, "")
        self.assertEqual(app.agent.worktree_branch, "")
        app.notify.assert_called_once()
        self.assertIn("no longer exists", app.notify.call_args[0][0])


