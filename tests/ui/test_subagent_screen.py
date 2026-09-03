import asyncio
import tempfile
import unittest
from unittest.mock import patch

from textual.app import App
from textual.screen import Screen

from core.infrastructure.storage.session_store import SessionStore
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
            title=desc,
            prompt=prompt,
            status="running",
        )
        return sess

    def test_tracker_create_and_find(self):
        sess = self._mk("task-123", "test subagent", "test prompt", role="worker")
        self.assertEqual(sess.id, "task-123")
        self.assertEqual(sess.title, "test subagent")
        self.assertEqual(sess.status, "running")

        found = self.store.find_session_by_title_or_id("task-123")
        self.assertEqual(found, sess)

        found_by_desc = self.store.find_session_by_title_or_id("test subagent")
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
        screen.session = store.find_session_by_title_or_id("task-789")
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
        self.assertEqual(reloaded.title, "Persistent Agent")
        self.assertTrue(any(m.get("text") == "persisted output" for m in reloaded.messages))

    def test_find_session_truncated_description(self):
        sess = self._mk("task-trunc", "Explore test setup and verify runner", "full prompt text", role="explorer")
        found = self.store.find_session_by_title_or_id('"Explore test setup...runner"')
        self.assertEqual(found, sess)

    def test_find_session_substring_description(self):
        sess = self._mk("task-sub", "Test subagent check env for py", "Test subagent check env for python environment")
        found = self.store.find_session_by_title_or_id("Test subagent check env")
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
            title=desc,
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

            from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter

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

    def test_subagent_status_footer_token_cache(self):
        from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter

        footer = SubagentStatusFooter()
        sess = self._mk("task-tok-cache", "Tok Agent", "prompt")
        sess.messages = [{"type": "user", "text": "hello"}]
        with patch("core.infrastructure.runtime.token_util.estimate_tokens", return_value=42) as mock_est:
            footer.update_session(sess)
            self.assertEqual(mock_est.call_count, 1)
            # Re-render with same message count uses cached estimate
            footer.update_session(sess)
            self.assertEqual(mock_est.call_count, 1)
            # When message count changes, token estimator runs again
            sess.messages = [{"type": "user", "text": "hello"}, {"type": "bot", "text": "world"}]
            footer.update_session(sess)
            self.assertEqual(mock_est.call_count, 2)

    def test_unmounted_footer_update_never_schedules_spinner_timer(self):
        """Regression: update_session on an unmounted footer used to call
        set_interval(); its Timer coroutine is created before the scheduling
        RuntimeError, leaking a 'Timer._run_timer never awaited' warning."""
        from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter

        footer = SubagentStatusFooter()
        sess = self._mk("task-unmounted-spin", "Spin Agent", "prompt")
        sess.status = "running"
        with patch.object(SubagentStatusFooter, "set_interval") as mock_interval:
            footer.update_session(sess)
            mock_interval.assert_not_called()
        self.assertIsNone(footer._spinner_timer)
        # Generating flag still set so a later mounted update starts the spinner.
        self.assertTrue(footer.is_generating)

    async def test_subagent_screen_plan_notch_update(self):
        from widgets.presentation.widgets.plan_notch import PlanNotch

        sess = self._mk("task-plan-sub", "Plan Agent", "Subagent Prompt")
        sess.add_event({
            "type": "tool",
            "tool_type": "update_plan",
            "args": {
                "plan": [{"step": "Sub-task 1", "status": "in_progress"}],
                "explanation": "Subagent step",
            },
        })
        screen = SubagentViewScreen("task-plan-sub")
        app = DummyHostApp(screen, store=self.store)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            notch = screen.query_one(PlanNotch)
            self.assertTrue(notch.display)
            self.assertEqual(len(notch.plan_items), 1)
            self.assertEqual(notch.plan_items[0]["step"], "Sub-task 1")
            self.assertEqual(notch.plan_explanation, "Subagent step")


    async def test_subagent_screen_preserves_expand_state(self):
        sess = self._mk("task-expand-persist", "Expand Agent", "Subagent Prompt")
        sess.add_event({"type": "thinking", "text": "Thought text", "duration": 1.5})
        sess.add_event({
            "type": "tool",
            "tool_type": "shell",
            "target": "echo hi",
            "result_text": "hi\n",
        })
        screen = SubagentViewScreen("task-expand-persist")
        app = DummyHostApp(screen, store=self.store)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            screen.action_toggle_expand()
            await pilot.pause(0.1)
            self.assertIn("task-expand-persist", getattr(app, "_subagent_expand_state", {}))
            expanded_set = app._subagent_expand_state["task-expand-persist"]
            self.assertTrue(len(expanded_set) > 0)

        # Reopen screen and check widgets are expanded
        screen2 = SubagentViewScreen("task-expand-persist")
        app2 = DummyHostApp(screen2, store=self.store)
        app2._subagent_expand_state = {"task-expand-persist": expanded_set}

        async with app2.run_test() as pilot:
            await pilot.pause(0.2)
            from widgets.chat_toolcall import ToolCallWidget
            from widgets.presentation.widgets.chat_messages import ThinkingWidget

            tw = screen2.query_one(ThinkingWidget)
            self.assertTrue(tw.is_expanded)
            tc = screen2.query_one(ToolCallWidget)
            self.assertTrue(tc.is_expanded)

    async def test_subagent_screen_active_streaming_not_finalized(self):
        sess = self._mk("task-active-stream", "Stream Agent", "Subagent Prompt")
        sess.status = "running"
        sess.add_event({"type": "bot", "text": "Partial stream content"})

        screen = SubagentViewScreen("task-active-stream")
        app = DummyHostApp(screen, store=self.store)

        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertIsNotNone(screen.bot_msg)
            self.assertTrue(screen.bot_msg._streaming)

            # Live event should continue streaming into the same bot_msg
            sess.add_event({"type": "bot", "text": "Partial stream content and more"})
            await pilot.pause(0.2)
            self.assertIn("and more", screen.bot_msg.content or screen.bot_msg._join_stream_content())

    async def test_subagent_screen_pagination_and_plan(self):
        sess = self._mk("task-paginated-plan", "Paginated Agent", "Subagent Prompt")
        sess.status = "completed"
        # Add 60 tool events to trigger pagination (PAGE_SIZE default is 50)
        for i in range(60):
            sess.add_event({
                "type": "tool",
                "tool_type": "shell",
                "target": f"echo {i}",
                "result_text": f"res {i}",
                "status": "done",
            })
        sess.add_event({
            "type": "tool",
            "tool_type": "update_plan",
            "args": {
                "plan": [{"step": "Task 1", "status": "completed"}, {"step": "Task 2", "status": "in_progress"}],
                "explanation": "Working on task 2",
            },
        })

        screen = SubagentViewScreen("task-paginated-plan")
        app = DummyHostApp(screen, store=self.store)

        async with app.run_test() as pilot:
            if getattr(screen, "_history_worker", None):
                await screen._history_worker.wait()
            await pilot.pause(0.1)
            chat_view = screen.query_one(ChatView)
            from widgets.presentation.widgets.plan_notch import PlanNotch

            notch = screen.query_one(PlanNotch)
            self.assertTrue(notch.display)
            self.assertEqual(len(notch.plan_items), 2)
            self.assertEqual(notch.plan_explanation, "Working on task 2")

            # Verify pagination state
            self.assertTrue(chat_view.has_older_messages())
            self.assertTrue(len(chat_view._unloaded_messages) > 0)

            # Test plan toggle actions from PlanActionsMixin
            screen.action_toggle_plan()
            self.assertTrue(notch.is_expanded)
            screen.action_toggle_plan_hidden()
            self.assertFalse(notch.display)


if __name__ == "__main__":
    unittest.main()


