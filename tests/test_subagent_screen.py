import unittest

from core.subagent_tracker import SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen


class TestSubagentTrackerAndScreen(unittest.TestCase):

    def setUp(self):
        import tempfile

        from core.subagent_tracker import SUBAGENTS_DIR
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    async def asyncTearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir
        self.temp_dir.cleanup()

    def test_tracker_create_and_find(self):
        sess = self.tracker.create_session("task-123", "test subagent", "test prompt", "general", False)
        self.assertEqual(sess.task_id, "task-123")
        self.assertEqual(sess.description, "test subagent")
        self.assertEqual(sess.status, "running")

        found = self.tracker.find_session_by_description_or_id("task-123")
        self.assertEqual(found, sess)

        found_by_desc = self.tracker.find_session_by_description_or_id("test subagent")
        self.assertEqual(found_by_desc, sess)

    def test_session_events(self):
        sess = self.tracker.create_session("task-456", "subagent task", "prompt text", "explore", True)
        events_received = []

        def listener(evt):
            events_received.append(evt)

        sess.add_listener(listener)
        sess.add_event({"type": "user", "text": "hello"})
        sess.finish("completed")

        self.assertEqual(len(sess.events), 2)
        self.assertEqual(len(events_received), 2)
        self.assertEqual(sess.status, "completed")

    def test_subagent_view_screen_initialization(self):
        sess = self.tracker.create_session("task-789", "my subagent", "do something", "general", False)
        screen = SubagentViewScreen("task-789")
        self.assertEqual(screen.session, sess)
        self.assertEqual(screen.task_id_or_desc, "task-789")

    def test_session_persistence(self):
        sess = self.tracker.create_session("task-persist", "Persistent Agent", "save to disk", "explore", False)
        sess.add_event({"type": "bot_text", "text": "persisted output"})

        # Reload tracker sessions from disk
        self.tracker.sessions.clear()
        self.tracker._load_all_sessions()

        reloaded = self.tracker.get_session("task-persist")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.description, "Persistent Agent")
        self.assertTrue(any(e.get("text") == "persisted output" for e in reloaded.events))

    def test_subagents_list_screen(self):
        from widgets.screens.subagents_list import SubagentsListScreen
        self.tracker.create_session("task-menu", "Menu subagent", "list in menu", "general", True)
        screen = SubagentsListScreen()
        sessions = screen._get_target_sessions()
        self.assertTrue(any(s.task_id == "task-menu" for s in sessions))


if __name__ == "__main__":
    unittest.main()
