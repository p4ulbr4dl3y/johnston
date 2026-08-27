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

    def test_format_truncation_for_ui(self):
        from widgets.chat_toolcall import _format_truncation_for_ui

        # Shell truncation header with log path & LLM hint
        header = (
            "[Output truncated: showing last 4000 chars (lines 256–338 of 338). "
            "Full log: /Users/yegor/.johnston/logs/shell-c14f.log. "
            "Pipe command to grep/head, or read full log.]\n...\ndiff content"
        )
        cleaned = _format_truncation_for_ui(header)
        self.assertEqual(
            cleaned,
            "[Output truncated: showing last 4000 chars | Log: /Users/yegor/.johnston/logs/shell-c14f.log]\n...\ndiff content",
        )

        # Footer with log path
        footer = (
            "diff content\n... [Output truncated: showing first 8000 chars (lines 1-100 of 500). "
            "Full log: /path/to/log. Use read to inspect.]"
        )
        cleaned_footer = _format_truncation_for_ui(footer)
        self.assertEqual(
            cleaned_footer,
            "diff content\n... [Output truncated: showing first 8000 chars | Log: /path/to/log]",
        )

        # Truncated without log
        recent = "[Output truncated: showing recent output]\nsome output"
        self.assertEqual(_format_truncation_for_ui(recent), "[Output truncated: showing recent output]\nsome output")

        # Double cleaning / idempotency
        double_cleaned = _format_truncation_for_ui(cleaned)
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

    def test_clean_bash_output(self):
        widget = ToolCallWidget("shell", "cmd")
        text = (
            "real output\n"
            "... [Output truncated: showing last 4000 chars (lines 1-100 of 500). "
            "Full log: /path/to.log. Use read to inspect.]\n"
            "[Hint: foo]"
        )
        cleaned = widget._clean_bash_output(text)
        self.assertIn("real output", cleaned)
        self.assertIn("Log: /path/to.log", cleaned)
        self.assertNotIn("Hint:", cleaned)
        self.assertEqual(widget._clean_bash_output(""), "")

    def test_append_shell_output(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.is_expanded = False
        widget.append_shell_output("part1\rpart2")
        self.assertEqual(widget.result_text, "part2")
        widget.is_expanded = True
        with patch.object(widget, "render_content") as render_mock, patch.object(widget, "_scroll_if_needed") as scroll_mock:
            widget.append_shell_output("more")
        render_mock.assert_called_once()
        scroll_mock.assert_called_once()

    def test_on_unmount_cancels_shell_timer(self):
        widget = ToolCallWidget("shell", "cmd")
        handle = MagicMock()
        widget._shell_update_handle = handle
        widget.on_unmount()
        handle.cancel.assert_called_once()
        self.assertIsNone(widget._shell_update_handle)

    def test_toggle_expanded_calls_scroll_if_needed_on_expand(self):
        widget = ToolCallWidget("shell", "cmd")
        widget.is_expanded = False
        with patch.object(widget, "_scroll_to_widget") as scroll_mock:
            widget.toggle_expanded()
            self.assertTrue(widget.is_expanded)
            scroll_mock.assert_called_once_with(top=False)

    def test_render_content_passes_force_when_should_scroll_on_render(self):
        widget = ToolCallWidget("shell", "cmd", result_text="output")
        widget.is_expanded = True
        widget._should_scroll_on_render = True
        with patch.object(widget, "_scroll_if_needed") as scroll_mock:
            widget.render_content()
            scroll_mock.assert_called_once_with(force=True)
            self.assertFalse(widget._should_scroll_on_render)

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
        self.assertIn("1/2 done", str(widget.header_label.render()))

        widget2 = self._widget(
            "update_plan",
            "plan",
            args={"plan": [{"status": "completed"}, {"status": "pending"}, {"step": "x", "status": "in_progress"}]},
        )
        widget2.render_header()
        self.assertIn("1/3: x", str(widget2.header_label.render()))

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
        mock_store = MagicMock()
        mock_store.find_session_by_description_or_id.return_value = MagicMock(status="running")
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        screen_cls.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_invoke_subagent_finished_toggles_expanded(self):
        widget = self._widget("invoke_subagent", "prompt", args={"session_id": "abc"}, result_text="Done work")
        event = MagicMock()
        mock_store = MagicMock()
        mock_store.find_session_by_description_or_id.return_value = MagicMock(status="completed")
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        screen_cls.assert_not_called()
        self.assertTrue(widget.is_expanded)
        event.stop.assert_called_once()

    def test_on_click_invoke_subagent_session_not_found_notifies(self):
        widget = self._widget("invoke_subagent", "prompt", args={"session_id": "missing"})
        event = MagicMock()
        mock_store = MagicMock()
        mock_store.find_session_by_description_or_id.return_value = None
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        screen_cls.assert_not_called()
        app.notify.assert_called_once_with("Subagent session not found", severity="warning")
        event.stop.assert_called_once()

    def test_on_click_invoke_subagent_error_not_clickable(self):
        widget = self._widget("invoke_subagent", "prompt", args={"session_id": "abc"})
        widget.set_result("Error: launch failed", status="error")
        self.assertFalse(widget.is_clickable_header())
        self.assertNotIn("tool-header-expandable", widget.header_label.classes)
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        screen_cls.assert_not_called()
        event.stop.assert_not_called()

    def test_on_click_invoke_subagent_cancelled_not_clickable(self):
        widget = self._widget("invoke_subagent", "prompt", args={"session_id": "abc"})
        widget.mark_cancelled()
        self.assertFalse(widget.is_clickable_header())
        self.assertNotIn("tool-header-expandable", widget.header_label.classes)
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        screen_cls.assert_not_called()
        event.stop.assert_not_called()

    def test_on_click_manage_shell_non_list_not_clickable(self):
        widget = self._widget("manage_shell", "t", args={"action": "kill", "task_id": "1"})
        self.assertFalse(widget.is_clickable_header())
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.tasks.ShellTasksScreen"),
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app_prop.return_value = MagicMock()
            widget.on_click(event)
        event.stop.assert_not_called()

    def test_on_click_manage_shell_list_with_active_tasks_opens_shell_tasks_screen(self):
        widget = self._widget("manage_shell", "list", args={"action": "list"})
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        dummy_task = MagicMock(kind="shell", is_background=True, is_running=True, session_id=None)
        with (
            patch("widgets.presentation.screens.tasks.ShellTasksScreen") as shell_screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.task_manager = [dummy_task]
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        shell_screen_cls.assert_called_once()
        app.push_screen.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_manage_shell_list_without_active_tasks_toggles_expanded(self):
        widget = self._widget("manage_shell", "list", args={"action": "list"})
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        with (
            patch("widgets.presentation.screens.tasks.ShellTasksScreen") as shell_screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.task_manager = []
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        shell_screen_cls.assert_not_called()
        self.assertTrue(widget.is_expanded)
        event.stop.assert_called_once()

    def test_on_click_manage_subagent_list_with_active_opens_subagents_screen(self):
        widget = self._widget("manage_subagent", "list", args={"action": "list"})
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        mock_store = MagicMock()
        mock_sub = MagicMock(status="running")
        mock_store.children.return_value = [mock_sub]
        with (
            patch("widgets.presentation.screens.tasks.SubagentsScreen") as subagents_screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = "parent_1"
            app_prop.return_value = app
            widget.on_click(event)
        subagents_screen_cls.assert_called_once()
        app.push_screen.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_manage_subagent_list_without_active_toggles_expanded(self):
        widget = self._widget("manage_subagent", "list", args={"action": "list"})
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        mock_store = MagicMock()
        mock_store.children.return_value = []
        with (
            patch("widgets.presentation.screens.tasks.SubagentsScreen") as subagents_screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = "parent_1"
            app_prop.return_value = app
            widget.on_click(event)
        subagents_screen_cls.assert_not_called()
        self.assertTrue(widget.is_expanded)
        event.stop.assert_called_once()

    def test_on_click_manage_subagent_with_session_id_opens_subagent_view_screen(self):
        widget = self._widget("manage_subagent", "sess_123", args={"action": "send_message", "session_id": "sess_123"})
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        mock_store = MagicMock()
        mock_store.find_session_by_description_or_id.return_value = MagicMock(status="running")
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as subagent_view_screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        subagent_view_screen_cls.assert_called_once_with("sess_123")
        app.push_screen.assert_called_once()
        event.stop.assert_called_once()

    def test_on_click_manage_subagent_session_not_found_notifies(self):
        widget = self._widget("manage_subagent", "sess_123", args={"action": "send_message", "session_id": "sess_123"})
        self.assertTrue(widget.is_clickable_header())
        event = MagicMock()
        mock_store = MagicMock()
        mock_store.find_session_by_description_or_id.return_value = None
        with (
            patch("widgets.presentation.screens.subagent_screen.SubagentViewScreen") as subagent_view_screen_cls,
            patch.object(ToolCallWidget, "app", new_callable=PropertyMock) as app_prop,
        ):
            app = MagicMock()
            app.sm = mock_store
            app.current_session_id = None
            app_prop.return_value = app
            widget.on_click(event)
        subagent_view_screen_cls.assert_not_called()
        app.notify.assert_called_once_with("Subagent session not found", severity="warning")
        event.stop.assert_called_once()

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
    def _widget(self, tool_type, result_text="", args=None, status=None):
        return ToolCallWidget(tool_type, "target", result_text=result_text, args=args, status=status)

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

    def test_render_content_generic_tool(self):
        w = self._widget("custom_tool", "output text", args={})
        w.render_content()
        self.assertTrue(w.content_widget.display)

        w2 = self._widget("custom_tool", '{"key": "value"}', args={})
        w2.render_content()
        self.assertTrue(w2.content_widget.display)

        w3 = self._widget("custom_tool", "", args={})
        w3.render_content()
        self.assertTrue(w3.content_widget.display)

    def test_render_content_shell_branches(self):
        w = self._widget("shell", "some output\nlines")
        w.render_content()
        self.assertTrue(w.content_widget.display)

        w2 = self._widget("shell", "", status="done")
        with patch.object(w2.content_widget, "update") as upd:
            w2.render_content()
        upd.assert_called_once_with("(No output)")

        w3 = self._widget("shell", "", status="running")
        with patch.object(w3.content_widget, "update") as upd:
            w3.render_content()
        upd.assert_called_once_with("(No output)")

    def test_render_content_other_tools(self):
        w = self._widget("some_tool", '{"data": [1, 2]}')
        w.render_content()
        w2 = self._widget("some_tool", "plain")
        w2.render_content()

    def test_render_content_exception_is_suppressed(self):
        w = self._widget("create", "")
        with patch.object(w, "_clean_markup_text", side_effect=Exception("boom")):
            w.render_content()

    def test_mcp_tool_expansion_forces_scroll(self):
        w = self._widget("codegraph_explore", "**Exploration: cached_json_read**\n\nFound symbols")
        w.is_mcp = True
        self.assertTrue(w.is_expandable())
        with patch.object(w, "_scroll_to_widget") as scroll_mock:
            w.toggle_expanded()
            self.assertTrue(w.is_expanded)
            scroll_mock.assert_called_with(top=False)

        w2 = self._widget("codegraph_explore", "")
        w2.is_mcp = True
        w2.is_expanded = True
        with patch.object(w2, "render_content") as render_mock:
            w2.set_result("**Result**", status="done")
            self.assertTrue(getattr(w2, "_should_scroll_on_render", False))
            render_mock.assert_called_once()

    def test_set_result_scroll_flag_respects_parent_position(self):
        w = self._widget("codegraph_explore", "")
        w.is_mcp = True
        w.is_expanded = True
        with (
            patch.object(w, "_is_parent_at_bottom", return_value=False),
            patch.object(w, "render_content") as render_mock,
        ):
            w.set_result("**Result**", status="done")
            self.assertFalse(w._should_scroll_on_render)
            render_mock.assert_called_once()

    def test_format_manage_shell_display(self):
        from widgets.chat_toolcall import format_manage_shell_display

        # Empty
        t_empty = format_manage_shell_display("no tasks active")
        self.assertIn("(No active tasks)", t_empty.plain)

        # Active tasks
        output = (
            "Active Background Tasks:\n"
            "- ID: task-1 | Status: RUNNING | Command: uv run pytest\n"
            "- ID: task-2 | Status: FINISHED | Command: npm run build\n"
        )
        t = format_manage_shell_display(output)
        self.assertIn("[>]", t.plain)
        self.assertIn("task-1", t.plain)
        self.assertIn("uv run pytest", t.plain)
        self.assertIn("[x]", t.plain)
        self.assertIn("task-2", t.plain)

    def test_render_content_manage_shell_list(self):
        w = self._widget(
            "manage_shell",
            "- ID: t1 | Status: RUNNING | Command: pytest",
            args={"action": "list"},
        )
        with patch.object(w.content_widget, "update") as upd:
            w.render_content()
        upd.assert_called_once()
        text_obj = upd.call_args[0][0]
        self.assertIn("t1", text_obj.plain)

    def test_format_manage_subagent_display(self):
        from widgets.chat_toolcall import format_manage_subagent_display

        # Empty
        t_empty = format_manage_subagent_display("No subagent sessions found for current session.")
        self.assertIn("(No active subagents)", t_empty.plain)

        # Active subagents
        output = (
            "Active/Past Subagent Sessions:\n"
            "• ID: sess_123 | Status: RUNNING | Type: explore | Title: search files\n"
            "• ID: sess_456 | Status: COMPLETED | Type: code_editor | Title: refactor auth\n"
        )
        t = format_manage_subagent_display(output)
        self.assertIn("[>]", t.plain)
        self.assertIn("sess_123", t.plain)
        self.assertIn("Explore: search files", t.plain)
        self.assertIn("[x]", t.plain)
        self.assertIn("sess_456", t.plain)
        self.assertIn("Code_editor: refactor auth", t.plain)

    def test_render_content_manage_subagent_list(self):
        w = self._widget(
            "manage_subagent",
            "• ID: s1 | Status: RUNNING | Type: explore | Title: find bugs",
            args={"action": "list"},
        )
        with patch.object(w.content_widget, "update") as upd:
            w.render_content()
        upd.assert_called_once()
        text_obj = upd.call_args[0][0]
        self.assertIn("s1", text_obj.plain)


if __name__ == "__main__":
    unittest.main()
