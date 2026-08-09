import json
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
        # Patch PROJECTS_DIR for the SessionManager instance we will test
        self.projects_dir_patcher = patch("core.session_manager.PROJECTS_DIR", self.test_dir)
        self.projects_dir_patcher.start()

        # Initialize session manager under temporary project path
        self.project_path = os.path.join(self.test_dir, "my_project")
        os.makedirs(self.project_path, exist_ok=True)
        self.sm = SessionManager(project_path=self.project_path)

    def tearDown(self):
        self.projects_dir_patcher.stop()
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

    def test_active_session_id(self):
        sid = self.sm.generate_session_id()
        self.sm.save_session(sid, {"id": sid, "ui_messages": [{"type": "user", "text": "hello"}]})

        self.sm.set_active_session_id(sid)
        self.assertEqual(self.sm.load_session(sid)["id"], sid)

class TestSessionManagerRegression(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.projects_dir_patcher = patch("core.session_manager.PROJECTS_DIR", os.path.join(self.test_dir, "projects"))
        self.projects_dir_patcher.start()
        self.project_path = os.path.join(self.test_dir, "my_project")
        os.makedirs(self.project_path, exist_ok=True)
        self.sm = SessionManager(project_path=self.project_path)

    def tearDown(self):
        self.projects_dir_patcher.stop()
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

    def test_atomic_save_session_persists_data_and_cleans_up_tmp(self):
        sid = self.sm.generate_session_id()
        data = {"id": sid, "ui_messages": [{"type": "user", "text": "test_atomic"}]}
        self.sm.save_session(sid, data)

        filepath = os.path.join(self.sm.sessions_dir, f"{sid}.json")
        self.assertTrue(os.path.exists(filepath))
        loaded = self.sm.load_session(sid)
        self.assertEqual(loaded["ui_messages"][0]["text"], "test_atomic")

        # Ensure no leftover .tmp files
        tmp_files = [f for f in os.listdir(self.sm.sessions_dir) if ".tmp." in f]
        self.assertEqual(tmp_files, [])


class TestSessionManagerPureReader(unittest.TestCase):
    """list_sessions must be a pure reader (no destructive side effects); empty-file
    cleanup happens on next save_session when a session becomes empty."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p1 = patch("core.session_manager.PROJECTS_DIR", self.test_dir)
        self.p1.start()
        self.project_path = os.path.join(self.test_dir, "proj")
        os.makedirs(self.project_path, exist_ok=True)
        from core.session_manager import SessionManager
        self.sm = SessionManager(project_path=self.project_path)

    def tearDown(self):
        self.p1.stop()
        shutil.rmtree(self.test_dir)

    def test_list_sessions_does_not_delete_empty_files(self):
        empty_path = os.path.join(self.sm.sessions_dir, "empty.json")
        with open(empty_path, "w") as f:
            json.dump({"id": "empty", "ui_messages": [], "agent_history": []}, f)

        sid = self.sm.generate_session_id()
        self.sm.save_session(sid, {"id": sid, "ui_messages": [{"type": "user", "text": "real"}]})

        sessions = self.sm.list_sessions()
        self.assertTrue(os.path.exists(empty_path))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], sid)

    def test_save_empty_session_removes_empty_file(self):
        empty_path = os.path.join(self.sm.sessions_dir, "empty.json")
        with open(empty_path, "w") as f:
            json.dump({"id": "empty", "ui_messages": [], "agent_history": []}, f)

        self.sm.save_session("empty", {"id": "empty", "ui_messages": [], "agent_history": []})
        self.assertFalse(os.path.exists(empty_path))


if __name__ == "__main__":
    unittest.main()
