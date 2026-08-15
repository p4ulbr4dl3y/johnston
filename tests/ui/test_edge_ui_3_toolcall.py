import unittest

from widgets.presentation.widgets.chat_tools import ToolCallWidget


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

    def test_mark_cancelled_when_not_running_noop(self):
        widget = ToolCallWidget("read", "f.py", "already done")
        widget.mark_cancelled()
        self.assertEqual(widget.status, "done")


if __name__ == "__main__":
    unittest.main()
