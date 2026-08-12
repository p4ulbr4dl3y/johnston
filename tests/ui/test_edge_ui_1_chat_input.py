"""Edge-case tests for widgets/chat_input.py (bug-hunting round)."""
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult
from textual.events import Key

from widgets.chat_input import ChatInput


class DummyChatApp(App[None]):
    def __init__(self, chat_input):
        super().__init__()
        self.chat_input = chat_input
        self.submitted_messages = []

    def compose(self) -> ComposeResult:
        yield self.chat_input

    def on_chat_input_submitted(self, message: ChatInput.Submitted):
        self.submitted_messages.append(message)


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

    async def test_multiple_artifacts_removed(self):
        self.ci.load_text("a M<65;1272;815M b [<65;1272;815M c")
        self.assertEqual(self.ci.text, "a  b  c")

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

    async def test_apply_at_index_zero(self):
        self.ci.load_text("/he")
        self.ci.move_cursor((0, len("/he")))
        self.ci.apply_suggestion("/help", 0)
        self.assertEqual(self.ci.text, "/help ")

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
