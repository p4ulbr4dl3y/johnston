"""Regression tests for unified tool error handling.

Covers three hardening fixes:
1. edit: a bare ValueError leaking from apply_chunk_replacements must still be
   wrapped as `ERR: params _format_*` instead of being returned unformatted.
2. registry execute_tool MCP branch: failures while listing active tools /
   resolving capabilities must be wrapped in format_tool_error("mcp").
3. ask_user: an asyncio.CancelledError is a real cooperative cancellation and
   must be re-raised (not returned as a result) after clearing pending state.
"""
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from tools import ask_user, edit
from tools.registry import execute_tool


class TestEditBareValueError(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = f"{self._tmp.name}/members.py"

    async def _helper(self, content: str, chunk, expected_substr):
        """Write content and run _execute_edit_helper against one bad chunk."""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(content)
        res = await edit._execute_edit_helper(self.path, [chunk], cwd=self._tmp.name)
        self.assertIn(expected_substr, res)
        return res

    async def test_bare_valueerror_wrapped_as_params_error(self):
        # A bare (not ERR:-prefixed) ValueError raised by a chunk consumer must be
        # wrapped in a unified `ERR: params` message, never leaked raw.
        def boom(*args, **kwargs):
            raise ValueError("some bare rejection text")

        with open(self.path, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        with patch.object(edit, "read_file_text", new=boom):
            res = await edit._execute_edit_helper(self.path, [{"old_str": "x", "new_str": "y"}], cwd=self._tmp.name)
        self.assertEqual(res, "ERR: params: some bare rejection text")

    async def test_preformatted_valueerror_passthrough(self):
        # A ValueError already formatted with format_tool_error must be returned
        # unchanged (no double-prefix).
        await self._helper("dup\ndup\n", {"old_str": "dup", "new_str": "X"}, "ERR: match")


class TestMCPListToolsFailure(unittest.IsolatedAsyncioTestCase):
    def _mode(self):
        mock_role = MagicMock()
        mock_role.name = "action"
        mock_role.disallowed_tools = []
        reg = MagicMock()
        reg.get_role.return_value = mock_role
        return patch("core.role_registry.RoleRegistry.get_instance", return_value=reg)

    async def test_get_active_tools_exception_wrapped(self):
        mock_mgr = MagicMock()
        mock_mgr.get_active_tools.side_effect = RuntimeError("broken transport")
        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr),
            self._mode(),
        ):
            res = await execute_tool("recent_tool", {"arg": 1})
        self.assertIn("ERR: mcp 'recent_tool'", res)
        self.assertIn("failed to list active tools", res)
        self.assertIn("broken transport", res)

    async def test_capabilities_exception_wrapped(self):
        mock_mgr = MagicMock()
        # No active-tool name match, so the `any(...)` short-circuit is False and
        # get_capabilities_for_exposed_tool is actually reached.
        mock_mgr.get_active_tools.return_value = []
        mock_mgr.get_capabilities_for_exposed_tool.side_effect = RuntimeError("policy crash")
        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr),
            self._mode(),
        ):
            res = await execute_tool("gh__search", {"q": "x"})
        self.assertIn("ERR: mcp 'gh__search'", res)
        self.assertIn("failed to resolve capabilities", res)
        self.assertIn("policy crash", res)


class TestAskUserCancellationRaises(unittest.IsolatedAsyncioTestCase):
    async def test_pending_cleared_and_cancelled_error_propagates(self):
        import asyncio

        tool = ask_user.AskUserTool()
        mock_app = MagicMock()
        mock_app._pending_ask_user = lambda: None

        async def cancelled(questions):
            raise asyncio.CancelledError()

        mock_app.ask_user = cancelled
        with self.assertRaises(asyncio.CancelledError):
            await tool.execute({"questions": [{"question_text": "Q?", "options": ["a"]}]}, ctx=mock_app)
        self.assertIsNone(mock_app._pending_ask_user)


if __name__ == "__main__":
    unittest.main()
