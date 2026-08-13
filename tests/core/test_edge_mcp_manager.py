"""Edge-case tests for MCP manager/process_client.

Goal: find bugs in the implementation. Some tests are intentionally RED
(bug-confirming); they are marked with a BUG comment explaining the finding.
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.mcp_manager import MCPManager, MCPProcessClient


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
    return m


def fake_proc():
    p = MagicMock()
    p.poll.return_value = None
    p.stdin = MagicMock()
    p.stdout = MagicMock()
    p.stderr = MagicMock()
    return p


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
        m.load_servers = lambda: [{"name": "s", "command": "python", "disabled": False}]
        tools = m.get_active_tools()
        self.assertEqual(tools, [])

    def test_missing_input_schema_defaults(self):
        m = make_manager(self.tmp)
        c = MagicMock()
        c.tools = [{"name": "t", "description": "d"}]
        c.start.return_value = True
        m.clients["s"] = c
        m.load_servers = lambda: [{"name": "s", "command": "python", "disabled": False}]
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


class BugTests(unittest.TestCase):
    """Intentional bug-confirming tests. Left RED if the code is broken."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_failed_start_does_not_leak_cached_client(self):
        # BUG (manager.py _load_server_tools_async, ~lines 314-335):
        # On start failure the freshly-created client is stored in self.clients
        # BEFORE _cleanup_if_created() runs, whose guard
        #   self.clients.get(name) is not client
        # then never matches, so the failed client (with a live subprocess) is
        # never stopped/removed. Sync get_active_tools (line 269-272) does NOT
        # store failed clients, so async path is inconsistent -> process leak.
        m = make_manager(self.tmp)
        m.load_servers = lambda: [{"name": "bad", "command": "python"}]

        failed = MagicMock()
        failed.start_async.return_value = False
        failed.stop = MagicMock()

        with patch("core.mcp_manager.manager.MCPProcessClient", return_value=failed) as mk:
            asyncio.run(m.get_active_tools_async())

        self.assertEqual(mk.call_count, 1)
        # Correct behavior: a client that failed to start must not remain cached
        # with a (possibly) running subprocess.
        self.assertNotIn("bad", m.clients)
        failed.stop.assert_called_once()

    def test_call_async_after_stop_does_not_raise(self):
        # BUG (process_client.py stop() lines 281-283 + call_tool_async lines
        # 572-582): stop() sets a RuntimeError exception on pending futures, but
        # call_tool_async only catches asyncio.TimeoutError and CancelledError.
        # A RuntimeError therefore propagates to the caller when the server is
        # stopped mid-call. The sync path (call_tool/_read_response) handles the
        # same scenario gracefully, so this is an async-only crash.
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
            # Correct behavior: a graceful error string, not an uncaught RuntimeError.
            self.assertIsInstance(res, str)
            return res

        asyncio.run(scenario())


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


if __name__ == "__main__":
    unittest.main()
