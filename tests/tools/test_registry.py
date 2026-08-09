import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tools.registry import REGISTRY, execute_tool, get_default_tools, normalize_tool_args, normalize_tool_name


class TestRegistry(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from core.permission_manager import PermissionManager
        PermissionManager.get_instance().set_session_override("call_mcp", "allow")

    def test_normalize_tool_name(self):
        self.assertEqual(normalize_tool_name("subagent"), "invoke_subagent")
        self.assertEqual(normalize_tool_name("view_file"), "read")
        self.assertEqual(normalize_tool_name("write_to_file"), "create")
        self.assertEqual(normalize_tool_name("unknown_tool"), "unknown_tool")
        self.assertEqual(normalize_tool_name(""), "")

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
        norm_multi = normalize_tool_args("multi_edit", {
            "file": "baz.py",
            "chunks": [{"search": "a", "replace": "b"}]
        })
        self.assertEqual(norm_multi["target_file"], "baz.py")
        self.assertEqual(norm_multi["edits"][0]["old_str"], "a")
        self.assertEqual(norm_multi["edits"][0]["new_str"], "b")

        # Test subagent session_id aliases (legacy task_id maps to canonical session_id)
        norm_invoke = normalize_tool_args("invoke_subagent", {"task_id": "sub-1", "role": "explorer"})
        self.assertEqual(norm_invoke["session_id"], "sub-1")
        self.assertEqual(norm_invoke["subagent_type"], "explorer")
        norm_manage = normalize_tool_args("manage_subagent", {"task_id": "sub-2", "id": "sub-2"})
        self.assertEqual(norm_manage["session_id"], "sub-2")
        # manage_task keeps its own task_id canonical arg untouched
        norm_task = normalize_tool_args("manage_task", {"task_id": "bash-1"})
        self.assertEqual(norm_task["task_id"], "bash-1")

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
        self.assertEqual(ALIAS_MAP["mcp"], "call_mcp")
        self.assertEqual(ALIAS_MAP["fetch"], "web_fetch")

    async def test_execute_tool_execution_exception(self):
        with patch.object(REGISTRY["read"], "execute", side_effect=RuntimeError("Execute failed")):
            res = await execute_tool("read", {"path": "foo.txt"})
            self.assertIn("ERR: execute 'read': Execute failed", res)

    async def test_execute_tool_unknown_with_alias_hint(self):
        # Match that resolves to an alias target
        res = await execute_tool("catx", None)
        self.assertIn("ERR: unknown tool 'catx'", res)
        self.assertIn("Did you mean 'cat' (target: read)?", res)

    async def test_execute_tool_unknown_with_direct_hint(self):
        # Match that maps directly to a registry tool name
        res = await execute_tool("creats", None)
        self.assertIn("ERR: unknown tool 'creats'", res)
        self.assertIn("Did you mean 'create'?", res)
        self.assertNotIn("target:", res)

    async def test_execute_tool_unknown_no_hint(self):
        res = await execute_tool("zzzzzzzzz_unknown", None)
        self.assertEqual(res, "ERR: unknown tool 'zzzzzzzzz_unknown'")

    async def test_execute_tool_mcp_disallowed_in_mode(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_tool_test"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_mode_def = MagicMock()
        mock_mode_def.name = "plan"
        mock_mode_def.disallowed_tools = ["mcp_tool_test"]

        mock_role_registry = MagicMock()
        mock_role_registry.get_role.return_value = mock_mode_def

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry):
            mock_app = MagicMock()
            mock_app.mode = "plan"
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

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry):
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

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry):
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

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.role_registry.RoleRegistry.get_instance", return_value=mock_role_registry):
            res = await execute_tool("none_mcp", {})
            self.assertEqual(res, "ERR: unknown tool 'none_mcp'")

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
            self.assertEqual(res, "ERR: tool 'read' denied by permission policy")

    async def test_execute_tool_permission_ask_confirmed(self):
        mock_app = MagicMock()
        mock_app.push_screen_wait = AsyncMock(return_value="allow")
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"}, app=mock_app)
        self.assertIn("ERR:", res)
        mock_app.push_screen_wait.assert_awaited_once()

    async def test_execute_tool_permission_ask_always_allow(self):
        mock_app = MagicMock()
        mock_app.push_screen_wait = AsyncMock(return_value="always_allow")
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"}, app=mock_app)
        self.assertIn("ERR:", res)
        mock_pm.set_session_override.assert_called_once_with("read", "allow")

    async def test_execute_tool_permission_ask_denied_by_user(self):
        mock_app = MagicMock()
        mock_app.push_screen_wait = AsyncMock(return_value="no")
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm please")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"}, app=mock_app)
        self.assertEqual(res, "ERR: tool 'read' execution denied by user")

    async def test_execute_tool_permission_ask_no_app(self):
        # No interactive app available -> fall back to a textual denial.
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "No interactive app")
        with patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("read", {"path": "foo.txt"})
        self.assertEqual(res, "ERR: tool 'read' requires user confirmation (No interactive app)")

    async def test_execute_tool_mcp_permission_denied(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_deny"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("deny", "MCP policy blocks it")
        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             self._mock_mode(), \
             patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("mcp_deny", {})
        self.assertEqual(res, "ERR: tool 'mcp_deny' denied by permission policy")

    async def test_execute_tool_mcp_permission_ask_no_app(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_ask"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm MCP call")
        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             self._mock_mode(), \
             patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("mcp_ask", {})
        self.assertEqual(res, "ERR: tool 'mcp_ask' requires user confirmation (Confirm MCP call)")

    async def test_execute_tool_mcp_permission_ask_always_allow(self):
        mock_app = MagicMock()
        mock_app.app = mock_app
        mock_app.push_screen_wait = AsyncMock(return_value="always_allow")
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_allow"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = "MCP Executed"
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm MCP call")
        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             self._mock_mode(), \
             patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("mcp_allow", {"x": 1}, app=mock_app)
        self.assertEqual(res, "MCP Executed")
        mock_pm.set_session_override.assert_called_once_with("call_mcp", "allow")

    async def test_execute_tool_mcp_permission_ask_denied_by_user(self):
        mock_app = MagicMock()
        mock_app.app = mock_app
        mock_app.push_screen_wait = AsyncMock(return_value="no")
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_no"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_pm = MagicMock()
        mock_pm.check_permission.return_value = ("ask", "Confirm MCP call")
        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             self._mock_mode(), \
             patch("core.permission_manager.PermissionManager.get_instance", return_value=mock_pm):
            res = await execute_tool("mcp_no", {}, app=mock_app)
        self.assertEqual(res, "ERR: tool 'mcp_no' execution denied by user")

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

        with patch("core.mcp_manager.get_mcp_manager", return_value=_FakeMCPManager()), \
             self._mock_mode():
            res = await execute_tool("async_mcp", {"q": 1})
        self.assertEqual(res, "async mcp output")


if __name__ == "__main__":
    unittest.main()
