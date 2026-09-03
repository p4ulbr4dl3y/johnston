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
from unittest.mock import AsyncMock, MagicMock, patch

from tools import ask_user, edit
from tools.registry import execute_tool


class TestEditBareValueError(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = f"{self._tmp.name}/members.py"

    async def test_bare_valueerror_wrapped_as_params_error(self):
        # A bare (not ERR:-prefixed) ValueError raised by apply_edit must be
        # wrapped in a unified `ERR: params` message, never leaked raw.
        def boom(*args, **kwargs):
            raise ValueError("some bare rejection text")

        with open(self.path, "w", encoding="utf-8") as f:
            f.write("x = 1\n")
        with patch.object(edit, "apply_edit", new=boom):
            res = await edit.EditTool().execute({"path": self.path, "old_str": "x", "new_str": "y"})
        self.assertEqual(str(res), "ERR: params: some bare rejection text")

    async def test_preformatted_valueerror_passthrough(self):
        # A ValueError already formatted with format_tool_error must be returned
        # unchanged (no double-prefix).
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("dup\ndup\n")
        res = await edit.EditTool().execute({"path": self.path, "old_str": "dup", "new_str": "X"})
        self.assertIn("ERR: match", str(res))
        self.assertNotIn("ERR: params: ERR:", str(res))


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
        mock_mgr.get_cached_tools.return_value = []
        mock_mgr.get_active_tools_async = AsyncMock(side_effect=RuntimeError("broken transport"))
        mock_mgr.get_active_tools.side_effect = RuntimeError("broken transport")
        # Explicit caps miss so the flow reaches the full active-tools listing.
        mock_mgr.get_capabilities_for_exposed_tool.return_value = None
        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr),
            self._mode(),
        ):
            res = await execute_tool("recent_tool", {"arg": 1})
        self.assertIn("ERR: unavailable 'recent_tool'", res.content)
        self.assertIn("failed to list active tools", res.content)
        self.assertIn("broken transport", res.content)
        self.assertTrue(res.is_error)

    async def test_capabilities_exception_wrapped(self):
        mock_mgr = MagicMock()
        mock_mgr.get_cached_tools.return_value = []
        # No active-tool name match, so the `any(...)` short-circuit is False and
        # get_capabilities_for_exposed_tool is actually reached.
        mock_mgr.get_active_tools.return_value = []
        mock_mgr.get_active_tools_async = AsyncMock(return_value=[])
        mock_mgr.get_capabilities_for_exposed_tool.side_effect = RuntimeError("policy crash")
        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr),
            self._mode(),
        ):
            res = await execute_tool("gh__search", {"q": "x"})
        self.assertIn("ERR: unavailable 'gh__search'", res.content)
        self.assertIn("failed to resolve capabilities", res.content)
        self.assertIn("policy crash", res.content)


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
            await tool.execute({"questions": [{"question": "Q?", "options": [{"label": "a"}]}]}, ctx=mock_app)
        self.assertIsNone(mock_app._pending_ask_user)


class TestMCPNameMissCache(unittest.IsolatedAsyncioTestCase):
    """A hallucinated MCP tool name must not re-list (and spawn) every server on
    every agent turn: a failed full listing is remembered briefly."""

    def setUp(self):
        from tools import registry

        registry._mcp_name_misses.clear()

    def _mock_mgr(self):
        mock_mgr = MagicMock()
        mock_mgr.get_cached_tools.return_value = []
        mock_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mgr.get_active_tools.return_value = []
        mock_mgr.get_active_tools_async = AsyncMock(return_value=[])
        return mock_mgr

    def _mode(self):
        mock_role = MagicMock()
        mock_role.name = "action"
        mock_role.disallowed_tools = []
        reg = MagicMock()
        reg.get_role.return_value = mock_role
        return patch("core.role_registry.RoleRegistry.get_instance", return_value=reg)

    async def test_first_miss_lists_second_hits_negative_cache(self):
        mock_mgr = self._mock_mgr()
        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mgr),
            self._mode(),
        ):
            r1 = await execute_tool("totally_hallucinated_tool", {})
            r2 = await execute_tool("totally_hallucinated_tool", {})

        self.assertTrue(r1.is_error)
        self.assertTrue(r2.is_error)
        # The listing ran exactly once, not per call.
        mock_mgr.get_active_tools_async.assert_called_once()

    def test_remember_and_forget_helpers(self):
        from tools import registry

        registry._remember_mcp_miss("srv__x")
        self.assertTrue(registry._mcp_name_recently_missed("srv__x"))
        registry._forget_mcp_miss("srv__x")
        self.assertFalse(registry._mcp_name_recently_missed("srv__x"))

    def test_ttl_expiry_forgets(self):
        from tools import registry

        registry._mcp_name_misses.clear()
        registry._mcp_name_misses["stale"] = 0.0  # long past TTL
        self.assertFalse(registry._mcp_name_recently_missed("stale"))
        self.assertNotIn("stale", registry._mcp_name_misses)


if __name__ == "__main__":
    unittest.main()
