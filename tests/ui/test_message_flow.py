"""Coverage-focused tests for core/app_mixins/message_flow.py.

These tests exercise the stream event handling branches in generate_ai_response
and helper methods, using a mounted real JohnstonApp with a stubbed agent
stream, matching the style in tests/ui/test_app.py.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from app import JohnstonApp
from core.app_mixins.message_flow import MessageFlowMixin
from core.base_provider import BaseAgent
from widgets.chat_view import ChatView


def _configure_connected(app, stream_fn):
    """Set up app so generate_ai_response proceeds past the connectivity check."""
    app.pm.is_provider_connected = MagicMock(return_value=True)
    app.pm.get_active_provider_key = MagicMock(return_value="openai")
    agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
    agent.stream_steps = stream_fn
    app.agent = agent
    app.pm.create_active_agent = MagicMock(return_value=agent)


class TestMessageFlowPaste(unittest.IsolatedAsyncioTestCase):
    async def test_on_paste_forwards_to_input(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            chat_input = MagicMock()
            chat_input.on_paste = unittest.mock.AsyncMock()
            with patch.object(app, "query_one", return_value=chat_input):
                await app.on_paste(events.Paste("hello"))
            chat_input.on_paste.assert_awaited_once()
            chat_input.focus.assert_called_once()

    async def test_on_paste_exception(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            with patch.object(
                app, "query_one", side_effect=Exception("boom")
            ):
                await app.on_paste(events.Paste("hello"))  # must not raise


class TestExecSlashCommand(unittest.IsolatedAsyncioTestCase):
    async def test_slash_command_unprocessed_single_tokens_notifies(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch("core.app_mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock) as mock_h:
                mock_h.return_value = False
                app.is_generating = False
                app.trigger_ai_response = MagicMock()
                await app._exec_slash_command("/unknown")
            app.notify.assert_called_once()

    async def test_slash_command_unprocessed_multiple_tokens_ai(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch("core.app_mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock) as mock_h:
                mock_h.return_value = False
                app.is_generating = False
                app.trigger_ai_response = MagicMock()
                await app._exec_slash_command("/help now")
            app.trigger_ai_response.assert_called_once_with("/help now", show_in_ui=True)

    async def test_slash_command_unprocessed_generating_queues(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch("core.app_mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock) as mock_h:
                mock_h.return_value = False
                app.is_generating = True
                app._queue_message_ui = MagicMock()
                await app._exec_slash_command("/help now")
            app._queue_message_ui.assert_called_once()

    async def test_slash_command_exception_notifies(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch("core.app_mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock) as mock_h:
                mock_h.side_effect = Exception("boom")
                await app._exec_slash_command("/help")
            app.notify.assert_called_once()
            self.assertIn("Command execution failed", app.notify.call_args.args[0])


class TestQueueMessageUi(unittest.TestCase):
    def test_queue_message_with_attachments(self):
        obj = MagicMock()
        obj.current_session_id = "s1"
        obj.message_queue = []
        att = MagicMock()
        MessageFlowMixin._queue_message_ui(obj, "prompt", show_in_ui=True, attachments=[att])
        self.assertEqual(obj.message_queue[0], ("prompt", True, [att], "s1"))

    def test_queue_message_notify_exception(self):
        obj = MagicMock()
        obj.current_session_id = "s1"
        obj.message_queue = []
        obj.notify.side_effect = Exception("boom")
        MessageFlowMixin._queue_message_ui(obj, "prompt", show_in_ui=True)
        self.assertEqual(len(obj.message_queue), 1)


class TestChatInputSubmitted(unittest.IsolatedAsyncioTestCase):
    async def test_empty_input_returns(self):
        app = JohnstonApp()
        async with app.run_test():
            event = MagicMock()
            event.value = "   "
            event.attachments = []
            await app.on_chat_input_submitted(event)
            self.assertEqual(len(app.message_queue), 0)

    async def test_attachments_no_text_sets_image_question(self):
        app = JohnstonApp()
        app.trigger_ai_response = MagicMock()
        async with app.run_test():
            event = MagicMock()
            event.attachments = ["file.png"]
            event.value = ""
            await app.on_chat_input_submitted(event)
            app.trigger_ai_response.assert_called_once()
            self.assertEqual(app.trigger_ai_response.call_args.args[0], "What is in this image?")

    async def test_slash_delegates_to_command(self):
        app = JohnstonApp()
        async with app.run_test():
            with patch(
                "core.app_mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock
            ) as mock_h:
                event = MagicMock()
                event.value = "/help"
                event.attachments = []
                await app.on_chat_input_submitted(event)
                await asyncio.sleep(0.05)
                mock_h.assert_awaited_once_with(app, "/help")


class TestTriggerAiResponse(unittest.IsolatedAsyncioTestCase):
    async def test_trigger_queues_when_generating(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True
            app._queue_message_ui = MagicMock()
            app.trigger_ai_response("hello")
            app._queue_message_ui.assert_called_once_with(
                "hello", show_in_ui=False, attachments=None
            )

    async def test_trigger_starts_generation(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            app.generate_ai_response = MagicMock()
            app.trigger_ai_response("hello")
            self.assertTrue(app.is_generating)
            app.generate_ai_response.assert_called_once_with("hello", show_in_ui=False)


class TestGenerateNotConnected(unittest.IsolatedAsyncioTestCase):
    async def test_not_connected_runs_providers_command(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.pm.is_provider_connected = MagicMock(return_value=False)
            app.pm.get_active_provider_key = MagicMock(return_value="openai")
            with patch(
                "core.commands.ProvidersCommand", return_value=MagicMock()
            ) as mock_cls:
                mock_cls.return_value.execute = unittest.mock.AsyncMock()
                app.generate_ai_response("hello")
                await pilot.pause(0.5)
            mock_cls.return_value.execute.assert_awaited_once_with(app)
            self.assertFalse(app.is_generating)

    async def test_connected_no_model_runs_models_command(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.pm.is_provider_connected = MagicMock(return_value=True)
            app.pm.get_active_provider_key = MagicMock(return_value="openai")
            app.agent = MagicMock()
            app.agent.model = ""
            with patch(
                "core.commands.ModelsCommand", return_value=MagicMock()
            ) as mock_cls:
                mock_cls.return_value.execute = unittest.mock.AsyncMock()
                app.generate_ai_response("hello")
                await pilot.pause(0.5)
            mock_cls.return_value.execute.assert_awaited_once_with(app)
            self.assertFalse(app.is_generating)


class TestGenerateStreamEvents(unittest.IsolatedAsyncioTestCase):
    async def _run(self, stream_fn, setup=None):
        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream_fn)
                if setup:
                    setup(app)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        return app

    async def test_thinking_events(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            yield ("thinking_delta", "delta text", "")
            yield ("thinking_end", "1.5", "summary")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_thinking_end_nonfinite_duration(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            yield ("thinking_end", "nan", "summary")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_tool_and_tool_result(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            yield ("tool", "bash", "run", {"cmd": "ls"})
            yield ("tool_result", "output", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_bot_delta_and_text(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "hello ", "")
            yield ("bot_delta", "world", "")
            yield ("bot_text", "final", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_compaction_divider(self):
        async def stream(prompt, attachments=None):
            yield ("compaction_divider", "Compacted", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_queued_user_message(self):
        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, True)

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_queued_user_message_no_show(self):
        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, False)

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_checkpoint_exception_prints(self):
        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, True)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint", side_effect=Exception("boom")):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_generation_exception_notifies(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            raise ValueError("API failed")

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.notify = MagicMock()
                app.generate_ai_response("Prompt")
                for _ in range(40):
                    await pilot.pause(0.1)
                    if not app.is_generating:
                        break
            self.assertTrue(app.notify.called)

    async def test_checkpoint_exception_main_flow(self):
        async def stream(prompt, attachments=None):
            yield ("bot_text", "hello", "")

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint", side_effect=Exception("boom")):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.6)
        self.assertFalse(app.is_generating)

    async def test_save_session_exception_tool_result(self):
        async def stream(prompt, attachments=None):
            yield ("tool", "bash", "run", {"cmd": "ls"})
            yield ("tool_result", "output", "")

        app = JohnstonApp()
        calls = {"n": 0}

        async def flaky_save(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise Exception("boom")

        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_save_session_exception_bot_text(self):
        async def stream(prompt, attachments=None):
            yield ("bot_text", "hello", "")

        app = JohnstonApp()
        calls = {"n": 0}

        async def flaky_save(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise Exception("boom")

        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_footer_exception_ignored(self):
        async def stream(prompt, attachments=None):
            yield ("bot_text", "hello", "")

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                real_qo = app.query_one

                def raiser(selector, *args, **kwargs):
                    if selector == "#status-footer":
                        raise Exception("boom")
                    return real_qo(selector, *args, **kwargs)

                app.query_one = raiser
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_thinking_end_duration_exception(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")

            class BadStr(str):
                pass

            yield ("thinking_end", BadStr("boom"), "summary")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_cancellation_partial_append_and_divider(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                app.message_queue.clear()
                # Trigger cancellation via Escape
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_thinking_finish_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_thinking_widget_finish_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                chat_view = app.query_one(ChatView)
                chat_view.add_thinking_widget = unittest.mock.AsyncMock(
                    return_value=MagicMock(finish_thinking=MagicMock(side_effect=Exception("boom")))
                )
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_interrupted_divider_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                chat_view = app.query_one(ChatView)
                chat_view.add_compaction_divider = unittest.mock.AsyncMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_thinking_widget_existing_finish_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                # Grab the real thinking widget and make finish_thinking raise
                for w in app.query("ThinkingWidget"):
                    w.finish_thinking = MagicMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_bot_msg_finalize_and_remove_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                # Patch bot message widgets to raise on finalize/remove
                for w in app.query("BotMessage"):
                    w.finalize_stream = unittest.mock.AsyncMock(side_effect=Exception("boom"))
                    w.remove = MagicMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_bot_msg_remove_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "content", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                # Make the bot message content empty and remove raise
                for w in app.query("BotMessage"):
                    w.content = ""
                    w.finalize_stream = unittest.mock.AsyncMock(side_effect=Exception("boom"))
                    w.remove = MagicMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_tool_event_after_bot_text_finalizes(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "text before tool", "")
            yield ("tool", "bash", "run", {"cmd": "ls"})
            yield ("bot_text", "after tool", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_tool_event_after_empty_bot_removes(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "   ", "")
            yield ("tool", "bash", "run", {"cmd": "ls"})

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_tool_event_after_empty_content_bot_msg(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "content", "")
            yield ("tool", "bash", "run", {"cmd": "ls"})

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                chat_view = app.query_one(ChatView)
                chat_view.add_bot_message = unittest.mock.AsyncMock(return_value=MagicMock(content=""))
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_bot_delta_existing_bot_msg(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "start", "")
            yield ("bot_delta", "more", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_bot_chunk_appends_content(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "hello", "")
            yield ("bot_chunk", " world", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_compaction_save_exception(self):
        async def stream(prompt, attachments=None):
            yield ("compaction_divider", "Compacted", "")

        app = JohnstonApp()
        calls = {"n": 0}

        async def flaky_save(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise Exception("boom")

        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_token_estimate_exception(self):
        import asyncio

        async def stream(prompt, attachments=None):
            yield ("bot_text", "", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
                self.assertTrue(app.is_generating)
                with patch("core.token_util.estimate_tokens", side_effect=Exception("boom")):
                    chat_input = app.query_one("#message-input")
                    chat_input.focus()
                    await pilot.press("escape")
                    await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_notify_exception_during_failure(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            raise ValueError("API failed")

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.notify = MagicMock(side_effect=Exception("boom"))
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_empty_bot_msg_removed_in_finally(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "   ", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_footer_reset_exception_in_finally(self):
        async def stream(prompt, attachments=None):
            yield ("bot_text", "done", "")

        app = JohnstonApp()
        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                real_qo = app.query_one

                def raiser(selector, *args, **kwargs):
                    if selector == "#status-footer":
                        raise Exception("boom")
                    return real_qo(selector, *args, **kwargs)

                app.query_one = raiser
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_save_force_exception_in_finally(self):
        async def stream(prompt, attachments=None):
            yield ("bot_text", "done", "")

        app = JohnstonApp()
        calls = {"n": 0}

        async def flaky_save(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 3:
                raise Exception("boom")

        with patch("core.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)


class TestBackgroundShellCompleted(unittest.IsolatedAsyncioTestCase):
    async def test_completed_not_active_returns(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_app_active = False
            app.on_background_shell_completed("t1", "ls", "out")

    async def test_completed_generating_queues(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True
            app.current_session_id = "s1"
            app.on_background_shell_completed("t1", "ls", "out")
            self.assertEqual(len(app.message_queue), 1)
            self.assertEqual(app.message_queue[0][3], "s1")

    async def test_completed_exception(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            with patch.object(app, "generate_ai_response", side_effect=Exception("boom")):
                app.on_background_shell_completed("t1", "ls", "out")


if __name__ == "__main__":
    unittest.main()
