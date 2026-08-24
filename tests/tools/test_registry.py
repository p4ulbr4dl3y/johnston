import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.domain.policies.permission_policy import PermissionAction, PermissionDecision
from tools.registry import REGISTRY, execute_tool, get_default_tools, normalize_tool_name


class TestRegistry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # MCP tools now go through the permission check (default 'ask'). Existing
        # MCP-path tests exercise dispatch/role logic, not permissions, so allow
        # their tools for the session.
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()
        for name in ("mcp_tool_test", "exposed_mcp_tool", "faulty_mcp", "none_mcp", "async_mcp", "err_mcp"):
            pm.set_session_override(name, "allow")

    def test_normalize_tool_name(self):
        # Case/whitespace normalization only; no alias resolution.
        self.assertEqual(normalize_tool_name("Read"), "read")
        self.assertEqual(normalize_tool_name("  multi_edit\n"), "multi_edit")
        self.assertEqual(normalize_tool_name("subagent"), "subagent")
        self.assertEqual(normalize_tool_name("view_file"), "view_file")
        self.assertEqual(normalize_tool_name("write_to_file"), "write_to_file")
        self.assertEqual(normalize_tool_name("unknown_tool"), "unknown_tool")
        self.assertEqual(normalize_tool_name(""), "")
        self.assertEqual(normalize_tool_name(None), "")

    def test_get_default_tools(self):
        tools = get_default_tools()
        self.assertIsInstance(tools, list)
        self.assertTrue(len(tools) > 0)
        for t in tools:
            self.assertIn("type", t)
            self.assertIn("function", t)

    async def test_execute_tool_success_and_unknown(self):
        # Execute tool via canonical name
        res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"})
        self.assertIn("ERR:", res.content)
        self.assertTrue(res.is_error)
        self.assertIn("file", res.content)

        # Aliases are no longer resolved: 'cat' is an unknown tool name.
        res_alias = await execute_tool("cat", {"path": "nonexistent_abc_123.txt"})
        self.assertIn("ERR: unknown 'cat'", res_alias.content)

    async def test_execute_tool_edit_routes_to_edit_tool(self):
        from tools.edit import EditTool
        from tools.registry import REGISTRY

        self.assertIs(REGISTRY["edit"], EditTool)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ALLOW, "")
        with (
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            patch.object(EditTool, "execute", new=AsyncMock(return_value="EDIT_OK")),
        ):
            res = await execute_tool("edit", {"path": "x.py", "old_str": "a", "new_str": "b"})
        self.assertEqual(res.content, "EDIT_OK")

    async def test_execute_tool_execution_exception(self):
        from core.permission_manager import PermissionManager

        PermissionManager.get_instance().set_session_override("read", "allow")
        with patch.object(REGISTRY["read"], "execute", side_effect=RuntimeError("Execute failed")):
            res = await execute_tool("read", {"path": "foo.txt"})
            self.assertIn("ERR: execute 'read': Execute failed", res.content)

    async def test_execute_tool_unknown_with_direct_hint(self):
        # Match that maps directly to a registry tool name
        res = await execute_tool("creats", None)
        self.assertIn("ERR: unknown 'creats'", res.content)
        self.assertIn("Did you mean 'create'?", res.content)

    async def test_execute_tool_unknown_without_alias_hint(self):
        # 'cat' used to be an alias for 'read'; without aliases it no longer
        # produces an alias-target hint.
        res = await execute_tool("cat", None)
        self.assertIn("ERR: unknown 'cat'", res.content)
        self.assertNotIn("target: read", res.content)

    async def test_execute_tool_unknown_no_hint(self):
        res = await execute_tool("zzzzzzzzz_unknown", None)
        self.assertEqual(res.content, "ERR: unknown 'zzzzzzzzz_unknown'")

    async def test_execute_tool_mcp_disallowed_in_mode(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_tool_test"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_mode_def = MagicMock()
        mock_mode_def.name = "plan"
        mock_mode_def.disallowed_tools = ["mcp_tool_test"]

        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            mock_app = MagicMock()
            mock_app.role = "plan"
            res = await execute_tool("mcp_tool_test", {"arg": "val"}, app=mock_app)
            self.assertIn("ERR: tool 'mcp_tool_test' disabled in plan role", res.content)

    async def test_execute_tool_mcp_success(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = []
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = {"server": "s1"}
        mock_mcp_mgr.call_tool.return_value = "MCP Executed Output"

        mock_mode_def = MagicMock()
        mock_mode_def.name = "action"
        mock_mode_def.disallowed_tools = []

        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            res = await execute_tool("exposed_mcp_tool", {"foo": "bar"})
            self.assertEqual(res.content, "MCP Executed Output")
            mock_mcp_mgr.call_tool.assert_called_once_with("exposed_mcp_tool", {"foo": "bar"})

    async def test_execute_tool_mcp_error_exception(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "faulty_mcp"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.side_effect = RuntimeError("MCP connection failed")

        mock_mode_def = MagicMock()
        mock_mode_def.name = "action"
        mock_mode_def.disallowed_tools = []

        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            res = await execute_tool("faulty_mcp", {})
            self.assertIn("ERR: mcp 'faulty_mcp': MCP connection failed", res.content)

    async def test_execute_tool_mcp_returns_none(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "none_mcp"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = None

        mock_mode_def = MagicMock()
        mock_mode_def.name = "action"
        mock_mode_def.disallowed_tools = []

        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            res = await execute_tool("none_mcp", {})
            self.assertEqual(res.content, "ERR: unknown 'none_mcp'")

    def _mock_mode(self, name="action"):
        mock_mode_def = MagicMock()
        mock_mode_def.name = name
        mock_mode_def.disallowed_tools = []
        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def
        return patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry)

    async def test_execute_tool_permission_denied(self):
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.DENY, "Policy blocks it")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"})
            self.assertEqual(res.content, "ERR: denied 'read': by permission policy")

    async def test_execute_tool_permission_ask_confirmed(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ASK, "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"}, app=mock_app)
        self.assertIn("ERR:", res.content)
        mock_app.confirm_permission.assert_awaited_once()

    async def test_execute_tool_permission_ask_always_allow(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ASK, "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"}, app=mock_app)
        self.assertIn("ERR:", res.content)
        mock_app.confirm_permission.assert_awaited_once()

    async def test_execute_tool_permission_ask_denied_by_user(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=False)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ASK, "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"}, app=mock_app)
        self.assertEqual(res.content, "ERR: denied 'read': by user")

    async def test_execute_tool_permission_ask_no_app(self):
        # No interactive app available -> fall back to a textual denial.
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ASK, "No interactive app")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"})
        self.assertEqual(res.content, "ERR: denied 'read': requires user confirmation (No interactive app)")

    async def test_execute_tool_mcp_async_call(self):
        # Manager class whose type name does not end with "Mock" and which exposes
        # call_tool_async -> the async MCP invocation branch must be used.
        class _FakeMCPManager:
            def get_active_tools(self, mode=None):
                return []

            def get_capabilities_for_exposed_tool(self, exposed_name):
                return ["server1"]

            async def call_tool_async(self, tool_name, arguments, target_server=None, timeout=None):
                return "async mcp output"

        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=_FakeMCPManager()), self._mock_mode():
            res = await execute_tool("async_mcp", {"q": 1})
        self.assertEqual(res.content, "async mcp output")

    async def test_execute_tool_mcp_permission_denied(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_deny_tool"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.DENY, "Policy blocks it")

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("mcp_deny_tool", {"arg": "val"})
        self.assertEqual(res.content, "ERR: denied 'mcp_deny_tool': by permission policy")
        mock_pm.check_permission.assert_called_once_with("mcp_deny_tool", {"arg": "val"})
        mock_mcp_mgr.call_tool.assert_not_called()

    async def test_execute_tool_mcp_permission_allow(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_allow_tool"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = "MCP ALLOWED OUTPUT"

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ALLOW, "")

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("mcp_allow_tool", {"arg": "val"})
        self.assertEqual(res.content, "MCP ALLOWED OUTPUT")
        mock_mcp_mgr.call_tool.assert_called_once_with("mcp_allow_tool", {"arg": "val"})

    async def test_execute_tool_mcp_permission_uses_exposed_name(self):
        # Collision-style exposed name ("server__tool"): the permission must be
        # checked under the exposed name, not the raw caller name.
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "gh__search"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.DENY, "Policy blocks it")

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("gh__search", {"q": "x"})
        self.assertEqual(res.content, "ERR: denied 'gh__search': by permission policy")
        mock_pm.check_permission.assert_called_once_with("gh__search", {"q": "x"})

    async def test_execute_tool_mcp_error_string_marked_error(self):
        # MCP failures now surface as ERR:-prefixed strings (JSON-RPC error,
        # isError result, transport failure), so the registry classifies them as
        # real tool errors (is_error=True) exactly like native-tool failures.
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "err_mcp"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = "ERR: mcp 'err_mcp': boom"

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            self._mock_mode(),
        ):
            res = await execute_tool("err_mcp", {})
        self.assertTrue(res.is_error)
        self.assertIn("ERR: mcp 'err_mcp': boom", res.content)
        self.assertIsNone(res.returncode)

    async def test_execute_tool_mcp_output_truncated(self):
        huge_output = "X" * 15000
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_huge_tool"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = huge_output

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ALLOW, "")

        with (
            patch("core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("mcp_huge_tool", {"arg": "val"})

        self.assertFalse(res.is_error)
        self.assertIn("[Output truncated: showing first 8000 chars", res.content)
        self.assertIn("Refine parameters or request partial data", res.content)

    async def test_subagent_auto_allows_non_denied_tools(self):
        from tools.context import ToolContext
        from tools.read import ReadTool

        ctx = ToolContext(is_subagent=True)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.ASK, "Ask confirmation")

        with (
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            patch.object(ReadTool, "execute", new=AsyncMock(return_value="CONTENT_OK")),
        ):
            res = await execute_tool("read", {"path": "dummy.txt"}, context=ctx)
        self.assertFalse(res.is_error)
        self.assertEqual(res.content, "CONTENT_OK")

    async def test_subagent_respects_explicit_deny(self):
        from tools.context import ToolContext

        ctx = ToolContext(is_subagent=True)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = PermissionDecision(PermissionAction.DENY, "Strictly forbidden")

        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("shell", {"command": "rm -rf /"}, context=ctx)
        self.assertTrue(res.is_error)
        self.assertIn("ERR: denied 'shell'", res.content)


if __name__ == "__main__":
    unittest.main()
