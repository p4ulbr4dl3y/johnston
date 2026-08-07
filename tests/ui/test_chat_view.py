import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from textual.widgets import Label

from app import JohnstonApp
from widgets.chat_view import (
    BotMessage,
    ChatView,
    CompactionDivider,
    CustomMarkdownFence,
    CustomMarkdownTable,
    CustomMarkdownTableContent,
    DiffRenderable,
    ThinkingWidget,
    ToolCallWidget,
    TransparentSyntax,
    UserMessage,
    WelcomeWidget,
    clean_markdown_for_rendering,
    format_edit_diff,
    safe_update_markdown,
    to_snake_case,
)


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
            self.assertEqual([type(child).__name__ for child in children[-3:]], ["UserMessage", "BotMessage", "ToolCallWidget"])
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

    async def test_large_bot_message_uses_single_static_renderable(self):
        app = JohnstonApp()

        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            bot = await chat_view.add_bot_message(animate=False)
            await pilot.pause()

            large_markdown = ("## Section\n\n- item\n\n" * 400).strip()
            with patch.object(bot.md_widget, "update", new_callable=AsyncMock) as markdown_update:
                await bot.set_final_content(large_markdown)

            markdown_update.assert_not_awaited()
            self.assertTrue(bot.stream_widget.display)
            self.assertFalse(bot.md_widget.display)

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
        self.assertIn(" * Text: Wait, unpaired star", cleaned)

    def test_tool_call_widget_extracts_mcp_info(self):
        # Case 1: Standard lowercase keys
        item = ToolCallWidget("call_mcp", "", "", args={"server": "colab", "tool": "add_cell", "arguments": {"x": 1}})
        tool, server, args = item._extract_mcp_call_info()
        self.assertEqual((tool, server, args), ("add_cell", "colab", {"x": 1}))

        # Case 2: PascalCase keys (ToolName / ServerName / Arguments)
        item2 = ToolCallWidget("call_mcp", "", "", args={"ServerName": "colab-mcp", "ToolName": "run_cell", "Arguments": {"y": 2}})
        tool2, server2, args2 = item2._extract_mcp_call_info()
        self.assertEqual((tool2, server2, args2), ("run_cell", "colab-mcp", {"y": 2}))

        # Case 3: Missing tool name key, top-level arguments
        item3 = ToolCallWidget("call_mcp", "", "", args={"server": "colab", "code": "print(1)"})
        tool3, server3, args3 = item3._extract_mcp_call_info()
        self.assertEqual((tool3, server3, args3), ("call_mcp", "colab", {"code": "print(1)"}))

    def test_to_snake_case(self):
        self.assertEqual(to_snake_case("CallMCPTool"), "call_mcp_tool")
        self.assertEqual(to_snake_case("openColabBrowser"), "open_colab_browser")
        self.assertEqual(to_snake_case("OpenColabBrowser"), "open_colab_browser")
        self.assertEqual(to_snake_case("search_issues"), "search_issues")
        self.assertEqual(to_snake_case(""), "")
        self.assertEqual(to_snake_case("  spaced name "), "_spaced_name_")


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
        content.word_wrap = True
        fence.set_content(content)
        self.assertEqual(content.code, "line1\nline2")
        self.assertFalse(content.word_wrap)
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
        from widgets.chat_view import _handle_markdown_task_done

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

    async def test_safe_update_markdown_awaitable_path(self):
        from textual.widgets import Markdown

        md = Markdown("")

        async def completed_coro():
            return None

        md.update = MagicMock(return_value=completed_coro())
        calls = []
        with patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=True):
            safe_update_markdown(md, "content", on_done=lambda: calls.append(1))
            await asyncio.sleep(0.01)
        self.assertEqual(calls, [1])

    async def test_safe_update_markdown_no_running_loop(self):
        from textual.widgets import Markdown

        md = Markdown("")

        async def completed_coro():
            return None

        md.update = MagicMock(return_value=completed_coro())
        calls = []
        with patch.object(type(md), "is_attached", new_callable=PropertyMock, return_value=True), patch(
            "asyncio.get_running_loop", side_effect=RuntimeError
        ):
            safe_update_markdown(md, "content", on_done=lambda: calls.append(1))
        self.assertEqual(calls, [1])

    def test_markdown_block_inline_code_style(self):
        from widgets.chat_view import _new_markdown_block_get_style

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
        self.assertIn("plain star", cleaned)


class TestCompactionDivider(unittest.TestCase):
    def test_compaction_divider_init_and_update(self):
        divider = CompactionDivider("Custom Title")
        self.assertEqual(divider.divider_title, "Custom Title")
        divider.update_title("New Title")
        self.assertEqual(divider.divider_title, "New Title")


class TestDiffRenderable(unittest.TestCase):
    def test_diff_renderable_console_and_measure(self):
        from rich.console import Console
        from rich.text import Text

        lines = [Text("old line"), Text("new line")] * 2
        renderable = DiffRenderable(lines)
        console = Console(width=20, record=True)
        console.print(renderable)
        self.assertIn("old line", console.export_text())
        self.assertIsNotNone(renderable.__rich_measure__(console, console.options))
        self.assertEqual(renderable.plain, "old line\nnew line\nold line\nnew line")

    def test_diff_renderable_pads_short_lines(self):
        from rich.console import Console
        from rich.text import Text

        lines = [Text("short"), Text("a much longer line that exceeds")]
        renderable = DiffRenderable(lines)
        console = Console(width=10, record=True)
        console.print(renderable)
        self.assertIn("short", console.export_text())


class TestFormatEditDiff(unittest.TestCase):
    def test_format_edit_diff_basic_hunk(self):
        diff = (
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,3 @@\n"
            " def keep():\n"
            "-    old = 1\n"
            "+    new = 2\n"
            "     return\n"
        )
        result = format_edit_diff(diff, "file.py")
        self.assertIsInstance(result, DiffRenderable)
        text = result.plain
        self.assertIn("keep", text)
        self.assertIn("old = 1", text)
        self.assertIn("new = 2", text)

    def test_format_edit_diff_linter_feedback_and_success_prefix(self):
        diff = (
            "[Linter Feedback]:\n"
            "some linter noise\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-a\n"
            "+b\n"
        )
        result = format_edit_diff(diff, "f.py")
        self.assertNotIn("Linter", result.plain)

        diff2 = (
            "Success: file 'f.py' updated\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-a\n"
            "+b\n"
        )
        result2 = format_edit_diff(diff2, "f.py")
        self.assertNotIn("Success", result2.plain)

    def test_format_edit_diff_no_hunk_and_unknown_lexer(self):
        diff = "just a plain status line\nmore status\n"
        result = format_edit_diff(diff, "unknown.xyz")
        self.assertIsInstance(result, DiffRenderable)
        self.assertIn("just a plain status line", result.plain)

    def test_format_edit_diff_html_js_and_css_detection(self):
        html_js = (
            "--- a/index.html\n"
            "+++ b/index.html\n"
            "@@ -1,2 +1,2 @@\n"
            "-<script>console.log(1)</script>\n"
            "+function run() { return 1; }\n"
        )
        result = format_edit_diff(html_js, "index.html")
        self.assertIn("console", result.plain)

        html_css = (
            "--- a/style.html\n"
            "+++ b/style.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-body { color: red; }\n"
            "+div { color: blue; }\n"
        )
        result2 = format_edit_diff(html_css, "style.html")
        self.assertIn("color", result2.plain)

    def test_format_edit_diff_backslash_and_outside_hunk_lines(self):
        diff = (
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
            "\\ No newline at end of file\n"
            "trailing garbage line\n"
        )
        result = format_edit_diff(diff, "f.py")
        self.assertIn("trailing garbage line", result.plain)

    def test_format_edit_diff_empty_code_lines_and_no_lexer(self):
        diff = (
            "--- a/f.txt\n"
            "+++ b/f.txt\n"
            "@@ -1,1 +1,1 @@\n"
            "-\n"
            "+\n"
        )
        result = format_edit_diff(diff, "f.txt")
        self.assertIsInstance(result, DiffRenderable)

    def test_format_edit_diff_http_path_and_multi_hunk_numbers(self):
        diff = (
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,2 +10,2 @@\n"
            "-line1\n"
            "-line2\n"
            "+lineA\n"
            "+lineB\n"
        )
        result = format_edit_diff(diff, "https://example.com/f.py")
        self.assertIsInstance(result, DiffRenderable)
        self.assertIn("lineA", result.plain)

    def test_format_edit_diff_empty_lines_and_hunk_marker_without_ranges(self):
        diff = (
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1 +1 @@\n"
            " context\n"
            "-\n"
            "+\n"
            " tail\n"
        )
        result = format_edit_diff(diff, "f.py")
        self.assertIsInstance(result, DiffRenderable)

    def test_format_edit_diff_success_ok_and_status_lines_outside_hunk(self):
        diff = (
            "OK: did something\n"
            "file.py updated\n"
            "file created\n"
            "file saved\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-a\n"
            "+b\n"
        )
        result = format_edit_diff(diff, "f.py")
        self.assertIn("1 + b", result.plain)

    def test_format_edit_diff_filters_ok_lines_without_hunk(self):
        diff = "OK: did something\nplain status\n"
        result = format_edit_diff(diff, "f.py")
        self.assertNotIn("OK:", result.plain)
        self.assertIn("plain status", result.plain)

    def test_format_edit_diff_html_with_style_block_detection(self):
        diff = (
            "--- a/s.html\n"
            "+++ b/s.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-<style>body { color: red; }</style>\n"
            "+<style>div { color: blue; }</style>\n"
        )
        result = format_edit_diff(diff, "s.html")
        self.assertIn("color", result.plain)

    def test_format_edit_diff_plain_lines_before_hunk_kept_dim(self):
        diff = "preamble line\n--- a/f.py\n+++ b/f.py\n@@ -1,1 +1,1 @@\n-a\n+b\n"
        result = format_edit_diff(diff, "f.py")
        self.assertIn("preamble line", result.plain)

    def test_format_edit_diff_empty_path_and_empty_context_line(self):
        diff = (
            "--- a/f\n"
            "+++ b/f\n"
            "@@ -1,2 +1,2 @@\n"
            " a\n"
            "\n"
            "-b\n"
            "+c\n"
        )
        result = format_edit_diff(diff, "")
        self.assertIsInstance(result, DiffRenderable)

    def test_format_edit_diff_html_script_tags_detection(self):
        diff = (
            "--- a/p.html\n"
            "+++ b/p.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-<script>const x = 1;</script>\n"
            "+<script>const y = 2;</script>\n"
        )
        result = format_edit_diff(diff, "p.html")
        self.assertIn("const", result.plain)

    def test_format_edit_diff_css_after_script_detection(self):
        diff = (
            "--- a/q.html\n"
            "+++ b/q.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-body { margin: 0; }\n"
            "+div { padding: 0; }\n"
        )
        result = format_edit_diff(diff, "q.html")
        self.assertIn("margin", result.plain)

    def test_format_edit_diff_js_without_script_tag(self):
        diff = (
            "--- a/r.html\n"
            "+++ b/r.html\n"
            "@@ -1,1 +1,1 @@\n"
            "-function init() { return 1; }\n"
            "+const value = 2;\n"
        )
        result = format_edit_diff(diff, "r.html")
        self.assertIn("function", result.plain)

    def test_format_edit_diff_lexer_exception_fallback(self):
        diff = (
            "--- a/f.unknownext\n"
            "+++ b/f.unknownext\n"
            "@@ -1,1 +1,1 @@\n"
            "-line one\n"
            "+line two\n"
        )
        result = format_edit_diff(diff, "f.unknownext")
        self.assertIn("line one", result.plain)


class TestBotMessageInternals(unittest.IsolatedAsyncioTestCase):
    async def test_set_final_content_large_message_uses_static_markdown(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            bot = await chat_view.add_bot_message(animate=False)
            await pilot.pause()
            with patch.object(bot.md_widget, "update", new_callable=AsyncMock) as markdown_update:
                await bot.set_final_content("## Big\n\n" * 300)
            markdown_update.assert_not_awaited()
            self.assertTrue(bot.stream_widget.display)
            self.assertFalse(bot.md_widget.display)

    async def test_schedule_stream_update_runtime_error_and_flush_unattached(self):
        bot = BotMessage()
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            bot._schedule_stream_update()
        self.assertFalse(bot._stream_update_scheduled)

    async def test_set_final_content_cancels_pending_render_task(self):
        bot = BotMessage()
        handle = MagicMock()
        bot._stream_update_handle = handle
        task = asyncio.create_task(asyncio.sleep(60))
        bot._markdown_render_task = task
        await bot.set_final_content("small content")
        handle.cancel.assert_called_once()
        self.assertTrue(task.cancelled())
        self.assertIsNone(bot._pending_markdown_content)

    async def test_schedule_markdown_render_reuses_existing_task(self):
        bot = BotMessage()
        task = asyncio.create_task(asyncio.sleep(60))
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


class TestThinkingWidget(unittest.TestCase):
    def _make_widget(self, text="Thinking..."):
        return ThinkingWidget(text)

    def test_thinking_widget_init_and_compose(self):
        widget = self._make_widget()
        self.assertTrue(widget.is_thinking)
        self.assertFalse(widget.is_expanded)
        self.assertIs(widget.md_widget, widget.content_widget)
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
        update_mock.assert_called_with("expanded thought")

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

    def test_thinking_widget_not_expandable_on_subagent_screen(self):
        class SubagentViewScreen:
            pass

        widget = self._make_widget()
        with patch.object(type(widget), "screen", new_callable=PropertyMock) as screen_prop:
            screen_prop.return_value = SubagentViewScreen()
            self.assertFalse(widget.is_expandable())
            event = MagicMock()
            widget.on_click(event)
            event.stop.assert_not_called()

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


class TestChatViewBehaviors(unittest.IsolatedAsyncioTestCase):
    async def test_add_user_message_with_attachments(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            msg = await chat_view.add_user_message("hello", attachments=["a.png", "b.png"])
            await pilot.pause()
            self.assertIn("2 images attached", msg.raw_text)
            self.assertIsInstance(msg, UserMessage)

    async def test_add_user_message_when_unattached_waits(self):
        chat_view = ChatView()
        with patch.object(ChatView, "is_attached", new_callable=PropertyMock, return_value=False), patch.object(
            chat_view, "_wait_until_attached", new_callable=AsyncMock
        ) as wait_mock, patch.object(chat_view, "mount", new_callable=AsyncMock):
            msg = await chat_view.add_user_message("waiting")
        wait_mock.assert_awaited_once()
        self.assertIsInstance(msg, UserMessage)

    async def test_add_thinking_and_compaction_widgets(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            thinking = await chat_view.add_thinking_widget("Thinking...", animate=False)
            divider = await chat_view.add_compaction_divider("Session Compacted", animate=False)
            await pilot.pause()
            self.assertIsInstance(thinking, ThinkingWidget)
            self.assertIsInstance(divider, CompactionDivider)

    async def test_add_tool_call_sequential_flag(self):
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one(ChatView)
            first = await chat_view.add_tool_call("shell", "cmd", "out1", animate=False)
            second = await chat_view.add_tool_call("shell", "cmd2", "out2", animate=False)
            await pilot.pause()
            self.assertNotIn("tool-sequential", first.classes)
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
        with patch.object(ChatView, "is_attached", new_callable=PropertyMock, return_value=False), patch.object(
            chat_view, "_wait_until_attached", new_callable=AsyncMock
        ) as wait_mock, patch.object(chat_view, "mount", new_callable=AsyncMock):
            bot = await chat_view.add_bot_message()
            thinking = await chat_view.add_thinking_widget()
            tool = await chat_view.add_tool_call("shell", "cmd")
            divider = await chat_view.add_compaction_divider()
        self.assertEqual(wait_mock.await_count, 4)
        self.assertIsInstance(bot, BotMessage)
        self.assertIsInstance(thinking, ThinkingWidget)
        self.assertIsInstance(tool, ToolCallWidget)
        self.assertIsInstance(divider, CompactionDivider)

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


class TestToolCallWidgetHelpers(unittest.TestCase):
    def test_is_expandable_variants(self):
        self.assertFalse(ToolCallWidget("read", "f.py").is_expandable())
        self.assertFalse(ToolCallWidget("web_fetch", "http://x").is_expandable())
        self.assertTrue(ToolCallWidget("shell", "cmd").is_expandable())
        self.assertTrue(ToolCallWidget("create", "f.py").is_expandable())
        self.assertTrue(ToolCallWidget("custom_tool", "x").is_expandable())
        self.assertFalse(ToolCallWidget("get_mcp_schema", "server").is_expandable())

    def test_is_expandable_subagent_screen(self):
        class SubagentViewScreen:
            pass

        widget = ToolCallWidget("shell", "cmd")
        with patch.object(type(widget), "screen", new_callable=PropertyMock) as screen_prop:
            screen_prop.return_value = SubagentViewScreen()
            self.assertFalse(widget.is_expandable())

    def test_init_normalizes_target_and_status(self):
        widget = ToolCallWidget("read", "a\n\n b \t c")
        self.assertEqual(widget.target, "a b c")
        self.assertEqual(widget.status, "running")
        widget2 = ToolCallWidget("shell", "cmd", result_text="Error: failed")
        self.assertEqual(widget2.status, "error")
        widget3 = ToolCallWidget("read", "f.py", result_text="ok")
        self.assertEqual(widget3.status, "done")
        widget4 = ToolCallWidget("read", "f.py", args={"is_error": True})
        self.assertEqual(widget4.status, "running")
        widget5 = ToolCallWidget("read", "f.py", result_text="Error: boom")
        self.assertEqual(widget5.status, "error")

    def test_clean_hints_and_markup(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget._clean_hints_for_ui("text\n[Hint: do x]"), "text")
        self.assertEqual(widget._clean_hints_for_ui("text [Hint: inline] rest"), "text")
        self.assertEqual(widget._clean_hints_for_ui(""), "")
        self.assertEqual(widget._clean_markup_text("[b]bold[/b]\n[Hint: nope]"), "\\[b]bold\\[/b]")

    def test_try_parse_json(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget._try_parse_json('{"a": 1}'), {"a": 1})
        self.assertIsNone(widget._try_parse_json("not json"))
        self.assertEqual(widget._try_parse_json('{"a": [1, 2'), {"a": [1, 2]})
        self.assertEqual(widget._try_parse_json('{"a": "unclosed'), {"a": "unclosed"})
        self.assertEqual(widget._try_parse_json("[1, 2"), [1, 2])
        self.assertIsNone(widget._try_parse_json("{unrepairable"))
        self.assertEqual(widget._try_parse_json('{"escaped": "a\\"b"}'), {"escaped": 'a"b'})
        self.assertIsNone(widget._try_parse_json("[] trailing"))
        self.assertIsNone(widget._try_parse_json("[1, 2}"))
        self.assertEqual(widget._try_parse_json('{"back\\\\slash": 1}'), {"back\\slash": 1})
        self.assertEqual(widget._try_parse_json('{"s": "a\\\\n"}'), {"s": "a\\n"})
        self.assertEqual(widget._try_parse_json('{"a": "str with \\\\" escape"}'), None)
        self.assertEqual(widget._try_parse_json('{"unclosed": "\\\\'), {"unclosed": "\\"})
        self.assertIsNone(widget._try_parse_json('{"unclosed": "\\'))

    def test_clean_markup_ansi_escape_removed(self):
        widget = ToolCallWidget("shell", "cmd")
        cleaned = widget._clean_markup_text("\x1b[31mred\x1b[0m text")
        self.assertNotIn("\x1b", cleaned)
        self.assertIn("red", cleaned)
        self.assertEqual(widget._clean_markup_text(""), "")
        self.assertEqual(widget._clean_markup_text(None), "")

    def test_format_json_result(self):
        widget = ToolCallWidget("call_mcp", "")
        self.assertIsNone(widget._format_json_result(""))
        self.assertIsNone(widget._format_json_result("   "))
        result = widget._format_json_result('{"x": 1}')
        self.assertIsNotNone(result)
        truncated = widget._format_json_result('{"x": 1}\n... [Output truncated at 100 chars]')
        self.assertIsNotNone(truncated)
        self.assertIsNone(widget._format_json_result("plain text"))

    def test_check_is_error(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertTrue(widget._check_is_error("Error: boom"))
        self.assertTrue(widget._check_is_error("err: boom"))
        self.assertTrue(widget._check_is_error("[Error] boom"))
        self.assertTrue(widget._check_is_error("Traceback (most recent call last):\n..."))
        self.assertTrue(widget._check_is_error("Permission denied"))
        self.assertTrue(widget._check_is_error("Command failed"))
        self.assertFalse(widget._check_is_error("all good"))
        self.assertFalse(widget._check_is_error(""))
        widget2 = ToolCallWidget("shell", "cmd", args={"is_error": True})
        self.assertTrue(widget2._check_is_error("even happy text"))

    def test_get_status_color(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.status = "running"
        self.assertEqual(widget._get_status_color(), "#e5c07b")
        widget.status = "error"
        self.assertEqual(widget._get_status_color(), "#e06c75")
        widget.status = "done"
        self.assertEqual(widget._get_status_color(), "#98c379")

    def test_format_compact_dict(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget._format_compact_dict({}), "")
        self.assertEqual(widget._format_compact_dict("nope"), "")
        self.assertEqual(widget._format_compact_dict({"a": 1}), '{a: 1}')
        self.assertEqual(
            widget._format_compact_dict({"this_key_is_way_too_long_for_sure": "value"}),
            '{this_key_is_way_t...: "value"}',
        )
        compact = widget._format_compact_dict({"long_value": "x" * 50})
        self.assertIn("...", compact)
        overflow = widget._format_compact_dict({f"k{i}": "v" * 10 for i in range(10)})
        self.assertIn("...", overflow)
        self.assertEqual(widget._format_compact_dict({"a": {"nested": 1}}), '{a: {"nested": 1}}')
        long_nonstr = widget._format_compact_dict({"k": ["item" * 20]})
        self.assertIn("...", long_nonstr)
        huge_key = widget._format_compact_dict({"k" * 30: "v" * 30})
        self.assertIn("...", huge_key)

    def test_display_names_dict_and_system_tools(self):
        widget = ToolCallWidget("shell", "cmd")
        names = widget.DISPLAY_NAMES
        self.assertEqual(names.get("read"), "Read")
        self.assertEqual(names.get("shell"), "Shell")
        self.assertEqual(names.get("nope", "fallback"), "fallback")
        self.assertEqual(names["create"], "Create")
        with self.assertRaises(KeyError):
            names["unknown_tool"]
        self.assertIn("whatever", names)
        self.assertIn("read", widget.SYSTEM_TOOLS)
        self.assertNotIn("not_a_real_tool_xyz", widget.SYSTEM_TOOLS)
        self.assertNotIn(123, widget.SYSTEM_TOOLS)

    def test_guess_lexer(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget._guess_lexer(""), "text")
        self.assertEqual(widget._guess_lexer("file.py"), "python")
        self.assertEqual(widget._guess_lexer("file.tsx"), "tsx")
        self.assertEqual(widget._guess_lexer("file.unknown"), "unknown")
        self.assertEqual(widget._guess_lexer("https://x.com/file.go"), "go")
        self.assertEqual(widget._guess_lexer("Makefile"), "text")

    def test_lex_block_to_line_texts(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget._lex_block_to_line_texts([], None), [])
        self.assertEqual([t.plain for t in widget._lex_block_to_line_texts(["a", "b"], None)], ["a", "b"])
        from pygments.lexers import get_lexer_by_name

        lexed = widget._lex_block_to_line_texts(["def f():", "    return 1"], get_lexer_by_name("python"))
        self.assertEqual(len(lexed), 2)
        bad = widget._lex_block_to_line_texts(["a"], object())
        self.assertEqual(bad[0].plain, "a")

    def test_lex_block_to_line_texts_pads_and_exception(self):
        widget = ToolCallWidget("shell", "cmd")
        multi = widget._lex_block_to_line_texts(["x = 1", "", "y = 2"], None)
        self.assertEqual(len(multi), 3)
        with patch("widgets.chat_view.pygments.lex", side_effect=Exception("boom")):
            fallback = widget._lex_block_to_line_texts(["z"], object())
        self.assertEqual(fallback[0].plain, "z")
        from pygments.token import Token

        with patch("widgets.chat_view.pygments.lex", return_value=iter([(Token.Text, "only one line")])):
            padded = widget._lex_block_to_line_texts(["a", "b", "c"], object())
        self.assertEqual(len(padded), 3)

    def test_format_plan_display(self):
        widget = ToolCallWidget("update_plan", "plan", args={"plan": []})
        widget._format_plan_display(
            [
                {"step": "done step", "status": "completed"},
                {"text": "in progress step", "status": "in_progress"},
                {"step": "pending step"},
                "not a dict",
            ],
            "Explanation",
        )

    def test_format_read_content(self):
        widget = ToolCallWidget("read", "f.py")
        self.assertEqual(widget._format_read_content("", "f.py"), ("", 1, "f.py"))
        header = "=== Lines 5-10 of 100 in /path/file.py\n  5 | line one\n  6 | line two"
        content, start, path = widget._format_read_content(header, "default.py")
        self.assertEqual(start, 5)
        self.assertEqual(path, "/path/file.py")
        self.assertIn("line one", content)
        with_hint = "line\n[Hint: skip me]"
        content2, _, _ = widget._format_read_content(with_hint, "f.py")
        self.assertNotIn("Hint", content2)

    def test_fix_markdown_nested_lists(self):
        widget = ToolCallWidget("read", "f.py")
        self.assertEqual(widget._fix_markdown_nested_lists(""), "")
        fixed = widget._fix_markdown_nested_lists("  - * item\n1. * numbered")
        self.assertIn("- item", fixed)
        self.assertIn("1. numbered", fixed)

    def test_clean_bash_output(self):
        widget = ToolCallWidget("shell", "cmd")
        text = (
            "[Background Task ID: 42] Command running\n"
            "Command is running in the background\n"
            "You will be notified automatically\n"
            "Use manage_task to inspect\n"
            "real output"
        )
        cleaned = widget._clean_bash_output(text)
        self.assertEqual(cleaned, "real output")
        self.assertEqual(widget._clean_bash_output(""), "")

    def test_append_shell_output(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.is_expanded = False
        widget.append_shell_output("part1\rpart2")
        self.assertEqual(widget.result_text, "part2")
        widget.is_expanded = True
        with patch.object(widget, "render_content") as render_mock:
            widget.append_shell_output("more")
        render_mock.assert_called_once()
        widget.append_bash_output("extra")

    def test_format_code_with_line_numbers(self):
        widget = ToolCallWidget("shell", "cmd")
        formatted = widget._format_code_with_line_numbers("a\nb\nc")
        self.assertIn("[dim] 1 │ [/dim]a", formatted)
        self.assertIn("[dim] 3 │ [/dim]c", formatted)
        empty = widget._format_code_with_line_numbers("")
        self.assertIn("1 │", empty)


class TestToolCallWidgetRendering(unittest.TestCase):
    def _widget(self, tool_type="shell", target="cmd", result_text="", args=None, **kwargs):
        return ToolCallWidget(tool_type, target, result_text=result_text, args=args, **kwargs)

    def test_render_header_update_plan_dict_and_list(self):
        widget = self._widget("update_plan", "plan", args={"plan": {"entries": [
            {"status": "completed"}, {"status": "pending"}
        ]}})
        widget.render_header()
        self.assertIn("[1/2 completed]", str(widget.header_label.render()))

        widget2 = self._widget("update_plan", "plan", args={"plan": [
            {"status": "done"}, {"status": "pending"}, {"step": "x", "status": "in_progress"}
        ]})
        widget2.render_header()
        self.assertIn("[1/3 completed]", str(widget2.header_label.render()))

        widget3 = self._widget("update_plan", "plan", args={"plan": "nope"})
        widget3.render_header()

    def test_render_header_call_mcp(self):
        widget = self._widget("call_mcp", "", args={"server": "colab", "tool": "add_cell", "arguments": {"x": 1}})
        widget.render_header()
        self.assertIn("add_cell", str(widget.header_label.render()))
        self.assertIn("{x: 1}", str(widget.header_label.render()))

        widget2 = self._widget("call_mcp", "", args={})
        widget2.render_header()

        widget3 = self._widget("call_mcp", "server", args={"server": "srv"})
        widget3.render_header()

    def test_render_header_system_tools_and_eager(self):
        widget = self._widget("read", "f.py", args={"path": "f.py"})
        widget.render_header()
        self.assertIn("Read", str(widget.header_label.render()))

        widget2 = self._widget("invoke_subagent", "do stuff", args={"prompt": "hello"})
        widget2.render_header()

        widget3 = self._widget("ask_user", "", args={"question": "q?"})
        widget3.render_header()

        widget4 = self._widget("manage_task", "", args={"task_id": "t1"})
        widget4.render_header()

        widget5 = self._widget("my_custom_thing", "t", args={"a": 1})
        widget5.render_header()

        widget6 = self._widget("my_custom_thing", "target")
        widget6.render_header()

        widget7 = self._widget("mcp_search", "", args={"query": "x"})
        widget7.render_header()

    def test_render_header_get_mcp_schema(self):
        widget = self._widget("get_mcp_schema", "srv", args={"server": "srv", "tool": "tool"})
        widget.render_header()

    def test_render_header_get_mcp_schema_via_call_mcp(self):
        widget = self._widget("call_mcp", "srv", args={"tool": "t", "server": "srv", "arguments": {}})
        widget.tool_type = "get_mcp_schema"
        widget.canonical_tool = "call_mcp"
        widget.render_header()

    def test_set_result_shell_background(self):
        widget = self._widget("shell", "cmd")
        widget.set_result("Command is running in the background", is_error=False)
        self.assertEqual(widget.status, "running")

    def test_set_result_error_and_nonexpandable(self):
        widget = self._widget("shell", "cmd")
        widget.is_expanded = True
        widget.set_result("Error: nope", is_error=True)
        self.assertEqual(widget.status, "error")

        widget2 = self._widget("read", "f.py")
        widget2.is_expanded = True
        with patch.object(widget2, "render_content") as render_mock:
            widget2.set_result("content")
        self.assertFalse(widget2.is_expanded)
        render_mock.assert_not_called()

    def test_on_click_invoke_subagent_pushes_screen(self):
        widget = self._widget("invoke_subagent", "prompt", args={"task_id": "abc"})
        event = MagicMock()
        with patch("widgets.screens.subagent_screen.SubagentViewScreen") as screen_cls, patch.object(
            ToolCallWidget, "app", new_callable=PropertyMock
        ) as app_prop:
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        screen_cls.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_manage_task_and_expandable(self):
        widget = self._widget("manage_task", "t", args={"description": "desc"})
        event = MagicMock()
        with patch("widgets.screens.subagent_screen.SubagentViewScreen"), patch.object(
            ToolCallWidget, "app", new_callable=PropertyMock
        ) as app_prop:
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        event.stop.assert_called_once()

    def test_on_click_exception_is_suppressed(self):
        widget = self._widget("invoke_subagent", "prompt", args={"task_id": "abc"})
        event = MagicMock()
        with patch("widgets.screens.subagent_screen.SubagentViewScreen", side_effect=Exception("boom")), patch.object(
            ToolCallWidget, "app", new_callable=PropertyMock
        ) as app_prop:
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        event.stop.assert_called_once()

        widget2 = self._widget("shell", "cmd")
        event2 = MagicMock()
        widget2.on_click(event2)
        self.assertTrue(widget2.is_expanded)
        event2.stop.assert_called_once()

        widget3 = self._widget("read", "f.py")
        event3 = MagicMock()
        widget3.on_click(event3)
        event3.stop.assert_not_called()

    def test_toggle_expanded(self):
        widget = self._widget("shell", "cmd")
        widget.is_expanded = False
        with patch.object(widget, "render_content") as render_mock:
            widget.toggle_expanded()
        render_mock.assert_called_once()
        self.assertTrue(widget.is_expanded)

        widget2 = self._widget("read", "f.py")
        widget2.toggle_expanded()
        self.assertFalse(widget2.is_expanded)


class TestToolCallWidgetRenderContent(unittest.TestCase):
    def _widget(self, tool_type, result_text="", args=None):
        return ToolCallWidget(tool_type, "target", result_text=result_text, args=args)

    def test_render_content_create_branches(self):
        # error
        w = self._widget("create", "Error: denied", args={})
        w.render_content()

        # diff in result
        w2 = self._widget("create", "@@ -1,1 +1,1 @@\n+new\n", args={"path": "f.py"})
        w2.render_content()

        # content in args
        w3 = self._widget("create", "", args={"content": "print(1)", "path": "f.py"})
        w3.render_content()

        # content from file
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "file.py")
            with open(fpath, "w") as f:
                f.write("print('file')\n")
            w4 = self._widget("create", "", args={"path": fpath})
            w4.render_content()

        # no content anywhere
        w5 = self._widget("create", "", args={})
        w5.render_content()

    def test_render_content_create_diff_without_hunk(self):
        w = self._widget("create", "file.py updated", args={"content": "line1\nline2", "path": "f.py"})
        w.render_content()
        self.assertTrue(w.content_widget.display)

    def test_render_content_create_builds_diff_from_args(self):
        w = self._widget("create", "file.py updated successfully", args={"content": "new\nlines", "path": "f.py"})
        w.render_content()
        self.assertTrue(w.content_widget.display)

    def test_render_content_create_file_read_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "file.py")
            with open(fpath, "w") as f:
                f.write("print(1)\n")
            w = self._widget("create", "", args={"path": fpath})
            with patch("builtins.open", side_effect=Exception("boom")):
                w.render_content()

    def test_render_content_create_syntax_exception_fallback(self):
        w = self._widget("create", "", args={"content": "print(1)", "path": "f.py"})
        with patch("widgets.chat_view.TransparentSyntax", side_effect=Exception("boom")):
            w.render_content()
        self.assertTrue(w.content_widget.display)

    def test_render_content_edit_branches(self):
        w = self._widget("edit", "Error: boom", args={})
        w.render_content()

        w2 = self._widget("edit", "@@ -1,1 +1,1 @@\n-a\n+b\n", args={"path": "f.py"})
        w2.render_content()

        w3 = self._widget("edit", "", args={
            "path": "f.py",
            "ReplacementChunks": [
                {"TargetContent": "old", "ReplacementContent": "new", "StartLine": 2},
            ],
        })
        w3.render_content()

        w4 = self._widget("edit", "", args={"old_string": "old", "new_string": "new", "StartLine": 1})
        w4.render_content()

        w5 = self._widget("edit", "", args={})
        w5.render_content()
        self.assertIn("(No diff)", str(w5.content_widget.render()))

        w6 = self._widget("edit", "no diff text", args={})
        w6.render_content()

    def test_render_content_update_plan(self):
        w = self._widget("update_plan", "Error: nope", args={})
        w.render_content()
        w2 = self._widget("update_plan", "", args={"plan": [{"step": "s", "status": "in_progress"}]})
        w2.render_content()

    def test_render_content_web_fetch(self):
        w = self._widget("web_fetch", "error: failed", args={"url": "http://x"})
        w.render_content()

        w2 = self._widget("web_fetch", "print(1)\nprint(2)", args={"url": "http://x/code.py"})
        w2.render_content()

        w3 = self._widget("web_fetch", "# Title\n\nbody", args={"url": "http://x/page.md"})
        w3.render_content()

        w4 = self._widget("web_fetch", "<html><body>hi</body></html>", args={"url": "http://x/page.html", "raw": True})
        w4.render_content()

        w5 = self._widget("web_fetch", "", args={"url": "http://x/page.md"})
        w5.render_content()

    def test_render_content_web_fetch_error_and_empty_code(self):
        w = self._widget("web_fetch", "Error: could not fetch", args={"url": "http://x/code.py"})
        with patch.object(w.content_widget, "update") as upd:
            w.render_content()
        upd.assert_called_once()
        self.assertTrue(w.content_widget.display)
        self.assertFalse(w.md_widget.display)

        w2 = self._widget("web_fetch", "", args={"url": "http://x/code.py", "raw": True})
        w2.render_content()

        w3 = self._widget("web_fetch", "def f():\n    pass", args={"url": "http://x/code.py", "raw": True})
        with patch("widgets.chat_view.TransparentSyntax", side_effect=Exception("boom")):
            w3.render_content()

    def test_render_content_read_error_and_fallback(self):
        w = self._widget("read", "Error: file missing", args={"path": "nope.py"})
        with patch.object(w.content_widget, "update") as upd:
            w.render_content()
        upd.assert_called_once()
        self.assertTrue(w.content_widget.display)
        self.assertFalse(w.md_widget.display)

        w2 = self._widget("read", "", args={"path": "missing_file.py"})
        w2.render_content()

        w3 = self._widget("read", "def f():\n    return 1", args={"path": "f.py"})
        with patch("widgets.chat_view.TransparentSyntax", side_effect=Exception("boom")):
            w3.render_content()
        self.assertTrue(w3.content_widget.display)

    def test_render_content_read_file_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "notes.md")
            with open(fpath, "w") as f:
                f.write("## From file\n")
            w = self._widget("read", "", args={"path": fpath})
            with patch("builtins.open", side_effect=Exception("boom")):
                w.render_content()

    def test_render_content_get_mcp_schema_exception(self):
        w = self._widget("get_mcp_schema", '{"server": "s"}', args={"server": "srv", "tool": "tool"})
        with patch("widgets.chat_view.TransparentSyntax", side_effect=Exception("boom")):
            w.render_content()

    def test_render_content_read_branches(self):
        w = self._widget("read", "Error: cannot read", args={"path": "f.py"})
        w.render_content()

        w2 = self._widget("read", "# Doc\n\ncontent", args={"path": "doc.md"})
        w2.render_content()

        w3 = self._widget("read", "def f():\n    return 1", args={"path": "f.py"})
        w3.render_content()

        w4 = self._widget("read", "", args={})
        w4.render_content()

        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "notes.md")
            with open(fpath, "w") as f:
                f.write("## From file\n")
            w5 = self._widget("read", "", args={"path": fpath})
            w5.render_content()

    def test_render_content_read_file_fallback_from_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            fpath = os.path.join(tmp, "script.py")
            with open(fpath, "w") as f:
                f.write("print('disk')\n")
            w = self._widget("read", "", args={"path": fpath})
            w.render_content()
            self.assertTrue(w.content_widget.display)

    def test_render_content_shell_branches(self):
        w = self._widget("shell", "some output\nlines")
        w.render_content()
        self.assertTrue(w.content_widget.display)

        w2 = self._widget("shell", "")
        with patch.object(ToolCallWidget, "app", new_callable=PropertyMock, return_value=MagicMock(background_tasks=[])), patch.object(
            w2.content_widget, "update"
        ) as upd:
            w2.render_content()
        upd.assert_called_once_with("(No output)")

        w3 = self._widget("shell", "[Background Task ID: 7] running")
        task = MagicMock()
        task.task_id = "7"
        task.is_running = True
        with patch.object(ToolCallWidget, "app", new_callable=PropertyMock, return_value=MagicMock(background_tasks=[task])), patch.object(
            w3.content_widget, "update"
        ) as upd:
            w3.render_content()
        self.assertIn("Running command", str(upd.call_args.args[0]))

        w4 = self._widget("shell", "")
        with patch.object(ToolCallWidget, "app", new_callable=PropertyMock, return_value=MagicMock(background_tasks=[])):
            w4.render_content()

    def test_render_content_get_mcp_schema(self):
        w = self._widget("get_mcp_schema", '{"server": "s"}', args={"server": "srv", "tool": "tool"})
        w.render_content()

    def test_render_content_call_mcp(self):
        w = self._widget("call_mcp", '{"ok": true}', args={"server": "s"})
        w.render_content()
        self.assertTrue(w.content_widget.display)

        w2 = self._widget("call_mcp", "plain result", args={"server": "s"})
        w2.render_content()

        w3 = self._widget("call_mcp_tool", "", args={})
        w3.render_content()

    def test_render_content_other_tools(self):
        w = self._widget("some_tool", '{"data": [1, 2]}')
        w.render_content()
        w2 = self._widget("some_tool", "plain")
        w2.render_content()

    def test_render_content_exception_is_suppressed(self):
        w = self._widget("create", "")
        with patch.object(w, "_clean_markup_text", side_effect=Exception("boom")):
            w.render_content()


if __name__ == "__main__":
    unittest.main()
