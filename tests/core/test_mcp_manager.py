import json
import os
import shutil
import tempfile
import unittest

from core.mcp_manager import MCPManager
from widgets.commands import COMMAND_REGISTRY


class TestMCPManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_global_and_project_mcp_servers(self):
        mm = MCPManager(project_dir=self.test_dir)
        mm.global_file = os.path.join(self.test_dir, "global_mcp.json")

        # Write global MCP server
        with open(mm.global_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mcpServers": {
                        "global-server": {"command": "python", "args": ["-m", "mcp_server"], "disabled": False}
                    }
                },
                f,
            )

        # Write project MCP server
        os.makedirs(os.path.dirname(mm.project_file), exist_ok=True)
        with open(mm.project_file, "w", encoding="utf-8") as f:
            json.dump(
                {"mcpServers": {"project-server": {"command": "node", "args": ["server.js"], "disabled": False}}}, f
            )

        servers = mm.load_servers()
        names = [s["name"] for s in servers]
        self.assertIn("global-server", names)
        self.assertIn("project-server", names)

        # Test toggle
        state = mm.toggle_server("project-server")
        self.assertFalse(state)  # toggled from False -> True (disabled)

        updated_servers = mm.load_servers()
        p_server = next(s for s in updated_servers if s["name"] == "project-server")
        self.assertTrue(p_server["disabled"])

    def test_same_file_global_and_project(self):
        mcp_file = os.path.join(self.test_dir, "mcp.json")
        with open(mcp_file, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"my-server": {"command": "python", "args": ["-m", "mcp_server"]}}}, f)

        mm = MCPManager(project_dir=self.test_dir)
        mm.global_file = mcp_file
        mm.project_file = mcp_file

        servers = mm.load_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["name"], "my-server")
        self.assertEqual(servers[0]["scope"], "global")

    def test_mcp_command_registered(self):
        self.assertIn("/mcp", COMMAND_REGISTRY)

    def test_namespacing_and_timeout(self):
        mm = MCPManager(project_dir=self.test_dir)

        # Mock client tools
        class DummyClient:
            def __init__(self, name, tools):
                self.name = name
                self.tools = tools

            def start(self):
                return True

            def call_tool(self, tool_name, args, **kwargs):
                return f"result from {self.name}:{tool_name}"

        c1 = DummyClient("serverA", [{"name": "search", "description": "s1"}])
        c2 = DummyClient("serverB", [{"name": "search", "description": "s2"}])
        mm.clients = {"serverA": c1, "serverB": c2}

        # Mock load_servers
        mm.load_servers = lambda: [
            {"name": "serverA", "command": "python", "disabled": False},
            {"name": "serverB", "command": "python", "disabled": False},
        ]

        tools = mm.get_active_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("search", names)
        self.assertIn("serverB__search", names)

        res1 = mm.call_tool("search", {})
        self.assertEqual(res1, "result from serverA:search")

        res2 = mm.call_tool("serverB__search", {})
        self.assertEqual(res2, "result from serverB:search")

    def test_all_mcp_servers_are_active(self):
        mm = MCPManager(project_dir=self.test_dir)

        class DummyClient:
            def __init__(self, name, tools):
                self.name = name
                self.tools = tools

            def start(self):
                return True

            def call_tool(self, tool_name, args, **kwargs):
                return f"executed {self.name}:{tool_name}"

        c1 = DummyClient("serverA", [{"name": "search", "description": "search desc"}])
        c2 = DummyClient("serverB", [{"name": "search_tool", "description": "search desc"}])
        mm.clients = {"serverA": c1, "serverB": c2}

        mm.load_servers = lambda: [
            {"name": "serverA", "command": "python", "disabled": False},
            {"name": "serverB", "command": "python", "disabled": False},
        ]

        all_tools = mm.get_active_tools()
        self.assertEqual(len(all_tools), 2)

        snippet = mm.get_system_prompt_snippet()
        self.assertIn("## MCP Tools", snippet)
        self.assertIn("### serverA", snippet)
        self.assertIn("- `search`: search desc", snippet)
        self.assertIn("- `search_tool`: search desc", snippet)

        # Call tool explicitly via call_tool
        res = mm.call_tool("search_tool", {}, target_server="serverB")
        self.assertEqual(res, "executed serverB:search_tool")


class TestMCPManagerRegression(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_disabled_server_tools_are_not_exposed_or_callable(self):
        class DummyClient:
            def __init__(self, name):
                self.name = name
                self.tools = [{"name": "search", "description": "Search", "inputSchema": {"type": "object"}}]

            def call_tool(self, name, args, timeout=None):
                return f"{self.name}:{name}:{args}:{timeout}"

        mm = MCPManager(project_dir=self.test_dir)
        mm.clients = {"enabled": DummyClient("enabled"), "disabled": DummyClient("disabled")}
        mm.load_servers = lambda: [
            {"name": "enabled", "command": "python", "disabled": False},
            {"name": "disabled", "command": "python", "disabled": True},
        ]

        names = [t["function"]["name"] for t in mm.get_active_tools()]

        self.assertEqual(names, ["search"])
        self.assertEqual(mm.call_tool("search", {"q": "x"}), "enabled:search:{'q': 'x'}:None")
        self.assertIsNone(mm.call_tool("disabled__search", {"q": "x"}))

    def test_namespaced_capabilities_are_resolved(self):
        mm = MCPManager(project_dir=self.test_dir)
        mm.load_servers = lambda: [
            {
                "name": "serverA",
                "command": "python",
                "disabled": False,
                "capabilities": {"serverA__search": ["network", "read"]},
            }
        ]

        self.assertEqual(mm.get_capabilities_for_exposed_tool("serverA__search"), ["network", "read"])


class TestMCPProcessClientAndExtra(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_get_mcp_manager_singleton(self):
        from core.mcp_manager import get_mcp_manager

        inst1 = get_mcp_manager(self.test_dir)
        self.assertEqual(inst1.project_dir, os.path.realpath(self.test_dir))
        dir2 = tempfile.mkdtemp()
        try:
            inst2 = get_mcp_manager(dir2)
            self.assertEqual(inst2.project_dir, os.path.realpath(dir2))
        finally:
            shutil.rmtree(dir2)

    def test_list_changed_notification(self):
        from unittest.mock import MagicMock, patch

        from core.mcp_manager import MCPProcessClient

        client = MCPProcessClient("test", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client.process.stdout.fileno.return_value = 1

        client._buffer = (
            json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}})
            + "\n"
        )
        with patch.object(client, "fetch_tools") as mock_fetch:
            res = client._read_response(req_id=1, timeout=0.1)
            mock_fetch.assert_called_once()
            self.assertEqual(res, {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_client_start_initialize_and_call_tool(self):
        from unittest.mock import MagicMock

        from core.mcp_manager import MCPProcessClient

        client = MCPProcessClient("mock_server", "echo hello", cwd=self.test_dir, env={"TEST_ENV": "1"})

        # Mock Popen process with pipes
        mock_proc = MagicMock()
        mock_stdin = MagicMock()
        mock_stdout = MagicMock()
        mock_stdout.fileno.return_value = 10
        mock_proc.stdin = mock_stdin
        mock_proc.stdout = mock_stdout
        mock_proc.poll.return_value = None

        with unittest.mock.patch("subprocess.Popen", return_value=mock_proc):
            with unittest.mock.patch("os.set_blocking"):
                # Mock _read_response for initialize and list_tools
                init_res = {"jsonrpc": "2.0", "id": 1, "result": {"capabilities": {}}}
                list_res = {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "result": {"tools": [{"name": "foo", "description": "foo tool"}]},
                }

                read_responses = [init_res, list_res]

                def mock_read(req_id=None, timeout=None):
                    if read_responses:
                        return read_responses.pop(0)
                    return None

                client._read_response = mock_read
                started = client.start()
                self.assertTrue(started)
                self.assertEqual(len(client.tools), 1)
                self.assertEqual(client.tools[0]["name"], "foo")

                # Test call_tool success
                call_res = {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "result": {"content": [{"type": "text", "text": "hello result"}]},
                }
                read_responses = [call_res, list_res]
                res_str = client.call_tool("foo", {"arg": 1})
                self.assertEqual(res_str, "hello result")

                # Test call_tool error response
                err_res = {"jsonrpc": "2.0", "id": 4, "error": {"message": "Invalid args"}}
                read_responses = [err_res]
                res_err = client.call_tool("foo", {})
                self.assertIn("MCP Error: Invalid args", res_err)

                # Test call_tool no response timeout
                read_responses = [None]
                res_timeout = client.call_tool("foo", {})
                self.assertIn("No response from MCP server", res_timeout)

                # Test stop
                client.stop()
                self.assertTrue(client._stopped)

    def test_out_of_order_responses_buffering(self):
        from core.mcp_manager import MCPProcessClient

        client = MCPProcessClient("buffer_test", "echo 1")
        client.process = unittest.mock.MagicMock()
        client.process.stdout = unittest.mock.MagicMock()

        # Simulate out of order json lines in buffer
        # e.g., line 1 is id=2, line 2 is id=1
        client._buffer = (
            json.dumps({"jsonrpc": "2.0", "id": 2, "result": "res2"})
            + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 1, "result": "res1"})
            + "\n"
        )

        # Request id=1
        res1 = client._read_response(req_id=1)
        self.assertIsNotNone(res1)
        self.assertEqual(res1["id"], 1)
        self.assertIn(2, client._pending_responses)

        # Request id=2 (should come from _pending_responses)
        res2 = client._read_response(req_id=2)
        self.assertIsNotNone(res2)
        self.assertEqual(res2["id"], 2)

    def test_client_call_tool_not_running(self):
        from core.mcp_manager import MCPProcessClient

        client = MCPProcessClient("dead_server", ["invalid_command_xyz_12345"])
        client.start = lambda: False
        res = client.call_tool("foo", {})
        self.assertIn("is not running", res)


class TestAsyncMCP(unittest.IsolatedAsyncioTestCase):
    async def test_async_cancellation_does_not_deadlock(self):
        import asyncio
        from unittest.mock import MagicMock

        from core.mcp_manager import MCPProcessClient

        test_dir = tempfile.mkdtemp()
        try:
            client = MCPProcessClient("mock_async", "echo hello", cwd=test_dir)
            client.process = MagicMock()
            client.process.poll.return_value = None
            client.process.stdin = MagicMock()

            task = asyncio.create_task(client.call_tool_async("run_code", {"cell": 1}))

            async def _await_pending():
                while not client._pending_futures:
                    await asyncio.sleep(0)
                return True

            await asyncio.wait_for(_await_pending(), timeout=5.0)

            self.assertIn(1, client._pending_futures)
            task.cancel()

            with self.assertRaises(asyncio.CancelledError):
                await task

            self.assertNotIn(1, client._pending_futures)
        finally:
            shutil.rmtree(test_dir)

    async def test_call_tool_async_after_sync_start(self):
        import sys

        from core.mcp_manager import MCPProcessClient

        # Python script that reads JSON-RPC requests from stdin and responds
        script = (
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    data = json.loads(line)\n"
            "    msg_id = data.get('id')\n"
            "    method = data.get('method')\n"
            "    if method == 'initialize':\n"
            "        res = {'jsonrpc': '2.0', 'id': msg_id, 'result': {'protocolVersion': '2024-11-05'}}\n"
            "    elif method == 'tools/list':\n"
            "        res = {'jsonrpc': '2.0', 'id': msg_id, 'result': {'tools': [{'name': 'echo', 'description': 'Echo'}]}}\n"
            "    elif method == 'tools/call':\n"
            "        res = {'jsonrpc': '2.0', 'id': msg_id, 'result': {'content': [{'type': 'text', 'text': 'ok'}]}}\n"
            "    else:\n"
            "        continue\n"
            "    sys.stdout.write(json.dumps(res) + '\\n')\n"
            "    sys.stdout.flush()\n"
        )
        test_dir = tempfile.mkdtemp()
        try:
            client = MCPProcessClient("mock_py", [sys.executable, "-c", script], cwd=test_dir)
            self.assertTrue(client.start())
            self.assertEqual(len(client.tools), 1)

            res = await client.call_tool_async("echo", {})
            self.assertEqual(res, "ok")
            client.stop()
        finally:
            shutil.rmtree(test_dir)


if __name__ == "__main__":
    unittest.main()
