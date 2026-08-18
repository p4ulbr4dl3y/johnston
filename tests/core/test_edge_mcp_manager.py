"""Edge-case tests for MCP manager/process_client.

Goal: find bugs in the implementation. Some tests are intentionally RED
(bug-confirming); they are marked with a BUG comment explaining the finding.
"""
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.infrastructure.mcp import MCPManager, MCPProcessClient


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
        self.assertIn("Error", res)


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
            {"name": "off", "command": "py", "disabled": True, "scope": "global"},
        ]

        st = m.get_server_status("ok")
        self.assertEqual(st["tools"], 2)
        self.assertIsNone(st["error"])
        self.assertTrue(st["running"])
        self.assertFalse(m.get_server_status("missing")["running"])
        # Only "ok" finished loading tools without error.
        self.assertEqual(m.active_server_count(), 1)


if __name__ == "__main__":
    unittest.main()
