import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from rich.text import Text

from widgets.presentation.widgets.chat_messages import BotMessage, EventDivider, ThinkingWidget, UserMessage
from widgets.presentation.widgets.chat_welcome import WelcomeWidget


class TestEventDivider(unittest.TestCase):
    def test_event_divider_init_and_update(self):
        divider = EventDivider("Custom Title")
        self.assertEqual(divider.divider_title, "Custom Title")
        divider.update_title("New Title")
        self.assertEqual(divider.divider_title, "New Title")

    def test_event_divider_sanitizes_newlines_and_truncates(self):
        divider = EventDivider("  Line 1 \n  Line 2   \n")
        self.assertEqual(divider.divider_title, "Line 1 Line 2")

        long_text = "A" * 120
        divider.update_title(long_text)
        self.assertEqual(len(divider.divider_title), 100)
        self.assertTrue(divider.divider_title.endswith("..."))


class TestBotMessageInternals(unittest.IsolatedAsyncioTestCase):
    async def test_schedule_stream_update_runtime_error_and_flush_unattached(self):
        bot = BotMessage()
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            bot._schedule_stream_update()
        self.assertFalse(bot._stream_update_scheduled)

    async def test_set_final_content_cancels_pending_render_task(self):
        bot = BotMessage()
        handle = MagicMock()
        bot._stream_update_handle = handle
        task = asyncio.Future()
        bot._markdown_render_task = task
        await bot.set_final_content("small content")
        handle.cancel.assert_called_once()
        self.assertTrue(task.cancelled())
        self.assertIsNone(bot._pending_markdown_content)

    async def test_schedule_markdown_render_reuses_existing_task(self):
        bot = BotMessage()
        task = asyncio.Future()
        bot._markdown_render_task = task
        bot._schedule_markdown_render("pending")
        self.assertEqual(bot._pending_markdown_content, "pending")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_schedule_markdown_render_runtime_error_falls_back(self):
        bot = BotMessage()
        with patch("asyncio.create_task", side_effect=RuntimeError):
            bot._schedule_markdown_render("fallback")
        self.assertEqual(bot._pending_markdown_content, "fallback")

    async def test_render_markdown_unattached_and_exceptions(self):
        bot = BotMessage()
        await bot._render_markdown("anything")
        with patch.object(type(bot.md_widget), "is_attached", new_callable=PropertyMock, return_value=True):
            with patch.object(bot.md_widget, "update", new_callable=AsyncMock, side_effect=Exception("boom")):
                await bot._render_markdown("x")
            with patch.object(bot.md_widget, "update", new_callable=AsyncMock, side_effect=asyncio.CancelledError()):
                with self.assertRaises(asyncio.CancelledError):
                    await bot._render_markdown("x")

    async def test_drain_markdown_render_loops_until_empty(self):
        bot = BotMessage()
        with patch.object(bot, "_render_markdown", new_callable=AsyncMock) as render_mock:
            bot._pending_markdown_content = "first"
            await bot._drain_markdown_render()
        render_mock.assert_awaited_once_with("first")
        self.assertIsNone(bot._pending_markdown_content)

    async def test_scroll_if_needed_handles_parent(self):
        from textual.containers import VerticalScroll

        bot = BotMessage()
        parent = VerticalScroll()
        bot._parent = parent
        bot._scroll_if_needed()

        parent2 = VerticalScroll()
        parent2.is_at_bottom = lambda: True
        parent2._is_loading_session = False
        bot2 = BotMessage()
        bot2._parent = parent2
        with patch.object(parent2, "call_after_refresh") as call_mock:
            bot2._scroll_if_needed()
        call_mock.assert_called_once()

        parent3 = VerticalScroll()
        parent3.is_at_bottom = MagicMock(side_effect=Exception("boom"))
        bot3 = BotMessage()
        bot3._parent = parent3
        bot3._scroll_if_needed()

    async def test_on_unmount_cancels_handles(self):
        bot = BotMessage()
        handle = MagicMock()
        bot._stream_update_handle = handle
        task = MagicMock()
        task.done.return_value = False
        bot._markdown_render_task = task
        bot.on_unmount()
        handle.cancel.assert_called_once()
        task.cancel.assert_called_once()

    async def test_reset_stream_clears_content_and_cancels_handles(self):
        bot = BotMessage()
        bot.content = "partial"
        handle = MagicMock()
        bot._stream_update_handle = handle
        task = asyncio.Future()
        bot._markdown_render_task = task
        await bot.reset_stream()
        self.assertEqual(bot.content, "")
        handle.cancel.assert_called_once()
        self.assertTrue(task.cancelled())
        self.assertIsNone(bot._pending_markdown_content)
        self.assertFalse(bot.stream_widget.display)
        self.assertFalse(bot.md_widget.display)
        self.assertFalse(bot._streaming)

    async def test_watch_content_streaming_schedules_update(self):
        bot = BotMessage()
        with patch.object(bot, "_schedule_stream_update") as sched:
            bot._streaming = True
            bot.set_stream_content("chunk")
            sched.assert_called()
        with patch.object(bot, "_schedule_markdown_render") as render_mock:
            bot._streaming = False
            bot._suppress_content_watch = True
            bot.content = "final"
            render_mock.assert_not_called()

    async def test_finalize_stream_with_explicit_content(self):
        bot = BotMessage()
        with patch.object(bot, "set_final_content", new_callable=AsyncMock) as final_mock:
            await bot.finalize_stream("explicit")
        final_mock.assert_awaited_once_with("explicit")

    async def test_append_stream_content_accumulates_without_updating_reactive_content(self):
        bot = BotMessage()
        with patch.object(bot, "_schedule_stream_update"):
            bot.append_stream_content("hello ")
            bot.append_stream_content("world")
            self.assertEqual(bot._stream_parts, ["hello ", "world"])
            self.assertEqual(bot.content, "")
            self.assertEqual(bot._join_stream_content(), "hello world")
            bot._flush_stream_update()
            self.assertEqual(bot.stream_widget.render(), "hello world")
            bot.flush_pending_stream()
            self.assertEqual(bot.content, "hello world")


class TestThinkingWidget(unittest.TestCase):
    def _make_widget(self, text="Thinking..."):
        return ThinkingWidget(text)

    def test_thinking_widget_accumulates_parts_and_debounces(self):
        widget = self._make_widget()
        widget.is_expanded = True
        with patch.object(widget.content_widget, "update") as update_mock:
            widget.update_thinking("part1 ")
            widget.update_thinking("part2")
            self.assertEqual(widget._thinking_parts, ["part1 ", "part2"])
            self.assertEqual(widget.thinking_text, "part1 part2")
            widget._flush_content_update()
            update_mock.assert_called_with("part1 part2")

    def test_thinking_widget_init_and_compose(self):
        widget = self._make_widget()
        self.assertTrue(widget.is_thinking)
        self.assertFalse(widget.is_expanded)
        composed = list(widget.compose())
        self.assertEqual(len(composed), 2)

        widget2 = self._make_widget("custom text")
        self.assertEqual(widget2.thinking_text, "custom text")

    def test_thinking_widget_on_mount_expandable(self):
        widget = self._make_widget()
        widget.on_mount()
        self.assertFalse(widget.content_widget.display)
        self.assertIn("thinking-header-expandable", widget.header_label.classes)

    def test_thinking_widget_on_mount_not_expandable(self):
        widget = self._make_widget()
        with patch.object(widget, "is_expandable", return_value=False):
            widget.on_mount()
        self.assertNotIn("thinking-header-expandable", widget.header_label.classes)

    def test_thinking_widget_toggle_when_not_expandable(self):
        widget = self._make_widget()
        with patch.object(widget, "is_expandable", return_value=False):
            widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)

    def test_thinking_widget_toggle_expanded_with_content(self):
        widget = self._make_widget("some thinking")
        widget.toggle_expanded()
        self.assertTrue(widget.is_expanded)
        self.assertTrue(widget.content_widget.display)
        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)
        self.assertFalse(widget.content_widget.display)

    def test_thinking_widget_update_finish_and_collapse(self):
        widget = self._make_widget()
        widget.update_thinking("new thought")
        self.assertEqual(widget.thinking_text, "new thought")

        widget.is_expanded = True
        with patch.object(widget.content_widget, "update") as update_mock:
            widget.update_thinking("expanded thought")
            widget._flush_content_update()
        update_mock.assert_called_with("new thoughtexpanded thought")

        widget.finish_thinking(2.5, "final thought")
        self.assertFalse(widget.is_thinking)
        self.assertEqual(widget.duration_seconds, 2.5)
        self.assertEqual(widget.thinking_text, "final thought")
        self.assertNotIn("thinking-active", widget.classes)

        widget2 = self._make_widget()
        widget2.finish_thinking(1.0)
        self.assertIn("Thought for 1.0 sec", str(widget2.header_label.render()))

        widget3 = self._make_widget()
        widget3.is_expanded = False
        widget3.finish_thinking(0.5)
        self.assertFalse(widget3.content_widget.display)

    def test_thinking_widget_click_and_toggle(self):
        widget = self._make_widget()
        event = MagicMock()
        widget.on_click(event)
        event.stop.assert_called_once()
        self.assertTrue(widget.is_expanded)
        self.assertTrue(widget.content_widget.display)

        widget.toggle_expanded()
        self.assertFalse(widget.is_expanded)
        self.assertFalse(widget.content_widget.display)

    def test_thinking_widget_is_expandable_default(self):
        widget = self._make_widget()
        self.assertTrue(widget.is_expandable())


class TestWelcomeWidget(unittest.TestCase):
    def test_welcome_widget_compose_and_banner_sizes(self):
        widget = WelcomeWidget()
        composed = list(widget.compose())
        self.assertEqual(len(composed), 1)

        with patch.object(widget, "query_one") as query_mock:
            logo = MagicMock()
            query_mock.return_value = logo
            widget._update_banner_for_size(30)
            logo.update.assert_called_once()
            widget._update_banner_for_size(80)
            self.assertEqual(logo.update.call_count, 2)

        widget2 = WelcomeWidget()
        with patch.object(widget2, "query_one", side_effect=Exception("no logo")):
            widget2._update_banner_for_size(80)

    def test_welcome_widget_mouse_events_clear_selection(self):
        widget = WelcomeWidget()
        screen = MagicMock()
        with patch.object(type(widget), "screen", new_callable=PropertyMock) as screen_prop:
            screen_prop.return_value = screen
            widget.on_mouse_down(MagicMock())
            widget.on_mouse_move(MagicMock())
            widget.on_mouse_up(MagicMock())
        self.assertEqual(screen.clear_selection.call_count, 3)


class TestUserMessageCoverage(unittest.TestCase):
    def test_content_is_text_instance(self):
        content = Text("plain text")
        msg = UserMessage(content, attachment_text="att")
        self.assertEqual(msg.raw_text, "plain text\natt")

    def test_attachment_only_sets_raw_text(self):
        msg = UserMessage(content="", attachment_text="att")
        self.assertEqual(msg.raw_text, "att")


class TestBotMessageCoverage(unittest.TestCase):
    def test_on_mount_with_content_hides_stream(self):
        msg = BotMessage()
        msg._suppress_content_watch = True
        msg.content = "cached"
        msg.on_mount()
        self.assertFalse(msg.stream_widget.display)
        self.assertTrue(msg.md_widget.display)

    def test_flush_stream_update_swallows_error(self):
        msg = BotMessage()
        with patch.object(msg.stream_widget, "update", side_effect=RuntimeError("boom")):
            msg._flush_stream_update()  # must not raise


class TestBotMessageResetStream(unittest.IsolatedAsyncioTestCase):
    async def test_reset_stream_swallows_update_error(self):
        msg = BotMessage()
        with patch.object(msg.stream_widget, "update", side_effect=RuntimeError("boom")):
            await msg.reset_stream()


class TestThinkingWidgetCoverage(unittest.TestCase):
    def test_thinking_text_setter(self):
        tw = ThinkingWidget("initial")
        tw.thinking_text = "new value"
        self.assertEqual(tw._thinking_parts, ["new value"])
        self.assertEqual(tw._cached_thinking_text, "new value")

    def test_schedule_content_update_skips_when_collapsed(self):
        tw = ThinkingWidget("x")
        tw.is_expanded = False
        tw._schedule_content_update()
        self.assertFalse(tw._update_scheduled)

    def test_flush_content_update_skips_when_collapsed(self):
        tw = ThinkingWidget("x")
        tw.is_expanded = False
        tw._update_scheduled = True
        tw._flush_content_update()

    def test_flush_content_update_swallows_error(self):
        tw = ThinkingWidget("x")
        tw.is_expanded = True
        with patch.object(tw.content_widget, "update", side_effect=RuntimeError("boom")):
            tw._flush_content_update()

    def test_finish_thinking_cancels_handle(self):
        tw = ThinkingWidget("x")
        handle = MagicMock()
        tw._update_handle = handle
        tw.finish_thinking(1.5, "done")
        handle.cancel.assert_called_once()

    def test_on_click_not_expandable_returns(self):
        tw = ThinkingWidget("x")
        tw.is_expanded = False
        with patch.object(tw, "is_expandable", return_value=False):
            tw.on_click(MagicMock(stop=MagicMock()))
        self.assertFalse(tw.is_expanded)

    def test_toggle_collapse_cancels_handle(self):
        tw = ThinkingWidget("x")
        handle = MagicMock()
        tw.is_expanded = True
        tw._update_handle = handle
        tw.toggle_expanded()
        handle.cancel.assert_called_once()
        self.assertFalse(tw.is_expanded)

    def test_on_unmount_cancels_handle(self):
        tw = ThinkingWidget("x")
        handle = MagicMock()
        tw._update_handle = handle
        tw.on_unmount()
        handle.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
