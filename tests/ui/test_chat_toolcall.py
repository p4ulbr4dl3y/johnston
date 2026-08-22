import os
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from widgets.chat_toolcall import ToolCallWidget


class TestToolCallWidgetHelpers(unittest.TestCase):
    def test_is_expandable_variants(self):
        self.assertFalse(ToolCallWidget("read", "f.py").is_expandable())
        self.assertFalse(ToolCallWidget("web_fetch", "http://x").is_expandable())
        self.assertTrue(ToolCallWidget("shell", "cmd").is_expandable())
        self.assertTrue(ToolCallWidget("create", "f.py").is_expandable())
        self.assertTrue(ToolCallWidget("custom_tool", "x").is_expandable())

    def test_init_normalizes_target_and_status(self):
        widget = ToolCallWidget("read", "a\n\n b \t c")
        self.assertEqual(widget.target, "a b c")
        self.assertEqual(widget.status, "running")
        # Status is a structured input, never parsed from result text: a plain
        # "Error:" line stays done unless a status/is_error is passed.
        widget2 = ToolCallWidget("shell", "cmd", result_text="Error: failed")
        self.assertEqual(widget2.status, "done")
        widget2b = ToolCallWidget("shell", "cmd", result_text="ERR: execute 'shell': boom")
        self.assertEqual(widget2b.status, "done")
        widget3 = ToolCallWidget("read", "f.py", result_text="ok")
        self.assertEqual(widget3.status, "done")
        widget4 = ToolCallWidget("read", "f.py", result_text="ERR: boom", status="error")
        self.assertEqual(widget4.status, "error")
        widget5 = ToolCallWidget("read", "f.py", result_text="Error: boom")
        self.assertEqual(widget5.status, "done")

    def test_clean_hints_and_markup(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget._clean_hints_for_ui("text\n[Hint: do x]"), "text")
        self.assertEqual(widget._clean_hints_for_ui("text [Hint: inline] rest"), "text")
        self.assertEqual(widget._clean_hints_for_ui(""), "")
        self.assertEqual(widget._clean_markup_text("[b]bold[/b]\n[Hint: nope]"), "[b]bold[/b]")

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

    def test_strip_hints_and_background_truncation(self):
        from widgets.chat_toolcall import _strip_hints_and_background

        # Shell truncation header with log path & LLM hint
        header = (
            "[Output truncated: showing last 4000 chars (lines 256–338 of 338). "
            "Full log: /Users/yegor/.johnston/logs/shell-c14f.log. "
            "Pipe command to grep/head, or read full log.]\n...\ndiff content"
        )
        cleaned = _strip_hints_and_background(header)
        self.assertEqual(
            cleaned,
            "[Output truncated: showing last 4000 chars | Log: /Users/yegor/.johnston/logs/shell-c14f.log]\n...\ndiff content",
        )

        # Footer with log path
        footer = (
            "diff content\n... [Output truncated: showing first 8000 chars (lines 1-100 of 500). "
            "Full log: /path/to/log. Use read to inspect.]"
        )
        cleaned_footer = _strip_hints_and_background(footer)
        self.assertEqual(
            cleaned_footer,
            "diff content\n... [Output truncated: showing first 8000 chars | Log: /path/to/log]",
        )

        # Truncated without log
        recent = "[Output truncated: showing recent output]\nsome output"
        self.assertEqual(_strip_hints_and_background(recent), "[Output truncated: showing recent output]\nsome output")

        # Double cleaning / idempotency
        double_cleaned = _strip_hints_and_background(cleaned)
        self.assertEqual(double_cleaned, cleaned)


    def test_format_json_result(self):
        widget = ToolCallWidget("read", "")
        self.assertIsNone(widget._format_json_result(""))
        self.assertIsNone(widget._format_json_result("   "))
        result = widget._format_json_result('{"x": 1}')
        self.assertIsNotNone(result)
        truncated = widget._format_json_result('{"x": 1}\n... [Output truncated at 100 chars]')
        self.assertIsNotNone(truncated)
        self.assertIsNone(widget._format_json_result("plain text"))

    def test_is_error(self):
        widget = ToolCallWidget("shell", "cmd")
        # Render helper drives the "error branch" strictly off the structured card status
        widget.status = "error"
        self.assertTrue(widget._is_error("success output"))
        widget.status = "cancelled"
        self.assertTrue(widget._is_error("partial output"))
        widget.status = "done"
        self.assertFalse(widget._is_error("all good"))
        self.assertFalse(widget._is_error("Error: boom"))
        self.assertFalse(widget._is_error(""))

    def test_get_status_color(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.status = "running"
        self.assertEqual(widget._get_status_color(), "#e5c07b")
        widget.status = "error"
        self.assertEqual(widget._get_status_color(), "#e06c75")
        widget.status = "cancelled"
        self.assertEqual(widget._get_status_color(), "#e06c75")
        widget.status = "done"
        self.assertEqual(widget._get_status_color(), "#98c379")

    def test_mark_cancelled_only_running(self):
        widget = ToolCallWidget("shell", "cmd")
        self.assertEqual(widget.status, "running")
        widget.mark_cancelled()
        self.assertEqual(widget.status, "cancelled")
        self.assertIn("interrupted or cancelled", widget.result_text)

    def test_mark_cancelled_noop_when_not_running(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.set_result("done output")
        self.assertEqual(widget.status, "done")
        widget.mark_cancelled()
        # A completed tool must not be flipped to cancelled retroactively.
        self.assertEqual(widget.status, "done")
        self.assertEqual(widget.result_text, "done output")

    def test_mark_cancelled_noop_when_error(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.set_result("Error: boom", is_error=True)
        self.assertEqual(widget.status, "error")
        widget.mark_cancelled()
        self.assertEqual(widget.status, "error")

    def test_format_compact_dict(self):
        from core.infrastructure.presentation.tool_display import format_compact_dict

        self.assertEqual(format_compact_dict({}), "")
        self.assertEqual(format_compact_dict("nope"), "")
        self.assertEqual(format_compact_dict({"a": 1}), "{a: 1}")
        self.assertEqual(
            format_compact_dict({"this_key_is_way_too_long_for_sure": "value"}),
            '{this_key_is_way_t...: "value"}',
        )
        compact = format_compact_dict({"long_value": "x" * 50})
        self.assertIn("...", compact)
        overflow = format_compact_dict({f"k{i}": "v" * 10 for i in range(10)})
        self.assertIn("...", overflow)
        self.assertEqual(format_compact_dict({"a": {"nested": 1}}), '{a: {"nested": 1}}')
        long_nonstr = format_compact_dict({"k": ["item" * 20]})
        self.assertIn("...", long_nonstr)
        huge_key = format_compact_dict({"k" * 30: "v" * 30})
        self.assertIn("...", huge_key)

    def test_display_names_dict_and_system_tools(self):
        widget = ToolCallWidget("shell", "cmd")
        names = widget.DISPLAY_NAMES
        self.assertEqual(names.get("read"), "Read")
        self.assertEqual(names.get("shell"), "Shell")
        self.assertEqual(names.get("nope", "fallback"), "fallback")
        self.assertEqual(names.get("create"), "Create")
        self.assertEqual(names.get("unknown_tool"), None)
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

    def test_render_header_update_plan_list(self):
        widget = self._widget(
            "update_plan", "plan", args={"plan": [{"status": "completed"}, {"status": "pending"}]}
        )
        widget.render_header()
        self.assertIn("[1/2 completed]", str(widget.header_label.render()))

        widget2 = self._widget(
            "update_plan",
            "plan",
            args={"plan": [{"status": "completed"}, {"status": "pending"}, {"step": "x", "status": "in_progress"}]},
        )
        widget2.render_header()
        self.assertIn("[1/3 completed]", str(widget2.header_label.render()))

        widget3 = self._widget("update_plan", "plan", args={"plan": "nope"})
        widget3.render_header()
        self.assertIn("UpdatePlan()", str(widget3.header_label.render()))

        widget4 = self._widget("update_plan", "plan", args={})
        widget4.render_header()
        self.assertIn("UpdatePlan()", str(widget4.header_label.render()))

    def test_render_header_system_tools(self):
        widget = self._widget("read", "f.py", args={"path": "f.py"})
        widget.render_header()
        self.assertIn("Read", str(widget.header_label.render()))

        widget2 = self._widget("invoke_subagent", "do stuff", args={"prompt": "hello"})
        widget2.render_header()

        widget3 = self._widget("ask_user", "", args={"questions": [{"question": "q?", "options": []}]})
        widget3.render_header()

        widget4 = self._widget("manage_shell", "", args={"task_id": "t1"})
        widget4.render_header()

        widget5 = self._widget("my_custom_thing", "t", args={"a": 1})
        widget5.render_header()

        widget6 = self._widget("my_custom_thing", "target")
        widget6.render_header()

        widget7 = self._widget("mcp_search", "", args={"query": "x"})
        widget7.render_header()

    def test_set_result_shell_background(self):
        widget = self._widget("shell", "cmd")
        # Status comes from the event: background text alone doesn't set running.
        widget.set_result("Command is running in the background")
        self.assertEqual(widget.status, "done")
        # Structured RUNNING status flips the card yellow.
        widget.set_result("Command is running in the background", status="running")
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
        widget = self._widget("invoke_subagent", "prompt", args={"session_id": "abc"})
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        screen_cls.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_manage_shell_no_longer_clickable(self):
        widget = self._widget("manage_shell", "t", args={"description": "desc"})
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen"),
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        event.stop.assert_not_called()

    def test_on_click_ask_user_resumes_pending(self):
        widget = self._widget("ask_user", "q", args={"questions": [{"question": "Q", "options": ["A"]}]})
        event = MagicMock()
        with (
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            setattr(app, "_pending_ask_user", MagicMock())
            app_prop.return_value = app
            widget.on_click(event)
        app._pending_ask_user.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_ask_user_expands_inline_when_completed(self):
        widget = self._widget(
            "ask_user",
            "q",
            args={"questions": [{"question": "Q1", "options": ["A", "B"]}]},
            result_text="Question: Q1\nAnswer: A",
        )
        event = MagicMock()
        with (
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            setattr(app, "_pending_ask_user", None)
            app_prop.return_value = app
            widget.on_click(event)
        self.assertTrue(widget.is_expanded)
        self.assertTrue(widget.is_expandable())
        event.stop.assert_called_once()

    def test_ask_user_not_expandable_without_answers(self):
        widget = self._widget("ask_user", "q", args={"questions": [{"question": "Q1", "options": ["A"]}]})
        self.assertFalse(widget.is_expandable())

    def test_parse_ask_user_answers_multi_question(self):
        widget = self._widget(
            "ask_user",
            "q",
            args={"questions": [{"question": "Q1", "options": ["A", "B"]}, {"question": "Q2", "options": ["C"]}]},
            result_text="Question: Q1\nAnswer: A\nQuestion: Q2\nAnswer: C",
        )
        qs = widget._parse_ask_user_questions()
        self.assertEqual(
            widget._parse_ask_user_answers(qs), {0: {"answer": "A"}, 1: {"answer": "C"}}
        )

    def test_parse_ask_user_answer_containing_question_marker(self):
        widget = self._widget(
            "ask_user",
            "q",
            args={"questions": [{"question": "Q1", "options": ["A"]}, {"question": "Q2", "options": ["C"]}]},
            result_text="Question: Q1\nAnswer: Question: foo\nQuestion: Q2\nAnswer: C",
        )
        qs = widget._parse_ask_user_questions()
        self.assertEqual(
            widget._parse_ask_user_answers(qs), {0: {"answer": "Question: foo"}, 1: {"answer": "C"}}
        )

    def test_parse_ask_user_missing_answer_defaults_no_response(self):
        widget = self._widget(
            "ask_user",
            "q",
            args={"questions": [{"question": "Q1", "options": ["A"]}, {"question": "Q2", "options": ["C"]}]},
            result_text="Question: Q1\nAnswer: A",
        )
        qs = widget._parse_ask_user_questions()
        self.assertEqual(
            widget._parse_ask_user_answers(qs), {0: {"answer": "A"}, 1: {"answer": "(No response)"}}
        )

    def test_parse_ask_user_cancelled_has_no_answers(self):
        widget = self._widget(
            "ask_user",
            "q",
            args={"questions": [{"question": "Q1", "options": ["A"]}]},
            result_text="Cancelled by user.",
        )
        qs = widget._parse_ask_user_questions()
        self.assertEqual(widget._parse_ask_user_answers(qs), {})
        self.assertFalse(widget.is_expandable())

    def test_parse_ask_user_questions(self):
        widget = self._widget(
            "ask_user",
            "q",
            args={"questions": [{"question": "F", "options": ["X", "Y"]}]},
            result_text="Question: F\nAnswer: X",
        )
        qs = widget._parse_ask_user_questions()
        self.assertEqual(qs, [{"question": "F", "options": ["X", "Y"]}])
        self.assertEqual(widget._parse_ask_user_answers(qs), {0: {"answer": "X"}})

    def test_on_click_exception_is_suppressed(self):
        widget = self._widget("invoke_subagent", "prompt", args={"session_id": "abc"})
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen", side_effect=Exception("boom")),
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
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
        with patch("widgets.chat_toolcall.TransparentSyntax", side_effect=Exception("boom")):
            w.render_content()
        self.assertTrue(w.content_widget.display)

    def test_render_content_edit_branches(self):
        w = self._widget("edit", "Error: boom", args={})
        w.render_content()

        w2 = self._widget("edit", "@@ -1,1 +1,1 @@\n-a\n+b\n", args={"path": "f.py"})
        w2.render_content()

        w3 = self._widget(
            "edit",
            "",
            args={
                "path": "f.py",
                "ReplacementChunks": [
                    {"TargetContent": "old", "ReplacementContent": "new", "StartLine": 2},
                ],
            },
        )
        w3.render_content()

        w4 = self._widget("edit", "", args={"old_str": "old", "new_str": "new", "start_line": 1})
        w4.render_content()

        w5 = self._widget("edit", "", args={})
        w5.render_content()
        self.assertIn("(No diff)", str(w5.content_widget.render()))

        w6 = self._widget("edit", "no diff text", args={})
        w6.render_content()

    def test_render_content_update_plan(self):
        w = self._widget("update_plan", "Error: nope", args={})
        w.render_content()
        w2 = self._widget(
            "update_plan",
            "",
            args={"plan": [{"step": "s", "status": "in_progress"}, {"step": "done step", "status": "completed"}]},
        )
        w2.render_content()
        plan_text = w2._format_plan_display(
            [{"step": "s", "status": "in_progress"}, {"step": "done step", "status": "completed"}], "explanation"
        )
        self.assertIn("s", plan_text.plain)
        self.assertIn("done step", plan_text.plain)

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
        with patch("widgets.chat_toolcall.TransparentSyntax", side_effect=Exception("boom")):
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
        with patch("widgets.chat_toolcall.TransparentSyntax", side_effect=Exception("boom")):
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

        from core.infrastructure.tasks.manager import TaskManager

        empty_mgr = TaskManager()
        w2 = self._widget("shell", "")
        with (
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock, return_value=MagicMock(task_manager=empty_mgr)),
            patch.object(w2.content_widget, "update") as upd,
        ):
            w2.render_content()
        upd.assert_called_once_with("(No output)")

        w3 = self._widget("shell", "[Background Task ID: 7] running")
        task = MagicMock()
        task.id = "7"
        task.task_id = "7"
        task.kind = "shell"
        task.is_running = True
        running_mgr = TaskManager()
        running_mgr.register(task)
        with (
            patch.object(
                ToolCallWidget, "app", new_callable=PropertyMock, return_value=MagicMock(task_manager=running_mgr)
            ),
            patch.object(w3.content_widget, "update") as upd,
        ):
            w3.render_content()
        self.assertIn("Running command", str(upd.call_args.args[0]))

        w4 = self._widget("shell", "")
        with patch.object(
            ToolCallWidget, "app", new_callable=PropertyMock, return_value=MagicMock(task_manager=empty_mgr)
        ):
            w4.render_content()

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
