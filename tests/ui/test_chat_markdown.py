import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from textual.widgets import Label

from widgets.presentation.widgets.chat_markdown import (
    CustomMarkdownFence,
    CustomMarkdownTable,
    CustomMarkdownTableContent,
    TransparentSyntax,
    clean_markdown_for_rendering,
    safe_update_markdown,
)


class TestMarkdownHelpers(unittest.TestCase):
    """Module-level helpers: syntax, fence widgets, table widgets, diff rendering."""

    def test_transparent_syntax_strips_background_colors(self):
        from rich.console import Console
        from rich.segment import Segment
        from rich.style import Style
        from rich.syntax import Syntax

        syntax = TransparentSyntax("x = 1", "python")
        console = Console(width=40)
        styled = Segment("x", Style(bgcolor="#ff0000"))
        plain = Segment(" ", None)
        with patch.object(Syntax, "_get_syntax", return_value=iter([styled, plain])):
            result = list(syntax._get_syntax(console, console.options))
        self.assertEqual(result[0].style.bgcolor, None)
        self.assertEqual(result[0].text, "x")
        self.assertIs(result[1], plain)

    def test_custom_markdown_fence_compose_lexers_and_theme(self):
        from textual._context import active_app

        mock_app = MagicMock()
        mock_app._compose_stacks = [[]]
        token = active_app.set(mock_app)
        try:
            fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence.lexer = "python"
            fence.code = "print(1)"
            fence.theme = None
            fence.markdown = MagicMock(theme=None)
            widgets = list(fence.compose())
            self.assertGreater(len(widgets), 0)
            labels = [w for w in widgets if isinstance(w, Label)]
            self.assertEqual(str(labels[0].render()), "python")

            fence2 = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence2.lexer = "text"
            fence2.code = "plain"
            fence2.theme = None
            fence2.markdown = None
            self.assertGreater(len(list(fence2.compose())), 0)

            fence3 = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence3.lexer = None
            fence3.code = "no lang"
            fence3.theme = None
            fence3.markdown = None
            self.assertGreater(len(list(fence3.compose())), 0)

            fence4 = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence4.lexer = "totally_unknown_lang"
            fence4.code = "x"
            fence4.theme = "one-dark"
            fence4.markdown = None
            self.assertGreater(len(list(fence4.compose())), 0)
        finally:
            active_app.reset(token)

    def test_custom_markdown_fence_allow_horizontal_scroll(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        self.assertFalse(fence.allow_horizontal_scroll)

    def test_custom_markdown_fence_set_content_and_render(self):
        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.query_one = MagicMock()
        label = MagicMock()
        fence.query_one.return_value = label

        content = MagicMock()
        content.code = "line1\nline2\r\n"
        content.word_wrap = False
        fence.set_content(content)
        self.assertEqual(content.code, "line1\nline2")
        self.assertTrue(content.word_wrap)
        label.update.assert_called_once_with(content)

        fence2 = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence2.query_one = MagicMock(side_effect=Exception("not mounted"))
        fence2.set_content(MagicMock(code="x"))
        self.assertEqual(fence2.render(), "")

    def test_custom_markdown_fence_button_press_copy_and_exceptions(self):
        from textual.widgets import Button

        fence = CustomMarkdownFence.__new__(CustomMarkdownFence)
        fence.code = "x = 1"
        event = MagicMock(spec=Button.Pressed)
        event.button = MagicMock(spec=Button)
        event.button.classes = {"fence-copy-btn"}

        with patch.object(CustomMarkdownFence, "app", new_callable=PropertyMock) as app_prop:
            app_prop.return_value = MagicMock()
            fence.on_button_pressed(event)
        event.stop.assert_called_once()

        event2 = MagicMock(spec=Button.Pressed)
        event2.button = MagicMock(spec=Button)
        event2.button.classes = {"other-btn"}
        fence.on_button_pressed(event2)
        event2.stop.assert_not_called()

        event3 = MagicMock(spec=Button.Pressed)
        event3.button = MagicMock(spec=Button)
        event3.button.classes = {"fence-copy-btn"}
        with patch.object(CustomMarkdownFence, "app", new_callable=PropertyMock) as app_prop:
            app_prop.side_effect = Exception("boom")
            fence.on_button_pressed(event3)

    def test_custom_markdown_table_compose(self):
        from rich.text import Text

        table = CustomMarkdownTable.__new__(CustomMarkdownTable)
        headers = [Text("a"), Text("b")]
        rows = [[Text("1"), Text("2")]]
        table._get_headers_and_rows = MagicMock(return_value=(headers, rows))
        result = list(table.compose())
        self.assertEqual(len(result), 1)
        self.assertIsInstance(result[0], CustomMarkdownTableContent)
        self.assertEqual(table._headers, headers)
        self.assertEqual(table._rows, rows)

    def test_markdown_blocks_table_open_is_patched(self):
        from textual.widgets import Markdown

        from widgets.presentation.widgets.chat_markdown import _apply_chat_markdown_patches

        _apply_chat_markdown_patches()
        self.assertIs(Markdown.BLOCKS["table_open"], CustomMarkdownTable)
        self.assertIs(Markdown.BLOCKS["table_open"], CustomMarkdownTable)
        instance = Markdown("")
        self.assertIs(instance.BLOCKS["table_open"], CustomMarkdownTable)
        self.assertIs(instance.BLOCKS, Markdown.BLOCKS)

    def test_custom_markdown_table_content_compose_update_rows_mount(self):
        from rich.text import Text
        from textual.widgets import Static

        content = CustomMarkdownTableContent.__new__(CustomMarkdownTableContent)
        content.headers = [Text("h1"), Text("h2")]
        content.rows = [[Text("a"), Text("b")], [Text("c"), Text("d")]]
        content.last_row = 0
        children = list(content.compose())
        self.assertEqual(len(children), 6)
        self.assertEqual(content.last_row, 2)

        content2 = CustomMarkdownTableContent.__new__(CustomMarkdownTableContent)
        content2.headers = [Text("h1")]
        content2.last_row = 1
        content2.styles = MagicMock()
        remove = AsyncMock()
        content2.query_children = MagicMock(return_value=MagicMock(remove=remove))
        content2.mount_all = AsyncMock()
        asyncio.run(content2._update_rows([[Text("x")], [Text("y")]]))
        remove.assert_awaited_once()
        self.assertEqual(content2.last_row, 2)
        mounted = content2.mount_all.await_args.args[0]
        self.assertEqual(len(mounted), 2)
        self.assertIsInstance(mounted[0], Static)

        content3 = CustomMarkdownTableContent.__new__(CustomMarkdownTableContent)
        content3.headers = [Text("h1"), Text("h2")]
        content3.styles = MagicMock()
        child_mock = MagicMock()
        content3.query = MagicMock(return_value=[child_mock])
        content3.on_mount()
        self.assertEqual(content3.styles.grid_size_columns, 2)
        child_mock.tooltip = None

    def test_handle_markdown_task_done(self):
        from widgets.presentation.widgets.chat_markdown import _handle_markdown_task_done

        cancelled = MagicMock()
        cancelled.cancelled.return_value = True
        _handle_markdown_task_done(cancelled)

        errored = MagicMock()
        errored.cancelled.return_value = False
        errored.exception.side_effect = RuntimeError("boom")
        _handle_markdown_task_done(errored)

        clean = MagicMock()
        clean.cancelled.return_value = False
        clean.exception.return_value = None
        _handle_markdown_task_done(clean)

    def test_safe_update_markdown_branches(self):
        from textual.widgets import Markdown

        md = Markdown("")
        with patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=False):
            safe_update_markdown(md, "content")

        md2 = Markdown("")
        md2.update = MagicMock(return_value=None)
        calls = []
        with patch.object(type(md2), "is_attached", new_callable=PropertyMock, return_value=True):
            safe_update_markdown(md2, "content", on_done=lambda: calls.append(1))
        self.assertEqual(calls, [1])

        md3 = Markdown("")
        md3.update = MagicMock(side_effect=Exception("boom"))
        calls2 = []
        with patch.object(type(md3), "is_attached", new_callable=PropertyMock, return_value=True):
            safe_update_markdown(md3, "content", on_done=lambda: calls2.append(1))
        self.assertEqual(calls2, [1])

    def test_safe_update_markdown_awaitable_path(self):
        from textual.widgets import Markdown

        async def _run():
            md = Markdown("")

            async def completed_coro():
                return None

            md.update = MagicMock(return_value=completed_coro())
            calls = []
            with patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=True):
                safe_update_markdown(md, "content", on_done=lambda: calls.append(1))
                await asyncio.sleep(0.01)
            return calls

        calls = asyncio.run(_run())
        self.assertEqual(calls, [1])

    def test_safe_update_markdown_no_running_loop(self):
        from textual.widgets import Markdown

        async def _run():
            md = Markdown("")

            async def completed_coro():
                return None

            md.update = MagicMock(return_value=completed_coro())
            calls = []
            with (
                patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=True),
                patch("asyncio.get_running_loop", side_effect=RuntimeError),
            ):
                safe_update_markdown(md, "content", on_done=lambda: calls.append(1))
            return calls

        calls = asyncio.run(_run())
        self.assertEqual(calls, [1])

    def test_markdown_block_inline_code_style(self):
        from widgets.presentation.widgets.chat_markdown import _new_markdown_block_get_style

        style = _new_markdown_block_get_style(object(), ".code_inline")
        self.assertEqual(style.background.rgb, (39, 39, 42))
        other = _new_markdown_block_get_style(MagicMock(), "bold")
        self.assertIsNotNone(other)


class TestCleanMarkdownExtended(unittest.TestCase):
    def test_clean_markdown_code_fences(self):
        raw = "```python\n* not a list\n\nstill code\n```\n\n- real list"
        cleaned = clean_markdown_for_rendering(raw)
        self.assertIn("* not a list", cleaned)
        self.assertIn("- real list", cleaned)

    def test_clean_markdown_unclosed_fence_appends_closer(self):
        raw = "before\n```python\ncode\n"
        cleaned = clean_markdown_for_rendering(raw)
        self.assertTrue(cleaned.rstrip().endswith("```"))

    def test_clean_markdown_empty_and_crlf(self):
        self.assertEqual(clean_markdown_for_rendering(""), "")
        self.assertEqual(clean_markdown_for_rendering("\r\n"), "")

    def test_clean_markdown_tabs_and_single_star(self):
        raw = "\t- item\nplain *star\n"
        cleaned = clean_markdown_for_rendering(raw)
        self.assertIn("    - item", cleaned)
        # Single asterisk in prose is preserved.
        self.assertIn("plain *star", cleaned)

    def test_clean_markdown_preserves_blank_lines_in_code_fence(self):
        raw = "```python\ndef f():\n\n\n    return x\n```\n\n- real list"
        cleaned = clean_markdown_for_rendering(raw)
        # Blank lines inside the fence stay intact; the single blank line before the list stays.
        self.assertIn("def f():\n\n\n    return x\n```", cleaned)
        self.assertIn("- real list", cleaned)

    def test_clean_markdown_collapses_excess_blank_lines_outside_fence(self):
        raw = "para one\n\n\n\npara two"
        cleaned = clean_markdown_for_rendering(raw)
        self.assertNotIn("\n\n\n", cleaned)
        self.assertEqual(cleaned, "para one\n\npara two")
