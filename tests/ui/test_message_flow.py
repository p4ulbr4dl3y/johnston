import asyncio
import unittest
from unittest.mock import MagicMock, patch

from app import JohnstonApp
from core.base_provider import BaseAgent
from widgets.mixins.message_flow import MessageFlowMixin


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
            with patch.object(app, "query_one", side_effect=Exception("boom")):
                await app.on_paste(events.Paste("hello"))  # must not raise


class TestExecSlashCommand(unittest.IsolatedAsyncioTestCase):
    async def test_slash_command_unprocessed_single_tokens_notifies(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch(
                "widgets.mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock
            ) as mock_h:
                mock_h.return_value = False
                app.is_generating = False
                app.trigger_ai_response = MagicMock()
                await app._exec_slash_command("/unknown")
            app.notify.assert_called_once()

    async def test_slash_command_unprocessed_multiple_tokens_ai(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch(
                "widgets.mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock
            ) as mock_h:
                mock_h.return_value = False
                app.is_generating = False
                app.trigger_ai_response = MagicMock()
                await app._exec_slash_command("/help now")
            app.trigger_ai_response.assert_called_once_with("/help now", show_in_ui=True)

    async def test_slash_command_unprocessed_generating_queues(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch(
                "widgets.mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock
            ) as mock_h:
                mock_h.return_value = False
                app.is_generating = True
                app._queue_message_ui = MagicMock()
                await app._exec_slash_command("/help now")
            app._queue_message_ui.assert_called_once()

    async def test_slash_command_exception_notifies(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            with patch(
                "widgets.mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock
            ) as mock_h:
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


class TestHasQueuedMessages(unittest.TestCase):
    def _agent(self, app):
        agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
        agent.app = app
        return agent

    def test_no_app_returns_false(self):
        agent = BaseAgent(api_key="test", model="gpt-4o", provider_key="openai")
        self.assertFalse(agent._has_queued_messages())

    def test_subagent_returns_false(self):
        app = MagicMock()
        app.message_queue = [("hi", True, None, "s1")]
        app.current_session_id = "s1"
        agent = self._agent(app)
        agent.is_subagent = True
        self.assertFalse(agent._has_queued_messages())

    def test_empty_queue_returns_false(self):
        app = MagicMock()
        app.message_queue = []
        app.current_session_id = "s1"
        self.assertFalse(self._agent(app)._has_queued_messages())

    def test_matching_session_returns_true(self):
        app = MagicMock()
        app.message_queue = [("hi", True, None, "s1")]
        app.current_session_id = "s1"
        self.assertTrue(self._agent(app)._has_queued_messages())

    def test_other_session_returns_false(self):
        app = MagicMock()
        app.message_queue = [("hi", True, None, "s_old")]
        app.current_session_id = "s1"
        self.assertFalse(self._agent(app)._has_queued_messages())

    def test_none_session_item_matches(self):
        app = MagicMock()
        app.message_queue = [("hi", True, None)]
        app.current_session_id = "s1"
        self.assertTrue(self._agent(app)._has_queued_messages())


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
                "widgets.mixins.message_flow.handle_slash_command", new_callable=unittest.mock.AsyncMock
            ) as mock_h:
                event = MagicMock()
                event.value = "/help"
                event.attachments = []
                await app.on_chat_input_submitted(event)
                deadline = asyncio.get_running_loop().time() + 10
                while asyncio.get_running_loop().time() < deadline:
                    if mock_h.await_count:
                        break
                    await asyncio.sleep(0)
                mock_h.assert_awaited_once_with(app, "/help")


class TestTriggerAiResponse(unittest.IsolatedAsyncioTestCase):
    async def test_trigger_queues_when_generating(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = True
            app._queue_message_ui = MagicMock()
            app.trigger_ai_response("hello")
            app._queue_message_ui.assert_called_once_with("hello", show_in_ui=False, attachments=None)

    async def test_trigger_starts_generation(self):
        app = JohnstonApp()
        async with app.run_test():
            app.is_generating = False
            app.generate_ai_response = MagicMock()
            app.trigger_ai_response("hello")
            self.assertTrue(app.is_generating)
            app.generate_ai_response.assert_called_once_with("hello", show_in_ui=False)
