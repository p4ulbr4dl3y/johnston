import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from PIL import Image
from textual.app import App, ComposeResult
from textual.events import Key, MouseUp, Paste

from widgets import chat_input as chat_input_mod
from widgets.chat_input import ChatInput, ClipboardAttachment


class DummyChatApp(App[None]):
    def __init__(self, chat_input):
        super().__init__()
        self.chat_input = chat_input
        self.submitted_messages = []
        self.mode_toggled = False

    def compose(self) -> ComposeResult:
        yield self.chat_input

    def action_toggle_role(self):
        self.mode_toggled = True

    def on_chat_input_submitted(self, message: ChatInput.Submitted):
        self.submitted_messages.append(message)


class TestClipboardAttachment(unittest.TestCase):
    def test_init(self):
        att = ClipboardAttachment("/tmp/img.png")
        self.assertEqual(att.path, "/tmp/img.png")


class TestChatInputUnit(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_file = os.path.join(self.tmp_dir.name, "prompt_history.json")
        self.patcher = patch("core.infrastructure.platform.paths.PROMPT_HISTORY_FILE", self.tmp_file)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        self.tmp_dir.cleanup()

    async def test_on_mount_and_update_height(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.load_text("Line 1\nLine 2\nLine 3")
            ci.update_height()
            self.assertEqual(ci.styles.height.value, 4)

            # Test height capping at min 2 and max 6
            ci.load_text("Single line")
            ci.update_height()
            self.assertEqual(ci.styles.height.value, 2)

            ci.load_text("1\n2\n3\n4\n5\n6\n7\n8")
            ci.update_height()
            self.assertEqual(ci.styles.height.value, 6)

    def test_placeholder_default_and_custom(self):
        ci_default = ChatInput()
        self.assertEqual(ci_default.placeholder, "Type a message or / for commands...")

        ci_custom = ChatInput(placeholder="Custom prompt...")
        self.assertEqual(ci_custom.placeholder, "Custom prompt...")

    async def test_get_full_text_and_tag_deletion(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.pasted_texts["[Pasted text #1 +12 lines]"] = "multi\nline\ncontent\nhere"
            ci.load_text("Check [Pasted text #1 +12 lines] please")
            self.assertEqual(ci.get_full_text(), "Check multi\nline\ncontent\nhere please")

            # Test backspace tag deletion
            ci.move_cursor((0, len("Check [Pasted text #1 +12 lines]")))
            handled = ci._handle_tag_deletion("backspace")
            self.assertTrue(handled)
            self.assertEqual(ci.text, "Check  please")
            self.assertNotIn("[Pasted text #1 +12 lines]", ci.pasted_texts)

    async def test_handle_tag_deletion_delete_key(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.pasted_texts["[Pasted text #2 +15 lines]"] = "secret text"
            ci.load_text("[Pasted text #2 +15 lines]")
            ci.move_cursor((0, 0))
            handled = ci._handle_tag_deletion("delete")
            self.assertTrue(handled)
            self.assertEqual(ci.text, "")
            self.assertNotIn("[Pasted text #2 +15 lines]", ci.pasted_texts)

    async def test_apply_suggestion(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.load_text("/he")
            ci.move_cursor((0, 3))
            ci.apply_suggestion("/help", 0)
            self.assertEqual(ci.text, "/help ")

    async def test_apply_file_suggestion(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.load_text("read @main")
            ci.move_cursor((0, 10))
            ci.apply_file_suggestion("main.py", 5)
            self.assertEqual(ci.text, "read @main.py ")

    async def test_format_pasted_file_path(self):
        ci = ChatInput()
        with tempfile.NamedTemporaryFile(suffix=".txt") as tmp:
            tmp_path = tmp.name

            # Blank lines
            self.assertEqual(ci.format_pasted_file_path(""), "")

            # Path with quotes or tilde or file:// or explicit relative
            res1 = ci.format_pasted_file_path(tmp_path)
            self.assertEqual(res1, f"@{tmp_path} ")

            res2 = ci.format_pasted_file_path(f"'{tmp_path}'")
            self.assertEqual(res2, f"@{tmp_path} ")

            res3 = ci.format_pasted_file_path("./local_file.py")
            self.assertEqual(res3, "@./local_file.py ")

            # Pre-formatted @file
            res4 = ci.format_pasted_file_path("@already_formatted")
            self.assertEqual(res4, "@already_formatted ")

            # Plain text
            res5 = ci.format_pasted_file_path("just normal prompt text")
            self.assertEqual(res5, "just normal prompt text")

    async def test_clear_clipboard_attachments(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            with tempfile.NamedTemporaryFile(suffix=".png", prefix="temp_images_") as tmp:
                att = ClipboardAttachment(tmp.name)
                ci.clipboard_attachments.append(att)

                with patch("os.remove") as mock_remove:
                    ci.clear_clipboard_attachments()
                    mock_remove.assert_called_once_with(tmp.name)
                    self.assertEqual(len(ci.clipboard_attachments), 0)

    async def test_try_paste_clipboard_image_non_rgb_mode(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            mock_img = Image.new("L", (50, 50))
            with (
                patch("core.infrastructure.platform.platform_utils.get_clipboard_image_or_file", return_value=(None, mock_img)),
                patch("os.makedirs"),
                patch("os.path.getsize", return_value=512),
                patch.object(Image.Image, "save") as mock_save,
            ):
                res = await ci.try_paste_clipboard_image()
                self.assertTrue(res)
                mock_save.assert_called_once()
                self.assertEqual(len(ci.clipboard_attachments), 1)

    async def test_on_paste_event_multiline(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            with patch.object(ci, "try_paste_clipboard_image", return_value=False):
                event = Paste("\n".join([f"line {i}" for i in range(12)]))
                event.prevent_default = MagicMock()
                event.stop = MagicMock()

                await ci.on_paste(event)
                event.prevent_default.assert_called_once()
                event.stop.assert_called_once()
                self.assertIn("[Pasted text #1 +12 lines]", ci.text)

    async def test_on_paste_event_drag_drop_file(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            event = Paste("file:///tmp/my%20test%20folder/app.py")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()

            await ci.on_paste(event)
            event.prevent_default.assert_called_once()
            event.stop.assert_called_once()
            self.assertEqual(ci.text, "@/tmp/my test folder/app.py ")

    async def test_history_navigation_up_down(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.add_to_history("First query")
            ci.add_to_history("Second query")
            ci.load_text("Draft text")

            # Press Up key at line 0 -> load "Second query"
            event_up = Key("up", "up")
            await ci._on_key(event_up)
            self.assertEqual(ci.text, "Second query")

            # Press Up key again -> load "First query"
            await ci._on_key(event_up)
            self.assertEqual(ci.text, "First query")

            # Press Up key again -> wraps around to draft
            await ci._on_key(event_up)
            self.assertEqual(ci.text, "Draft text")

            # Press Down key -> load "First query"
            event_down = Key("down", "down")
            await ci._on_key(event_down)
            self.assertEqual(ci.text, "First query")

            await ci._on_key(event_down)
            self.assertEqual(ci.text, "Second query")

            await ci._on_key(event_down)
            self.assertEqual(ci.text, "Draft text")

    async def test_prompt_history_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_history_file = os.path.join(tmpdir, "prompt_history.json")
            with patch("core.infrastructure.platform.paths.PROMPT_HISTORY_FILE", tmp_history_file), patch("core.infrastructure.platform.paths.CONFIG_DIR", tmpdir):
                ci = ChatInput()
                self.assertEqual(ci.prompt_history, [])

                ci.add_to_history("Global prompt 1")
                ci.add_to_history("Global prompt 2")
                if getattr(ci, "_save_task", None):
                    await ci._save_task
                else:
                    for _ in range(20):
                        if os.path.exists(tmp_history_file):
                            break
                        await asyncio.sleep(0.05)
                self.assertTrue(os.path.exists(tmp_history_file))

                # New ChatInput instance loads persisted history
                ci2 = ChatInput()
                self.assertEqual(ci2.prompt_history, ["Global prompt 1", "Global prompt 2"])
                self.assertEqual(ci2.prompt_history_index, 2)

    async def test_key_shortcuts(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            # ctrl+c -> exit
            with patch.object(app, "exit") as mock_exit:
                event = Key("ctrl+c", "ctrl+c")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
                mock_exit.assert_called_once()

            # ctrl+c with selection -> still exits immediately
            ci.load_text("copy me")
            ci.selection = ci.selection.__class__((0, 0), (0, 4))
            with patch.object(app, "exit") as mock_exit:
                event = Key("ctrl+c", "ctrl+c")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
                mock_exit.assert_called_once()

            # ctrl+x with selection -> cut, no exit
            with patch.object(ci, "action_cut") as mock_cut, patch.object(app, "exit") as mock_exit:
                event = Key("ctrl+x", "ctrl+x")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
                mock_cut.assert_called_once()
                mock_exit.assert_not_called()

            ci.load_text("")

            # shift+tab -> toggle mode
            event_st = Key("shift+tab", "shift+tab")
            event_st.prevent_default = MagicMock()
            event_st.stop = MagicMock()
            await ci._on_key(event_st)
            self.assertTrue(app.mode_toggled)

            # ctrl+enter -> insert newline
            event_ce = Key("ctrl+enter", "ctrl+enter")
            event_ce.prevent_default = MagicMock()
            event_ce.stop = MagicMock()
            await ci._on_key(event_ce)
            self.assertEqual(ci.text, "\n")

    async def test_mouse_up_auto_copies_selection(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.load_text("copy with mouse")
            ci.selection = ci.selection.__class__((0, 0), (0, 4))
            with patch.object(app, "copy_to_clipboard") as mock_copy:
                event = MouseUp(
                    widget=ci,
                    x=0,
                    y=0,
                    delta_x=0,
                    delta_y=0,
                    button=1,
                    shift=False,
                    meta=False,
                    ctrl=False,
                    screen_x=0,
                    screen_y=0,
                )
                await ci._on_mouse_up(event)
                mock_copy.assert_called_once_with("copy")
                self.assertTrue(ci.selection.is_empty)

    async def test_escape_cancels_workers(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            mock_worker = MagicMock()
            mock_worker.is_running = True
            with patch.object(App, "workers", new_callable=PropertyMock, return_value=[mock_worker]):
                event = Key("escape", "escape")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
                mock_worker.cancel.assert_called_once()
                event.prevent_default.assert_called_once()

    async def test_enter_submits_message(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test() as pilot:
            ci.load_text("Test submit message")
            event_enter = Key("enter", "enter")
            event_enter.prevent_default = MagicMock()
            event_enter.stop = MagicMock()
            await ci._on_key(event_enter)
            await pilot.pause()

            self.assertEqual(len(app.submitted_messages), 1)
            self.assertEqual(app.submitted_messages[0].value, "Test submit message")
            self.assertEqual(ci.text, "")

    async def test_suggestions_interaction(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            mock_suggestions = MagicMock()
            mock_suggestions.display = True
            mock_suggestions.highlighted = 0
            mock_suggestions.mode = "command"
            mock_suggestions.current_matched = ["/help", "/clear"]
            mock_suggestions.at_start_idx = 0

            with patch.object(app, "query_one", return_value=mock_suggestions):
                mock_suggestions.update_query = AsyncMock(return_value=[])
                await ci.update_suggestions()
                mock_suggestions.update_query.assert_called_once()

                # Tab key autocompletes command suggestion
                event_tab = Key("tab", "tab")
                event_tab.prevent_default = MagicMock()
                event_tab.stop = MagicMock()
                await ci._on_key(event_tab)
                self.assertEqual(ci.text, "/help ")
                self.assertFalse(mock_suggestions.display)

                # Up and Down key navigate suggestions
                mock_suggestions.display = True
                event_up = Key("up", "up")
                event_up.prevent_default = MagicMock()
                event_up.stop = MagicMock()
                await ci._on_key(event_up)
                mock_suggestions.action_cursor_up.assert_called_once()

                event_down = Key("down", "down")
                event_down.prevent_default = MagicMock()
                event_down.stop = MagicMock()
                await ci._on_key(event_down)
                mock_suggestions.action_cursor_down.assert_called_once()

                # Escape hides suggestions
                event_esc = Key("escape", "escape")
                event_esc.prevent_default = MagicMock()
                event_esc.stop = MagicMock()
                await ci._on_key(event_esc)
                self.assertFalse(mock_suggestions.display)

                # Test file suggestion mode with Enter key
                mock_suggestions.display = True
                mock_suggestions.mode = "file"
                mock_suggestions.highlighted = 0
                mock_suggestions.current_matched = ["main.py"]
                mock_suggestions.at_start_idx = 0
                event_enter = Key("enter", "enter")
                event_enter.prevent_default = MagicMock()
                event_enter.stop = MagicMock()
                await ci._on_key(event_enter)
                self.assertIn("@main.py", ci.text)

    async def test_ctrl_d_and_ctrl_v(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            # ctrl+d detaches attachments one by one (LIFO)
            att1 = ClipboardAttachment("/tmp/img1.png")
            att2 = ClipboardAttachment("/tmp/img2.png")
            ci.clipboard_attachments.extend([att1, att2])

            event_d = Key("ctrl+d", "ctrl+d")
            event_d.prevent_default = MagicMock()
            event_d.stop = MagicMock()
            await ci._on_key(event_d)
            self.assertEqual(ci.clipboard_attachments, [att1])

            event_d2 = Key("ctrl+d", "ctrl+d")
            event_d2.prevent_default = MagicMock()
            event_d2.stop = MagicMock()
            await ci._on_key(event_d2)
            self.assertEqual(len(ci.clipboard_attachments), 0)

            # ctrl+v triggers try_paste_clipboard_image
            with patch.object(ci, "try_paste_clipboard_image", return_value=True) as mock_paste:
                event_v = Key("ctrl+v", "ctrl+v")
                event_v.prevent_default = MagicMock()
                event_v.stop = MagicMock()
                await ci._on_key(event_v)
                mock_paste.assert_called_once()

    async def test_update_attachment_bar_and_error_handling(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            mock_footer = MagicMock()
            with patch.object(app, "query_one", return_value=mock_footer):
                ci.update_attachment_bar()
                mock_footer.refresh_footer.assert_called_once()

            # Handles exception when query_one raises
            with patch.object(app, "query_one", side_effect=Exception("no footer")):
                ci.update_attachment_bar()  # Should not raise exception

    async def test_sanitize_mouse_artifacts(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.load_text("Hello M<65;1272;815M World [<65;1272;815M")
            self.assertEqual(ci.text, "Hello  World ")

    async def test_file_suggestion_replaces_current_at_token_and_preserves_cursor(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            ci.load_text("attach @REA")
            ci.move_cursor((0, len("attach @REA")))
            ci.apply_file_suggestion("README.md", 7)

            self.assertEqual(ci.text, "attach @README.md ")
            self.assertEqual(ci.cursor_location, (0, len("attach @README.md ")))

    async def test_typing_runs_one_input_change_per_key(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test() as pilot:
            change_count = 0
            original = ci._on_input_change

            def count_change():
                nonlocal change_count
                change_count += 1
                return original()

            ci._on_input_change = count_change
            await pilot.press(*list("abcdefghij"))
            await pilot.pause(0.1)

            self.assertEqual(change_count, 10)


if __name__ == "__main__":
    unittest.main()


class TestChatInputClipboard(unittest.IsolatedAsyncioTestCase):
    async def test_try_paste_clipboard_image_file_path(self):
        chat_input = ChatInput()
        chat_input.insert = MagicMock()
        chat_input._on_input_change = MagicMock()

        with patch("core.infrastructure.platform.platform_utils.get_clipboard_image_or_file", return_value=("/tmp/sample.png", None)):
            res = await chat_input.try_paste_clipboard_image()
            self.assertTrue(res)
            chat_input.insert.assert_called_once_with("@/tmp/sample.png ")
            chat_input._on_input_change.assert_called_once()

    async def test_try_paste_clipboard_image_data(self):
        chat_input = ChatInput()
        chat_input.update_attachment_bar = MagicMock()

        mock_img = Image.new("RGB", (100, 50))
        with (
            patch("core.infrastructure.platform.platform_utils.get_clipboard_image_or_file", return_value=(None, mock_img)),
            patch("os.makedirs"),
            patch("os.path.getsize", return_value=1024),
            patch.object(Image.Image, "save"),
        ):
            res = await chat_input.try_paste_clipboard_image()
            self.assertTrue(res)
            self.assertEqual(len(chat_input.clipboard_attachments), 1)
            chat_input.update_attachment_bar.assert_called_once()

    async def test_try_paste_clipboard_image_none(self):
        chat_input = ChatInput()
        with patch("core.infrastructure.platform.platform_utils.get_clipboard_image_or_file", return_value=(None, None)):
            res = await chat_input.try_paste_clipboard_image()
            self.assertFalse(res)
            self.assertEqual(len(chat_input.clipboard_attachments), 0)


def _make_input():
    ci = ChatInput()
    app = DummyChatApp(ci)
    return ci, app, app.run_test()


class TestLoadTextEmpty(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        self.pilot = await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_load_none_clears(self):
        self.ci.load_text("sometext")
        self.ci.load_text(None)
        self.assertEqual(self.ci.text, "")

    async def test_load_newlines_updates_height(self):
        self.ci.load_text("a\n\nb")
        self.ci.update_height()
        self.assertGreaterEqual(self.ci.styles.height.value, 3)

    async def test_pasted_texts_cleared_on_empty_load(self):
        self.ci.pasted_texts["[Pasted text #1 +3 lines]"] = "x\ny\nz"
        self.ci.load_text("")
        self.assertEqual(self.ci.pasted_texts, {})


class TestSanitizeMouseArtifacts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_artifact_removed_multiline_at_end_no_crash(self):
        self.ci.load_text("line1\nline2 M<65;1272;815M")
        self.assertNotIn("M<", self.ci.text)


class TestFullTextWithTags(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_tag_expansion_preserves_newlines(self):
        raw = "a\nb\nc"
        self.ci.pasted_texts["[TAG]"] = raw
        self.ci.load_text("before [TAG] after")
        self.assertEqual(self.ci.get_full_text(), "before a\nb\nc after")

    async def test_tag_in_unicode_text(self):
        self.ci.pasted_texts["[TAG]"] = "привет"
        self.ci.load_text("скажи [TAG]")
        self.assertEqual(self.ci.get_full_text(), "скажи привет")


class TestApplySuggestionEdge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_apply_mid_line_keeps_after_text(self):
        self.ci.load_text("do /he please")
        self.ci.move_cursor((0, 6))
        self.ci.apply_suggestion("/help", 3)
        self.assertEqual(self.ci.text, "do /help  please")

    async def test_apply_file_suggestion_at_zero(self):
        self.ci.load_text("@main")
        self.ci.move_cursor((0, len("@main")))
        self.ci.apply_file_suggestion("main.py", 0)
        self.assertEqual(self.ci.text, "@main.py ")

    async def test_apply_file_suggestion_no_duplicate_at(self):
        self.ci.load_text("@main")
        self.ci.move_cursor((0, len("@main")))
        self.ci.apply_file_suggestion("@main.py", 0)
        self.assertEqual(self.ci.text, "@main.py ")


class TestSubmitWhitespace(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_enter_submits_whitespace_message_value(self):
        self.ci.load_text("   ")
        event_enter = Key("enter", "enter")
        event_enter.prevent_default = MagicMock()
        event_enter.stop = MagicMock()
        with patch.object(self.ci, "post_message") as post:
            await self.ci._on_key(event_enter)
        values = [
            c[0][0].value for c in post.call_args_list if c[0] and hasattr(c[0][0], "value") and c[0][0].__class__.__name__ == "Submitted"
        ]
        self.assertIn("   ", values)

    async def test_history_ignores_whitespace_add(self):
        self.ci.prompt_history = []
        self.ci.add_to_history("   ")
        self.assertEqual(self.ci.prompt_history, [])

    async def test_history_dedup_consecutive(self):
        self.ci.prompt_history = []
        self.ci.add_to_history("a")
        self.ci.add_to_history("a")
        self.assertEqual(self.ci.prompt_history, ["a"])


class TestFormatPastedPathEdge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_empty_input_returns_same(self):
        self.assertEqual(self.ci.format_pasted_file_path(""), "")

    async def test_none_input_returns_same(self):
        self.assertEqual(self.ci.format_pasted_file_path(None), None)

    async def test_windows_style_path(self):
        res = self.ci.format_pasted_file_path(r"C:\Users\me\file.py")
        self.assertIn("file.py", res)

    async def test_spaces_in_path_kept(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", prefix="my file ") as tmp:
            res = self.ci.format_pasted_file_path(tmp.name)
            self.assertEqual(res, f"@{tmp.name} ")

    async def test_multibyte_path(self):
        with tempfile.NamedTemporaryFile(suffix=".txt", prefix="файл ") as tmp:
            res = self.ci.format_pasted_file_path(tmp.name)
            self.assertTrue(res.startswith("@"))
            self.assertTrue(res.endswith(" "))
            self.assertIn("файл", res)


class TestOnPasteEdge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ci, self.app, self._ctx = _make_input()
        await self._ctx.__aenter__()

    async def asyncTearDown(self):
        await self._ctx.__aexit__(None, None, None)

    async def test_paste_empty_is_noop(self):
        from textual.events import Paste

        with patch.object(self.ci, "format_pasted_file_path", return_value=""), patch.object(
            self.ci, "_decode_pasted_path", return_value=""
        ):
            event = Paste("")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await self.ci.on_paste(event)  # empty paste must not raise
            self.assertEqual(self.ci.text, "")

    async def test_paste_multiline_under_threshold_no_crash(self):
        from textual.events import Paste

        with patch.object(self.ci, "format_pasted_file_path", return_value="a\nb"), patch.object(
            self.ci, "_decode_pasted_path", return_value="a\nb"
        ):
            event = Paste("a\nb")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await self.ci.on_paste(event)
            self.assertIn("a\nb", self.ci.text)


if __name__ == "__main__":
    unittest.main()



class TestChatInputHistoryFile(unittest.TestCase):
    def test_load_prompt_history_invalid_json_returns_empty(self):
        ci = ChatInput()
        with patch.object(chat_input_mod.config, "PROMPT_HISTORY_FILE", "/nonexistent/history.json"):
            with patch("widgets.chat_input.read_json", return_value=None):
                self.assertEqual(ci.load_prompt_history(), [])

    def test_save_prompt_history_swallows_write_error(self):
        ci = ChatInput()
        ci.prompt_history = ["a", "b"]
        with patch("widgets.chat_input.atomic_write_json", side_effect=OSError("disk full")):
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


class TestChatInputKeyboardScroll(unittest.IsolatedAsyncioTestCase):
    async def test_page_up_scrolls_chat_view_up(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        mock_chat_view = MagicMock()
        with patch.object(ci.app, "query_one", return_value=mock_chat_view):
            event = Key("pageup", "pageup")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await ci._on_key(event)
            mock_chat_view.scroll_up_page.assert_called_once()
            event.prevent_default.assert_called()
            event.stop.assert_called()

    async def test_page_down_scrolls_chat_view_down(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        mock_chat_view = MagicMock()
        with patch.object(ci.app, "query_one", return_value=mock_chat_view):
            event = Key("pagedown", "pagedown")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await ci._on_key(event)
            mock_chat_view.scroll_down_page.assert_called_once()
            event.prevent_default.assert_called()
            event.stop.assert_called()

    async def test_shift_page_up_scrolls_to_top(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        mock_chat_view = MagicMock()
        with patch.object(ci.app, "query_one", return_value=mock_chat_view):
            event = Key("shift+pageup", "shift+pageup")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await ci._on_key(event)
            mock_chat_view.scroll_to_top.assert_called_once()
            event.prevent_default.assert_called()
            event.stop.assert_called()

    async def test_shift_page_down_scrolls_to_bottom(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        mock_chat_view = MagicMock()
        with patch.object(ci.app, "query_one", return_value=mock_chat_view):
            event = Key("shift+pagedown", "shift+pagedown")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await ci._on_key(event)
            mock_chat_view.scroll_to_bottom.assert_called_once()
            event.prevent_default.assert_called()
            event.stop.assert_called()

    async def test_scroll_error_swallowed_when_no_chat_view(self):
        ci, ctx = _app_context()
        await ctx.__aenter__()
        self.addAsyncCleanup(ctx.__aexit__, None, None, None)
        with patch.object(ci.app, "query_one", side_effect=Exception("no chat view")):
            event = Key("pageup", "pageup")
            event.prevent_default = MagicMock()
            event.stop = MagicMock()
            await ci._on_key(event)  # must not raise


def _app_context():
    ci = ChatInput()
    ctx = DummyChatApp(ci).run_test()
    return ci, ctx


def _make_fake_suggestions(mode="command"):
    sugg = MagicMock()
    sugg.display = True
    sugg.highlighted = 0
    sugg.mode = mode
    sugg.current_matched = ["/help"] if mode == "command" else ["/main.py"]
    sugg.at_start_idx = 0
    return sugg
