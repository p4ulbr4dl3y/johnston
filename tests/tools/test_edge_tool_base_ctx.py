"""Edge-case tests for tools/base.py, tools/context.py, tools/utils.py.

Focus: find bugs (crashes on valid input, path traversal, data loss, broken
surrogates). Red tests = real code bugs (kept failing intentionally).
"""
import os
import tempfile
import unittest

from core.infrastructure.errors import format_tool_error
from core.infrastructure.tasks.output import tail_output
from tools.base import (
    BaseTool,
    execute_mcp_tool,
    format_background_notification,
    resolve_path,
    truncate_output,
    try_int,
)
from tools.context import ToolContext
from tools.utils import format_line_pagination


class TestTryIntEdge(unittest.TestCase):
    def test_float_string(self):
        self.assertEqual(try_int("3.9", 7), 7)

    def test_bool(self):
        self.assertEqual(try_int(True, 7), 1)

    def test_whitespace(self):
        self.assertEqual(try_int("  ", 7), 7)

    def test_none(self):
        self.assertIsNone(try_int(None))


class TestTruncateTailEdge(unittest.TestCase):
    def test_negative_max_chars(self):
        # tail_output with negative max -> impossible truncation, returns prefix
        res = tail_output("hello", -5)
        self.assertIn("... [Output truncated", res)

    def test_truncate_negative_max_chars(self):
        res = truncate_output("hello", -5, save_log=False)
        self.assertIn("Output truncated at -5 chars", res)

    def test_truncate_does_not_break_surrogate(self):
        # 4-byte emoji sliced mid-character must remain valid UTF-8
        s = "ab\U0001f600cd"
        res = truncate_output(s, max_chars=3, save_log=False)
        res.encode("utf-8")  # raises UnicodeEncodeError if broken surrogate

    def test_truncate_zero(self):
        res = truncate_output("abc", max_chars=0, save_log=False)
        self.assertIn("Output truncated at 0 chars", res)

    def test_truncate_unicode_short(self):
        self.assertEqual(truncate_output("привет", max_chars=100, save_log=False), "привет")

    def test_truncate_huge(self):
        res = truncate_output("x" * 100_000, max_chars=100, save_log=False)
        self.assertIn("Output truncated at 100 chars", res)


class TestFormatEdge(unittest.TestCase):
    def test_format_tool_error_empty(self):
        self.assertEqual(format_tool_error("kind"), "ERR: kind")

    def test_format_tool_error_unicode(self):
        self.assertEqual(format_tool_error("kind", "детале", "тool"), "ERR: kind 'тool': детале")

    def test_background_no_result(self):
        res = format_background_notification("kind", "name", "id", "")
        self.assertIn("<task_result>\n\n</task_result>", res)

    def test_background_unicode(self):
        res = format_background_notification("к", "имя", "1", "résultat")
        self.assertIn("имя", res)


class TestResolvePathEdge(unittest.TestCase):
    def test_none_returns_base(self):
        self.assertTrue(os.path.isabs(resolve_path(None, None)))

    def test_absolute_wins(self):
        base = tempfile.gettempdir()
        res = resolve_path("/etc/hosts", base)
        self.assertEqual(os.path.abspath("/etc/hosts"), res)

    def test_unicode_relative(self):
        base = tempfile.mkdtemp()
        res = resolve_path("папка/файл.txt", base)
        self.assertTrue(res.startswith(os.path.realpath(base)))

    def test_dotdot_resolves(self):
        base = tempfile.mkdtemp()
        res = resolve_path("../x", os.path.join(base, "sub"))
        self.assertNotIn("sub", os.path.realpath(res))


class TestExecuteMcpEdge(unittest.IsolatedAsyncioTestCase):
    async def test_sync_manager(self):
        class SyncMgr:
            def call_tool(self, n, a, **k):
                return f"S:{n}"

        self.assertEqual(await execute_mcp_tool(SyncMgr(), "x", {}), "S:x")

    async def test_async_manager(self):
        class AsyncMgr:
            async def call_tool_async(self, n, a, **k):
                return f"A:{n}"

        self.assertEqual(await execute_mcp_tool(AsyncMgr(), "x", {}), "A:x")

    async def test_mock_manager_uses_sync(self):
        # type name ends with "Mock" -> sync path even if async exists
        class ManagerMock:
            def call_tool(self, n, a, **k):
                return "M-sync"

            async def call_tool_async(self, n, a, **k):
                return "M-async"

        self.assertEqual(await execute_mcp_tool(ManagerMock(), "x", {}), "M-sync")

    async def test_returns_none(self):
        class NoneMgr:
            def call_tool(self, n, a, **k):
                return None

        self.assertIsNone(await execute_mcp_tool(NoneMgr(), "x", {}))

    async def test_result_not_string(self):
        class DictMgr:
            def call_tool(self, n, a, **k):
                return {"ok": True}

        res = await execute_mcp_tool(DictMgr(), "x", {})
        self.assertEqual(res, {"ok": True})


class TestBaseToolEdge(unittest.TestCase):
    def test_schema_none_subclass(self):
        class T(BaseTool):
            name = "t"
            description = "d"
            schema = None

        self.assertEqual(T.name, "t")

    def test_schema_without_function(self):
        class T(BaseTool):
            schema = {"type": "object"}

        self.assertEqual(T.schema, {"type": "object"})

    def test_unicode_description_propagates(self):
        class T(BaseTool):
            description = "emoji 😀 деск"
            schema = {"function": {"description": "old", "parameters": {"type": "object"}}}

        self.assertEqual(T.schema["function"]["description"], "emoji 😀 деск")

    def test_ensure_context_none(self):
        t = BaseTool()
        ctx = t._ensure_context(None)
        self.assertIsInstance(ctx, ToolContext)
        self.assertIsNone(ctx.app)

    def test_ensure_context_tool_context_passthrough(self):
        ctx = ToolContext(None)
        self.assertIs(BaseTool()._ensure_context(ctx), ctx)

    def test_ensure_context_agent(self):
        class FakeApp:
            pass

        fake = FakeApp()
        ctx = BaseTool()._ensure_context(fake)
        self.assertIs(ctx.app, fake)


class TestToolContextEdge(unittest.TestCase):
    def test_agent_without_app_attr(self):
        class Agent:
            pass

        agent = Agent()
        ctx = ToolContext(agent)
        # agent has no host app -> falls back to keeping the agent as ctx.app
        self.assertIs(ctx.app, agent)
        self.assertEqual(ctx.background_tasks, [])
        ctx.refresh_status()  # should not raise

    def test_metadata_absent_getattr(self):
        ctx = ToolContext(None)
        self.assertIsNone(getattr(ctx, "missing", None))

    def test_unicode_cwd(self):
        base = tempfile.mkdtemp()
        ud = os.path.join(base, "папка")
        os.makedirs(ud)
        ctx = ToolContext(None, cwd=ud)
        self.assertEqual(ctx.cwd, os.path.realpath(ud))

    def test_nonexistent_cwd(self):
        ctx = ToolContext(None, cwd="/nonexistent/zzz")
        self.assertIsNone(ctx.cwd)

    def test_blank_cwd(self):
        ctx = ToolContext(None, cwd="   ")
        self.assertIsNone(ctx.cwd)

    def test_project_dir_fallback(self):
        ctx = ToolContext(None)
        pd = ctx.project_dir
        self.assertTrue(os.path.isabs(pd))

    def test_project_dir_blank_app(self):
        class App:
            project_dir = "   "

        ctx = ToolContext(App())
        pd = ctx.project_dir
        self.assertTrue(os.path.isabs(pd))

    def test_add_background_task_no_app(self):
        ctx = ToolContext(None)
        ctx.add_background_task("t")  # should not raise

    def test_trigger_no_app(self):
        ToolContext(None).trigger_ai_response("p")  # should not raise


class TestFormatLinePaginationEdge(unittest.TestCase):
    def test_empty_lines_zero_total(self):
        res = format_line_pagination([], total_lines=0)
        self.assertEqual(res, "=== 0 lines ===")

    def test_empty_lines_positive_total(self):
        res = format_line_pagination([], total_lines=5)
        self.assertIn("of 5", res)

    def test_start_line_exceeds_total(self):
        res = format_line_pagination(["a"], total_lines=1, start_line=50)
        self.assertIn("ERR: range", res)

    def test_unicode_lines(self):
        res = format_line_pagination(["привет", "😀"], start_line=1, end_line=2)
        self.assertIn("привет", res)
        self.assertIn("😀", res)

    def test_non_string_line(self):
        res = format_line_pagination([1, 2, 3], start_line=1, end_line=2)
        self.assertIn("1 | 1", res)

    def test_window_shorter_than_total_lines_crash(self):
        # BUG FOUND (RED): partial-read window (lines has fewer entries than
        # total_lines) + start_line beyond the window -> IndexError crash.
        # tools/utils.py format_line_pagination accesses lines[i - window_start]
        # without bounds check. Expected: safe truncation, actual: crash.
        res = format_line_pagination(["a", "b"], total_lines=5000, start_line=4900)
        self.assertIn("of 5000", res)

    def test_window_shorter_than_total_lines_near_end(self):
        # same bug, different trigger
        res = format_line_pagination(["a", "b"], total_lines=5000, start_line=4999)
        self.assertIn("of 5000", res)


class TestPathTraversalContext(unittest.TestCase):
    def test_abs_path_kept(self):
        # resolve_path keeps absolute paths as-is (no confinement)
        base = tempfile.mkdtemp()
        res = resolve_path("/tmp/outside.txt", base)
        self.assertEqual(res, os.path.abspath("/tmp/outside.txt"))


if __name__ == "__main__":
    unittest.main()
