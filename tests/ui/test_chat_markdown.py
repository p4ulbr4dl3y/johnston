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
        console = Console(width=40, _environ={})
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
            self.assertFalse(getattr(widgets[0], "ALLOW_SELECT", True))
            labels = [w for w in widgets if isinstance(w, Label)]
            self.assertEqual(str(labels[0].render()), "python")
            self.assertFalse(getattr(labels[0], "ALLOW_SELECT", True))

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
            f3_widgets = list(fence3.compose())
            self.assertGreater(len(f3_widgets), 0)
            f3_labels = [w for w in f3_widgets if isinstance(w, Label)]
            self.assertEqual(str(f3_labels[0].render()), "text")

            fence4 = CustomMarkdownFence.__new__(CustomMarkdownFence)
            fence4.lexer = "totally_unknown_lang"
            fence4.code = "x"
            fence4.theme = "one-dark"
            fence4.markdown = None
            f4_widgets = list(fence4.compose())
            self.assertGreater(len(f4_widgets), 0)

            from textual.content import Content

            highlighted_none = CustomMarkdownFence.highlight("sample code", None)
            self.assertIsInstance(highlighted_none, Content)
        finally:
            active_app.reset(token)

    def test_custom_markdown_fence_default_css_contains_dimensions(self):
        self.assertIn("height: 1", CustomMarkdownFence.DEFAULT_CSS)
        self.assertIn(".fence-header", CustomMarkdownFence.DEFAULT_CSS)
        self.assertIn(".fence-scroll-box", CustomMarkdownFence.DEFAULT_CSS)

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
        self.assertIsNotNone(style)
        self.assertIsNotNone(style.background)
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


class TestFenceHighlightCache(unittest.TestCase):
    """Regression: fence highlighting is cached + pre-warmed off the UI thread.

    Before the fix, every Markdown mount re-ran pygments synchronously inside
    CustomMarkdownFence.compose() (~10ms per large block; 250ms+ for an answer
    with many code blocks), freezing the event loop at final render.
    """

    def _clear_cache(self):
        from widgets.presentation.widgets import chat_markdown

        chat_markdown._highlight_cache.clear()

    def setUp(self):
        self._clear_cache()

    def tearDown(self):
        self._clear_cache()

    def test_highlight_returns_cached_content_for_same_inputs(self):
        code = "def f():\n    return 1\n"
        first = CustomMarkdownFence.highlight(code, "python")
        second = CustomMarkdownFence.highlight(code, "python")
        self.assertIs(first, second)

    def test_highlight_distinguishes_language_dark_and_code(self):
        code = "x = 1"
        py = CustomMarkdownFence.highlight(code, "python")
        py_dark2 = CustomMarkdownFence.highlight(code, "python", dark=True)
        self.assertIs(py, py_dark2)  # same key -> same object
        js = CustomMarkdownFence.highlight(code, "javascript")
        plain = CustomMarkdownFence.highlight(code, "text")
        light = CustomMarkdownFence.highlight(code, "python", dark=False)
        self.assertIsNot(py, js)
        self.assertIsNot(py, plain)
        self.assertIsNot(py, light)

    def test_resolve_highlight_lexer_fallbacks(self):
        from widgets.presentation.widgets.chat_markdown import resolve_highlight_lexer

        self.assertEqual(resolve_highlight_lexer("python"), "python")
        self.assertEqual(resolve_highlight_lexer(" PYTHON "), "python")
        self.assertEqual(resolve_highlight_lexer("not-a-real-lexer-xyz"), "text")
        self.assertEqual(resolve_highlight_lexer(""), "text")
        self.assertEqual(resolve_highlight_lexer(None), "text")
        self.assertEqual(resolve_highlight_lexer("log"), "text")

    def test_prewarm_fills_cache_and_compose_hits_it(self):
        from widgets.presentation.widgets.chat_markdown import (
            _highlight_cache,
            prewarm_fences_from_markdown,
        )

        md = "intro\n\n```python\nx = 1\n```\n\nmid\n\n```js\nlet y = 2;\n```\n"
        count = prewarm_fences_from_markdown(md, dark=True)
        self.assertEqual(count, 2)
        self.assertEqual(len(_highlight_cache), 2)
        # compose() path (same normalized inputs) must hit the warm entries.
        content = CustomMarkdownFence.highlight("x = 1", "python")
        self.assertIn(content, list(_highlight_cache.values()))

    def test_prewarm_skips_empty_and_unclosed_blocks(self):
        from widgets.presentation.widgets.chat_markdown import _highlight_cache, prewarm_fences_from_markdown

        self.assertEqual(prewarm_fences_from_markdown("no fences here", dark=True), 0)
        self.assertEqual(_highlight_cache, {})
        # Unclosed fence at EOF is not pre-warmed.
        self.assertEqual(prewarm_fences_from_markdown("```python\ncode without closer\n", dark=True), 0)
        # An immediately-closed empty fence is not pre-warmed.
        self.assertEqual(prewarm_fences_from_markdown("```\n```\n", dark=True), 0)
        self.assertEqual(_highlight_cache, {})

    def test_prewarm_matches_indented_fence_like_clean_markdown(self):
        from widgets.presentation.widgets.chat_markdown import prewarm_fences_from_markdown

        md = "text\n\n  ```python\n  y = 3\n  ```\n"
        self.assertEqual(prewarm_fences_from_markdown(md, dark=True), 1)

    def test_highlight_cache_invalidated_by_theme_change(self):
        from widgets.presentation.widgets import chat_markdown

        code = "z = 9"
        before = CustomMarkdownFence.highlight(code, "python")
        sentinel = object()  # hashable theme-object stand-in
        original = chat_markdown._CURRENT_SYNTAX_THEME
        chat_markdown._CURRENT_SYNTAX_THEME = sentinel
        try:
            after = CustomMarkdownFence.highlight(code, "python")
        finally:
            chat_markdown._CURRENT_SYNTAX_THEME = original
        self.assertIsNot(before, after)

    def test_prepare_markdown_text_prewarms_and_cleans(self):
        from widgets.presentation.widgets.chat_markdown import (
            _highlight_cache,
            prepare_markdown_text,
        )

        md = "para\n\n```python\nq = 4\n```\n"
        cleaned = prepare_markdown_text(md, dark=True)
        self.assertEqual(cleaned, clean_markdown_for_rendering(md))
        self.assertTrue(any("q = 4" in key[0] for key in _highlight_cache))

    def test_highlight_cache_lru_bounded(self):
        from widgets.presentation.widgets.chat_markdown import (
            _HIGHLIGHT_CACHE_MAX,
            _highlight_cache,
        )

        for i in range(_HIGHLIGHT_CACHE_MAX + 10):
            CustomMarkdownFence.highlight(f"v = {i}\n", "python")
        self.assertEqual(len(_highlight_cache), _HIGHLIGHT_CACHE_MAX)
