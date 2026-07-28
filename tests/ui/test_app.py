import unittest

from app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView, UserMessage
from widgets.modal_screens import (
    HelpScreen,
    ModelScreen,
    ProvidersScreen,
    ResumeScreen,
    RewindScreen,
    TasksListScreen,
)


class TestJohnstonAppUI(unittest.IsolatedAsyncioTestCase):
    async def test_chat_app_flow(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_input = app.query_one("#message-input", ChatInput)
            chat_input.focus()

            # 1. Test /help
            from core.commands import handle_slash_command
            await handle_slash_command(app, "/help")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, HelpScreen)

            await pilot.press("escape")
            await pilot.pause(0.2)
            self.assertFalse(isinstance(app.screen, HelpScreen))

            # 2. User messages
            chat_view = app.query_one(ChatView)
            for msg in ["First message", "Second message", "Third message"]:
                await chat_view.add_user_message(msg)

            # 3. Test /rewind
            await handle_slash_command(app, "/rewind")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, RewindScreen)

            # Select first element with Enter
            await pilot.press("enter")
            await pilot.pause(0.5)

            chat_view = app.query_one(ChatView)
            user_msgs = [c for c in chat_view.children if isinstance(c, UserMessage)]
            self.assertEqual(len(user_msgs), 2)
            self.assertEqual(chat_input.text, "Third message")

            # 4. Test /resume
            await handle_slash_command(app, "/resume")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, ResumeScreen)

            await pilot.press("escape")
            await pilot.pause(0.5)
            self.assertFalse(isinstance(app.screen, ResumeScreen))

            # 5. Test /connect and ProvidersScreen
            await handle_slash_command(app, "/connect")
            await pilot.pause(0.5)
            self.assertIsInstance(app.screen, ProvidersScreen)
            await pilot.press("escape")
            await pilot.pause(0.2)

            # 6. Test /models and model search
            await handle_slash_command(app, "/models")
            await pilot.pause(0.5)
            self.assertIsInstance(app.screen, ModelScreen)
            await pilot.press("d", "e", "e", "p", "space", "f", "l", "a", "s", "h")
            await pilot.pause(0.2)
            self.assertGreater(len(app.screen.filtered_items), 0)
            await pilot.press("escape")
            await pilot.pause(0.2)

            # 7. Test /new
            await handle_slash_command(app, "/new")
            await pilot.pause(0.5)
            chat_view = app.query_one(ChatView)
            self.assertEqual(len(chat_view.get_user_messages()), 0)

            # 8. Test /tasks
            await handle_slash_command(app, "/tasks")
            await pilot.pause(0.2)
            self.assertFalse(isinstance(app.screen, TasksListScreen))

            # 9. Test mode toggle via Shift+Tab
            self.assertEqual(getattr(app.agent, "mode", "action"), "action")
            await pilot.press("shift+tab")
            await pilot.pause(0.2)
            self.assertEqual(getattr(app.agent, "mode", "action"), "explore")
            await pilot.press("shift+tab")
            await pilot.pause(0.2)
            self.assertEqual(getattr(app.agent, "mode", "action"), "action")

            # 10. Test input height auto-expansion on multiline text insert
            chat_input.load_text("")
            chat_input.insert("line1\nline2\nline3\nline4")
            await pilot.pause(0.1)
            self.assertEqual(chat_input.styles.height.value, 5)

            # 11. Test long text folding on paste (> 10 lines)
            chat_input.load_text("")
            from textual import events

            chat_input.on_paste(events.Paste("hello\n" * 15))
            await pilot.pause(0.1)
            self.assertIn("[Pasted text #1 +15 lines]", chat_input.text)
            self.assertEqual(chat_input.get_full_text(), "hello\n" * 15)

            # 12. Test atomic deletion of paste block via Backspace
            chat_input.move_cursor((0, len(chat_input.text)))
            await pilot.press("backspace")
            await pilot.pause(0.1)
            self.assertEqual(chat_input.text, "")
            self.assertEqual(chat_input.pasted_texts, {})

    async def test_message_queue(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True

            class FakeEvent:
                value = "Queued message"

            await app.on_chat_input_submitted(FakeEvent())
            self.assertEqual(len(app.message_queue), 1)
            self.assertEqual(app.message_queue[0], ("Queued message", True))

    def test_resume_tip_on_exit(self):
        from io import StringIO
        from unittest.mock import patch

        app = JohnstonApp()
        app.sm.save_session(app.current_session_id, {"ui_messages": [{"type": "user", "text": "hi"}]})

        out = StringIO()
        with patch("sys.stdout", out):
            if getattr(app, "current_session_id", None) and hasattr(app, "sm"):
                sess = app.sm.load_session(app.current_session_id)
                if sess and (sess.get("ui_messages") or sess.get("agent_history")):
                    print(f"\nTo resume this session, run:\n  johnston --resume {app.current_session_id}")

        self.assertIn(f"johnston --resume {app.current_session_id}", out.getvalue())

    async def test_resume_cli_flag(self):
        app = JohnstonApp()
        app.sm.save_session(
            "test_sess_123",
            {
                "ui_messages": [{"type": "user", "text": "Resumed user msg"}],
                "agent_history": [{"role": "user", "content": "Resumed user msg"}],
            },
        )

        resumed_app = JohnstonApp(resume_session_id="test_sess_123")
        async with resumed_app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertEqual(resumed_app.current_session_id, "test_sess_123")
            chat_view = resumed_app.query_one(ChatView)
            user_msgs = chat_view.get_user_messages()
            self.assertEqual(len(user_msgs), 1)
            self.assertEqual(user_msgs[0][1], "Resumed user msg")

    async def test_modal_ctrl_c_quit(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            from core.commands import handle_slash_command
            await handle_slash_command(app, "/models")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, ModelScreen)

            await pilot.press("ctrl+c")
            await pilot.pause(0.2)
            self.assertFalse(app.is_running)

    async def test_interrupted_divider_serialization(self):
        app = JohnstonApp()
        async with app.run_test():
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("Hello")
            divider = await chat_view.add_compaction_divider("Response Interrupted")
            self.assertEqual(divider.divider_title, "Response Interrupted")

            app.save_current_session()
            sess = app.sm.load_session(app.current_session_id)
            self.assertIsNotNone(sess)
            ui_msgs = sess.get("ui_messages", [])
            self.assertTrue(
                any(m.get("type") == "compaction_divider" and m.get("text") == "Response Interrupted" for m in ui_msgs)
            )

    async def test_click_event_handler(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            app.on_click(click_evt)


if __name__ == "__main__":
    unittest.main()
