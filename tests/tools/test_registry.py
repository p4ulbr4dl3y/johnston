import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.registry import REGISTRY, execute_tool, get_default_tools, normalize_tool_args, normalize_tool_name


class TestRegistry(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # MCP tools now go through the permission check (default 'ask'). Existing
        # MCP-path tests exercise dispatch/role logic, not permissions, so allow
        # their tools for the session.
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()
        for name in ("mcp_tool_test", "exposed_mcp_tool", "faulty_mcp", "none_mcp", "async_mcp"):
            pm.set_session_override(name, "allow")

    def test_normalize_tool_name(self):
        self.assertEqual(normalize_tool_name("subagent"), "invoke_subagent")
        self.assertEqual(normalize_tool_name("view_file"), "read")
        self.assertEqual(normalize_tool_name("write_to_file"), "create")
        self.assertEqual(normalize_tool_name("unknown_tool"), "unknown_tool")
        self.assertEqual(normalize_tool_name(""), "")
        # Canonical registry names win over alias entries
        self.assertEqual(normalize_tool_name("multi_edit"), "multi_edit")
        # Newly added aliases
        self.assertEqual(normalize_tool_name("apply_patch"), "edit")
        self.assertEqual(normalize_tool_name("curl"), "web_fetch")
        self.assertEqual(normalize_tool_name("delegate"), "invoke_subagent")
        self.assertEqual(normalize_tool_name("shells"), "manage_shell")

    def test_normalize_tool_args(self):
        # Test shell argument aliases
        norm_shell = normalize_tool_args("shell", {"cmd": "ls -l", "time_limit": 30, "async": True})
        self.assertEqual(norm_shell["command"], "ls -l")
        self.assertEqual(norm_shell["timeout"], 30)
        self.assertEqual(norm_shell["run_in_background"], True)

        # Test read argument aliases
        norm_read = normalize_tool_args("read", {"file_path": "foo.py", "start": 10, "end": 20})
        self.assertEqual(norm_read["path"], "foo.py")
        self.assertEqual(norm_read["start_line"], 10)
        self.assertEqual(norm_read["end_line"], 20)

        # Test create argument aliases
        norm_create = normalize_tool_args("create", {"filepath": "bar.py", "content": "print(1)"})
        self.assertEqual(norm_create["target_file"], "bar.py")
        self.assertEqual(norm_create["code"], "print(1)")

        # Test edit argument aliases
        norm_edit = normalize_tool_args("edit", {"file": "baz.py", "target_content": "a", "replacement_content": "b"})
        self.assertEqual(norm_edit["target_file"], "baz.py")
        self.assertEqual(norm_edit["old_str"], "a")
        self.assertEqual(norm_edit["new_str"], "b")

        # Test multi_edit chunk aliases
        norm_multi = normalize_tool_args("multi_edit", {"file": "baz.py", "chunks": [{"search": "a", "replace": "b"}]})
        self.assertEqual(norm_multi["target_file"], "baz.py")
        self.assertEqual(norm_multi["edits"][0]["old_str"], "a")
        self.assertEqual(norm_multi["edits"][0]["new_str"], "b")

        # Test subagent branch aliases (legacy mode maps to canonical branch)
        norm_invoke = normalize_tool_args("invoke_subagent", {"mode": "dev", "role": "explorer"})
        self.assertEqual(norm_invoke["branch"], "dev")
        self.assertEqual(norm_invoke["subagent_type"], "explorer")
        norm_manage = normalize_tool_args("manage_subagent", {"task_id": "sub-2", "id": "sub-2"})
        self.assertEqual(norm_manage["session_id"], "sub-2")
        # manage_shell keeps its own task_id canonical arg untouched
        norm_task = normalize_tool_args("manage_shell", {"task_id": "bash-1"})
        self.assertEqual(norm_task["task_id"], "bash-1")

        # Newly added param aliases
        norm_shell2 = normalize_tool_args("shell", {"timeout_seconds": 45, "bg": True, "skip_confirmation": True})
        self.assertEqual(norm_shell2["timeout"], 45)
        self.assertEqual(norm_shell2["run_in_background"], True)
        self.assertEqual(norm_shell2["skip_confirm"], True)
        norm_read2 = normalize_tool_args("read", {"last_line": 30, "image_detail": "low"})
        self.assertEqual(norm_read2["end_line"], 30)
        self.assertEqual(norm_read2["detail"], "low")
        norm_create2 = normalize_tool_args("create", {"file_contents": "x", "data": "x"})
        self.assertEqual(norm_create2["code"], "x")
        norm_edit2 = normalize_tool_args("edit", {"old_string": "a", "new_string": "b", "replacements": []})
        self.assertEqual(norm_edit2["old_str"], "a")
        self.assertEqual(norm_edit2["new_str"], "b")
        self.assertEqual(norm_edit2["edits"], [])
        norm_fetch2 = normalize_tool_args("web_fetch", {"page_url": "http://x", "as_raw": True})
        self.assertEqual(norm_fetch2["url"], "http://x")
        self.assertEqual(norm_fetch2["raw"], True)
        norm_ask = normalize_tool_args("ask_user", {"question_list": [{"q": 1}]})
        self.assertEqual(norm_ask["questions"], [{"q": 1}])
        norm_plan2 = normalize_tool_args("update_plan", {"note": "why"})
        self.assertEqual(norm_plan2["explanation"], "why")
        norm_manage2 = normalize_tool_args("manage_subagent", {"msg": "hi", "async": True, "show_all": True})
        self.assertEqual(norm_manage2["message"], "hi")
        self.assertEqual(norm_manage2["background"], True)
        self.assertEqual(norm_manage2["all"], True)
        norm_mshell2 = normalize_tool_args("manage_shell", {"message": "data"})
        self.assertEqual(norm_mshell2["input"], "data")

    def test_get_default_tools(self):
        tools = get_default_tools()
        self.assertIsInstance(tools, list)
        self.assertTrue(len(tools) > 0)
        for t in tools:
            self.assertIn("type", t)
            self.assertIn("function", t)

    async def test_execute_tool_success_and_alias(self):
        # Execute tool via canonical name
        res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"})
        self.assertIn("ERR:", res)

        # Execute tool via alias
        res_alias = await execute_tool("cat", {"path": "nonexistent_abc_123.txt"})
        self.assertIn("ERR:", res_alias)

        # Test additional aliases resolution
        from tools.registry import ALIAS_MAP

        self.assertEqual(ALIAS_MAP["edit_file"], "edit")
        self.assertEqual(ALIAS_MAP["spawn_subagent"], "invoke_subagent")
        self.assertEqual(ALIAS_MAP["fetch"], "web_fetch")
        self.assertEqual(ALIAS_MAP["patch"], "edit")
        self.assertEqual(ALIAS_MAP["get"], "web_fetch")
        self.assertEqual(ALIAS_MAP["shells"], "manage_shell")
        self.assertNotIn("multi_edit", ALIAS_MAP)

    async def test_execute_tool_multi_edit_routes_to_multiedit_tool(self):
        # Canonical 'multi_edit' must reach MultiEditTool, not be aliased to 'edit'
        from tools.edit import MultiEditTool
        from tools.registry import REGISTRY

        self.assertIs(REGISTRY["multi_edit"], MultiEditTool)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("allow", "")
        with (
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            patch.object(MultiEditTool, "execute", new=AsyncMock(return_value="MULTI_EDIT_OK")),
        ):
            res = await execute_tool("multi_edit", {"target_file": "x.py", "replacement_chunks": []})
        self.assertEqual(res, "MULTI_EDIT_OK")

    async def test_execute_tool_execution_exception(self):
        from core.permission_manager import PermissionManager

        PermissionManager.get_instance().set_session_override("read", "allow")
        with patch.object(REGISTRY["read"], "execute", side_effect=RuntimeError("Execute failed")):
            res = await execute_tool("read", {"path": "foo.txt"})
            self.assertIn("ERR: execute 'read': Execute failed", res)

    async def test_execute_tool_unknown_with_alias_hint(self):
        # Match that resolves to an alias target
        res = await execute_tool("catx", None)
        self.assertIn("ERR: unknown 'catx'", res)
        self.assertIn("Did you mean 'cat' (target: read)?", res)

    async def test_execute_tool_unknown_with_direct_hint(self):
        # Match that maps directly to a registry tool name
        res = await execute_tool("creats", None)
        self.assertIn("ERR: unknown 'creats'", res)
        self.assertIn("Did you mean 'create'?", res)
        self.assertNotIn("target:", res)

    async def test_execute_tool_unknown_no_hint(self):
        res = await execute_tool("zzzzzzzzz_unknown", None)
        self.assertEqual(res, "ERR: unknown 'zzzzzzzzz_unknown'")

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
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            mock_app = MagicMock()
            mock_app.role = "plan"
            res = await execute_tool("mcp_tool_test", {"arg": "val"}, app=mock_app)
            self.assertIn("ERR: tool 'mcp_tool_test' disabled in plan role", res)

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
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            res = await execute_tool("exposed_mcp_tool", {"foo": "bar"})
            self.assertEqual(res, "MCP Executed Output")
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
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            res = await execute_tool("faulty_mcp", {})
            self.assertIn("ERR: mcp 'faulty_mcp': MCP connection failed", res)

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
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry),
        ):
            res = await execute_tool("none_mcp", {})
            self.assertEqual(res, "ERR: unknown 'none_mcp'")

    def test_normalize_tool_args_non_dict_chunk(self):
        # Non-dict entries inside the edits list must pass through untouched.
        norm = normalize_tool_args("multi_edit", {"edits": ["raw", {"search": "a", "replace": "b"}]})
        self.assertEqual(norm["edits"][0], "raw")
        self.assertEqual(norm["edits"][1]["old_str"], "a")
        self.assertEqual(norm["edits"][1]["new_str"], "b")

    def _mock_mode(self, name="action"):
        mock_mode_def = MagicMock()
        mock_mode_def.name = name
        mock_mode_def.disallowed_tools = []
        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def
        return patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry)

    async def test_execute_tool_permission_denied(self):
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("deny", "Policy blocks it")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"})
            self.assertEqual(res, "ERR: denied 'read': by permission policy")

    async def test_execute_tool_permission_ask_confirmed(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"}, app=mock_app)
        self.assertIn("ERR:", res)
        mock_app.confirm_permission.assert_awaited_once()

    async def test_execute_tool_permission_ask_always_allow(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=True)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"}, app=mock_app)
        self.assertIn("ERR:", res)
        mock_app.confirm_permission.assert_awaited_once()

    async def test_execute_tool_permission_ask_denied_by_user(self):
        mock_app = MagicMock()
        mock_app.confirm_permission = AsyncMock(return_value=False)
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"}, app=mock_app)
        self.assertEqual(res, "ERR: denied 'read': by user")

    async def test_execute_tool_permission_ask_no_app(self):
        # No interactive app available -> fall back to a textual denial.
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "No interactive app")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"})
        self.assertEqual(res, "ERR: denied 'read': requires user confirmation (No interactive app)")

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

        with patch("core.mcp_manager.get_mcp_manager", return_value=_FakeMCPManager()), self._mock_mode():
            res = await execute_tool("async_mcp", {"q": 1})
        self.assertEqual(res, "async mcp output")

    async def test_execute_tool_mcp_permission_denied(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_deny_tool"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("deny", "Policy blocks it")

        with (
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("mcp_deny_tool", {"arg": "val"})
        self.assertEqual(res, "ERR: denied 'mcp_deny_tool': by permission policy")
        mock_pm.check_permission.assert_called_once_with("mcp_deny_tool", {"arg": "val"})
        mock_mcp_mgr.call_tool.assert_not_called()

    async def test_execute_tool_mcp_permission_allow(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_allow_tool"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = "MCP ALLOWED OUTPUT"

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("allow", "")

        with (
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("mcp_allow_tool", {"arg": "val"})
        self.assertEqual(res, "MCP ALLOWED OUTPUT")
        mock_mcp_mgr.call_tool.assert_called_once_with("mcp_allow_tool", {"arg": "val"})

    async def test_execute_tool_mcp_permission_uses_exposed_name(self):
        # Collision-style exposed name ("server__tool"): the permission must be
        # checked under the exposed name, not the raw caller name.
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "gh__search"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("deny", "Policy blocks it")

        with (
            patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr),
            patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm),
            self._mock_mode(),
        ):
            res = await execute_tool("gh__search", {"q": "x"})
        self.assertEqual(res, "ERR: denied 'gh__search': by permission policy")
        mock_pm.check_permission.assert_called_once_with("gh__search", {"q": "x"})


if __name__ == "__main__":
    unittest.main()
