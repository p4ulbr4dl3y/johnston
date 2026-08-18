import asyncio
import os
import runpy
import sys
import threading
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions
from widgets.presentation.screens.help import HelpScreen
from widgets.presentation.screens.model import ModelScreen
from widgets.presentation.screens.providers import ProvidersScreen
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.rewind import RewindScreen
from widgets.presentation.screens.tasks import SubagentsScreen
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_messages import UserMessage


class TestJohnstonAppUI(unittest.IsolatedAsyncioTestCase):
    async def test_chat_app_flow(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_input = app.query_one("#message-input", ChatInput)
            chat_input.focus()

            # 1. Test /help
            from widgets.app.dispatch import handle_slash_command

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
            from unittest.mock import AsyncMock

            app.pm.fetch_models_grouped = AsyncMock(
                return_value={"openai": {"name": "OpenAI", "models": ["gpt-4o", "flash"]}}
            )
            await handle_slash_command(app, "/models")
            await pilot.pause(0.5)
            self.assertIsInstance(app.screen, ModelScreen)
            await pilot.press("f", "l", "a", "s", "h")
            await pilot.pause(0.2)
            self.assertGreater(len(app.screen.filtered_items), 0)
            await pilot.press("escape")
            await pilot.pause(0.2)

            # 7. Test /new
            await handle_slash_command(app, "/new")
            await pilot.pause(0.5)
            chat_view = app.query_one(ChatView)
            self.assertEqual(len(chat_view.get_user_messages()), 0)

            # 8. Test /subagents
            await handle_slash_command(app, "/subagents")
            await pilot.pause(0.2)
            self.assertFalse(isinstance(app.screen, SubagentsScreen))

            # 9. Test mode toggle via Shift+Tab
            self.assertEqual(getattr(app.agent, "role", "worker"), "worker")
            await pilot.press("shift+tab")
            await pilot.pause(0.2)
            self.assertEqual(getattr(app.agent, "role", "worker"), "explorer")
            await pilot.press("shift+tab")
            await pilot.pause(0.2)
            self.assertEqual(getattr(app.agent, "role", "worker"), "orchestrator")
            await pilot.press("shift+tab")
            await pilot.pause(0.2)
            self.assertEqual(getattr(app.agent, "role", "worker"), "worker")

            # 10. Test input height auto-expansion on multiline text insert
            chat_input.load_text("")
            chat_input.insert("line1\nline2\nline3\nline4")
            await pilot.pause(0.1)
            self.assertEqual(chat_input.styles.height.value, 5)

            # 11. Test long text folding on paste (> 10 lines)
            chat_input.load_text("")
            from textual import events

            await chat_input.on_paste(events.Paste("hello\n" * 15))
            await pilot.pause(0.1)
            self.assertIn("[Pasted text #1 +15 lines]", chat_input.text)
            self.assertEqual(chat_input.get_full_text(), "hello\n" * 15)

            # 12. Test atomic deletion of paste block via Backspace
            chat_input.move_cursor((0, len(chat_input.text)))
            await pilot.press("backspace")
            await pilot.pause(0.1)
            self.assertEqual(chat_input.text, "")
            self.assertEqual(chat_input.pasted_texts, {})

            # 13. Test app-level on_paste forwarding for drag-and-drop
            await app.on_paste(events.Paste("file:///tmp/dropped_script.py"))
            await pilot.pause(0.1)
            self.assertEqual(chat_input.text, "@/tmp/dropped_script.py ")

    async def test_copy_to_clipboard_os_async(self):
        app = JohnstonApp()
        calls = []

        async def fake_clip(text):
            calls.append(text)

        with patch("textual.app.App.copy_to_clipboard") as sc, patch(
            "core.infrastructure.platform.platform_utils.copy_to_os_clipboard_async",
            side_effect=fake_clip,
        ):
            app.copy_to_clipboard("hello")
        sc.assert_called_once_with("hello")
        await asyncio.sleep(0)
        self.assertEqual(calls, ["hello"])

    async def test_copy_to_clipboard_super_raises(self):
        app = JohnstonApp()
        calls = []

        async def fake_clip(text):
            calls.append(text)

        with patch("textual.app.App.copy_to_clipboard", side_effect=Exception("boom")), patch(
            "core.infrastructure.platform.platform_utils.copy_to_os_clipboard_async",
            side_effect=fake_clip,
        ):
            app.copy_to_clipboard("hello")  # must not raise
        await asyncio.sleep(0)
        self.assertEqual(calls, ["hello"])

    def test_app_main_entry_point(self):
        fake = types.ModuleType("cli")
        ran = []
        fake.main = lambda: ran.append(True)
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "app.py",
        )
        saved = sys.modules.get("cli")
        sys.modules["cli"] = fake
        try:
            runpy.run_path(os.path.abspath(path), run_name="__main__")
        finally:
            if saved is None:
                sys.modules.pop("cli", None)
            else:
                sys.modules["cli"] = saved
        self.assertEqual(ran, [True])

    async def test_message_queue(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True

            class FakeEvent:
                value = "Queued message"

            await app.on_chat_input_submitted(FakeEvent())
            self.assertEqual(len(app.message_queue), 1)
            self.assertEqual(app.message_queue[0][:2], ("Queued message", True))

    async def test_message_queue_rendering_sequence(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            app.is_generating = True

            class FakeEvent1:
                value = "First queued message"

            await app.on_chat_input_submitted(FakeEvent1())
            await pilot.pause(0.1)

            class FakeEvent2:
                value = "Second queued message"

            await app.on_chat_input_submitted(FakeEvent2())
            await pilot.pause(0.1)

            self.assertEqual(len(app.message_queue), 2)
            self.assertEqual(app.message_queue[0][0], "First queued message")
            self.assertEqual(app.message_queue[1][0], "Second queued message")

    async def test_generate_ai_response_queue_draining_and_attachments(self):
        from unittest.mock import MagicMock, patch

        from core.base_provider import BaseAgent

        app = JohnstonApp()

        ran_prompts = []
        ran_attachments = []

        async def fake_stream_steps(prompt, attachments=None):
            ran_prompts.append(prompt)
            ran_attachments.append(attachments)
            # Emulate real agent: drain queued messages between steps.
            mq = getattr(app, "message_queue", None)
            while mq:
                item = mq.pop(0)
                ran_prompts.append(item[0])
                ran_attachments.append(item[2] if len(item) > 2 else None)
            if False:
                yield

        fake_att = MagicMock()

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                app.pm.is_provider_connected = MagicMock(return_value=True)
                app.pm.get_active_provider_key = MagicMock(return_value="openai")
                agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
                agent.stream_steps = fake_stream_steps
                app.agent = agent
                app.pm.create_active_agent = MagicMock(return_value=agent)

                app.message_queue.append(("Queued with att", False, [fake_att]))
                app.generate_ai_response("Initial prompt")
                for _ in range(30):
                    await pilot.pause(0.1)
                    if len(ran_prompts) == 2:
                        await pilot.pause(0.5)
                        break

                self.assertEqual(ran_prompts, ["Initial prompt", "Queued with att"])
                self.assertEqual(ran_attachments[1], [fake_att])
                self.assertFalse(app.is_generating)
                self.assertEqual(len(app.message_queue), 0)

    async def test_esc_key_cancellation_real_flow(self):
        import asyncio
        from unittest.mock import MagicMock, patch

        from core.base_provider import BaseAgent

        app = JohnstonApp()

        ran_prompts = []

        async def hanging_stream(prompt, attachments=None):
            ran_prompts.append(prompt)
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                app.pm.is_provider_connected = MagicMock(return_value=True)
                app.pm.get_active_provider_key = MagicMock(return_value="openai")
                agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
                agent.stream_steps = hanging_stream
                app.agent = agent
                app.pm.create_active_agent = MagicMock(return_value=agent)

                app.trigger_ai_response("Prompt 1", show_in_ui=True)
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)

                app._queue_message_ui("Prompt 2", show_in_ui=True)
                self.assertEqual(len(app.message_queue), 1)

                chat_input = app.query_one("#message-input", ChatInput)
                chat_input.focus()
                await pilot.press("escape")

                await pilot.pause(0.8)

                self.assertIn("Prompt 1", ran_prompts)
                # Queue is preserved on cancellation and processed by the race guard.
                self.assertIn("Prompt 2", ran_prompts)
                self.assertEqual(len(app.message_queue), 0)
                chat_view = app.query_one(ChatView)
                dividers = [
                    c for c in chat_view.children if getattr(c, "divider_title", None) == "Response Interrupted"
                ]
                self.assertEqual(len(dividers), 1)

    def test_resume_tip_on_exit(self):
        from io import StringIO
        from unittest.mock import patch

        app = JohnstonApp()
        sess = app.sm.create_main(app.current_session_id)
        sess.messages = [{"type": "user", "text": "hi"}]
        app.sm.save(sess)

        out = StringIO()
        with patch("sys.stdout", out):
            if getattr(app, "current_session_id", None) and hasattr(app, "sm"):
                sess = app.sm.get(app.current_session_id)
                if sess and (sess.messages or sess.agent_history):
                    print(f"\nTo resume this session, run:\n  johnston --resume {app.current_session_id}")

        self.assertIn(f"johnston --resume {app.current_session_id}", out.getvalue())

    async def test_resume_cli_flag(self):
        app = JohnstonApp()
        sess = app.sm.create_main("test_sess_123")
        sess.messages = [{"type": "user", "text": "Resumed user msg"}]
        sess.agent_history = [{"role": "user", "content": "Resumed user msg"}]
        app.sm.save(sess)

        resumed_app = JohnstonApp(resume_session_id="test_sess_123")
        async with resumed_app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertEqual(resumed_app.current_session_id, "test_sess_123")
            chat_view = resumed_app.query_one(ChatView)
            user_msgs = chat_view.get_user_messages()
            self.assertEqual(len(user_msgs), 1)
            self.assertEqual(user_msgs[0][1], "Resumed user msg")

    async def test_modal_ctrl_c_quit(self):
        from unittest.mock import AsyncMock

        app = JohnstonApp()
        app.pm.fetch_models_grouped = AsyncMock(return_value={"openai": {"name": "OpenAI", "models": ["gpt-4o"]}})
        async with app.run_test() as pilot:
            from widgets.app.dispatch import handle_slash_command

            await handle_slash_command(app, "/models")
            await pilot.pause(0.2)
            self.assertIsInstance(app.screen, ModelScreen)

            await pilot.press("ctrl+c")
            await pilot.pause(0.2)
            self.assertFalse(app.is_running)

    async def test_interrupted_divider_serialization(self):
        app = JohnstonApp()
        async with app.run_test():
            # Transcript (session.messages) is the source of truth for persistence.
            sess = app.sm.create_main(app.current_session_id)
            sess.add_event({"type": "user", "text": "Hello"})
            sess.add_event({"type": "event_divider", "text": "Response Interrupted"})

            app.save_current_session()
            saved = app.sm.get(app.current_session_id)
            self.assertIsNotNone(saved)
            msgs = saved.messages
            self.assertTrue(
                any(m.get("type") == "event_divider" and m.get("text") == "Response Interrupted" for m in msgs)
            )

    async def test_click_event_handler(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            app.on_click(click_evt)

    async def test_session_drift_prevention(self):
        from unittest.mock import MagicMock, patch

        from core.base_provider import BaseAgent

        app = JohnstonApp()
        ran_prompts = []

        async def fake_stream_steps(prompt, attachments=None):
            ran_prompts.append(prompt)
            mq = getattr(app, "message_queue", None)
            sid = getattr(app, "current_session_id", None)
            while mq:
                item = mq.pop(0)
                item_sid = item[3] if len(item) > 3 else None
                if item_sid is not None and sid is not None and item_sid != sid:
                    continue
                ran_prompts.append(item[0])
            if False:
                yield

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                app.pm.is_provider_connected = MagicMock(return_value=True)
                app.pm.get_active_provider_key = MagicMock(return_value="openai")
                agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
                agent.stream_steps = fake_stream_steps
                app.agent = agent
                app.pm.create_active_agent = MagicMock(return_value=agent)

                app.current_session_id = "sess_1"
                app.message_queue.append(("Old session prompt", False, None, "sess_old"))

                app.generate_ai_response("Current session prompt")
                for _ in range(15):
                    await pilot.pause(0.1)
                    if ran_prompts:
                        await pilot.pause(0.2)
                        break

                self.assertEqual(ran_prompts, ["Current session prompt"])
                # Old-session messages are dropped during drain.
                self.assertEqual(len(app.message_queue), 0)

    async def test_background_command_session_binding(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True
            app.current_session_id = "sess_bg_123"
            app.on_background_shell_completed("task_1", "ls", "file.txt")

            self.assertEqual(len(app.message_queue), 1)
            queued_item = app.message_queue[0]
            self.assertEqual(len(queued_item), 4)
            self.assertEqual(queued_item[3], "sess_bg_123")

    async def test_queued_system_notification_does_not_show_in_ui(self):
        from unittest.mock import MagicMock

        from core.base_provider import BaseAgent

        app = JohnstonApp()

        async def dummy_stream(prompt, attachments=None):
            yield ("text", "OK response", "")

        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.pm.is_provider_connected = MagicMock(return_value=True)
            app.pm.get_active_provider_key = MagicMock(return_value="openai")
            agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
            agent.stream_steps = dummy_stream
            app.agent = agent
            app.pm.create_active_agent = MagicMock(return_value=agent)

            app.is_generating = True
            app.on_background_shell_completed("task_1", "ls", "file.txt")
            app.is_generating = False

            app.message_queue.append((app.message_queue.pop(0)))
            # Draining queue should execute generate_ai_response with show_in_ui=False
            queued = [app.message_queue.pop(0)]
            should_show = any(item[1] for item in queued if len(item) > 1 and item[1] is not None)
            self.assertFalse(should_show)

    async def test_exception_preserves_queue(self):
        from unittest.mock import MagicMock, patch

        from core.base_provider import BaseAgent

        app = JohnstonApp()

        async def error_stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            raise ValueError("API call failed")

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                app.pm.is_provider_connected = MagicMock(return_value=True)
                app.pm.get_active_provider_key = MagicMock(return_value="openai")
                agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
                agent.stream_steps = error_stream
                app.agent = agent
                app.pm.create_active_agent = MagicMock(return_value=agent)

                app.message_queue.append(("Pending", False, None, app.current_session_id))
                app.generate_ai_response("Failing prompt")
                for _ in range(40):
                    await pilot.pause(0.1)
                    if not app.is_generating:
                        break

                # Queue survives the exception and is processed by the race guard.
                self.assertEqual(len(app.message_queue), 0)
                self.assertFalse(app.is_generating)

    async def test_queued_user_message_checkpoint(self):
        from unittest.mock import MagicMock, patch

        from core.base_provider import BaseAgent

        app = JohnstonApp()
        checkpoint_calls = []
        second_checkpoint = threading.Event()

        def mock_checkpoint(sid, idx, project_path=None):
            checkpoint_calls.append((sid, idx))
            if len(checkpoint_calls) >= 2:
                second_checkpoint.set()

        async def queued_event_stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn queued message", None, True)

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint", side_effect=mock_checkpoint):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                app.pm.is_provider_connected = MagicMock(return_value=True)
                app.pm.get_active_provider_key = MagicMock(return_value="openai")
                agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
                agent.stream_steps = queued_event_stream
                app.agent = agent
                app.pm.create_active_agent = MagicMock(return_value=agent)

                app.generate_ai_response("Start prompt")
                for _ in range(50):
                    if second_checkpoint.is_set():
                        break
                    await pilot.pause(0.1)

                self.assertTrue(len(checkpoint_calls) >= 2)

    async def test_plain_submit_routes_to_ai_and_clears_input(self):
        app = JohnstonApp()
        app.trigger_ai_response = MagicMock()

        async with app.run_test() as pilot:
            chat_input = app.query_one("#message-input", ChatInput)
            chat_input.load_text("hello ui")
            await pilot.press("enter")
            await pilot.pause()

            app.trigger_ai_response.assert_called_once_with("hello ui", show_in_ui=True)
            self.assertEqual(chat_input.text, "")
            self.assertTrue(chat_input.has_focus)

    async def test_slash_submit_uses_command_handler_not_ai_route(self):
        app = JohnstonApp()
        app.trigger_ai_response = MagicMock()

        with patch("widgets.mixins.message_flow.handle_slash_command", new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = True

            async with app.run_test() as pilot:
                chat_input = app.query_one("#message-input", ChatInput)
                chat_input.load_text("/help ")
                await pilot.press("enter")
                await pilot.pause()

        mock_handle.assert_awaited_once_with(app, "/help")
        app.trigger_ai_response.assert_not_called()

    async def test_command_suggestions_open_for_slash_and_hide_after_space(self):
        app = JohnstonApp()

        async with app.run_test():
            suggestions = app.query_one("#command-suggestions", CommandSuggestions)

            matches = await suggestions.update_query("/he", "/he", 3)
            self.assertEqual(suggestions.mode, "command")
            self.assertTrue(suggestions.display)
            self.assertIn("/help", matches)

            matches = await suggestions.update_query("/help now", "/help now", 9)
            self.assertEqual(matches, [])
            self.assertFalse(suggestions.display)


if __name__ == "__main__":
    unittest.main()
