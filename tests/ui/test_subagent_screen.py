import asyncio
import tempfile
import unittest
from unittest.mock import patch

from textual.app import App
from textual.screen import Screen

from core.session_manager import SessionStore
from widgets.presentation.screens.subagent_screen import SubagentViewScreen
from widgets.presentation.widgets.chat_container import ChatView


class DummyHostApp(App[None]):
    """Host app for testing Textual modal screens with pilot."""

    def __init__(self, screen_to_test, store=None):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None
        self.current_session_id = None
        self.sm = store

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res

        self.push_screen(self.screen_to_test, callback=callback)

    def refresh_status_footer(self):
        pass


def _make_store(tmpdir: str) -> SessionStore:
    store = SessionStore(project_path=tmpdir)
    return store


class TestSubagentStreamAndScreen(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = _make_store(self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    def tearDown(self):
        SessionStore._instance = self._old_instance

    def _mk(self, sid: str, desc: str, prompt: str, role: str = "worker"):
        sess = self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            description=desc,
            prompt=prompt,
            status="running",
        )
        return sess

    def test_tracker_create_and_find(self):
        sess = self._mk("task-123", "test subagent", "test prompt", role="worker")
        self.assertEqual(sess.id, "task-123")
        self.assertEqual(sess.description, "test subagent")
        self.assertEqual(sess.status, "running")

        found = self.store.find_session_by_description_or_id("task-123")
        self.assertEqual(found, sess)

        found_by_desc = self.store.find_session_by_description_or_id("test subagent")
        self.assertEqual(found_by_desc, sess)

    def test_session_events(self):
        sess = self._mk("task-456", "subagent task", "prompt text", role="explorer")
        events_received = []

        def listener(evt):
            events_received.append(evt)

        sess.add_listener(listener)
        sess.add_event({"type": "user", "text": "hello"})
        sess.finish("completed")

        self.assertEqual(len(sess.messages), 2)
        self.assertEqual(len(events_received), 2)
        self.assertEqual(sess.status, "completed")

    def test_bot_cumulative_text_handling(self):
        sess = self._mk("task-delta", "delta subagent", "prompt", role="explorer")
        sess.add_event({"type": "bot", "text": "Hello"})
        sess.add_event({"type": "bot", "text": "Hello world"})
        self.assertEqual(len(sess.messages), 1)
        self.assertEqual(sess.messages[0]["text"], "Hello world")

    def test_record_subagent_step_canonical_format(self):
        from core.application.session.stream import record_subagent_step

        sess = self._mk("task-canon", "canonical", "prompt")
        acc = [""]
        record_subagent_step(("thinking_start", "Thinking...", ""), sess, acc)
        record_subagent_step(("thinking_delta", "Thinking... deep", ""), sess, acc)
        record_subagent_step(("thinking_end", "1.0", "Final thought"), sess, acc)
        record_subagent_step(("tool", "read", "x", {"path": "x"}), sess, acc)
        record_subagent_step(("tool_result", "contents", ""), sess, acc)
        record_subagent_step(("bot_delta", "Hello world", ""), sess, acc)
        record_subagent_step(("bot_text", "Final answer", ""), sess, acc)
        record_subagent_step(("event_divider", "Session Compacted", ""), sess, acc)

        msgs = sess.messages
        self.assertEqual(msgs[0], {"type": "thinking", "text": "Final thought", "duration": 1.0})
        self.assertEqual(
            msgs[1],
            {"type": "tool", "tool_type": "read", "target": "x", "args": {"path": "x"}, "result_text": "contents"},
        )
        self.assertEqual(msgs[2], {"type": "bot", "text": "Final answer", "final": True})
        self.assertEqual(msgs[3], {"type": "event_divider", "text": "Session Compacted"})
        self.assertEqual(acc[0], "Final answer")

    def test_record_subagent_step_multistep_tools_no_accumulation(self):
        from core.application.session.stream import record_subagent_step

        sess = self._mk("task-multi", "multistep", "prompt")
        acc = [""]
        # Step 1: text before tool
        record_subagent_step(("bot_delta", "Step 1 checking files...", ""), sess, acc)
        record_subagent_step(("tool", "read", "a.py", {"path": "a.py"}), sess, acc)
        record_subagent_step(("tool_result", "content A", ""), sess, acc)

        # Step 2: text before second tool (should NOT accumulate Step 1 text)
        record_subagent_step(("bot_delta", "Step 2 checking tests...", ""), sess, acc)
        record_subagent_step(("tool", "read", "b.py", {"path": "b.py"}), sess, acc)
        record_subagent_step(("tool_result", "content B", ""), sess, acc)

        # Step 3: final answer
        record_subagent_step(("bot_delta", "All done!", ""), sess, acc)
        record_subagent_step(("bot_text", "All done!", ""), sess, acc)

        msgs = sess.messages
        # Message 0: bot step 1
        self.assertEqual(msgs[0], {"type": "bot", "text": "Step 1 checking files..."})
        # Message 1: tool 1
        self.assertEqual(msgs[1]["type"], "tool")
        self.assertEqual(msgs[1]["target"], "a.py")
        # Message 2: bot step 2 (isolated text, no step 1 prefix!)
        self.assertEqual(msgs[2], {"type": "bot", "text": "Step 2 checking tests..."})
        # Message 3: tool 2
        self.assertEqual(msgs[3]["type"], "tool")
        self.assertEqual(msgs[3]["target"], "b.py")
        # Message 4: final bot
        self.assertEqual(msgs[4], {"type": "bot", "text": "All done!", "final": True})
        self.assertEqual(acc[0], "All done!")

    def test_record_subagent_step_bot_reset(self):
        from core.application.session.stream import record_subagent_step

        sess = self._mk("task-reset", "reset", "prompt")
        acc = [""]
        record_subagent_step(("bot_delta", "flaky draft", ""), sess, acc)
        self.assertEqual(sess.messages[0]["text"], "flaky draft")
        # Retry triggers bot_reset
        record_subagent_step(("bot_reset", "", ""), sess, acc)
        self.assertEqual(sess.messages[0]["text"], "")
        self.assertEqual(acc[0], "")
        # Retried attempt generates clean output
        record_subagent_step(("bot_delta", "clean reply", ""), sess, acc)
        record_subagent_step(("bot_text", "clean reply", ""), sess, acc)
        self.assertEqual(sess.messages[0]["text"], "clean reply")
        self.assertEqual(acc[0], "clean reply")

    def test_record_subagent_step_thinking_info_and_outro(self):
        from core.application.session.stream import record_subagent_step

        sess = self._mk("task-info", "info", "prompt")
        acc = [""]
        record_subagent_step(("thinking", "Auto-compacting...", ""), sess, acc)
        record_subagent_step(("bot_delta", "partial", ""), sess, acc)
        record_subagent_step(("outro", "final", ""), sess, acc)
        self.assertEqual(sess.messages[0], {"type": "thinking", "text": "Auto-compacting...", "duration": 0.0})
        self.assertEqual(sess.messages[1], {"type": "bot", "text": "final", "final": True})

    def test_subagent_view_screen_initialization(self):
        sess = self._mk("task-789", "my subagent", "do something")
        store = self.store
        screen = SubagentViewScreen("task-789")
        screen.session = store.find_session_by_description_or_id("task-789")
        self.assertEqual(screen.session, sess)
        self.assertEqual(screen.session_id_or_desc, "task-789")
        self.assertIsInstance(screen, Screen)

    def test_session_persistence(self):
        sess = self._mk("task-persist", "Persistent Agent", "save to disk", role="explorer")
        sess.add_event({"type": "bot", "text": "persisted output", "final": True})
        self.store.save(sess)

        # Reload from disk
        self.store._sessions.clear()
        reloaded = self.store.get("task-persist")
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.description, "Persistent Agent")
        self.assertTrue(any(m.get("text") == "persisted output" for m in reloaded.messages))

    def test_find_session_truncated_description(self):
        sess = self._mk("task-trunc", "Explore test setup and verify runner", "full prompt text", role="explorer")
        found = self.store.find_session_by_description_or_id('"Explore test setup...runner"')
        self.assertEqual(found, sess)

    def test_find_session_substring_description(self):
        sess = self._mk("task-sub", "Test subagent check env for py", "Test subagent check env for python environment")
        found = self.store.find_session_by_description_or_id("Test subagent check env")
        self.assertEqual(found, sess)


class TestSubagentViewScreenPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = _make_store(self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    def tearDown(self):
        SessionStore._instance = self._old_instance

    def _mk(self, sid: str, desc: str, prompt: str, role: str = "worker"):
        sess = self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            description=desc,
            prompt=prompt,
            status="running",
        )
        return sess

    async def test_render_all_event_types_pilot(self):
        sess = self._mk("task-events", "Event Agent", "prompt")
        sess.add_event({"type": "user", "text": "hello subagent"})
        sess.add_event({"type": "thinking", "text": "thinking..."})
        sess.add_event({"type": "thinking", "text": "thinking... delta"})
        sess.add_event({"type": "thinking", "text": "thought done", "duration": 1.0})
        sess.add_event({"type": "bot", "text": "   "})  # empty text, will be removed when tool arrives
        sess.add_event({"type": "tool", "tool_type": "read", "target": "main.py", "args": {"path": "main.py"}})
        sess.add_event({"type": "tool", "result_text": "file contents"})
        sess.add_event({"type": "bot", "text": " chunk message 1"})
        sess.add_event({"type": "bot", "text": " chunk message 2"})
        sess.add_event({"type": "bot", "text": "bot text message", "final": True})
        sess.add_event({"type": "status_change", "status": "completed"})

        screen = SubagentViewScreen("task-events")
        app = DummyHostApp(screen, store=self.store)
        app.current_session_id = "sess-main"

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            # Add live event via store
            sess.add_event({"type": "bot", "text": " live chunk", "final": True})
            await pilot.pause(0.2)
            # Check action_dismiss
            res = screen.action_dismiss()
            if asyncio.iscoroutine(res):
                await res
            await pilot.pause()

    async def test_session_found_via_current_session_id(self):
        sess = self._mk("task-curr-sess", "Curr Sess Agent", "prompt")
        screen = SubagentViewScreen("Curr Sess Agent")
        screen.session = None  # Force fallback in on_mount

        app = DummyHostApp(screen, store=self.store)
        app.current_session_id = "sess-main"

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertEqual(screen.session, sess)
            await pilot.press("escape")
            await pilot.pause()

    async def test_session_not_found(self):
        screen = SubagentViewScreen("nonexistent-task")
        app = DummyHostApp(screen, store=self.store)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            await pilot.press("escape")
            await pilot.pause()

    async def test_render_event_edge_cases(self):
        self._mk("task-edges", "Edge Agent", "prompt")
        screen = SubagentViewScreen("task-edges")
        app = DummyHostApp(screen, store=self.store)
        app.current_session_id = "sess-main"

        async with app.run_test() as pilot:
            await pilot.pause(0.1)

            # Test edge cases where state variables are None or empty
            screen.thinking_widget = None
            await screen._render_event({"type": "thinking", "text": "orphaned delta"})
            await screen._render_event({"type": "thinking", "text": "orphaned end", "duration": 0.5})

            screen.current_tool_widget = None
            await screen._render_event({"type": "tool", "result_text": "orphaned result"})

            await screen._render_event({"type": "bot", "text": ""})
            await screen._render_event({"type": "bot", "text": ""})

            # Bot when bot_msg is None
            screen.bot_msg = None
            await screen._render_event({"type": "bot", "text": "fresh chunk"})
            screen.bot_msg.flush_pending_stream()
            self.assertEqual(screen.bot_msg.content, "fresh chunk")

            await pilot.press("escape")
            await pilot.pause()

    async def test_subagent_screen_widgets_expandable(self):
        sess = self._mk("task-select", "Select Agent", "prompt")
        sess.add_event({"type": "thinking", "text": "thinking..."})
        sess.add_event({"type": "thinking", "text": "thought done", "duration": 1.0})
        sess.add_event({"type": "tool", "tool_type": "edit", "target": "main.py"})

        screen = SubagentViewScreen("task-select")
        app = DummyHostApp(screen, store=self.store)
        app.current_session_id = "sess-main"

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            from widgets.chat_toolcall import ToolCallWidget
            from widgets.presentation.widgets.chat_messages import ThinkingWidget

            tw = screen.query_one(ThinkingWidget)
            tc = screen.query_one(ToolCallWidget)
            self.assertTrue(tw.is_expandable())
            self.assertTrue(tc.is_expandable())
            await pilot.press("escape")
            await pilot.pause()

    async def test_subagent_screen_prompt_and_canonical_tool_history(self):
        sess = self._mk("task-canon-hist", "Canon Agent", "My initial subagent prompt")
        sess.add_event(
            {"type": "tool", "tool_type": "shell", "target": "ls", "args": {"cmd": "ls"}, "result_text": "file.txt"}
        )
        sess.add_event({"type": "bot", "text": "Done", "final": True})

        screen = SubagentViewScreen("task-canon-hist")
        app = DummyHostApp(screen, store=self.store)
        app.current_session_id = "sess-main"

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            from widgets.presentation.widgets.chat_messages import UserMessage

            um = screen.query_one(UserMessage)
            self.assertIn("My initial subagent prompt", um.raw_text)
            from widgets.status_footer import SubagentHeader, SubagentStatusFooter

            header = screen.query_one("#subagent-header", SubagentHeader)
            self.assertTrue(header.is_mounted)
            footer = screen.query_one("#subagent-status-footer", SubagentStatusFooter)
            self.assertTrue(footer.is_mounted)
            await pilot.press("escape")
            await pilot.pause()

    async def test_subagent_screen_bindings_and_ctrl_o(self):
        sess = self._mk("task-bind-test", "Bind Agent", "Prompt")
        sess.add_event(
            {"type": "tool", "tool_type": "shell", "target": "ls", "args": {"cmd": "ls"}, "result_text": "file.txt"}
        )
        screen = SubagentViewScreen("task-bind-test")
        self.assertFalse(screen.inherit_bindings)

        app = DummyHostApp(screen, store=self.store)
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            chat_view = screen.query_one("#subagent-chat-view", ChatView)
            with patch.object(chat_view, "toggle_expand") as mock_te:
                screen.action_toggle_expand()
                mock_te.assert_called_once_with("all")

            with patch.object(app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

    async def test_subagent_screen_allows_selection(self):
        sess = self._mk("task-sel-test", "Sel Agent", "Prompt to select")
        sess.add_event({"type": "bot", "text": "Bot response to select", "final": True})
        screen = SubagentViewScreen("task-sel-test")
        self.assertTrue(screen.allow_select)

        app = DummyHostApp(screen, store=self.store)
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            from widgets.presentation.widgets.chat_messages import BotMessage, UserMessage

            bm = screen.query_one(BotMessage)
            um = screen.query_one(UserMessage)
            self.assertTrue(bm.allow_select)
            self.assertTrue(um.allow_select)


if __name__ == "__main__":
    unittest.main()

