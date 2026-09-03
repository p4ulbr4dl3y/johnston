import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from app import JohnstonApp
from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_markdown import clean_markdown_for_rendering, safe_update_markdown, to_snake_case
from widgets.presentation.widgets.chat_messages import (
    BotMessage,
    ErrorMessage,
    EventDivider,
    ThinkingWidget,
    UserMessage,
)
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
            user_msg1 = await chat_view.add_user_message("after divider", animate=False)
            err_msg = await chat_view.add_error_message("API Error: rate limit", animate=False)
            user_msg2 = await chat_view.add_user_message("after error", animate=False)
            await pilot.pause()
            self.assertIsInstance(thinking, ThinkingWidget)
            self.assertIsInstance(divider, EventDivider)
            self.assertIn("user-msg-first", user_msg1.classes)
            self.assertIsInstance(err_msg, ErrorMessage)
            self.assertEqual(err_msg.raw_text, "API Error: rate limit")
            self.assertNotIn("user-msg-first", user_msg2.classes)

    async def test_user_message_after_error_without_prior_user_message_not_first(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            # Remove welcome if present to simulate container starting with error
            chat_view.clear_welcome()
            await chat_view.add_error_message("API Error: 429", animate=False)
            user_msg = await chat_view.add_user_message("retry", animate=False)
            await pilot.pause()
            self.assertNotIn("user-msg-first", user_msg.classes)

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
            chat_view._auto_follow = False
            chat_view.rollback_to(0)
            await pilot.pause()
            self.assertLessEqual(len(list(chat_view.children)), 2)
            self.assertTrue(chat_view._auto_follow)

    async def test_rollback_to_negative_mounts_welcome(self):
        from widgets.presentation.widgets.chat_welcome import WelcomeWidget

        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("one")
            await chat_view.add_bot_message()
            await pilot.pause()
            self.assertFalse(any(isinstance(c, WelcomeWidget) for c in chat_view.children))

            chat_view.rollback_to(-1)
            await pilot.pause()
            self.assertTrue(any(isinstance(c, WelcomeWidget) for c in chat_view.children))

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

    async def test_auto_expand_all_new_widgets(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            # Toggle expand before any widget exists -> auto_expand_all becomes True
            chat_view.toggle_expand()
            self.assertTrue(chat_view.auto_expand_all)

            thinking = await chat_view.add_thinking_widget("Thinking text", animate=False)
            tool = await chat_view.add_tool_call("shell", "echo test", "result", animate=False)
            ask_tool = await chat_view.add_tool_call(
                "ask_user", "q", args={"questions": [{"question": "Q?", "options": []}]}, animate=False
            )
            await pilot.pause()

            self.assertTrue(thinking.is_expanded)
            self.assertTrue(tool.is_expanded)
            self.assertFalse(ask_tool.is_expanded)

            # Completing ask_user auto-expands it when auto_expand_all is True
            ask_tool.set_result("Question: Q?\nAnswer: Yes", status="done")
            await pilot.pause()
            self.assertTrue(ask_tool.is_expanded)

            # Toggle expand again -> collapses all and auto_expand_all becomes False
            chat_view.toggle_expand()
            self.assertFalse(chat_view.auto_expand_all)
            self.assertFalse(thinking.is_expanded)
            self.assertFalse(tool.is_expanded)
            self.assertFalse(ask_tool.is_expanded)

            # New widgets added after collapsing are not expanded
            new_tool = await chat_view.add_tool_call("shell", "ls", "files", animate=False)
            await pilot.pause()
            self.assertFalse(new_tool.is_expanded)


class TestChatViewAutoFollow(unittest.IsolatedAsyncioTestCase):
    def _make_view(self, max_scroll_y: int, scroll_y: int) -> ChatView:
        view = ChatView()
        patcher_max = patch.object(ChatView, "max_scroll_y", new_callable=PropertyMock, return_value=max_scroll_y)
        patcher_y = patch.object(ChatView, "scroll_y", new_callable=PropertyMock, return_value=scroll_y)
        patcher_max.start()
        patcher_y.start()
        self.addCleanup(patcher_max.stop)
        self.addCleanup(patcher_y.stop)
        return view

    def test_wheel_up_pauses_auto_follow_when_scrollable(self):
        view = self._make_view(max_scroll_y=100, scroll_y=50)
        self.assertTrue(view._auto_follow)
        view.on_mouse_scroll_up(MagicMock())
        self.assertFalse(view._auto_follow)

    def test_wheel_up_ignores_unscrollable_view(self):
        # Content fits viewport: wheel-up must not disable later bottom-follow.
        view = self._make_view(max_scroll_y=0, scroll_y=0)
        view.on_mouse_scroll_up(MagicMock())
        self.assertTrue(view._auto_follow)

    def test_wheel_down_at_bottom_resumes_auto_follow(self):
        view = self._make_view(max_scroll_y=100, scroll_y=100)
        view._auto_follow = False
        view._resume_follow_if_at_bottom()
        self.assertTrue(view._auto_follow)

    def test_wheel_down_mid_history_keeps_auto_follow_off(self):
        view = self._make_view(max_scroll_y=100, scroll_y=40)
        view._auto_follow = False
        view._resume_follow_if_at_bottom()
        self.assertFalse(view._auto_follow)

    def test_wheel_down_handler_defers_resume_check(self):
        view = self._make_view(max_scroll_y=100, scroll_y=100)
        view.call_after_refresh = MagicMock()
        view.on_mouse_scroll_down(MagicMock())
        view.call_after_refresh.assert_called_once_with(view._resume_follow_if_at_bottom)

    @pytest.mark.slow  # timing-sensitive (run_test + pilot.pause) — flaky under -n auto
    async def test_sending_message_resumes_auto_follow(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            chat_view._auto_follow = False
            await chat_view.add_user_message("back to live")
            await pilot.pause()
            self.assertTrue(chat_view._auto_follow)

    @pytest.mark.slow  # timing-sensitive (run_test + pilot.pause) — flaky under -n auto
    async def test_stream_growth_keeps_follow_when_pinned(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("\n".join(f"history line {i}" for i in range(60)))
            bot = await chat_view.add_bot_message()
            await pilot.pause()
            self.assertTrue(chat_view.is_at_bottom())
            initial_max = chat_view.max_scroll_y
            bot.append_stream_content("tail line\n" * 40)
            bot.flush_pending_stream()
            for _ in range(50):
                if chat_view.max_scroll_y > initial_max and chat_view.is_at_bottom():
                    break
                await pilot.pause(0.05)
            self.assertTrue(chat_view.is_at_bottom())

    @pytest.mark.slow  # timing-sensitive (run_test + pilot.pause) — flaky under -n auto
    async def test_wheel_up_mid_stream_prevents_follow(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            await chat_view.add_user_message("\n".join(f"history line {i}" for i in range(60)))
            bot = await chat_view.add_bot_message()
            await pilot.pause()
            chat_view.on_mouse_scroll_up(MagicMock())
            self.assertFalse(chat_view._auto_follow)
            initial_max = chat_view.max_scroll_y
            bot.append_stream_content("tail line\n" * 40)
            bot.flush_pending_stream()
            for _ in range(50):
                if chat_view.max_scroll_y > initial_max:
                    break
                await pilot.pause(0.05)
            self.assertFalse(chat_view.is_at_bottom())

    def test_scroll_up_page_pauses_auto_follow(self):
        view = self._make_view(max_scroll_y=100, scroll_y=50)
        view.scroll_page_up = MagicMock()
        self.assertTrue(view._auto_follow)
        view.scroll_up_page()
        self.assertFalse(view._auto_follow)
        view.scroll_page_up.assert_called_once_with(animate=False)

    def test_scroll_down_page_defers_resume_check(self):
        view = self._make_view(max_scroll_y=100, scroll_y=50)
        view.scroll_page_down = MagicMock()
        view.call_after_refresh = MagicMock()
        view.scroll_down_page()
        view.scroll_page_down.assert_called_once_with(animate=False)
        view.call_after_refresh.assert_called_once_with(view._resume_follow_if_at_bottom)

    def test_scroll_to_top_pauses_auto_follow(self):
        view = self._make_view(max_scroll_y=100, scroll_y=50)
        view.scroll_home = MagicMock()
        self.assertTrue(view._auto_follow)
        view.scroll_to_top()
        self.assertFalse(view._auto_follow)
        view.scroll_home.assert_called_once_with(animate=False)

    def test_scroll_to_bottom_resumes_auto_follow(self):
        view = self._make_view(max_scroll_y=100, scroll_y=0)
        view._auto_follow = False
        view.scroll_end = MagicMock()
        view.scroll_to_bottom()
        self.assertTrue(view._auto_follow)
        view.scroll_end.assert_called_once_with(animate=False)

    def test_get_last_bot_message_text(self):
        view = ChatView(show_welcome=False)
        self.assertIsNone(view.get_last_bot_message_text())

        bot1 = BotMessage()
        bot1.content = "First bot message"
        bot2 = BotMessage()
        bot2.content = "Second bot message"
        user = UserMessage("User message")

        view._nodes = [user, bot1, bot2]
        self.assertEqual(view.get_last_bot_message_text(), "Second bot message")

        # Test empty content ignored
        bot3 = BotMessage()
        bot3.content = "   "
        view._nodes = [user, bot1, bot2, bot3]
        self.assertEqual(view.get_last_bot_message_text(), "Second bot message")


class TestChatViewPagination(unittest.IsolatedAsyncioTestCase):
    async def test_pagination_initial_load_and_older_chunks(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            chat_view.PAGE_SIZE = 5

            # Prepare 12 messages
            msgs = [{"type": "user", "text": f"msg_{i}"} for i in range(12)]
            chat_view._unloaded_messages = msgs[:-5]

            # Mount initial latest 5 (indices 7..11) while loading session
            chat_view._is_loading_session = True
            for m in msgs[-5:]:
                await chat_view.restore_message(m)
            chat_view._is_loading_session = False
            await pilot.pause()

            # Now manually verify chunk loading
            chat_view._is_loading_session = True
            self.assertTrue(chat_view.has_older_messages())
            self.assertEqual(len(chat_view._unloaded_messages), 7)
            # Check currently mounted user messages
            current = [text for _, text in chat_view.get_user_messages()]
            self.assertEqual(current, [f"msg_{i}" for i in range(7, 12)])

            # Trigger loading older chunk (indices 2..6)
            await chat_view._load_older_messages_worker()
            await pilot.pause()

            self.assertTrue(chat_view.has_older_messages())
            self.assertEqual(len(chat_view._unloaded_messages), 2)
            current = [text for _, text in chat_view.get_user_messages()]
            self.assertEqual(current, [f"msg_{i}" for i in range(2, 12)])

            # Trigger loading final older chunk (indices 0..1)
            await chat_view._load_older_messages_worker()
            await pilot.pause()

            self.assertFalse(chat_view.has_older_messages())
            self.assertEqual(len(chat_view._unloaded_messages), 0)
            current = [text for _, text in chat_view.get_user_messages()]
            self.assertEqual(current, [f"msg_{i}" for i in range(12)])
            chat_view._is_loading_session = False

    async def test_scroll_up_triggers_load_older(self):
        chat_view = ChatView()
        chat_view._unloaded_messages = [{"type": "user", "text": "older"}]
        chat_view.load_older_messages = MagicMock()
        chat_view.scroll_page_up = MagicMock()
        chat_view.scroll_home = MagicMock()

        # scroll_y > 2 does not trigger
        with patch.object(type(chat_view), "scroll_y", new_callable=PropertyMock, return_value=10):
            with patch.object(type(chat_view), "max_scroll_y", new_callable=PropertyMock, return_value=20):
                chat_view.on_mouse_scroll_up(MagicMock())
                chat_view.load_older_messages.assert_not_called()

        # scroll_y <= 2 triggers load_older_messages on scroll up
        with patch.object(type(chat_view), "scroll_y", new_callable=PropertyMock, return_value=1):
            with patch.object(type(chat_view), "max_scroll_y", new_callable=PropertyMock, return_value=20):
                chat_view.on_mouse_scroll_up(MagicMock())
                chat_view.load_older_messages.assert_called_once()

        chat_view.load_older_messages.reset_mock()
        with patch.object(type(chat_view), "scroll_y", new_callable=PropertyMock, return_value=1):
            with patch.object(type(chat_view), "max_scroll_y", new_callable=PropertyMock, return_value=20):
                chat_view.scroll_up_page()
                chat_view.load_older_messages.assert_called_once()

        chat_view.load_older_messages.reset_mock()
        with patch.object(type(chat_view), "scroll_y", new_callable=PropertyMock, return_value=1):
            with patch.object(type(chat_view), "max_scroll_y", new_callable=PropertyMock, return_value=20):
                chat_view.scroll_to_top()
                chat_view.load_older_messages.assert_called_once()

    async def test_restore_message_all_types(self):
        chat_view = ChatView()
        chat_view._wait_until_attached = AsyncMock()
        chat_view.mount = AsyncMock()

        # user
        u = await chat_view.restore_message({"type": "user", "text": "hi"})
        self.assertIsInstance(u, UserMessage)

        # bot
        b = await chat_view.restore_message({"type": "bot", "text": "ans"})
        self.assertIsInstance(b, BotMessage)

        # thinking
        t = await chat_view.restore_message({"type": "thinking", "duration": 2.0, "text": "think"})
        self.assertIsInstance(t, ThinkingWidget)

        # tool
        tool = await chat_view.restore_message({"type": "tool", "tool_type": "shell", "target": "ls", "result_text": "ok"})
        self.assertIsInstance(tool, ToolCallWidget)

        # event divider
        d = await chat_view.restore_message({"type": "event_divider", "text": "Compacted"})
        self.assertIsInstance(d, EventDivider)

        # error
        err = await chat_view.restore_message({"type": "error", "text": "API Error: failed"})
        self.assertIsInstance(err, ErrorMessage)
        self.assertEqual(err.raw_text, "API Error: failed")

        # invalid / hidden
        none_msg = await chat_view.restore_message("not-a-dict")
        self.assertIsNone(none_msg)

        hidden_msg = await chat_view.restore_message({"type": "user", "text": "hi", "show_in_ui": False})
        self.assertIsNone(hidden_msg)

    async def test_load_all_older_messages_and_count(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            chat_view.PAGE_SIZE = 3
            msgs = [{"type": "user", "text": f"turn_{i}"} for i in range(10)]
            chat_view._unloaded_messages = msgs[:-3]
            chat_view._is_loading_session = True
            for m in msgs[-3:]:
                await chat_view.restore_message(m)
            chat_view._is_loading_session = False
            await pilot.pause()

            self.assertEqual(chat_view.get_total_user_message_count(), 10)
            self.assertEqual(len(chat_view.get_user_messages()), 3)

            await chat_view.load_all_older_messages()
            await pilot.pause()

            self.assertFalse(chat_view.has_older_messages())
            self.assertEqual(len(chat_view.get_user_messages()), 10)

    async def test_reset_to_messages(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            chat_view.PAGE_SIZE = 3
            # Initial 10 messages
            msgs = [{"type": "user", "text": f"turn_{i}"} for i in range(10)]
            await chat_view.reset_to_messages(msgs)
            await pilot.pause()

            self.assertEqual(len(chat_view._unloaded_messages), 7)
            self.assertEqual([text for _, text in chat_view.get_user_messages()], [f"turn_{i}" for i in range(7, 10)])

            # Truncate / reset to earlier 4 messages
            truncated = msgs[:4]
            await chat_view.reset_to_messages(truncated)
            await pilot.pause()

            self.assertEqual(len(chat_view._unloaded_messages), 1)
            self.assertEqual(chat_view._unloaded_messages, [{"type": "user", "text": "turn_0"}])
            self.assertEqual([text for _, text in chat_view.get_user_messages()], [f"turn_{i}" for i in range(1, 4)])

            # Reset to empty
            await chat_view.reset_to_messages([])
            await pilot.pause()
            self.assertEqual(len(chat_view._unloaded_messages), 0)
            self.assertEqual(len(chat_view.get_user_messages()), 0)
