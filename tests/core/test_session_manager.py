import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from core.domain.policies.messages import is_ui_visible_user_message
from core.infrastructure.storage.session_store import SessionStore


def _make_store(test_dir: str, project_name: str = "my_project") -> SessionStore:
    project_path = os.path.join(test_dir, project_name)
    os.makedirs(project_path, exist_ok=True)
    return SessionStore(project_path=project_path)


class TestSessionManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.projects_dir_patcher = patch("core.infrastructure.storage.session_store.PROJECTS_DIR", self.test_dir)
        self.projects_dir_patcher.start()
        self.addCleanup(self.projects_dir_patcher.stop)
        self.store = _make_store(self.test_dir)

    def test_init_dirs(self):
        self.assertTrue(os.path.exists(self.store.sessions_dir))
        self.assertTrue(self.store.project_key.startswith("my_project_"))

    def test_generate_session_id(self):
        sid = self.store.generate_session_id()
        self.assertTrue(sid.startswith("session_"))

    def test_save_and_load_session(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.messages = [{"type": "user", "text": "hello"}]
        self.store.save(sess)

        loaded = self.store.get(sid)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.messages[0]["text"], "hello")

    def test_message_count_counts_agent_loop_iterations(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.agent_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "ok"},
            {"role": "assistant", "content": "done"},
        ]
        self.assertEqual(self.store.get(sid).message_count, 2)

    def test_message_count_empty(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        self.assertEqual(sess.message_count, 0)

    def test_from_dict_preserves_canonical_messages(self):
        sess = self.store.create_subagent(parent_id="main", subagent_id="legacy-1", role="worker")
        sess.messages = [
            {"type": "thinking", "text": "Done", "duration": 0.5},
            {"type": "bot", "text": "hello", "final": True},
        ]
        self.store.save(sess)
        self.store._sessions.clear()
        loaded = self.store.get("legacy-1")
        self.assertEqual(loaded.messages[0], {"type": "thinking", "text": "Done", "duration": 0.5})
        self.assertEqual(loaded.messages[1], {"type": "bot", "text": "hello", "final": True})

    def test_list_main_sessions(self):
        sid1 = self.store.generate_session_id()
        sid2 = self.store.generate_session_id()

        s1 = self.store.create_main(sid1)
        s1.messages = [{"type": "user", "text": "one"}]
        s1.created_at = 1
        s1.updated_at = 1
        self.store.save(s1)

        s2 = self.store.create_main(sid2)
        s2.messages = [{"type": "user", "text": "two"}]
        s2.created_at = 2
        s2.updated_at = 2
        self.store.save(s2)

        sessions = self.store.list_main_sessions()
        self.assertEqual(len(sessions), 2)
        # Check sorting (latest first)
        self.assertEqual(sessions[0]["id"], sid2)

    def test_subagent_nested_layout(self):
        main = self.store.create_main()
        sub = self.store.create_subagent(parent_id=main.id, subagent_id="sub-1", title="d", prompt="p")
        self.store.save(main)
        self.store.save(sub)

        sub_path = os.path.join(self.store.sessions_dir, f"{main.id}.subagents", "sub-1.jsonl")
        self.assertTrue(os.path.exists(sub_path))

        self.store._sessions.clear()
        children = self.store.children(main.id)
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0].id, "sub-1")

    def test_delete_main_removes_subagents(self):
        main = self.store.create_main()
        self.store.create_subagent(parent_id=main.id, subagent_id="sub-1", title="d", prompt="p")
        self.store.save(main)
        self.store.save(self.store.get("sub-1"))

        self.store.delete(main.id)
        sub_dir = os.path.join(self.store.sessions_dir, f"{main.id}.subagents")
        self.assertFalse(os.path.exists(sub_dir) and bool(os.listdir(sub_dir)))
        self.assertIsNone(self.store.get(main.id))


class TestSessionManagerRegression(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir, ignore_errors=True)
        self.projects_dir_patcher = patch("core.infrastructure.storage.session_store.PROJECTS_DIR", os.path.join(self.test_dir, "projects"))
        self.projects_dir_patcher.start()
        self.addCleanup(self.projects_dir_patcher.stop)
        self.store = _make_store(self.test_dir)

    def test_load_session_returns_none_for_malformed_json(self):
        bad_path = os.path.join(self.store.sessions_dir, "broken.jsonl")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not json")

        self.assertIsNone(self.store.get("broken"))

    def test_list_main_sessions_ignores_malformed_json_without_deleting_it(self):
        bad_path = os.path.join(self.store.sessions_dir, "broken.jsonl")
        with open(bad_path, "w", encoding="utf-8") as f:
            f.write("{not json")

        self.assertEqual(self.store.list_main_sessions(), [])
        self.assertTrue(os.path.exists(bad_path))

    def test_save_without_messages_still_creates_file(self):
        # Unlike old SessionManager (which skipped empty sessions), AgentSession
        # persists regardless; empty-session filtering happens in list_main_sessions.
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        self.store.save(sess)

        self.assertTrue(os.path.exists(os.path.join(self.store.sessions_dir, f"{sid}.jsonl")))
        self.assertEqual(self.store.list_main_sessions(), [])

    def test_atomic_save_session_persists_data_and_cleans_up_tmp(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.messages = [{"type": "user", "text": "test_atomic"}]
        self.store.save(sess)

        filepath = os.path.join(self.store.sessions_dir, f"{sid}.jsonl")
        self.assertTrue(os.path.exists(filepath))
        loaded = self.store.get(sid)
        self.assertEqual(loaded.messages[0]["text"], "test_atomic")

        # Ensure no leftover .tmp files
        tmp_files = [f for f in os.listdir(self.store.sessions_dir) if ".tmp." in f]
        self.assertEqual(tmp_files, [])


class TestSessionManagerPureReader(unittest.TestCase):
    """list_main_sessions must be a pure reader (no destructive side effects)."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.test_dir)
        self.p1 = patch("core.infrastructure.storage.session_store.PROJECTS_DIR", self.test_dir)
        self.p1.start()
        self.addCleanup(self.p1.stop)
        self.store = _make_store(self.test_dir)

    def test_list_main_sessions_does_not_delete_empty_files(self):
        empty_path = os.path.join(self.store.sessions_dir, "empty.json")
        with open(empty_path, "w") as f:
            json.dump({"id": "empty", "kind": "main", "messages": [], "agent_history": []}, f)

        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.messages = [{"type": "user", "text": "real"}]
        self.store.save(sess)

        sessions = self.store.list_main_sessions()
        self.assertTrue(os.path.exists(empty_path))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], sid)

    def test_is_ui_visible_user_message(self):
        self.assertTrue(is_ui_visible_user_message({"type": "user", "text": "hello"}))
        self.assertTrue(is_ui_visible_user_message({"type": "user", "text": "hello", "show_in_ui": True}))
        self.assertFalse(is_ui_visible_user_message({"type": "user", "text": "hello", "show_in_ui": False}))
        self.assertFalse(is_ui_visible_user_message({"type": "user", "text": '<notification type="shell">Background shell</notification>'}))
        self.assertFalse(is_ui_visible_user_message({"type": "user", "text": '<system_note kind="interrupted"></system_note>'}))
        self.assertFalse(is_ui_visible_user_message("not a dict"))
        self.assertFalse(is_ui_visible_user_message(None))


    def test_add_event_prunes_empty_bot_message_before_tool(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.add_event({"type": "bot", "text": "   \n\n  "})
        self.assertEqual(len(sess.messages), 1)
        sess.add_event({"type": "tool", "tool_type": "shell", "target": "ls"})
        self.assertEqual(len(sess.messages), 1)
        self.assertEqual(sess.messages[0]["type"], "tool")

    def test_add_event_keeps_non_empty_bot_message_before_tool(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.add_event({"type": "bot", "text": "Вот 5 яблок\n"})
        self.assertEqual(len(sess.messages), 1)
        sess.add_event({"type": "tool", "tool_type": "shell", "target": "ls"})
        self.assertEqual(len(sess.messages), 2)
        self.assertEqual(sess.messages[0]["type"], "bot")
        self.assertEqual(sess.messages[1]["type"], "tool")

    def test_title_from_messages_uses_display_text(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.messages = [
            {"type": "user", "text": "The following skill(s) have been invoked: <skill>...", "display_text": "/caveman help"}
        ]
        title = sess.title
        self.assertEqual(title, "/caveman help")

    def test_add_event_deduplicates_consecutive_event_dividers(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.add_event({"type": "event_divider", "text": "Session Compacted"})
        sess.add_event({"type": "event_divider", "text": "Session Compacted"})
        self.assertEqual(len(sess.messages), 1)
        sess.add_event({"type": "event_divider", "text": "API Error: 400"})
        self.assertEqual(len(sess.messages), 2)


    def test_list_main_sessions_includes_forks(self):
        sid = self.store.generate_session_id()
        s1 = self.store.create_main(sid)
        s1.messages = [{"type": "user", "text": "turn 1"}]
        self.store.save(s1)

        forked = self.store.fork_session(sid, new_title="Forked turn")
        self.assertIsNotNone(forked)
        self.assertEqual(forked.parent_id, sid)

        sessions = self.store.list_main_sessions()
        session_ids = [s["id"] for s in sessions]
        self.assertIn(sid, session_ids)
        self.assertIn(forked.id, session_ids)

    def test_list_prefers_live_in_memory_over_disk(self):
        sid = self.store.generate_session_id()
        sess = self.store.create_main(sid)
        sess.messages = [{"type": "user", "text": "initial disk content"}]
        self.store.save(sess)

        # Mutate in-memory session without saving to disk
        sess.messages.append({"type": "user", "text": "live follow-up"})

        results = self.store.list()
        matching = [s for s in results if s.id == sid]
        self.assertEqual(len(matching), 1)
        self.assertEqual(len(matching[0].messages), 2)
        self.assertEqual(matching[0].messages[1]["text"], "live follow-up")

    def test_find_session_by_title_or_id_registers_in_sessions(self):
        sub_id = "sub-find-reg"
        sess = self.store.create_subagent("sess-main", subagent_id=sub_id, title="My Sub")
        sess.messages = [{"type": "user", "text": "hello"}]
        self.store.save(sess)

        self.store._sessions.clear()
        found = self.store.find_session_by_title_or_id(sub_id)
        self.assertIsNotNone(found)
        self.assertIn(sub_id, self.store._sessions)

        found_again = self.store.find_session_by_title_or_id(sub_id)
        self.assertIs(found, found_again)


if __name__ == "__main__":
    unittest.main()

