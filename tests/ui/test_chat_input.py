import os
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from PIL import Image
from textual.app import App, ComposeResult
from textual.events import Key, Paste

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
        att = ClipboardAttachment("/tmp/img.png", width=640, height=480, size_kb=12.5)
        self.assertEqual(att.path, "/tmp/img.png")
        self.assertEqual(att.width, 640)
        self.assertEqual(att.height, 480)
        self.assertEqual(att.size_kb, 12.5)
        self.assertTrue(att.id.startswith("att_"))


class TestChatInputUnit(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_file = os.path.join(self.tmp_dir.name, "prompt_history.json")
        self.patcher = patch("core.config.PROMPT_HISTORY_FILE", self.tmp_file)
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
                att = ClipboardAttachment(tmp.name, 10, 10, 1.0)
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
                patch("core.platform_utils.get_clipboard_image_or_file", return_value=(None, mock_img)),
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
            with patch("core.config.PROMPT_HISTORY_FILE", tmp_history_file), patch("core.config.CONFIG_DIR", tmpdir):
                ci = ChatInput()
                self.assertEqual(ci.prompt_history, [])

                ci.add_to_history("Global prompt 1")
                ci.add_to_history("Global prompt 2")
                self.assertTrue(os.path.exists(tmp_history_file))

                # New ChatInput instance loads persisted history
                ci2 = ChatInput()
                self.assertEqual(ci2.prompt_history, ["Global prompt 1", "Global prompt 2"])
                self.assertEqual(ci2.prompt_history_index, 2)

    async def test_key_shortcuts(self):
        ci = ChatInput()
        app = DummyChatApp(ci)
        async with app.run_test():
            # ctrl+c / ctrl+q -> exit
            with patch.object(app, "exit") as mock_exit:
                event = Key("ctrl+c", "ctrl+c")
                event.prevent_default = MagicMock()
                event.stop = MagicMock()
                await ci._on_key(event)
                mock_exit.assert_called_once()

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
                ci.update_suggestions()
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
            # ctrl+d clears attachments
            att = ClipboardAttachment("/tmp/img.png")
            ci.clipboard_attachments.append(att)

            event_d = Key("ctrl+d", "ctrl+d")
            event_d.prevent_default = MagicMock()
            event_d.stop = MagicMock()
            await ci._on_key(event_d)
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
