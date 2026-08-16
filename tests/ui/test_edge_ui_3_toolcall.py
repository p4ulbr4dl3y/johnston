import unittest

from widgets.chat_toolcall import ToolCallWidget


class TestEdgeToolCallInit(unittest.TestCase):
    def test_empty_tool_type_is_tolerated(self):
        """Empty tool name must not crash construction or header rendering."""
        widget = ToolCallWidget("", "readme.md", "", args={})
        self.assertEqual(widget.tool_type, "")
        self.assertEqual(widget.canonical_tool, "")
        widget.render_header()
        self.assertIsNotNone(widget.header_label)

    def test_whitespace_only_tool_type(self):
        widget = ToolCallWidget("   ", "target", "")
        widget.render_header()
        self.assertIn("target", widget.header_label.render().plain)

    def test_none_tool_type_does_not_crash(self):
        """None tool_type is a malformed tool-call; must not raise AttributeError."""
        widget = ToolCallWidget(None, "target")
        widget.render_header()
        self.assertIsNotNone(widget.header_label)

    def test_none_target_does_not_crash(self):
        widget = ToolCallWidget("read", None)
        widget.render_header()
        self.assertIsNotNone(widget.header_label)

    def test_none_args_does_not_crash_render(self):
        widget = ToolCallWidget("create", "f.py", "content", None)
        widget.render_header()
        widget.render_content()
        self.assertIsNotNone(widget.content_widget)

    def test_none_result_text_render_content(self):
        widget = ToolCallWidget("shell", "ls", None)
        widget.render_content()
        self.assertIsNotNone(widget.content_widget)


class TestEdgeToolCallMalformedArgs(unittest.TestCase):
    def test_non_serializable_arg_value_does_not_crash_header(self):
        """A malformed args dict containing a non-JSON value (e.g. set) must not
        crash header rendering via json.dumps."""
        widget = ToolCallWidget("mcp_custom", "t", "", args={"path": {1, 2}})
        widget.render_header()
        self.assertIsNotNone(widget.header_label)

    def test_non_str_arg_key_does_not_crash_header(self):
        widget = ToolCallWidget("mcp_custom", "t", "", args={1: "x"})
        widget.render_header()
        self.assertIsNotNone(widget.header_label)

    def test_malformed_json_repair_returns_valid(self):
        from widgets.chat_toolcall import ParsingMixin

        obj = ParsingMixin()
        self.assertEqual(obj._parse_json('{"a": "b'), {"a": "b"})
        self.assertEqual(obj._parse_json("[1, 2"), [1, 2])

    def test_empty_dict_args_renders_target(self):
        widget = ToolCallWidget("mcp_fetch", "", "", args={})
        widget.render_header()
        self.assertIsNotNone(widget.header_label)


class TestEdgeToolCallStatus(unittest.TestCase):
    def test_set_result_none_does_not_crash(self):
        widget = ToolCallWidget("shell", "ls")
        widget.set_result(None)
        self.assertEqual(widget.status, "done")

    def test_set_result_status_is_structured_not_parsed(self):
        """Status arrives as a field; result text is never classified to derive it.
        A shell background payload only becomes ``running`` when status says so,
        and a plain error-like string stays ``done`` without a structured flag."""
        widget = ToolCallWidget("shell", "ls")
        widget.set_result("Command is running in the background [Background Task ID: shell_1]")
        self.assertEqual(widget.status, "done")
        widget.set_result("[Background Task ID: shell_1] moved to background", status="running")
        self.assertEqual(widget.status, "running")

    def test_set_result_error_via_flag(self):
        widget = ToolCallWidget("shell", "ls")
        widget.set_result("ERR: provider unavailable", is_error=True)
        self.assertEqual(widget.status, "error")

    def test_mark_cancelled_when_not_running_noop(self):
        widget = ToolCallWidget("read", "f.py", "already done")
        widget.mark_cancelled()
        self.assertEqual(widget.status, "done")


class TestEdgeToolCallInvokeSubagentStatus(unittest.TestCase):
    def test_launch_result_is_running_when_status_running(self):
        """Invoke-subagent status comes from the event ('launched' is status
        RUNNING because the subagent runs in the background, not parsed from
        text). A bare set_result with no status still defaults to done."""
        widget = ToolCallWidget("invoke_subagent", "task", args={})
        widget.set_result("subagent 'fix bug' launched (session_id: subagent-abc)", status="running")
        self.assertEqual(widget.status, "running")
        widget2 = ToolCallWidget("invoke_subagent", "task", args={})
        widget2.set_result("subagent 'fix bug' launched (session_id: subagent-abc)")
        self.assertEqual(widget2.status, "done")

    def test_final_result_is_done_green(self):
        widget = ToolCallWidget("invoke_subagent", "task", args={})
        widget.set_result("subagent 'fix bug' launched (session_id: subagent-abc)", status="running")
        widget.set_result("the bug is fixed")
        self.assertEqual(widget.status, "done")

    def test_launch_error_is_red(self):
        widget = ToolCallWidget("invoke_subagent", "task", args={})
        widget.set_result("ERR: provider unavailable", status="error")
        self.assertEqual(widget.status, "error")

    def test_final_error_is_red(self):
        widget = ToolCallWidget("invoke_subagent", "task", args={})
        widget.set_result("subagent 'x' launched (session_id: subagent-abc)", status="running")
        widget.set_result("Subagent error: boom", status="error")
        self.assertEqual(widget.status, "error")


class TestEdgeToolCallMarkRunning(unittest.TestCase):
    def test_mark_running_sets_yellow_status(self):
        widget = ToolCallWidget("invoke_subagent", "task", args={})
        self.assertEqual(widget.status, "running")
        widget.set_result("the bug is fixed")
        self.assertEqual(widget.status, "done")
        widget.mark_running(text="follow-up sent to subagent-abc")
        self.assertEqual(widget.status, "running")
        self.assertEqual(widget.result_text, "follow-up sent to subagent-abc")

    def test_mark_running_no_text_keeps_result(self):
        widget = ToolCallWidget("invoke_subagent", "task", args={})
        widget.set_result("result text")
        widget.mark_running()
        self.assertEqual(widget.status, "running")
        self.assertEqual(widget.result_text, "result text")

    def test_mark_running_on_non_subagent_tool(self):
        widget = ToolCallWidget("read", "f.py")
        widget.set_result("content")
        widget.mark_running(text="working")
        self.assertEqual(widget.status, "running")
        self.assertEqual(widget.result_text, "working")


if __name__ == "__main__":
    unittest.main()
