import asyncio
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView, ToolCallWidget
from widgets.command_suggestions import CommandSuggestions


class IsolatedJohnstonUITest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.config_dir = os.path.join(self.test_dir, "config")
        self.projects_dir = os.path.join(self.test_dir, "projects")
        self.provider_config = os.path.join(self.config_dir, "config.json")
        self.providers_json = os.path.join(self.config_dir, "providers.json")
        self.patchers = [
            patch("core.provider_manager.CONFIG_DIR", self.config_dir),
            patch("core.provider_manager.CONFIG_FILE", self.provider_config),
            patch("core.provider_manager.PROVIDERS_JSON_FILE", self.providers_json),
            patch("core.session_manager.CONFIG_DIR", self.config_dir),
            patch("core.session_manager.PROJECTS_DIR", self.projects_dir),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        shutil.rmtree(self.test_dir)

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

        with patch("app.handle_slash_command", new_callable=AsyncMock) as mock_handle:
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

            matches = suggestions.update_query("/he", "/he", 3)
            self.assertEqual(suggestions.mode, "command")
            self.assertTrue(suggestions.display)
            self.assertIn("/help", matches)

            matches = suggestions.update_query("/help now", "/help now", 9)
            self.assertEqual(matches, [])
            self.assertFalse(suggestions.display)

    async def test_file_suggestion_replaces_current_at_token_and_preserves_cursor(self):
        app = JohnstonApp()

        async with app.run_test():
            chat_input = app.query_one("#message-input", ChatInput)

            chat_input.load_text("attach @REA")
            chat_input.move_cursor((0, len("attach @REA")))
            chat_input.apply_file_suggestion("README.md", 7)

            self.assertEqual(chat_input.text, "attach @README.md ")
            self.assertEqual(chat_input.cursor_location, (0, len("attach @README.md ")))

    async def test_chat_view_appends_messages_and_tool_widgets_in_order(self):
        app = JohnstonApp()

        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("first")
            await chat_view.add_bot_message()
            tool = await chat_view.add_tool_call("read", "README.md", "contents", {"path": "README.md"})
            await pilot.pause()

            children = list(chat_view.children)
            self.assertEqual([type(child).__name__ for child in children[-3:]], ["UserMessage", "BotMessage", "ToolCallWidget"])
            self.assertIsInstance(tool, ToolCallWidget)
            self.assertEqual(chat_view.get_user_messages()[-1][1], "first")

    async def test_safe_update_markdown_handles_cancellation(self):
        from unittest.mock import PropertyMock

        from textual.widgets import Markdown

        from widgets.chat_view import safe_update_markdown

        md = Markdown("")

        async def dummy_cancelled_coro():
            raise asyncio.CancelledError()

        mock_update = MagicMock(return_value=dummy_cancelled_coro())
        md.update = mock_update

        with patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=True):
            safe_update_markdown(md, "test content")
            await asyncio.sleep(0.01)

    def test_clean_markdown_for_rendering(self):
        from widgets.chat_view import clean_markdown_for_rendering

        raw = (
            "3. Section:\n"
            "   * * Double bullet item\n"
            " * *Drafting:* label\n"
            "     > * Blockquote bullet\n"
            " * Text: *Wait, unpaired star\n"
        )
        cleaned = clean_markdown_for_rendering(raw)
        self.assertIn("   * Double bullet item", cleaned)
        self.assertIn(" * **Drafting:** label", cleaned)
        self.assertIn("     > Blockquote bullet", cleaned)
        self.assertIn(" * Text: Wait, unpaired star", cleaned)

    def test_tool_call_widget_extracts_mcp_info(self):
        from widgets.chat_view import ToolCallWidget

        # Case 1: Standard lowercase keys
        item = ToolCallWidget("call_mcp_tool", "", "", args={"server": "colab", "tool": "add_cell", "arguments": {"x": 1}})
        tool, server, args = item._extract_mcp_call_info()
        self.assertEqual((tool, server, args), ("add_cell", "colab", {"x": 1}))

        # Case 2: PascalCase keys (ToolName / ServerName / Arguments)
        item2 = ToolCallWidget("call_mcp_tool", "", "", args={"ServerName": "colab-mcp", "ToolName": "run_cell", "Arguments": {"y": 2}})
        tool2, server2, args2 = item2._extract_mcp_call_info()
        self.assertEqual((tool2, server2, args2), ("run_cell", "colab-mcp", {"y": 2}))

        # Case 3: Missing tool name key, top-level arguments
        item3 = ToolCallWidget("call_mcp_tool", "", "", args={"server": "colab", "code": "print(1)"})
        tool3, server3, args3 = item3._extract_mcp_call_info()
        self.assertEqual((tool3, server3, args3), ("call_mcp_tool", "colab", {"code": "print(1)"}))


if __name__ == "__main__":
    unittest.main()

