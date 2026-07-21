import os
import tempfile
import unittest
import shutil
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
        
        self.sm.save_session(sid1, {"id": sid1, "ui_messages": [{"type": "user", "text": "one"}]})
        self.sm.save_session(sid2, {"id": sid2, "ui_messages": [{"type": "user", "text": "two"}]})
        
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

if __name__ == "__main__":
    unittest.main()
