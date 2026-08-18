"""Coverage-focused tests for widgets/chat_input and chat_messages (no source changes)."""
import json
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from rich.text import Text
from textual.app import App, ComposeResult
from textual.events import Key, Paste

from widgets import chat_input as chat_input_mod
from widgets.chat_input import ChatInput
from widgets.presentation.widgets.chat_messages import BotMessage, ThinkingWidget, UserMessage


class _DummyChatApp(App[None]):
    def __init__(self, chat_input):
        super().__init__()
        self.chat_input = chat_input

    def compose(self) -> ComposeResult:
        yield self.chat_input


def _app_context():
    ci = ChatInput()
    ctx = _DummyChatApp(ci).run_test()
    return ci, ctx


def _make_fake_suggestions(mode="command"):
    sugg = MagicMock()
    sugg.display = True
    sugg.highlighted = 0
    sugg.mode = mode
    sugg.current_matched = ["/help"] if mode == "command" else ["/main.py"]
    sugg.at_start_idx = 0
    return sugg


class TestChatInputHistoryFile(unittest.TestCase):
    def test_load_prompt_history_invalid_json_returns_empty(self):
        ci = ChatInput()
        with patch.object(chat_input_mod.config, "PROMPT_HISTORY_FILE", "/nonexistent/history.json"):
            with patch("widgets.chat_input.os.path.exists", return_value=True):
                with patch("widgets.chat_input.json.load", side_effect=json.JSONDecodeError("x", "d", 0)):
                    self.assertEqual(ci.load_prompt_history(), [])

    def test_save_prompt_history_swallows_write_error(self):
        ci = ChatInput()
        ci.prompt_history = ["a", "b"]
        with patch("widgets.chat_input.json.dump", side_effect=OSError("disk full")):
            ci.save_prompt_history()  # must not raise


class TestChatInputScheduleSuggestions(unittest.TestCase):
    def test_schedule_not_mounted_returns(self):
        ci = ChatInput()
        self.assertIsNone(ci._schedule_suggestions_update())

    def test_schedule_runtime_error_swallowed(self):
        ci = ChatInput()
        with patch.object(type(ci), "is_mounted", new_callable=PropertyMock, return_value=True):
            with patch("widgets.chat_input.asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
                ci._schedule_suggestions_update()  # must not raise


class TestChatInputFormatPasted(unittest.TestCase):
    def test_blank_line_preserved_in_multi_line(self):
        ci = ChatInput()
        result = ci.format_pasted_file_path("line1\n\nline3")
        self.assertEqual(result, "line1\n\nline3")

    def test_clear_attachments_swallows_oserror(self):
        ci = ChatInput()
        with tempfile.TemporaryDirectory(prefix="temp_images") as tmp:
            path = f"{tmp}/img.png"
            att = chat_input_mod.ClipboardAttachment(path)
            ci.clipboard_attachments = [att]
            with patch("widgets.chat_input.os.path.exists", return_value=True):
                with patch("widgets.chat_input.os.remove", side_effect=OSError("busy")):
                    ci.clear_clipboard_attachments()
            self.assertEqual(ci.clipboard_attachments, [])


class TestChatInputOnPaste(unittest.IsolatedAsyncioTestCase):
    async def test_empty_paste_with_clipboard_image_returns(self):
        ci = ChatInput()
        event = Paste("")
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        with patch.object(ci, "format_pasted_file_path", return_value=""), patch.object(
            ci, "_decode_pasted_path", return_value=""
        ):
            with patch.object(ci, "try_paste_clipboard_image", new=AsyncMock(return_value=True)):
                with patch.object(ci, "insert") as insert:
                    await ci.on_paste(event)
            insert.assert_not_called()


class TestChatInputHistoryTrim(unittest.TestCase):
    def test_add_to_history_trims_over_max(self):
        ci = ChatInput()
        ci.MAX_PROMPT_HISTORY = 2
        ci.prompt_history = ["a", "b"]
        with patch.object(ci, "save_prompt_history") as save:
            ci.add_to_history("c")
        self.assertEqual(ci.prompt_history, ["b", "c"])
        save.assert_called_once()


class TestChatInputTagDeletion(unittest.IsolatedAsyncioTestCase):
    async def _bootstrap(self):
        ci, ctx = _app_context()
        pilot = await ctx.__aenter__()
        return ci, ctx, pilot

    async def test_empty_pasted_texts_returns_false(self):
        ci, ctx, _pilot = await self._bootstrap()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        self.assertFalse(ci._handle_tag_deletion("backspace"))

    async def test_duplicate_tags_loop_terminates(self):
        ci, ctx, _pilot = await self._bootstrap()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        ci.load_text("[TAG]x[TAG]")
        ci.move_cursor((0, 0))
        ci.pasted_texts = {"[TAG]": "raw"}
        self.assertFalse(ci._handle_tag_deletion("backspace"))
        # Both [TAG] markers still present (nothing deleted).
        self.assertEqual(ci.text, "[TAG]x[TAG]")


class TestChatInputTabFileMode(unittest.IsolatedAsyncioTestCase):
    async def test_tab_file_suggestion_applies(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        with patch.object(ci, "apply_file_suggestion") as apply:
            with patch.object(ci.app, "query_one", return_value=_make_fake_suggestions("file")):
                event = Key("tab", "tab")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
        apply.assert_called_once_with("/main.py", 0)

    async def test_tab_query_error_swallowed(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        with patch.object(ci.app, "query_one", side_effect=Exception("no widget")):
            event = Key("tab", "tab")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await ci._on_key(event)  # must not raise


class TestChatInputEnterCommandSelection(unittest.IsolatedAsyncioTestCase):
    async def test_enter_selects_command_suggestion(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        sugg = _make_fake_suggestions("command")
        with patch.object(ci, "apply_suggestion") as apply:
            with patch.object(ci.app, "query_one", return_value=sugg):
                event = Key("enter", "enter")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
        apply.assert_called_once_with("/help", 0)
        self.assertFalse(sugg.display)
        event.prevent_default.assert_called()


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
