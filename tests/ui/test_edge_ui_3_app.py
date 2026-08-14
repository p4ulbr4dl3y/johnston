import unittest
from unittest.mock import patch

from app import JohnstonApp


class TestAppBootEdge(unittest.TestCase):
    def test_init_resume_invalid_session_falls_back(self):
        app = JohnstonApp(resume_session_id="missing_sess_xyz")
        self.assertIsInstance(app.current_session_id, str)
        self.assertTrue(app.current_session_id)

    def test_init_no_agent_tolerated(self):
        with patch("core.provider_manager.ProviderManager.create_active_agent", return_value=None):
            app = JohnstonApp()
            self.assertIsNone(app.agent)
            self.assertEqual(app.role, "worker")

    def test_on_unmount_survives_all_exceptions(self):
        """Teardown must tolerate failures in every cleanup subsystem."""
        app = JohnstonApp()
        with (
            patch.object(app.task_manager, "kill_all", side_effect=RuntimeError("bg")),
            patch("core.subagent_stream.cancel_running_subagents", side_effect=RuntimeError("sub")),
            patch("app.JohnstonApp.save_current_session", side_effect=RuntimeError("save")),
            patch("core.infrastructure.mcp.get_mcp_manager", side_effect=RuntimeError("mcp")),
        ):
            # Must not raise
            app.on_unmount()
        self.assertFalse(getattr(app, "is_app_active", True))


class TestAppInitResume(unittest.IsolatedAsyncioTestCase):
    async def test_resume_session_loads_ui(self):
        app = JohnstonApp()
        sess = app.sm.create_main("sess_edge_r")
        sess.messages = [{"type": "user", "text": "resume me"}]
        app.sm.save(sess)

        resumed = JohnstonApp(resume_session_id="sess_edge_r")
        async with resumed.run_test():
            from widgets.chat_view import ChatView

            chat_view = resumed.query_one(ChatView)
            user_msgs = chat_view.get_user_messages()
            self.assertGreaterEqual(len(user_msgs), 1)


if __name__ == "__main__":
    unittest.main()
