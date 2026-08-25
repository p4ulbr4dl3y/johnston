import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.mcp import MCPManager, MCPProcessClient
from core.infrastructure.mcp.manager import DEFAULT_MCP_CALL_TIMEOUT
from widgets.app.dispatch import COMMAND_REGISTRY


def make_manager(project_dir=None) -> MCPManager:
    """Build a manager without triggering __init__ (avoids real config writes)."""
    m = MCPManager.__new__(MCPManager)
    m.project_dir = os.path.realpath(project_dir or os.getcwd())
    m.project_file = os.path.join(m.project_dir, ".johnston", "mcp.json")
    m.global_file = os.path.join(m.project_dir, "global_mcp.json")
    m.clients = {}
    m._tools_refresh_time = 0.0
    m._tools_refresh_task = None
    m._servers_cache_signature = None
    m._servers_cache = []
    m._warned_broken_config_files = set()
    m._global_config_ensured = True
    m._start_locks = {}
    m._generation = 0
    m._server_errors = {}
    return m


def fake_proc():
    p = MagicMock()
    p.poll.return_value = None
    p.stdin = MagicMock()
    p.stdout = MagicMock()
    p.stderr = MagicMock()
    return p


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
                        "global-server": {"command": "python", "args": ["-m", "mcp_server"]}
                    }
                },
                f,
            )

        # Write project MCP server
        os.makedirs(os.path.dirname(mm.project_file), exist_ok=True)
        with open(mm.project_file, "w", encoding="utf-8") as f:
            json.dump(
                {"mcpServers": {"project-server": {"command": "node", "args": ["server.js"]}}}, f
            )

        servers = mm.load_servers()
        names = [s["name"] for s in servers]
        self.assertIn("global-server", names)
        self.assertIn("project-server", names)

        # Test toggle
        state = mm.toggle_server("project-server")
        self.assertFalse(state)  # toggled from enabled -> disabled

        updated_servers = mm.load_servers()
        p_server = next(s for s in updated_servers if s["name"] == "project-server")
        self.assertFalse(p_server["enabled"])

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

            def stop(self):
                pass

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, tool_name, args, **kwargs):
                return f"result from {self.name}:{tool_name}"

        c1 = DummyClient("serverA", [{"name": "search", "description": "s1"}])
        c2 = DummyClient("serverB", [{"name": "search", "description": "s2"}])
        mm.clients = {"serverA": c1, "serverB": c2}

        # Mock load_servers
        mm.load_servers = lambda: [
            {"name": "serverA", "command": "python"},
            {"name": "serverB", "command": "python"},
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

            def stop(self):
                pass

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, tool_name, args, **kwargs):
                return f"executed {self.name}:{tool_name}"

        c1 = DummyClient("serverA", [{"name": "search", "description": "search desc"}])
        c2 = DummyClient("serverB", [{"name": "search_tool", "description": "search desc"}])
        mm.clients = {"serverA": c1, "serverB": c2}

        mm.load_servers = lambda: [
            {"name": "serverA", "command": "python"},
            {"name": "serverB", "command": "python"},
        ]

        all_tools = mm.get_active_tools()
        self.assertEqual(len(all_tools), 2)

        snippet = mm.get_system_prompt_snippet()
        self.assertIn("## MCP Tools", snippet)
        self.assertIn("- serverA: search", snippet)
        self.assertIn("- serverB: search_tool", snippet)

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

            def stop(self):
                pass

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, name, args, timeout=None):
                return f"{self.name}:{name}:{args}:{timeout}"

        mm = MCPManager(project_dir=self.test_dir)
        mm.clients = {"enabled": DummyClient("enabled"), "disabled": DummyClient("disabled")}
        mm.load_servers = lambda: [
            {"name": "enabled", "command": "python"},
            {"name": "disabled", "command": "python", "enabled": False},
        ]

        names = [t["function"]["name"] for t in mm.get_active_tools()]

        self.assertEqual(names, ["search"])
        # A default tools/call timeout is applied when none is given, so a hung
        # server can never stall the agent turn forever.
        self.assertEqual(
            mm.call_tool("search", {"q": "x"}),
            f"enabled:search:{{'q': 'x'}}:{DEFAULT_MCP_CALL_TIMEOUT}",
        )
        self.assertIsNone(mm.call_tool("disabled__search", {"q": "x"}))

    def test_namespaced_capabilities_are_resolved(self):
        mm = MCPManager(project_dir=self.test_dir)
        mm.load_servers = lambda: [
            {
                "name": "serverA",
                "command": "python",
                "capabilities": {"serverA__search": ["network", "read"]},
            }
        ]

        self.assertEqual(mm.get_capabilities_for_exposed_tool("serverA__search"), ["network", "read"])

    def test_invalid_command_entries_are_skipped_without_crashing(self):
        mm = MCPManager(project_dir=self.test_dir)
        mm.global_file = os.path.join(self.test_dir, "global_mcp.json")
        with open(mm.global_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mcpServers": {
                        "good": {"command": "python", "args": ["-m", "srv"]},
                        "bad-int": {"command": 42},
                        "bad-list": {"command": [1, 2]},
                        "no-cmd": {"args": []},
                        "bad-env": {"command": "node", "env": "not-a-dict"},
                        "bad-args": {"command": "node", "args": "-x"},
                    }
                },
                f,
            )

        servers = mm.load_servers()
        by_name = {s["name"]: s for s in servers}
        # Broken commands are dropped entirely; valid commands keep their raw
        # shape, and mis-typed env/args are sanitized away (server kept).
        self.assertEqual(sorted(by_name), ["bad-args", "bad-env", "good"])
        self.assertEqual(by_name["good"]["command"], "python")
        self.assertEqual(by_name["good"]["args"], ["-m", "srv"])
        self.assertEqual(by_name["bad-args"]["args"], [])
        self.assertIsNone(by_name["bad-env"]["env"])

    def test_url_only_server_skipped_with_clear_warning(self):
        # stdio-only client: an HTTP/SSE 'url' entry can never be served, so it
        # is skipped with an explicit warning instead of "invalid command None".
        mm = MCPManager(project_dir=self.test_dir)
        mm.global_file = os.path.join(self.test_dir, "global_mcp.json")
        with open(mm.global_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "mcpServers": {
                        "remote": {"url": "https://example.com/sse"},
                        "local": {"command": "python", "args": ["-m", "srv"]},
                    }
                },
                f,
            )

        with self.assertLogs("core.infrastructure.mcp.manager", level="WARNING") as captured:
            servers = mm.load_servers()

        self.assertEqual([s["name"] for s in servers], ["local"])
        self.assertTrue(any("'url' transport" in message for message in captured.output))

    def test_constructor_does_not_write_real_global_config(self):
        # Regression: instantiating the manager must not scribble the default
        # config into the user's real ~/.johnston/mcp.json (was a constructor
        # side effect). Merely constructing with a tmp project dir is enough;
        # the lazy ensure only touches the (test-overridden) global_file.
        real_global = os.path.join(os.path.expanduser("~"), ".johnston", "mcp.json")
        before = os.path.exists(real_global)
        MCPManager(project_dir=self.test_dir)
        self.assertEqual(os.path.exists(real_global), before)


class TestMCPProcessClientAndExtra(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_get_mcp_manager_singleton(self):
        from core.infrastructure.mcp import get_mcp_manager

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

        from core.infrastructure.mcp import MCPProcessClient

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

        from core.infrastructure.mcp import MCPProcessClient

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
                self.assertIn("ERR: mcp 'foo': Invalid args", res_err)

                # Test call_tool no response timeout
                read_responses = [None]
                res_timeout = client.call_tool("foo", {})
                self.assertIn("No response from MCP server", res_timeout)

                # Test stop
                client.stop()
                self.assertTrue(client._stopped)

    def test_out_of_order_responses_buffering(self):
        from core.infrastructure.mcp import MCPProcessClient

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
        from core.infrastructure.mcp import MCPProcessClient

        client = MCPProcessClient("dead_server", ["invalid_command_xyz_12345"])
        client.start = lambda: False
        res = client.call_tool("foo", {})
        self.assertIn("is not running", res)


class TestAsyncMCP(unittest.IsolatedAsyncioTestCase):
    @pytest.mark.slow
    async def test_async_cancellation_does_not_deadlock(self):
        import asyncio
        from unittest.mock import MagicMock

        from core.infrastructure.mcp import MCPProcessClient

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

        from core.infrastructure.mcp import MCPProcessClient

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


class ProcessLifecycleEdge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_start_missing_binary_returns_false(self):
        client = MCPProcessClient("ghost", ["/nonexistent/binary_xyz_42"], cwd=self.tmp)
        with patch("subprocess.Popen", side_effect=FileNotFoundError("no such file")):
            ok = client.start()
        self.assertFalse(ok)
        self.assertIn("Process start failed", client.last_error or "")

    def test_double_start_is_idempotent(self):
        proc = fake_proc()
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        with patch("subprocess.Popen", return_value=proc):
            client.process = proc
            client._stopped = False
            # Second start while already running should not spawn a new process.
            with patch.object(client, "_initialize", return_value=True) as init:
                ok = client.start()
                self.assertTrue(ok)
                init.assert_not_called()
        self.assertIs(client.process, proc)

    def test_double_stop_is_idempotent(self):
        proc = fake_proc()
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        client.process = proc
        client.stop()  # first stop
        client.stop()  # second stop must not raise
        self.assertIsNone(client.process)
        self.assertTrue(client._stopped)

    def test_stop_not_started_is_safe(self):
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        client.stop()  # no process -> no exception
        self.assertTrue(client._stopped)

    def test_start_after_stop_restarts(self):
        proc = fake_proc()
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        with patch("subprocess.Popen", return_value=proc):
            client.process = proc
            client.stop()
            with patch.object(client, "_initialize", return_value=True):
                self.assertTrue(client.start())
        self.assertEqual(client._stopped, False)


class ConfigEdge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_broken_json_config_returns_no_servers(self):
        m = make_manager(self.tmp)
        with open(m.global_file, "w", encoding="utf-8") as f:
            f.write("{ not valid json !!! ")
        self.assertEqual(m.load_servers(), [])

    def test_missing_config_returns_empty(self):
        m = make_manager(self.tmp)
        self.assertEqual(m.load_servers(), [])

    def test_empty_mcp_servers_field_returns_empty(self):
        m = make_manager(self.tmp)
        with open(m.global_file, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {}}, f)
        self.assertEqual(m.load_servers(), [])

    def test_server_without_command_is_skipped(self):
        m = make_manager(self.tmp)
        with open(m.global_file, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"noCmd": {"args": []}}}, f)
        tools = m.get_active_tools()
        self.assertEqual(tools, [])
        # no client should have been spawned
        self.assertEqual(len(list(m.clients.values())), 0)

    def test_project_overrides_global_same_name(self):
        m = make_manager(self.tmp)
        with open(m.global_file, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"dup": {"command": "g", "scope": "global"}}}, f)
        os.makedirs(os.path.dirname(m.project_file), exist_ok=True)
        with open(m.project_file, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"dup": {"command": "p"}}}, f)
        servers = m.load_servers()
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["command"], "p")
        self.assertEqual(servers[0]["scope"], "project")

    def test_env_with_secret_not_in_last_error(self):
        client = MCPProcessClient(
            "s", ["/nope"], cwd=self.tmp, env={"API_KEY": "super_secret_12345"}
        )
        with patch("subprocess.Popen", side_effect=FileNotFoundError("boom")):
            client.start()
        self.assertNotIn("super_secret_12345", str(client.last_error))


class ToolSchemaEdge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tool_without_name_is_skipped(self):
        m = make_manager(self.tmp)
        c = MagicMock()
        c.tools = [{"description": "no name"}, {"name": "", "description": "empty"}]
        c.start.return_value = True
        m.clients["s"] = c
        m.load_servers = lambda: [{"name": "s", "command": "python"}]
        tools = m.get_active_tools()
        self.assertEqual(tools, [])

    def test_missing_input_schema_defaults(self):
        m = make_manager(self.tmp)
        c = MagicMock()
        c.tools = [{"name": "t", "description": "d"}]
        c.start.return_value = True
        m.clients["s"] = c
        m.load_servers = lambda: [{"name": "s", "command": "python"}]
        tools = m.get_active_tools()
        self.assertEqual(tools[0]["function"]["parameters"], {"type": "object", "properties": {}})

    def test_call_tool_with_none_args_does_not_crash(self):
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        client.process = fake_proc()
        with patch.object(client, "_send"), patch.object(client, "_read_response", return_value=None):
            res = client.call_tool("t", None)
        self.assertIn("No response", res)

    def test_call_tool_huge_args_serializes(self):
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        client.process = fake_proc()
        big = {"data": "x" * 100000}
        with patch.object(client, "_send") as send, patch.object(client, "_read_response", return_value=None):
            client.call_tool("t", big)
        # First send is the tools/call; later sends are the stale-tools refresh.
        sent = send.call_args_list[0][0][0]
        self.assertEqual(sent["method"], "tools/call")
        self.assertEqual(sent["params"]["arguments"], big)

    def test_call_tool_nonexistent_returns_none(self):
        m = make_manager(self.tmp)
        m.load_servers = lambda: []
        self.assertIsNone(m.call_tool("does_not_exist", {}))


class TransportEdge(unittest.TestCase):
    def test_malformed_lines_are_skipped(self):
        client = MCPProcessClient("s", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._buffer = (
            "not json at all\n"
            '{"jsonrpc": "1.0"}\n'  # valid json but not a dict? still dict
            '{"jsonrpc": "2.0", "id": 7, "result": "ok"}\n'
        )
        res = client._read_response(req_id=7, timeout=0.1)
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], 7)

    def test_response_without_id_is_dropped(self):
        client = MCPProcessClient("s", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._buffer = '{"jsonrpc": "2.0", "result": "no-id"}\n'
        res = client._read_response(req_id=1, timeout=0.1)
        self.assertIsNone(res)

    def test_out_of_order_and_unpaired_id(self):
        client = MCPProcessClient("s", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        client._buffer = (
            '{"jsonrpc": "2.0", "id": 99, "result": "unpaired"}\n'
            '{"jsonrpc": "2.0", "id": 2, "result": "r2"}\n'
            '{"jsonrpc": "2.0", "id": 1, "result": "r1"}\n'
        )
        r1 = client._read_response(req_id=1, timeout=0.1)
        self.assertEqual(r1["id"], 1)
        r2 = client._read_response(req_id=2, timeout=0.1)
        self.assertEqual(r2["id"], 2)
        self.assertIn(99, client._pending_responses)


class BugTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for fixed MCP bugs."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    async def test_failed_start_does_not_leak_cached_client(self):
        # A client whose async start reported ok=False must be torn down and
        # never remain cached with a (possibly) running subprocess. Uses a real
        # awaitable mock so the ok=False branch is the one exercised (the old
        # plain MagicMock made the test pass via a TypeError instead).
        m = make_manager(self.tmp)
        m.load_servers = lambda: [{"name": "bad", "command": "python"}]

        failed = MagicMock()
        failed.start_async = AsyncMock(return_value=False)
        failed.stop_async = AsyncMock()
        failed.last_error = "boom"

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=failed) as mk:
            tools = await m.get_active_tools_async()

        self.assertEqual(tools, [])
        self.assertEqual(mk.call_count, 1)
        self.assertNotIn("bad", m.clients)
        failed.stop_async.assert_awaited_once()

    async def test_start_timeout_does_not_leak_cached_client(self):
        # A client whose async start times out past the per-server deadline must
        # be torn down too, with a descriptive last_error. The mocked start
        # raises asyncio.TimeoutError so the timeout branch is genuinely
        # exercised without waiting out the real 15s deadline.
        m = make_manager(self.tmp)
        m.load_servers = lambda: [{"name": "slow", "command": "python"}]

        hanging = MagicMock()
        hanging.last_error = None

        async def raise_timeout():
            raise asyncio.TimeoutError("simulated hang")

        hanging.start_async = AsyncMock(side_effect=raise_timeout)
        hanging.stop_async = AsyncMock()

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=hanging):
            tools = await m.get_active_tools_async()

        self.assertEqual(tools, [])
        self.assertNotIn("slow", m.clients)
        self.assertIn("timed out", hanging.last_error or "")
        hanging.stop_async.assert_awaited_once()
        # The fatal error must survive client teardown so the UI keeps an
        # ERR/Timeout badge instead of a bare ON row.
        self.assertIn("timed out", m._server_errors.get("slow", ""))
        self.assertEqual(m.get_server_status("slow")["error"], m._server_errors["slow"])

    async def test_call_async_after_stop_does_not_raise(self):
        # Regression: stop() failing the pending future (RuntimeError) while an
        # async call is awaiting must surface as a graceful error string, never
        # an uncaught exception.
        async def scenario():
            client = MCPProcessClient("s", "echo", cwd=self.tmp)
            client.process = fake_proc()
            with patch.object(client, "_start_async_reader"):
                task = asyncio.create_task(client.call_tool_async("t", {}))
                while not client._pending_futures:
                    await asyncio.sleep(0)
                client.stop()
                try:
                    res = await task
                except asyncio.CancelledError:
                    return "cancelled"
            self.assertIsInstance(res, str)
            return res

        res = await scenario()
        self.assertIn("ERR: mcp 't': MCP server 's' stopped", res)


    async def test_warm_server_async_bypasses_freshness_window(self):
        # Regression: enabling a server right after a recent global warmup used
        # to leave it unstarted for up to 30s — ensure_tools_ready_async hit
        # its freshness window and skipped the fetch entirely, so the /mcp row
        # stayed a bare ON with no tool count. The targeted warm must start the
        # server regardless of that window.
        m = make_manager(self.tmp)
        m.load_servers = lambda: [{"name": "x", "command": "python", "cwd": self.tmp}]
        m._tools_refresh_time = time.monotonic()  # a warmup finished just now

        client = MagicMock()
        client.start_async = AsyncMock(return_value=True)
        client.stop_async = AsyncMock()
        client.last_error = None
        client.tools = [{"name": "t1"}]

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=client) as mk:
            await m.warm_server_async("x")

        mk.assert_called_once()
        self.assertIn("x", m.clients)
        self.assertNotIn("x", m._server_errors)

    async def test_warm_server_async_ignores_disabled_or_unknown(self):
        m = make_manager(self.tmp)
        m.load_servers = lambda: [
            {"name": "off", "command": "python", "enabled": False},
            {"name": "other", "command": "python"},
        ]
        with patch("core.infrastructure.mcp.manager.MCPProcessClient") as mk:
            await m.warm_server_async("off")
            await m.warm_server_async("missing")
        mk.assert_not_called()
        self.assertEqual(m.clients, {})

    async def test_failed_start_error_survives_for_status_and_clears_on_success(self):
        # The failed client is torn down and popped from clients; its fatal
        # error must still reach get_server_status (UI ERR badge), then vanish
        # once a later start succeeds.
        m = make_manager(self.tmp)
        servers = [{"name": "bad", "command": "python"}]
        m.load_servers = lambda: servers

        failed = MagicMock()
        failed.start_async = AsyncMock(return_value=False)
        failed.stop_async = AsyncMock()
        failed.last_error = "Process start failed: boom"

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=failed):
            await m.get_active_tools_async()

        self.assertEqual(m._server_errors.get("bad"), "Process start failed: boom")
        self.assertIs(m.clients.get("bad"), None)
        self.assertEqual(m.get_server_status("bad")["error"], "Process start failed: boom")

        ok_client = MagicMock()
        ok_client.start_async = AsyncMock(return_value=True)
        ok_client.stop_async = AsyncMock()
        ok_client.last_error = None
        ok_client.tools = [{"name": "t1"}]

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=ok_client):
            await m.warm_server_async("bad")

        self.assertNotIn("bad", m._server_errors)
        self.assertIn("bad", m.clients)
        self.assertEqual(m.get_server_status("bad")["error"], None)

    def test_disable_clears_remembered_start_error(self):
        # Disabling is deliberate, not a failure: any remembered start error
        # must be dropped so re-enabling renders a clean status.
        m = make_manager(self.tmp)
        with open(m.global_file, "w", encoding="utf-8") as f:
            json.dump({"mcpServers": {"srv": {"command": "py"}}}, f)
        m._server_errors["srv"] = "boom"

        self.assertFalse(m.toggle_server("srv"))
        self.assertNotIn("srv", m._server_errors)

    async def test_stop_all_variants_clear_remembered_start_errors(self):
        # Both teardown entrypoints reset per-server start errors together with
        # the clients, so no stale ERR badge survives a manager restart.
        m = make_manager(self.tmp)
        m._server_errors["a"] = "boom"
        m.stop_all()
        self.assertEqual(m._server_errors, {})

        m._server_errors["b"] = "boom"

        async def _never():
            await asyncio.Event().wait()

        m._tools_refresh_task = asyncio.create_task(_never())
        await m.stop_all_async()
        self.assertEqual(m._server_errors, {})
        # Cancellation is delivered on the next loop pass; awaiting it both
        # asserts it and retrieves the cancelled task cleanly.
        with self.assertRaises(asyncio.CancelledError):
            await m._tools_refresh_task

    def test_sync_get_active_tools_records_and_clears_start_error(self):
        # The sync fallback path must remember a fatal start error (for the UI
        # ERR badge) and clear it once the same server starts successfully.
        m = make_manager(self.tmp)
        servers = [{"name": "s", "command": "python", "args": []}]
        m.load_servers = lambda: servers

        failed = MagicMock()
        failed.start.return_value = False
        failed.last_error = "start failed"
        failed.tools = []
        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=failed):
            self.assertEqual(m.get_active_tools(), [])
        self.assertEqual(m._server_errors.get("s"), "start failed")
        self.assertNotIn("s", m.clients)

        ok = MagicMock()
        ok.start.return_value = True
        ok.last_error = None
        ok.tools = [{"name": "t1"}]
        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=ok):
            tools = m.get_active_tools()
        self.assertEqual([t["function"]["name"] for t in tools], ["t1"])
        self.assertNotIn("s", m._server_errors)


class NamespaceResolutionEdge(unittest.TestCase):
    """Exact-match-before-split resolution for tool names containing ``__``."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _manager_with_client(self, tools):
        m = make_manager(self.tmp)

        class DummyClient:
            def __init__(self, tools):
                self.tools = tools
                self.called = []

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, tool_name, arguments, timeout=None):
                self.called.append(tool_name)
                return f"called {tool_name}"

        client = DummyClient(tools)
        m.clients["db"] = client
        m.load_servers = lambda: [{"name": "db", "command": "python"}]
        return m, client

    def test_double_underscore_tool_name_not_confused_with_namespace(self):
        # Tool named "db__query" must resolve to itself, not to the "db" server
        # namespace split ("db" server + "query" tool).
        m, client = self._manager_with_client(
            [{"name": "query", "description": "q1"}, {"name": "db__query", "description": "q2"}]
        )
        res = m.call_tool("db__query", {})
        self.assertEqual(res, "called db__query")
        self.assertEqual(client.called, ["db__query"])

    def test_namespaced_exposed_name_still_resolves_via_split(self):
        # Collision case: plain "search" exists (unprefixed winner) so the
        # other server's exposed name is serverB__search; calls to the exposed
        # name still route to serverB.
        m = make_manager(self.tmp)

        class DummyClient:
            def __init__(self, name, tools):
                self.name = name
                self.tools = tools
                self.called = []

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, tool_name, arguments, timeout=None):
                self.called.append((self.name, tool_name))
                return f"called {self.name}:{tool_name}"

        cA = DummyClient("serverA", [{"name": "search", "description": "s"}])
        cB = DummyClient("serverB", [{"name": "search", "description": "s"}])
        m.clients = {"serverA": cA, "serverB": cB}
        m.load_servers = lambda: [
            {"name": "serverA", "command": "python"},
            {"name": "serverB", "command": "python"},
        ]

        self.assertEqual(m.call_tool("serverB__search", {}), "called serverB:search")
        self.assertEqual(cB.called, [("serverB", "search")])
        self.assertEqual(cA.called, [])


class AsyncNamingEdge(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    async def test_async_collision_naming_is_deterministic(self):
        # Namespace assignment must follow config order even though servers
        # start concurrently (old code raced on a shared seen_names dict).
        m = make_manager(self.tmp)
        m.load_servers = lambda: [
            {"name": "serverA", "command": "python"},
            {"name": "serverB", "command": "python"},
        ]

        class DummyClient:
            def __init__(self, tools):
                self.tools = tools

            def is_tools_stale(self, ttl=5.0):
                return False

            async def start_async(self):
                return True

            async def fetch_tools_async(self):
                return self.tools

        m.clients = {
            "serverA": DummyClient([{"name": "search", "description": "s"}]),
            "serverB": DummyClient([{"name": "search", "description": "s"}]),
        }

        tools = await m.get_active_tools_async()
        names = [t["function"]["name"] for t in tools]
        self.assertEqual(names, ["search", "serverB__search"])

    async def test_inflight_tools_refresh_task_is_reused(self):
        # A second ensure_tools_ready_async while the first warmup is still in
        # flight must reuse the task, never spawn an orphaned second one.
        m = make_manager(self.tmp)
        m.get_cached_tools = lambda: []
        started = 0
        release = asyncio.Event()

        async def slow_warmup():
            nonlocal started
            started += 1
            await release.wait()
            return []

        m.get_active_tools_async = slow_warmup

        t1 = asyncio.create_task(m.ensure_tools_ready_async())
        await asyncio.sleep(0)
        t2 = asyncio.create_task(m.ensure_tools_ready_async())
        await asyncio.sleep(0)
        release.set()
        await asyncio.gather(t1, t2)

        self.assertEqual(started, 1)


class ProcessClientRobustnessEdge(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_tools_fetch_stale_without_client_is_false(self):
        m = make_manager(self.tmp)
        self.assertFalse(m._tools_fetch_stale("ghost"))

    def test_stderr_is_drained_and_tail_captured(self):
        from io import StringIO

        client = MCPProcessClient("s", ["python", "-c", "x"], cwd=self.tmp)
        proc = fake_proc()
        proc.stderr = StringIO("line1\nline2\n")
        proc.stderr.fileno = lambda: 4
        client.process = proc
        client._spawn_stderr_drain()

        deadline = time.time() + 2.0
        while not client._stderr_tail and time.time() < deadline:
            time.sleep(0.01)

        self.assertIn("line1", client.stderr_tail())
        client.stop()
        self.assertIsNone(client.process)
        self.assertIsNone(client._stderr_thread)

    def test_stderr_drain_thread_is_skipped_for_mocked_process(self):
        # MagicMock streams must not spawn a spin-looping drain thread.
        client = MCPProcessClient("s", ["python", "-c", "x"], cwd=self.tmp)
        client.process = fake_proc()
        client._spawn_stderr_drain()
        self.assertIsNone(client._stderr_thread)

    async def test_async_restart_after_stop_recreates_reader(self):
        client = MCPProcessClient("s", "echo", cwd=self.tmp)
        with patch("subprocess.Popen", return_value=fake_proc()):
            with patch.object(client, "_initialize_async", new=AsyncMock(return_value=True)):
                ok = await client.start_async()
        self.assertTrue(ok)
        self.assertIsNotNone(client._read_task)

        client.stop()
        self.assertIsNone(client._read_task)

        with patch("subprocess.Popen", return_value=fake_proc()):
            with patch.object(client, "_initialize_async", new=AsyncMock(return_value=True)):
                ok2 = await client.start_async()
        self.assertTrue(ok2)
        # A fresh async reader must have been spawned for the new process.
        self.assertIsNotNone(client._read_task)
        client.stop()


class DefaultTimeoutEdge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_call_tool_applies_default_timeout(self):
        from core.infrastructure.mcp.manager import DEFAULT_MCP_CALL_TIMEOUT

        m = make_manager(self.tmp)
        seen = {}

        class DummyClient:
            tools = [{"name": "t", "description": "d"}]

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, tool_name, arguments, timeout=None):
                seen["timeout"] = timeout
                return "ok"

        m.clients["srv"] = DummyClient()
        m.load_servers = lambda: [{"name": "srv", "command": "python"}]

        self.assertEqual(m.call_tool("t", {}), "ok")
        self.assertEqual(seen["timeout"], DEFAULT_MCP_CALL_TIMEOUT)

    def test_call_tool_respects_explicit_timeout(self):
        m = make_manager(self.tmp)
        seen = {}

        class DummyClient:
            tools = [{"name": "t", "description": "d"}]

            def is_tools_stale(self, ttl=5.0):
                return False

            def call_tool(self, tool_name, arguments, timeout=None):
                seen["timeout"] = timeout
                return "ok"

        m.clients["srv"] = DummyClient()
        m.load_servers = lambda: [{"name": "srv", "command": "python"}]

        self.assertEqual(m.call_tool("t", {}, timeout=7.5), "ok")
        self.assertEqual(seen["timeout"], 7.5)


class ParallelCallsEdge(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_jsonrpc_message_type_does_not_crash_reader(self):
        # Test the deterministic sync parse path (the async loop rebuilds its own
        # queue internally, so a pre-seeded queue is the wrong seam to test).
        client = MCPProcessClient("s", "echo")
        client.process = MagicMock()
        client.process.stdout = MagicMock()
        # Batch (JSON list) messages are invalid JSON-RPC requests from a client
        # perspective; _parse_line returns None for them and they must be skipped.
        client._buffer = (
            'garbage not json\n'
            '[{"jsonrpc":"2.0","id":9}]\n'
            '{"jsonrpc":"2.0","id":5,"result":"ok"}\n'
        )
        res = client._read_response(req_id=5, timeout=0.1)
        self.assertEqual(res, {"jsonrpc": "2.0", "id": 5, "result": "ok"})

    async def test_async_call_timeout_leaves_no_pending_future(self):
        client = MCPProcessClient("s", "echo")
        client.process = fake_proc()
        with patch.object(client, "_start_async_reader"):
            res = await client.call_tool_async("t", {}, timeout=0.05)
        self.assertIn("No response", res)
        self.assertEqual(client._pending_futures, {})

    async def test_parallel_async_calls_get_distinct_ids_and_resolve(self):
        # Concurrent callers must never share a req_id: the _call_lock serializes
        # id allocation + future registration, and each future resolves with its
        # own response.
        client = MCPProcessClient("s", "echo")
        client.process = fake_proc()
        client.process.stdin = MagicMock()
        # Fresh tools cache so the per-call post-refresh does not add ids.
        client._tools_fetch_time = time.monotonic()
        with patch.object(client, "_start_async_reader"):
            seen_ids: list = []

            def on_write(line):
                req = json.loads(line)
                seen_ids.append(req["id"])
                fut = client._pending_futures.get(req["id"])
                if fut and not fut.done():
                    fut.set_result(
                        {"jsonrpc": "2.0", "id": req["id"], "result": {"content": [{"type": "text", "text": f"r{req['id']}"}]}}
                    )

            client.process.stdin.write.side_effect = on_write

            out = await asyncio.gather(*(client.call_tool_async("t", {}) for _ in range(5)))

        self.assertEqual(len(seen_ids), 5)
        self.assertEqual(len(set(seen_ids)), 5)
        self.assertEqual([f"r{i}" for i in seen_ids], list(out))
        # In real operation the async reader pops futures as responses arrive;
        # the mocked write path resolves them directly, so nothing may be left
        # pending/unresolved.
        self.assertEqual([f for f in client._pending_futures.values() if not f.done()], [])


class UiInteractionRegression(unittest.IsolatedAsyncioTestCase):
    """Regressions from the UI MCP audit: shared client creation, stop_all vs
    in-flight warmup, generation guard, cancel cleanup, public status accessors."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _server(self, name="srv"):
        return {"name": name, "command": "python", "args": [], "scope": "global"}

    async def test_concurrent_same_server_start_shares_one_client(self):
        # Two parallel warmup callers (lifecycle mount + MCP/permissions screen)
        # must never double-spawn npx: the per-server lock makes the second
        # caller reuse the first client.
        m = make_manager(self.tmp)
        ok_client = MagicMock()
        ok_client.start_async = AsyncMock(return_value=True)
        ok_client.stop_async = AsyncMock()
        ok_client.is_tools_stale = lambda ttl=5.0: False
        ok_client.tools = [{"name": "t1"}]
        ok_client.last_error = None

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=ok_client) as mk:
            results = await asyncio.gather(
                m._load_server_tools_async(self._server()),
                m._load_server_tools_async(self._server()),
            )

        self.assertEqual(mk.call_count, 1)
        self.assertEqual(list(m.clients), ["srv"])
        self.assertEqual(results, [[{"name": "t1"}], [{"name": "t1"}]])

    async def test_stop_all_cancels_inflight_warmup_and_stops_half_started_client(self):
        # A client is registered BEFORE its subprocess starts, so stop_all() can
        # always reach it; the cancelled warmup must not re-spawn anything after.
        m = make_manager(self.tmp)
        m.load_servers = lambda: [self._server()]

        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_start():
            started.set()
            await release.wait()
            return True

        client = MagicMock()
        client.start_async = AsyncMock(side_effect=slow_start)
        client.stop_async = AsyncMock()
        client.stop = MagicMock()
        client.tools = []
        client.last_error = None
        client.process = None

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=client):
            warmup = asyncio.create_task(m.ensure_tools_ready_async())
            await started.wait()
            # Half-started client is already reachable before its start returns.
            self.assertIn("srv", m.clients)

            m.stop_all()
            release.set()
            try:
                await m._tools_refresh_task
            except asyncio.CancelledError:
                pass
            await warmup

        client.stop.assert_called()
        self.assertEqual(m.clients, {})

    async def test_stop_during_lock_wait_prevents_recreation(self):
        # stop_all() bumps the generation; a warmup coroutine still waiting on
        # the per-server lock must abort instead of spawning a stale client.
        m = make_manager(self.tmp)
        lock = asyncio.Lock()
        await lock.acquire()
        m._start_locks = {"srv": lock}

        with patch("core.infrastructure.mcp.manager.MCPProcessClient") as mk:
            task = asyncio.create_task(m._load_server_tools_async(self._server()))
            await asyncio.sleep(0)
            m.stop_all()
            lock.release()
            res = await task

        self.assertEqual(res, [])
        mk.assert_not_called()
        self.assertEqual(m.clients, {})

    async def test_cancelled_start_cleans_up_subprocess(self):
        # Cancelling the warmup task while a server start is in flight must tear
        # down the spawned client, never orphan it.
        m = make_manager(self.tmp)
        m.load_servers = lambda: [self._server()]

        started = asyncio.Event()

        async def slow_start():
            started.set()
            await asyncio.sleep(30)
            return True

        client = MagicMock()
        client.start_async = AsyncMock(side_effect=slow_start)
        client.stop_async = AsyncMock()
        client.last_error = None
        client.process = None

        with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=client):
            task = asyncio.create_task(m._load_server_tools_async(self._server()))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        client.stop_async.assert_awaited_once()
        self.assertEqual(m.clients, {})

    def test_server_status_and_active_count(self):
        m = make_manager(self.tmp)
        ok_client = MagicMock()
        ok_client.tools = [{"x": 1}, {"y": 2}]
        ok_client.last_error = None
        ok_client.process = fake_proc()
        err_client = MagicMock()
        err_client.tools = []
        err_client.last_error = "boom"
        err_client.process = fake_proc()
        m.clients = {"ok": ok_client, "bad": err_client}
        m.load_servers = lambda: [
            {"name": "ok", "command": "py", "scope": "global"},
            {"name": "bad", "command": "py", "scope": "global"},
            {"name": "urlsrv", "url": "http://x", "scope": "global"},
            {"name": "off", "command": "py", "enabled": False, "scope": "global"},
        ]

        st = m.get_server_status("ok")
        self.assertEqual(st["tools"], 2)
        self.assertIsNone(st["error"])
        self.assertTrue(st["running"])
        self.assertFalse(m.get_server_status("missing")["running"])
        # Only "ok" finished loading tools without error.
        self.assertEqual(m.active_server_count(), 1)

    async def test_stop_all_async_stops_clients_concurrently(self):
        m = make_manager(self.tmp)
        c1 = MagicMock()
        c1.stop_async = AsyncMock()
        c2 = MagicMock()
        c2.stop_async = AsyncMock()
        m.clients = {"c1": c1, "c2": c2}

        await m.stop_all_async()

        self.assertEqual(len(m.clients), 0)
        c1.stop_async.assert_awaited_once()
        c2.stop_async.assert_awaited_once()

    async def test_ensure_tools_ready_async_fresh_ttl_does_not_spawn_task(self):
        m = make_manager(self.tmp)
        m._tools_refresh_time = time.monotonic()
        m._tools_refresh_task = None
        m.get_cached_tools = MagicMock(return_value=[{"tool": 1}])
        with patch.object(m, "get_active_tools_async") as mock_get:
            tools = await m.ensure_tools_ready_async(max_age=60.0)
            self.assertEqual(tools, [{"tool": 1}])
            mock_get.assert_not_called()

    async def test_call_tool_async_fast_path_with_target_server(self):
        m = make_manager(self.tmp)
        client = MagicMock()
        client.call_tool_async = AsyncMock(return_value="tool_result")
        m.clients = {"srv_a": client}

        res = await m.call_tool_async("srv_a__query", {"q": 1}, target_server="srv_a")
        self.assertEqual(res, "tool_result")
        client.call_tool_async.assert_awaited_once_with("query", {"q": 1}, timeout=120.0)
