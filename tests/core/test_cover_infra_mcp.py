"""Coverage tests for core/infrastructure/mcp/manager.py edge/error branches.

Stays self-contained: no real MCP servers are spawned. The manager is built via
``__new__`` (avoiding constructor config writes) and clients are lightweight
mocks, mirroring the existing test_mcp_manager / test_edge_mcp_manager style.
"""

import asyncio
import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.mcp.manager import DEFAULT_MCP_CALL_TIMEOUT, MCPManager


def make_manager(project_dir=None) -> MCPManager:
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
    return m


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_atexit_stop_all_swallows_errors(monkeypatch):
    import core.infrastructure.mcp.manager as mod

    inst = MagicMock()
    inst.stop_all.side_effect = RuntimeError("boom")
    monkeypatch.setattr(mod, "_mcp_manager_instance", inst)
    mod._atexit_stop_all()  # exception -> debug log, no raise
    inst.stop_all.assert_called_once()

    monkeypatch.setattr(mod, "_mcp_manager_instance", None)
    mod._atexit_stop_all()  # inst is None -> early return


# ---------------------------------------------------------------------------
# stop_all / stop_all_async
# ---------------------------------------------------------------------------


def test_stop_all_non_callable_and_raising_stop():
    m = make_manager()
    idle = MagicMock()
    idle.stop = None  # not callable -> continue
    broken = MagicMock()
    broken.stop.side_effect = RuntimeError("stop fail")

    task = MagicMock()
    task.done.return_value = False
    m._tools_refresh_task = task
    m.clients = {"idle": idle, "broken": broken}

    m.stop_all()
    task.cancel.assert_called_once()
    broken.stop.assert_called_once()
    assert m.clients == {}


@pytest.mark.asyncio
async def test_stop_all_async_cancels_task_and_falls_back_to_stop():
    m = make_manager()
    m._start_locks = {"a": asyncio.Lock()}
    in_flight = asyncio.create_task(asyncio.sleep(5))
    m._tools_refresh_task = in_flight

    async_def = MagicMock()
    async_def.stop_async = AsyncMock()
    async_def.stop = MagicMock()
    fallback = MagicMock()
    fallback.stop_async = None
    fallback.stop = MagicMock()
    nothing = MagicMock()
    nothing.stop_async = None
    nothing.stop = None

    m.clients = {"ad": async_def, "fb": fallback, "nn": nothing}
    await m.stop_all_async()
    in_flight.cancel()
    async_def.stop_async.assert_awaited_once()
    fallback.stop.assert_called_once()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def test_ensure_global_config_swallows_errors(monkeypatch):
    import core.infrastructure.config.config_helpers as ch

    def _boom(*a, **k):
        raise OSError("no permissions")

    monkeypatch.setattr(ch, "ensure_json_config", _boom)
    m = make_manager()
    m._global_config_ensured = False
    m._ensure_global_config()
    assert m._global_config_ensured is True


def test_warn_broken_config_deduplicates():
    m = make_manager()
    m._warn_broken_config("/a", reason="r1")
    m._warn_broken_config("/a", reason="r1")  # already warned -> early return
    assert ("/a", "r1") in m._warned_broken_config_files


def test_load_config_file_missing_and_bad_entries(tmp_path):
    m = make_manager(str(tmp_path))
    m.global_file = os.path.join(str(tmp_path), "global.json")
    m._load_config_file(os.path.join(str(tmp_path), "not_there.json"), "global", {})  # missing -> return

    # mcpServers not a dict -> warning, empty result
    with open(m.global_file, "w", encoding="utf-8") as f:
        f.write('{"mcpServers": [1, 2]}')
    servers = {}
    m._load_config_file(m.global_file, "global", servers)
    assert servers == {}

    # non-dict entry and bad cwd type
    with open(m.global_file, "w", encoding="utf-8") as f:
        f.write('{"mcpServers": {"s1": [], "s2": {"command": "python", "cwd": 42}}}')
    servers = {}
    m._load_config_file(m.global_file, "global", servers)
    # s1 entry not an object -> skipped; s2 cwd sanitized to None
    assert "s1" not in servers
    assert servers["s2"]["cwd"] is None


# ---------------------------------------------------------------------------
# _update_server_config / toggle_server
# ---------------------------------------------------------------------------


async def test_update_server_config_target_missing(tmp_path):
    m = make_manager(str(tmp_path))
    m.load_servers = lambda: [{"name": "other", "command": "p"}]
    assert m._update_server_config("missing", {"enabled": False}) is None


async def test_update_server_config_creates_new_entry_and_adds_key(tmp_path):
    m = make_manager(str(tmp_path))
    # global file exists but has no "mcpServers" key -> line adds it then creates entry
    with open(m.global_file, "w", encoding="utf-8") as f:
        f.write("{}")
    m.load_servers = lambda: [{"name": "new", "command": "python", "args": ["-m", "x"], "scope": "global"}]
    target = m._update_server_config("new", {"enabled": False})
    assert target is not None

    written = json.load(open(m.global_file, encoding="utf-8"))
    assert written["mcpServers"]["new"]["enabled"] is False


async def test_update_server_config_write_error_is_swallowed(tmp_path):
    m = make_manager(str(tmp_path))
    m.load_servers = lambda: [{"name": "x", "command": "p", "scope": "global"}]
    with patch("core.infrastructure.mcp.manager.atomic_write_json", side_effect=OSError("disk")):
        res = m._update_server_config("x", {"enabled": False})
    assert res is not None  # target still returned despite write failure


async def test_update_server_config_reenabling_drops_enabled_key(tmp_path):
    m = make_manager(str(tmp_path))
    with open(m.global_file, "w", encoding="utf-8") as f:
        json.dump({"mcpServers": {"x": {"command": "p", "enabled": False}}}, f)
    m.load_servers = lambda: [{"name": "x", "command": "p", "enabled": False, "scope": "global"}]
    # Re-enabling must drop the redundant "enabled" key — absent means enabled.
    m._update_server_config("x", {"enabled": True})
    written = json.load(open(m.global_file, encoding="utf-8"))
    assert "enabled" not in written["mcpServers"]["x"]


async def test_update_server_config_new_entry_omits_enabled_key(tmp_path):
    m = make_manager(str(tmp_path))
    with open(m.global_file, "w", encoding="utf-8") as f:
        f.write("{}")
    m.load_servers = lambda: [{"name": "new", "command": "python", "args": ["-m", "x"], "scope": "global"}]
    m._update_server_config("new", {"env": {"A": "1"}})
    written = json.load(open(m.global_file, encoding="utf-8"))
    written_entry = written["mcpServers"]["new"]
    assert "enabled" not in written_entry
    assert written_entry["env"] == {"A": "1"}


def test_toggle_server_target_missing(tmp_path):
    m = make_manager(str(tmp_path))
    m.load_servers = lambda: []
    assert m.toggle_server("nope") is False


def test_server_enabled_semantics():
    m = make_manager()
    assert m.server_enabled({}) is True  # absent key means enabled
    assert m.server_enabled({"enabled": True}) is True
    assert m.server_enabled({"enabled": False}) is False
    # Only the canonical key matters: legacy "disabled" is ignored.
    assert m.server_enabled({"disabled": True}) is True


def test_toggle_server_update_failure_returns_false(tmp_path):
    m = make_manager(str(tmp_path))
    m.load_servers = lambda: [{"name": "x", "command": "p"}]
    m._update_server_config = MagicMock(return_value=None)
    assert m.toggle_server("x") is False


def test_toggle_server_disables_and_stops_client(tmp_path):
    m = make_manager(str(tmp_path))
    client = MagicMock()
    m.clients = {"x": client}
    m.load_servers = lambda: [{"name": "x", "command": "p"}]
    m._update_server_config = MagicMock(return_value={"name": "x"})
    assert m.toggle_server("x") is False  # now disabled
    client.stop.assert_called_once()
    assert "x" not in m.clients


# ---------------------------------------------------------------------------
# get_active_tools (sync)
# ---------------------------------------------------------------------------


def test_get_active_tools_creates_and_starts_clients(tmp_path):
    m = make_manager(str(tmp_path))
    m.load_servers = lambda: [{"name": "s1", "command": "python"}, {"name": "s2", "command": "python"}]

    c1 = MagicMock()
    c1.start.return_value = True
    c1.is_tools_stale.return_value = False
    c1.tools = [{"name": "t1", "description": "d", "inputSchema": {"type": "object"}}]
    c2 = MagicMock()
    c2.start.return_value = False

    with patch("core.infrastructure.mcp.manager.MCPProcessClient", side_effect=[c1, c2]):
        tools = m.get_active_tools()

    assert "s1" in m.clients
    assert "s2" not in m.clients
    assert [t["function"]["name"] for t in tools] == ["t1"]


def test_get_active_tools_fetch_error_is_logged(tmp_path):
    m = make_manager(str(tmp_path))
    client = MagicMock()
    client.is_tools_stale.return_value = True
    client.fetch_tools.side_effect = RuntimeError("fetch boom")
    client.tools = []
    m.clients = {"s3": client}
    m.load_servers = lambda: [{"name": "s3", "command": "python"}]
    assert m.get_active_tools() == []


# ---------------------------------------------------------------------------
# _load_server_tools_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_server_tools_async_no_command():
    m = make_manager()
    assert await m._load_server_tools_async({"name": "x"}) == []


@pytest.mark.asyncio
async def test_load_server_tools_async_start_raises():
    m = make_manager()
    client = MagicMock()
    client.start_async = AsyncMock(side_effect=RuntimeError("start boom"))
    client.last_error = None
    client.stop_async = AsyncMock()
    with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=client):
        res = await m._load_server_tools_async({"name": "bad", "command": "python"})
    assert res == []
    assert "bad" not in m.clients
    assert isinstance(client.last_error, str)


@pytest.mark.asyncio
async def test_load_server_tools_async_failed_start_and_teardown_error():
    m = make_manager()
    client = MagicMock()
    client.start_async = AsyncMock(return_value=False)
    client.last_error = None
    client.stop_async = AsyncMock(side_effect=RuntimeError("stop fail"))
    with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=client):
        res = await m._load_server_tools_async({"name": "f", "command": "python"})
    assert res == []
    assert client.last_error == "Failed to start"
    assert "f" not in m.clients


@pytest.mark.asyncio
async def test_load_server_tools_async_generation_changed_after_start():
    m = make_manager()

    async def _start_bumps_generation():
        m._generation += 1  # simulate stop_all during start
        return True

    client = MagicMock()
    client.start_async = AsyncMock(side_effect=_start_bumps_generation)
    client.stop_async = AsyncMock()
    client.last_error = None
    with patch("core.infrastructure.mcp.manager.MCPProcessClient", return_value=client):
        res = await m._load_server_tools_async({"name": "g", "command": "python"})
    assert res == []
    assert "g" not in m.clients


@pytest.mark.asyncio
async def test_load_server_tools_async_fetch_stale_raises():
    m = make_manager()
    client = MagicMock()
    client.is_tools_stale.return_value = True
    client.fetch_tools_async = AsyncMock(side_effect=RuntimeError("fetch boom"))
    client.tools = []
    m.clients["stale"] = client
    res = await m._load_server_tools_async({"name": "stale", "command": "python"})
    assert res == []
    client.fetch_tools_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_server_tools_async_is_tools_stale_raises():
    m = make_manager()
    client = MagicMock()
    client.is_tools_stale.side_effect = RuntimeError("stale boom")
    client.tools = []
    m.clients["s"] = client
    res = await m._load_server_tools_async({"name": "s", "command": "python"})
    assert res == []


# ---------------------------------------------------------------------------
# get_active_tools_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_active_tools_async_handles_exceptions():
    m = make_manager()
    m.load_servers_async = AsyncMock(return_value=[{"name": "s", "command": "python"}])
    m._load_server_tools_async = AsyncMock(side_effect=ValueError("boom"))
    assert await m.get_active_tools_async() == []


# ---------------------------------------------------------------------------
# get_server_status
# ---------------------------------------------------------------------------


def test_get_server_status_poll_error_marks_not_running():
    m = make_manager()
    client = MagicMock()
    client.process = MagicMock()
    client.process.poll.side_effect = OSError("poll fail")
    client.last_error = None
    client.tools = []
    m.clients = {"s": client}
    st = m.get_server_status("s")
    assert st["running"] is False
    assert st["tools"] == 0


# ---------------------------------------------------------------------------
# ensure_tools_ready_async error path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_tools_ready_async_warmup_failure_clears_task():
    m = make_manager()
    m.get_cached_tools = MagicMock(return_value=[])

    async def _boom():
        raise RuntimeError("warmup fail")

    m.get_active_tools_async = AsyncMock(side_effect=_boom)
    await m.ensure_tools_ready_async()
    spawned = m._tools_refresh_task
    assert spawned is not None
    with pytest.raises(RuntimeError):
        await spawned  # finish it so the done-callback clears the ref
    assert m._tools_refresh_task is None


# ---------------------------------------------------------------------------
# capabilities
# ---------------------------------------------------------------------------


def test_get_tool_capabilities_variants():
    m = make_manager()
    m.load_servers = lambda: [
        {"name": "s", "command": "python", "capabilities": {"str_t": "net", "list_t": ["a", "b"], "bad_t": 9}}
    ]
    assert m.get_tool_capabilities("s", "str_t") == ["net"]
    assert m.get_tool_capabilities("s", "list_t") == ["a", "b"]
    assert m.get_tool_capabilities("s", "bad_t") == []  # non-str/list value -> []
    assert m.get_tool_capabilities("missing", "any") == []  # no matching server -> []


def test_get_capabilities_for_exposed_tool_aggregates():
    m = make_manager()
    m.load_servers = lambda: [
        {"name": "a", "command": "x", "capabilities": {"t": "net"}},
        {"name": "a2", "command": "x", "capabilities": {"t": "read"}},
    ]
    assert m.get_capabilities_for_exposed_tool("t") == ["net", "read"]


# ---------------------------------------------------------------------------
# _resolve_target_client_and_tool
# ---------------------------------------------------------------------------


def test_resolve_target_client_and_tool_edges():
    m = make_manager()
    m.clients = {"srv": "CLIENT"}

    # malformed entry (no _mcp_server) is skipped; match still found
    tools = [{"no_srv": 1}, {"_mcp_server": "srv", "_mcp_tool_name": "tool", "function": {"name": "tool"}}]
    client, o = m._resolve_target_client_and_tool("tool", tools)
    assert client == "CLIENT"
    assert o == "tool"

    # target_server mismatch -> no match
    client, o = m._resolve_target_client_and_tool("tool", tools, target_server="other")
    assert client is None and o is None

    # namespace split path: exposed name differs, legacy ns name resolves
    tools2 = [{"_mcp_server": "srv", "_mcp_tool_name": "oldtool", "function": {"name": "deprecated__oldtool"}}]
    client, o = m._resolve_target_client_and_tool("srv__oldtool", tools2)
    assert client == "CLIENT"
    assert o == "oldtool"


# ---------------------------------------------------------------------------
# call_tool / call_tool_async
# ---------------------------------------------------------------------------


def test_call_tool_target_server_strips_namespace():
    m = make_manager()
    client = MagicMock()
    client.call_tool = MagicMock(return_value="ok")
    m.clients = {"srv": client}
    res = m.call_tool("srv__foo", {"a": 1}, target_server="srv")
    assert res == "ok"
    client.call_tool.assert_called_once_with("foo", {"a": 1}, timeout=DEFAULT_MCP_CALL_TIMEOUT)


@pytest.mark.asyncio
async def test_call_tool_async_resolves_via_active_tools():
    m = make_manager()
    client = MagicMock()
    client.call_tool_async = AsyncMock(return_value="ok")
    m.clients = {"srv": client}
    m.get_active_tools_async = AsyncMock(
        return_value=[{"_mcp_server": "srv", "_mcp_tool_name": "tool", "function": {"name": "tool"}}]
    )
    res = await m.call_tool_async("tool", {})
    assert res == "ok"
    client.call_tool_async.assert_awaited_once_with("tool", {}, timeout=DEFAULT_MCP_CALL_TIMEOUT)


@pytest.mark.asyncio
async def test_call_tool_async_no_match_returns_none():
    m = make_manager()
    m.get_active_tools_async = AsyncMock(return_value=[])
    assert await m.call_tool_async("missing", {}) is None


# ---------------------------------------------------------------------------
# get_system_prompt_snippet
# ---------------------------------------------------------------------------


def test_system_prompt_snippet_skips_nameless_tool():
    m = make_manager()
    m.get_cached_tools = lambda: [{"function": {"name": None}, "_mcp_server": "s"}, {"x": 1}]
    assert m.get_system_prompt_snippet() == "## MCP Tools"


if __name__ == "__main__":
    pytest.main([__file__])
