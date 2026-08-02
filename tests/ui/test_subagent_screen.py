import tempfile
import unittest
from unittest.mock import patch

from textual.app import App

from core.subagent_tracker import SUBAGENTS_DIR, SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen


class DummyHostApp(App[None]):
    """Host app for testing Textual modal screens with pilot."""

    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None
        self.current_session_id = None

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res
        self.push_screen(self.screen_to_test, callback=callback)

    def refresh_status_footer(self):
        pass


class TestSubagentTrackerAndScreen(unittest.TestCase):

    def setUp(self):
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    def tearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir

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

    def test_bot_delta_cumulative_text_handling(self):
        sess = self.tracker.create_session("task-delta", "delta subagent", "prompt", "explore", True)
        sess.add_event({"type": "bot_delta", "text": "Hello"})
        sess.add_event({"type": "bot_delta", "text": "Hello world"})
        self.assertEqual(len(sess.events), 1)
        self.assertEqual(sess.events[0]["text"], "Hello world")

    def test_subagent_view_screen_initialization(self):
        sess = self.tracker.create_session("task-789", "my subagent", "do something", "general", False)
        screen = SubagentViewScreen("task-789")
        self.assertEqual(screen.session, sess)
        self.assertEqual(screen.task_id_or_desc, "task-789")
        self.assertFalse(screen.ALLOW_SELECT)

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

    def test_find_session_truncated_description(self):
        sess = self.tracker.create_session("task-trunc", "Explore test setup and verify runner", "full prompt text", "explore", False)
        found = self.tracker.find_session_by_description_or_id('"Explore test setup...runner"')
        self.assertEqual(found, sess)

    def test_find_session_substring_description(self):
        sess = self.tracker.create_session("task-sub", "Test subagent check env for py", "Test subagent check env for python environment", "general", False)
        found = self.tracker.find_session_by_description_or_id("Test subagent check env")
        self.assertEqual(found, sess)


class TestSubagentViewScreenPilot(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    def tearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir

    async def test_render_all_event_types_pilot(self):
        sess = self.tracker.create_session("task-events", "Event Agent", "prompt", "general", False)
        sess.add_event({"type": "user", "text": "hello subagent"})
        sess.add_event({"type": "thinking_start", "val1": "thinking..."})
        sess.add_event({"type": "thinking_delta", "val1": " delta"})
        sess.add_event({"type": "thinking_end", "duration": 1.0, "content": "thought done"})
        sess.add_event({"type": "bot_delta", "text": "   "})  # empty text, will be removed when tool arrives
        sess.add_event({"type": "tool", "tool_type": "read_file", "target": "main.py", "args": {"path": "main.py"}})
        sess.add_event({"type": "tool_result", "result_text": "file contents"})
        sess.add_event({"type": "bot_chunk", "text": " chunk message 1"})
        sess.add_event({"type": "bot_chunk", "text": " chunk message 2"})
        sess.add_event({"type": "bot_text", "text": "bot text message"})
        sess.add_event({"type": "status_change", "status": "completed"})

        screen = SubagentViewScreen("task-events")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            # Add live event via tracker
            sess.add_event({"type": "bot_chunk", "text": " live chunk"})
            await pilot.pause(0.2)
            # Check action_quit_app
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

            await pilot.press("escape")
            await pilot.pause()

    async def test_session_found_via_current_session_id(self):
        sess = self.tracker.create_session("task-curr-sess", "Curr Sess Agent", "prompt", "general", False, session_id="sess-xyz")
        screen = SubagentViewScreen("Curr Sess Agent")
        screen.session = None  # Force fallback in on_mount

        app = DummyHostApp(screen)
        app.current_session_id = "sess-xyz"

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertEqual(screen.session, sess)
            await pilot.press("escape")
            await pilot.pause()

    async def test_session_not_found(self):
        screen = SubagentViewScreen("nonexistent-task")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("escape")
            await pilot.pause()

    async def test_render_event_edge_cases(self):
        self.tracker.create_session("task-edges", "Edge Agent", "prompt", "general", False)
        screen = SubagentViewScreen("task-edges")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause(0.1)

            # Test edge cases where state variables are None or empty
            screen.thinking_widget = None
            await screen._render_event({"type": "thinking_delta", "val1": "orphaned delta"})
            await screen._render_event({"type": "thinking_end", "duration": 0.5, "content": "orphaned end"})

            screen.current_tool_widget = None
            await screen._render_event({"type": "tool_result", "result_text": "orphaned result"})

            await screen._render_event({"type": "bot_delta", "text": ""})
            await screen._render_event({"type": "bot_chunk", "text": ""})
            await screen._render_event({"type": "bot_text", "text": ""})

            # Bot chunk when bot_msg is None
            screen.bot_msg = None
            await screen._render_event({"type": "bot_chunk", "text": "fresh chunk"})
            self.assertEqual(screen.bot_msg.content, "fresh chunk")

            await pilot.press("escape")
            await pilot.pause()

    async def test_subagent_screen_widgets_not_expandable(self):
        sess = self.tracker.create_session("task-select", "Select Agent", "prompt", "general", False)
        sess.add_event({"type": "thinking_start", "val1": "thinking..."})
        sess.add_event({"type": "thinking_end", "duration": 1.0, "content": "thought done"})
        sess.add_event({"type": "tool", "tool_type": "read_file", "target": "main.py"})

        screen = SubagentViewScreen("task-select")
        app = DummyHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            from widgets.chat_view import ThinkingWidget, ToolCallWidget
            tw = screen.query_one(ThinkingWidget)
            tc = screen.query_one(ToolCallWidget)
            self.assertFalse(tw.is_expandable())
            self.assertFalse(tc.is_expandable())
            await pilot.press("escape")
            await pilot.pause()


if __name__ == "__main__":
    unittest.main()




