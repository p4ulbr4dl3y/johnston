import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from johnston.core.domain.defaults.errors import ToolResult
from johnston.core.domain.entities.session import AgentSession
from johnston.tui.mixins.message_flow_auto_title import schedule_auto_title
from johnston.tui.mixins.message_flow_queue import (
    pop_queued_for_current_session,
    process_queued_message,
    queue_message_ui,
)
from johnston.tui.mixins.message_flow_shell import exec_shell_command


class TestMessageFlowQueueModule(unittest.IsolatedAsyncioTestCase):
    def test_queue_message_ui_variants(self):
        app = SimpleNamespace(current_session_id="s123", message_queue=[], notify=MagicMock())

        # With display_text
        queue_message_ui(app, "cmd", show_in_ui=True, attachments=["a1"], display_text="/display")
        self.assertEqual(len(app.message_queue), 1)
        self.assertEqual(app.message_queue[0], ("cmd", True, ["a1"], "s123", "/display"))
        app.notify.assert_called_once_with("Message queued", severity="information")

        # Without attachments or display_text
        queue_message_ui(app, "prompt2", show_in_ui=False)
        self.assertEqual(len(app.message_queue), 2)
        self.assertEqual(app.message_queue[1], ("prompt2", False, None, "s123"))

    def test_pop_queued_for_current_session(self):
        # Empty queue or None queue
        app = SimpleNamespace(current_session_id="s1", message_queue=None)
        self.assertIsNone(pop_queued_for_current_session(app))

        app.message_queue = [
            ("other_msg", True, None, "s_other"),
            ("curr_msg", True, None, "s1"),
        ]
        item = pop_queued_for_current_session(app)
        self.assertEqual(item[0], "curr_msg")
        self.assertEqual(len(app.message_queue), 1)

    async def test_process_queued_message_delegation(self):
        app = SimpleNamespace(
            _exec_shell_command=AsyncMock(),
            _exec_slash_command=AsyncMock(),
            trigger_ai_response=MagicMock(),
        )

        # Shell command
        await process_queued_message(app, "!echo hi")
        await asyncio.sleep(0.01)
        app._exec_shell_command.assert_awaited_once_with("echo hi", user_text="!echo hi")

        # Slash command
        await process_queued_message(app, "/help")
        app._exec_slash_command.assert_awaited_once_with("/help", attachments=None)

        # Regular prompt
        await process_queued_message(app, "hello AI", show_in_ui=False)
        app.trigger_ai_response.assert_called_once_with("hello AI", show_in_ui=False, attachments=None)


class TestMessageFlowShellModule(unittest.IsolatedAsyncioTestCase):
    async def test_exec_shell_command_lifecycle(self):
        chat_input = MagicMock()
        chat_view = MagicMock()
        tool_widget = MagicMock()
        chat_view.add_tool_call = AsyncMock(return_value=tool_widget)
        chat_view.add_user_message = AsyncMock()

        session = AgentSession("s-test")
        sm = MagicMock()
        sm.get.return_value = session

        agent = SimpleNamespace(history=[])

        def query_one(cls_or_selector, default=None):
            if cls_or_selector == "#message-input":
                return chat_input
            return chat_view

        app = SimpleNamespace(
            query_one=query_one,
            current_session_id="s-test",
            sm=sm,
            agent=agent,
            current_tool_widget=None,
            save_current_session_async=AsyncMock(),
            is_app_active=False,
            _apply_pending_fork_or_readonly=MagicMock(),
        )

        res = ToolResult.done(content="hello output", display="hello output", returncode=0)
        with patch("johnston.core.tools.shell.ShellTool.execute", new_callable=AsyncMock, return_value=res):
            await exec_shell_command(app, "echo hello", user_text="!echo hello")

        chat_input.focus.assert_called_once()
        app._apply_pending_fork_or_readonly.assert_called_once()
        chat_view.add_user_message.assert_awaited_once_with("!echo hello")
        tool_widget.set_result.assert_called_once()
        self.assertEqual(len(agent.history), 1)
        self.assertIn("hello output", agent.history[0]["content"])

    async def test_exec_shell_command_handles_exception(self):
        chat_view = MagicMock()
        tool_widget = MagicMock()
        chat_view.add_tool_call = AsyncMock(return_value=tool_widget)
        chat_view.add_user_message = AsyncMock()

        app = SimpleNamespace(
            query_one=MagicMock(side_effect=lambda target, default=None: chat_view),
            current_session_id=None,
            session=AgentSession("s-fallback"),
            agent=None,
            current_tool_widget=None,
            save_current_session=MagicMock(),
            is_app_active=False,
        )

        with patch("johnston.core.tools.shell.ShellTool.execute", new_callable=AsyncMock, side_effect=RuntimeError("exec error")):
            await exec_shell_command(app, "broken")

        tool_widget.set_result.assert_called_once()
        self.assertTrue(tool_widget.set_result.call_args[1]["is_error"])


class TestMessageFlowAutoTitleModule(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_auto_title_inactivity_guards(self):
        app = SimpleNamespace(is_app_active=False)
        session = MagicMock(auto_titled=False)
        with patch("johnston.core.application.session.auto_title.auto_title_session") as mock_fn:
            schedule_auto_title(app, session)
            await asyncio.sleep(0.01)
            mock_fn.assert_not_called()

        app.is_app_active = True
        session.auto_titled = True
        with patch("johnston.core.application.session.auto_title.auto_title_session") as mock_fn:
            schedule_auto_title(app, session)
            await asyncio.sleep(0.01)
            mock_fn.assert_not_called()
