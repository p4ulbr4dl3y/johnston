import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from app import JohnstonApp
from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_markdown import clean_markdown_for_rendering, safe_update_markdown, to_snake_case
from widgets.presentation.widgets.chat_messages import BotMessage, EventDivider, ThinkingWidget, UserMessage
from widgets.presentation.widgets.chat_welcome import WelcomeWidget


class TestChatView(unittest.IsolatedAsyncioTestCase):
    async def test_chat_view_appends_messages_and_tool_widgets_in_order(self):
        app = JohnstonApp()

        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("first")
            await chat_view.add_bot_message()
            tool = await chat_view.add_tool_call("read", "README.md", "contents", {"path": "README.md"})
            await pilot.pause()

            children = list(chat_view.children)
            self.assertEqual(
                [type(child).__name__ for child in children[-3:]], ["UserMessage", "BotMessage", "ToolCallWidget"]
            )
            self.assertIsInstance(tool, ToolCallWidget)
            self.assertEqual(chat_view.get_user_messages()[-1][1], "first")

    async def test_safe_update_markdown_handles_cancellation(self):
        from unittest.mock import PropertyMock

        from textual.widgets import Markdown

        md = Markdown("")

        async def dummy_cancelled_coro():
            raise asyncio.CancelledError()

        mock_update = MagicMock(return_value=dummy_cancelled_coro())
        md.update = mock_update

        with patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=True):
            safe_update_markdown(md, "test content")
            await asyncio.sleep(0.01)

    async def test_streaming_bot_message_renders_markdown_only_once_at_end(self):
        app = JohnstonApp()

        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            bot = await chat_view.add_bot_message(animate=False)
            await pilot.pause()

            with patch.object(bot.md_widget, "update", new_callable=AsyncMock) as markdown_update:
                markdown_update.return_value = None
                for idx in range(100):
                    bot.set_stream_content(f"stream chunk {idx}")

                await pilot.pause(0.1)
                markdown_update.assert_not_awaited()
                self.assertTrue(bot.stream_widget.display)
                self.assertFalse(bot.md_widget.display)

                await bot.finalize_stream()

                markdown_update.assert_awaited_once_with("stream chunk 99")
                self.assertFalse(bot.stream_widget.display)
                self.assertTrue(bot.md_widget.display)

    async def test_large_bot_message_renders_via_interactive_markdown(self):
        app = JohnstonApp()

        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            bot = await chat_view.add_bot_message(animate=False)
            await pilot.pause()

            large_markdown = ("## Section\n\n- item\n\n" * 400).strip()
            with patch.object(bot.md_widget, "update", new_callable=AsyncMock) as markdown_update:
                await bot.set_final_content(large_markdown)

            markdown_update.assert_awaited_once()
            self.assertFalse(bot.stream_widget.display)
            self.assertTrue(bot.md_widget.display)

    def test_clean_markdown_for_rendering(self):
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
        # Single asterisks in prose are preserved (not stripped as "unpaired italic").
        self.assertIn(" * Text: *Wait, unpaired star", cleaned)

    def test_clean_markdown_preserves_single_asterisks(self):
        cases = [
            "def f(*args): return x",
            "2 * 3 = 6",
            "from x import *",
            "value = a * b",
            "Filename: *.py",
            "`rm *.py`",
            "5*5=25",
        ]
        for raw in cases:
            self.assertEqual(clean_markdown_for_rendering(raw), raw)

    def test_to_snake_case(self):
        self.assertEqual(to_snake_case("openColabBrowser"), "open_colab_browser")
        self.assertEqual(to_snake_case("OpenColabBrowser"), "open_colab_browser")
        self.assertEqual(to_snake_case("search_issues"), "search_issues")
        self.assertEqual(to_snake_case(""), "")
        self.assertEqual(to_snake_case("  spaced name "), "_spaced_name_")


class TestChatViewBehaviors(unittest.IsolatedAsyncioTestCase):
    async def test_add_user_message_with_attachments(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            msg = await chat_view.add_user_message("hello", attachments=["a.png", "b.png"])
            await pilot.pause()
            self.assertIn("2 images attached", msg.raw_text)
            self.assertIsInstance(msg, UserMessage)

    async def test_add_user_message_with_attachments_count(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            msg = await chat_view.add_user_message("hello", attachments_count=1)
            await pilot.pause()
            self.assertIn("1 image attached", msg.raw_text)
            self.assertIsInstance(msg, UserMessage)


    async def test_add_user_message_when_unattached_waits(self):
        chat_view = ChatView()
        with (
            patch.object(ChatView, "is_attached", new_callable=PropertyMock, return_value=False),
            patch.object(chat_view, "_wait_until_attached", new_callable=AsyncMock) as wait_mock,
            patch.object(chat_view, "mount", new_callable=AsyncMock),
        ):
            msg = await chat_view.add_user_message("waiting")
        wait_mock.assert_awaited_once()
        self.assertIsInstance(msg, UserMessage)

    async def test_add_thinking_and_compaction_widgets(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            thinking = await chat_view.add_thinking_widget("Thinking...", animate=False)
            divider = await chat_view.add_event_divider("Session Compacted", animate=False)
            await pilot.pause()
            self.assertIsInstance(thinking, ThinkingWidget)
            self.assertIsInstance(divider, EventDivider)

    async def test_add_tool_call_sequential_flag(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            first = await chat_view.add_tool_call("shell", "cmd", "out1", animate=False)
            second = await chat_view.add_tool_call("shell", "cmd2", "out2", animate=False)
            await pilot.pause()
            self.assertNotIn("tool-sequential", first.classes)
            self.assertIn("tool-sequential", second.classes)

            # Expanding first removes tool-sequential on second so it gets top margin
            first.toggle_expanded()
            self.assertNotIn("tool-sequential", second.classes)

            # Collapsing first restores tool-sequential on second
            first.toggle_expanded()
            self.assertIn("tool-sequential", second.classes)

    async def test_add_tool_call_sequential_flag_when_first_already_expanded(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            first = await chat_view.add_tool_call("shell", "cmd", "out1", animate=False)
            first.toggle_expanded()
            second = await chat_view.add_tool_call("shell", "cmd2", "out2", animate=False)
            await pilot.pause()
            self.assertNotIn("tool-sequential", second.classes)

    async def test_add_tool_call_sequential_flag_ignores_empty_bot_message(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_tool_call("shell", "cmd", "out1", animate=False)
            await chat_view.add_bot_message(animate=False)
            second = await chat_view.add_tool_call("shell", "cmd2", "out2", animate=False)
            await pilot.pause()
            self.assertIn("tool-sequential", second.classes)

    async def test_check_welcome_mounts_and_clears(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await pilot.pause()
            self.assertEqual(len(chat_view.query(WelcomeWidget)), 1)
            await chat_view.add_user_message("hello")
            await pilot.pause()
            self.assertEqual(len(chat_view.query(WelcomeWidget)), 0)

    async def test_check_welcome_removes_welcome_when_messages_exist(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await pilot.pause()
            self.assertEqual(len(chat_view.query(WelcomeWidget)), 1)
            welcome = chat_view.query_one(WelcomeWidget)
            with patch.object(welcome, "remove") as remove_mock:
                chat_view.check_welcome()
            remove_mock.assert_not_called()

            await chat_view.add_user_message("hello")
            await pilot.pause()
            extra = WelcomeWidget()
            await chat_view.mount(extra)
            with patch.object(extra, "remove") as remove_mock2:
                chat_view.check_welcome()
            remove_mock2.assert_called_once()

    async def test_check_welcome_show_welcome_false(self):
        chat_view = ChatView(show_welcome=False)
        chat_view.clear_welcome = MagicMock()
        chat_view.check_welcome()
        chat_view.clear_welcome.assert_called_once()

        chat_view2 = ChatView(show_welcome=False)
        with patch.object(chat_view2, "query", return_value=[MagicMock()]):
            chat_view2.clear_welcome = MagicMock()
            chat_view2.check_welcome()

    async def test_rollback_to_removes_children(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("one")
            await chat_view.add_user_message("two")
            await chat_view.add_bot_message()
            await pilot.pause()
            chat_view.rollback_to(0)
            await pilot.pause()
            self.assertLessEqual(len(list(chat_view.children)), 2)

    async def test_toggle_expand_modes(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            tool = await chat_view.add_tool_call("shell", "cmd", "out", animate=False)
            await pilot.pause()

            chat_view.toggle_expand("expand")
            self.assertTrue(tool.is_expanded)
            chat_view.toggle_expand("collapse")
            self.assertFalse(tool.is_expanded)
            chat_view.toggle_expand("expand_all")
            self.assertTrue(tool.is_expanded)
            chat_view.toggle_expand("collapse_all")
            self.assertFalse(tool.is_expanded)
            chat_view.toggle_expand("focus")
            self.assertTrue(tool.is_expanded)
            chat_view.toggle_expand("toggle")
            self.assertFalse(tool.is_expanded)

    async def test_toggle_expand_with_thinking_widget_and_focus(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            thinking = await chat_view.add_thinking_widget("Thinking...", animate=False)
            tool = await chat_view.add_tool_call("shell", "cmd", "out", animate=False)
            await pilot.pause()

            chat_view.toggle_expand("expand")
            self.assertTrue(thinking.is_expanded)
            self.assertTrue(tool.is_expanded)

            app.set_focus(tool)
            chat_view.toggle_expand("collapse")
            self.assertFalse(tool.is_expanded)
            chat_view.toggle_expand("focus")
            self.assertTrue(tool.is_expanded)

    async def test_add_bot_message_loading_session_no_scroll(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            chat_view._is_loading_session = True
            bot = await chat_view.add_bot_message(animate=True)
            await pilot.pause()
            self.assertIsInstance(bot, BotMessage)

    async def test_add_widgets_when_unattached_wait(self):
        chat_view = ChatView()
        with (
            patch.object(ChatView, "is_attached", new_callable=PropertyMock, return_value=False),
            patch.object(chat_view, "_wait_until_attached", new_callable=AsyncMock) as wait_mock,
            patch.object(chat_view, "mount", new_callable=AsyncMock),
        ):
            bot = await chat_view.add_bot_message()
            thinking = await chat_view.add_thinking_widget()
            tool = await chat_view.add_tool_call("shell", "cmd")
            divider = await chat_view.add_event_divider()
        self.assertEqual(wait_mock.await_count, 4)
        self.assertIsInstance(bot, BotMessage)
        self.assertIsInstance(thinking, ThinkingWidget)
        self.assertIsInstance(tool, ToolCallWidget)
        self.assertIsInstance(divider, EventDivider)

    async def test_toggle_expand_default_toggle_all(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            tool1 = await chat_view.add_tool_call("shell", "cmd1", "out1", animate=False)
            tool2 = await chat_view.add_tool_call("shell", "cmd2", "out2", animate=False)
            await pilot.pause()

            # Default mode: any collapsed -> expand all
            chat_view.toggle_expand()
            self.assertTrue(tool1.is_expanded)
            self.assertTrue(tool2.is_expanded)
            # Default mode: all expanded -> collapse all
            chat_view.toggle_expand()
            self.assertFalse(tool1.is_expanded)
            self.assertFalse(tool2.is_expanded)

    async def test_toggle_expand_no_expandables(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("only text")
            await pilot.pause()
            chat_view.toggle_expand("expand")

    async def test_wait_until_attached_exception_path(self):
        chat_view = ChatView()
        with patch("asyncio.sleep", side_effect=Exception("interrupted")):
            await chat_view._wait_until_attached(0.01)

    async def test_is_at_bottom(self):
        app = JohnstonApp()
        async with app.run_test() as _:
            chat_view = app.query_one(ChatView)
            self.assertIsInstance(chat_view.is_at_bottom(), bool)
