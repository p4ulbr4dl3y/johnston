import asyncio
import unittest
from unittest.mock import MagicMock, patch

from app import JohnstonApp
from core.base_provider import BaseAgent
from widgets.presentation.widgets.chat_container import ChatView


def _configure_connected(app, stream_fn):
    """Set up app so generate_ai_response proceeds past the connectivity check."""
    app.pm.is_provider_connected = MagicMock(return_value=True)
    app.pm.get_active_provider_key = MagicMock(return_value="openai")
    agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
    agent.stream_steps = stream_fn
    app.agent = agent
    app.pm.create_active_agent = MagicMock(return_value=agent)


class TestGenerateNotConnected(unittest.IsolatedAsyncioTestCase):
    async def test_not_connected_runs_providers_command(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            app.pm.is_provider_connected = MagicMock(return_value=False)
            app.pm.get_active_provider_key = MagicMock(return_value="openai")
            with patch("widgets.commands.ProvidersCommand", return_value=MagicMock()) as mock_cls:
                mock_cls.return_value.execute = unittest.mock.AsyncMock()
                app.generate_ai_response("hello")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if mock_cls.return_value.execute.await_count:
                        break
                    await asyncio.sleep(0)
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
            with patch("widgets.commands.ModelsCommand", return_value=MagicMock()) as mock_cls:
                mock_cls.return_value.execute = unittest.mock.AsyncMock()
                app.generate_ai_response("hello")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if mock_cls.return_value.execute.await_count:
                        break
                    await asyncio.sleep(0)
            mock_cls.return_value.execute.assert_awaited_once_with(app)
            self.assertFalse(app.is_generating)


class TestGenerateStreamEvents(unittest.IsolatedAsyncioTestCase):
    async def _run(self, stream_fn, setup=None):
        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream_fn)
                if setup:
                    setup(app)
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        return app

    async def _wait_not_generating(self, pilot, app, deadline=10.0) -> None:
        """Wait up to `deadline` seconds for generation to finish (replaces fixed sleep)."""
        loop = asyncio.get_running_loop()
        end = loop.time() + deadline
        while loop.time() < end:
            if app.is_generating:
                break
            await pilot.pause(0.05)
        while loop.time() < end:
            if not app.is_generating:
                return
            await pilot.pause(0.05)
        self.assertFalse(app.is_generating)

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
            yield ("tool", "shell", "run", {"cmd": "ls"})
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

    async def test_event_divider(self):
        async def stream(prompt, attachments=None):
            yield ("event_divider", "Compacted", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_queued_user_message(self):
        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, True)

        seen_events = []
        ui_texts = []

        def record(event):
            seen_events.append(event.get("text"))

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                session = app.sm.create_main()
                app.sm.get = MagicMock(return_value=session)
                app.sm.create_main = MagicMock(return_value=session)
                session.add_event = record
                chat_view = app.query_one(ChatView)
                chat_view.add_user_message = unittest.mock.AsyncMock(
                    side_effect=lambda text, attachments=None: ui_texts.append(text)
                )
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)
        # queued message recorded into transcript AND rendered to the UI
        self.assertIn("Mid-turn", seen_events)
        self.assertIn("Mid-turn", ui_texts)

    async def test_queued_user_message_no_show(self):
        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, False)

        ui_texts = []
        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                chat_view = app.query_one(ChatView)
                chat_view.add_user_message = unittest.mock.AsyncMock(
                    side_effect=lambda text, attachments=None: ui_texts.append(text)
                )
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)
        # the initial prompt renders, but the queued (show=False) one must not
        self.assertIn("Prompt", ui_texts)
        self.assertNotIn("Mid-turn", ui_texts)

    async def test_checkpoint_exception_prints(self):
        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, True)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint", side_effect=Exception("boom")):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = unittest.mock.AsyncMock()
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_generation_exception_notifies(self):
        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            raise ValueError("API failed")

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
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
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint", side_effect=Exception("boom")):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = unittest.mock.AsyncMock()
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_save_session_exception_tool_result(self):
        async def stream(prompt, attachments=None):
            yield ("tool", "shell", "run", {"cmd": "ls"})
            yield ("tool_result", "output", "")

        app = JohnstonApp()
        calls = {"n": 0}

        async def flaky_save(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise Exception("boom")

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
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

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_footer_exception_ignored(self):
        async def stream(prompt, attachments=None):
            yield ("bot_text", "hello", "")

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
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
                await self._wait_not_generating(pilot, app)
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
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                app.message_queue.clear()
                # Trigger cancellation via Escape
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.pause(0.1)
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_cancellation_during_add_user_message_not_stuck(self):
        """If Esc lands while the user message is being mounted (before the stream
        loop), is_generating must be released so later input starts a fresh
        generation instead of being queued against a dead one."""
        app = JohnstonApp()
        ran = []
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)

                async def stream(prompt, attachments=None):
                    ran.append(prompt)
                    yield ("bot_text", f"reply to {prompt}", "")

                _configure_connected(app, stream)
                chat_view = app.query_one(ChatView)
                calls = {"n": 0}

                async def cancelled_add_user_message(*args, **kwargs):
                    calls["n"] += 1
                    if calls["n"] == 1:
                        await asyncio.sleep(0.01)
                        raise asyncio.CancelledError
                    return await ChatView.add_user_message(chat_view, *args, **kwargs)

                chat_view.add_user_message = cancelled_add_user_message
                app.generate_ai_response("Prompt 1")
                # A queued message that could otherwise get stuck behind a dead
                # generation must be drained once the cancellation resets the flag.
                app._queue_message_ui("Prompt 2", show_in_ui=True)
                await self._wait_not_generating(pilot, app)
                self.assertFalse(app.is_generating)
                # Drained message spawns a fresh exclusive worker; give it a beat.
                deadline = asyncio.get_running_loop().time() + 2.0
                while asyncio.get_running_loop().time() < deadline:
                    if not app.message_queue and "Prompt 2" in ran:
                        break
                    await pilot.pause(0.1)
        self.assertEqual(len(app.message_queue), 0)
        self.assertIn("Prompt 2", ran)

    async def test_cancellation_thinking_finish_exception(self):

        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_cancellation_thinking_widget_finish_exception(self):

        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                chat_view = app.query_one(ChatView)
                chat_view.add_thinking_widget = unittest.mock.AsyncMock(
                    return_value=MagicMock(finish_thinking=MagicMock(side_effect=Exception("boom")))
                )
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_cancellation_interrupted_divider_exception(self):

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                chat_view = app.query_one(ChatView)
                chat_view.add_event_divider = unittest.mock.AsyncMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_cancellation_thinking_widget_existing_finish_exception(self):

        async def stream(prompt, attachments=None):
            yield ("thinking_start", "Thinking...", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                # Grab the real thinking widget and make finish_thinking raise
                for w in app.query("ThinkingWidget"):
                    w.finish_thinking = MagicMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_cancellation_bot_msg_finalize_and_remove_exception(self):

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                # Patch bot message widgets to raise on finalize/remove
                for w in app.query("BotMessage"):
                    w.finalize_stream = unittest.mock.AsyncMock(side_effect=Exception("boom"))
                    w.remove = MagicMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_cancellation_bot_msg_remove_exception(self):

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "content", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                # Make the bot message content empty and remove raise
                for w in app.query("BotMessage"):
                    w.content = ""
                    w.finalize_stream = unittest.mock.AsyncMock(side_effect=Exception("boom"))
                    w.remove = MagicMock(side_effect=Exception("boom"))
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)

    async def test_tool_event_after_bot_text_finalizes(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "text before tool", "")
            yield ("tool", "shell", "run", {"cmd": "ls"})
            yield ("bot_text", "after tool", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_tool_event_after_empty_bot_removes(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "   ", "")
            yield ("tool", "shell", "run", {"cmd": "ls"})

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_tool_event_flushes_pending_stream(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "text before tool", "")
            yield ("tool", "shell", "run", {"cmd": "ls"})

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_tool_event_after_empty_content_bot_msg(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "content", "")
            yield ("tool", "shell", "run", {"cmd": "ls"})

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                chat_view = app.query_one(ChatView)
                chat_view.add_bot_message = unittest.mock.AsyncMock(return_value=MagicMock(content=""))
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_cancellation_marks_current_tool_cancelled(self):
        # A tool call is emitted, then the stream hangs. Esc interrupts the
        # generation; the in-flight tool widget must be marked cancelled (not
        # left stuck in "running").
        async def stream(prompt, attachments=None):
            yield ("tool", "shell", "run", {"cmd": "tail -f log"})
            await asyncio.sleep(30.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if getattr(app, "current_tool_widget", None) is not None:
                        break
                    await pilot.pause(0.1)
                self.assertIsNotNone(getattr(app, "current_tool_widget", None))
                self.assertEqual(app.current_tool_widget.status, "running")
                chat_input = app.query_one("#message-input")
                chat_input.focus()
                await pilot.press("escape")
                await self._wait_not_generating(pilot, app)
        self.assertEqual(app.current_tool_widget.status, "cancelled")
        self.assertIn("interrupted or cancelled", app.current_tool_widget.result_text)

    async def test_bot_delta_existing_bot_msg(self):
        async def stream(prompt, attachments=None):
            yield ("bot_delta", "start", "")
            yield ("bot_delta", "more", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_bot_delta_preserves_whitespace_chunks(self):
        """Whitespace-only deltas must not be dropped (would glue words together)."""
        calls = []

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "hello", "")
            yield ("bot_delta", " ", "")
            yield ("bot_delta", "world", "")

        def setup(app):
            chat_view = app.query_one(ChatView)
            orig = chat_view.add_bot_message

            async def wrapped_add():
                msg = await orig()
                msg.append_stream_content = lambda c: calls.append(c)
                return msg

            chat_view.add_bot_message = wrapped_add

        await self._run(stream, setup=setup)
        self.assertEqual("".join(calls), "hello world")

    async def test_bot_delta_whitespace_only_does_not_create_message(self):
        """A whitespace-only leading delta must not mount an empty bot message."""
        created = []

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "   ", "")
            yield ("bot_delta", "text", "")

        def setup(app):
            chat_view = app.query_one(ChatView)
            orig = chat_view.add_bot_message

            async def wrapped_add():
                msg = await orig()
                created.append(msg)
                return msg

            chat_view.add_bot_message = wrapped_add

        await self._run(stream, setup=setup)
        self.assertEqual(len(created), 1)

    async def test_bot_reset_clears_partial_stream(self):
        """bot_reset must clear partial streamed text so a retry starts blank."""
        reset_calls = []
        appended = []

        async def stream(prompt, attachments=None):
            yield ("bot_delta", "partial text", "")
            yield ("bot_reset", "", "")
            yield ("bot_delta", "fresh", "")
            yield ("bot_text", "fresh", "")

        def setup(app):
            chat_view = app.query_one(ChatView)
            orig = chat_view.add_bot_message

            async def wrapped_add():
                msg = await orig()
                msg.reset_stream = unittest.mock.AsyncMock(side_effect=lambda: reset_calls.append(1))
                msg.append_stream_content = lambda c: appended.append(c)
                return msg

            chat_view.add_bot_message = wrapped_add

        await self._run(stream, setup=setup)
        self.assertEqual(len(reset_calls), 1)
        self.assertEqual("".join(appended), "partial textfresh")

    async def test_bot_reset_without_bot_msg_is_noop(self):
        """bot_reset with no bot message must not raise."""

        async def stream(prompt, attachments=None):
            yield ("bot_reset", "", "")
            yield ("bot_text", "ok", "")

        app = await self._run(stream)
        self.assertFalse(app.is_generating)

    async def test_compaction_save_exception(self):
        async def stream(prompt, attachments=None):
            yield ("event_divider", "Compacted", "")

        app = JohnstonApp()
        calls = {"n": 0}

        async def flaky_save(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                raise Exception("boom")

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await pilot.pause(0.5)
        self.assertFalse(app.is_generating)

    async def test_token_estimate_exception(self):

        async def stream(prompt, attachments=None):
            yield ("bot_text", "", "")
            await asyncio.sleep(5.0)

        app = JohnstonApp()
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.generate_ai_response("Prompt")
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if app.is_generating:
                        break
                    await pilot.pause(0.1)
                self.assertTrue(app.is_generating)
                with patch("core.infrastructure.runtime.token_util.estimate_tokens", side_effect=Exception("boom")):
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
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.notify = MagicMock(side_effect=Exception("boom"))
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
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
        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
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
                await self._wait_not_generating(pilot, app)
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

        with patch("core.infrastructure.storage.git_checkpoint.GitCheckpointManager.create_checkpoint"):
            async with app.run_test() as pilot:
                await pilot.pause(0.1)
                _configure_connected(app, stream)
                app.save_current_session_async = flaky_save
                app.generate_ai_response("Prompt")
                await self._wait_not_generating(pilot, app)
        self.assertFalse(app.is_generating)
