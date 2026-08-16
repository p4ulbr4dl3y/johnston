"""Unit tests for the ToolResult domain entity (factories, consistency, str)."""
import unittest

from core.domain.defaults.errors import ToolResult, format_tool_error


class TestToolResultFactories(unittest.TestCase):
    def test_done_defaults(self):
        r = ToolResult.done()
        self.assertEqual(r.content, "")
        self.assertFalse(r.is_error)
        self.assertEqual(r.status, "done")
        self.assertIsNone(r.returncode)

    def test_done_with_content_and_returncode(self):
        r = ToolResult.done("hello", returncode=0)
        self.assertEqual(r.content, "hello")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(r.is_error)
        self.assertEqual(r.status, "done")

    def test_error_produces_canonical_content(self):
        r = ToolResult.error("file", detail="not found", name="/tmp/x.py")
        self.assertTrue(r.is_error)
        self.assertEqual(r.status, "error")
        self.assertEqual(r.content, format_tool_error("file", detail="not found", name="/tmp/x.py"))
        self.assertEqual(r.content, "ERR: file '/tmp/x.py': not found")

    def test_error_returncode(self):
        r = ToolResult.error("execute", detail="boom", name="shell", returncode=1)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.status, "error")

    def test_running(self):
        r = ToolResult.running("working")
        self.assertEqual(r.status, "running")
        self.assertFalse(r.is_error)
        self.assertEqual(r.content, "working")

    def test_cancelled(self):
        r = ToolResult.cancelled()
        self.assertEqual(r.status, "cancelled")
        self.assertFalse(r.is_error)
        self.assertEqual(r.content, "")


class TestToolResultStr(unittest.TestCase):
    def test_str_returns_content(self):
        self.assertEqual(str(ToolResult.done("abc")), "abc")

    def test_str_empty_for_none_content(self):
        self.assertEqual(str(ToolResult()), "")
        self.assertEqual(str(ToolResult.done()), "")

    def test_str_on_error_returns_err_text(self):
        r = ToolResult.error("denied", name="read", detail="by policy")
        self.assertEqual(str(r), "ERR: denied 'read': by policy")


class TestToolResultConsistency(unittest.TestCase):
    def test_error_status_and_is_error_synced(self):
        # Factories must keep is_error/status consistent.
        done = ToolResult.done()
        err = ToolResult.error("kind")
        run = ToolResult.running()
        canc = ToolResult.cancelled()
        self.assertEqual(done.is_error, done.status == "error")
        self.assertEqual(err.is_error, err.status == "error")
        self.assertEqual(run.is_error, run.status == "error")
        self.assertEqual(canc.is_error, canc.status == "error")
        self.assertTrue(err.is_error)
        self.assertEqual(err.status, "error")


if __name__ == "__main__":
    unittest.main()
