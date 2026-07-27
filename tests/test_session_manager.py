import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

with patch("core.config.CONFIG_DIR", "/dummy"), patch("core.config.PROJECTS_DIR", "/dummy"):
    from core.session_manager import SessionManager

class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        # Patch PROJECTS_DIR and CONFIG_DIR for the SessionManager instance we will test
        self.projects_dir_patcher = patch("core.session_manager.PROJECTS_DIR", self.test_dir)
        self.config_dir_patcher = patch("core.session_manager.CONFIG_DIR", self.test_dir)
        self.projects_dir_patcher.start()
        self.config_dir_patcher.start()

        # Initialize session manager under temporary project path
        self.project_path = os.path.join(self.test_dir, "my_project")
        os.makedirs(self.project_path, exist_ok=True)
        self.sm = SessionManager(project_path=self.project_path)

    def tearDown(self):
        self.projects_dir_patcher.stop()
        self.config_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_init_dirs(self):
        self.assertTrue(os.path.exists(self.sm.sessions_dir))
        self.assertTrue(self.sm.project_key.startswith("my_project_"))

    def test_generate_session_id(self):
        sid = self.sm.generate_session_id()
        self.assertTrue(sid.startswith("session_"))

    def test_save_and_load_session(self):
        sid = self.sm.generate_session_id()
        data = {
            "id": sid,
            "ui_messages": [{"type": "user", "text": "hello"}]
        }
        self.sm.save_session(sid, data)

        loaded = self.sm.load_session(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["ui_messages"][0]["text"], "hello")

    def test_save_empty_session_removes_or_ignores(self):
        sid = self.sm.generate_session_id()
        data = {
            "id": sid,
            "ui_messages": []
        }
        # Saving empty session should not create file
        self.sm.save_session(sid, data)
        self.assertIsNone(self.sm.load_session(sid))

        # If file existed and then saved empty, it should be deleted
        data_non_empty = {
            "id": sid,
            "ui_messages": [{"type": "user", "text": "hello"}]
        }
        self.sm.save_session(sid, data_non_empty)
        self.assertIsNotNone(self.sm.load_session(sid))

        self.sm.save_session(sid, data)
        self.assertIsNone(self.sm.load_session(sid))

    def test_list_sessions(self):
        sid1 = self.sm.generate_session_id()
        sid2 = self.sm.generate_session_id()

        self.sm.save_session(
            sid1,
            {"id": sid1, "ui_messages": [{"type": "user", "text": "one"}], "created_at": 1, "updated_at": 1},
        )
        self.sm.save_session(
            sid2,
            {"id": sid2, "ui_messages": [{"type": "user", "text": "two"}], "created_at": 2, "updated_at": 2},
        )

        sessions = self.sm.list_sessions()
        self.assertEqual(len(sessions), 2)
        # Check sorting (latest first)
        self.assertEqual(sessions[0]["id"], sid2)

    def test_delete_session(self):
        sid = self.sm.generate_session_id()
        self.sm.save_session(sid, {"id": sid, "ui_messages": [{"type": "user", "text": "hello"}]})
        self.assertIsNotNone(self.sm.load_session(sid))

        self.sm.delete_session(sid)
        self.assertIsNone(self.sm.load_session(sid))

    def test_active_session_id(self):
        sid = self.sm.generate_session_id()
        self.sm.save_session(sid, {"id": sid, "ui_messages": [{"type": "user", "text": "hello"}]})

        self.sm.set_active_session_id(sid)
        self.assertEqual(self.sm.get_active_session_id(), sid)

class TestSessionManagerRegression(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.projects_dir_patcher = patch("core.session_manager.PROJECTS_DIR", os.path.join(self.test_dir, "projects"))
        self.config_dir_patcher = patch("core.session_manager.CONFIG_DIR", os.path.join(self.test_dir, "config"))
        self.projects_dir_patcher.start()
        self.config_dir_patcher.start()
        self.project_path = os.path.join(self.test_dir, "my_project")
        os.makedirs(self.project_path, exist_ok=True)
        self.sm = SessionManager(project_path=self.project_path)

    def tearDown(self):
        self.projects_dir_patcher.stop()
        self.config_dir_patcher.stop()
        shutil.rmtree(self.test_dir)

    def test_load_session_returns_none_for_malformed_json(self):
        bad_path = os.path.join(self.sm.sessions_dir, "broken.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not json")

        self.assertIsNone(self.sm.load_session("broken"))

    def test_list_sessions_ignores_malformed_json_without_deleting_it(self):
        bad_path = os.path.join(self.sm.sessions_dir, "broken.json")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not json")

        self.assertEqual(self.sm.list_sessions(), [])
        self.assertTrue(os.path.exists(bad_path))

    def test_save_session_without_messages_does_not_create_file_or_active_session(self):
        sid = self.sm.generate_session_id()
        self.sm.save_session(sid, {"id": sid, "ui_messages": [], "agent_history": []})

        self.assertFalse(os.path.exists(os.path.join(self.sm.sessions_dir, f"{sid}.json")))
        self.assertIsNone(self.sm.get_active_session_id())


if __name__ == "__main__":
    unittest.main()
