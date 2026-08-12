"""Edge-case tests for tools/aliases.py and tools/registry.py.

Deliberately probes degenerate inputs (None, empty, unicode, long names, alias
chains, mutation of the shared ALIAS_MAP/REGISTRY) to smoke out bugs.

Tests asserting the *correct* intended behavior that expose real product bugs are
left RED and marked `# BUG`. Tests that only document current-but-debatable
behavior are marked `# NOTE`.
"""

import pytest

from tools.aliases import ALIAS_MAP
from tools.base import BaseTool
from tools.registry import (
    REGISTRY,
    get_default_tools,
    normalize_tool_args,
    normalize_tool_name,
)


# --------------------------------------------------------------------------- #
# normalize_tool_name edge cases
# --------------------------------------------------------------------------- #
class TestNormalizeNameEdge:
    def test_none(self):
        assert normalize_tool_name(None) == ""

    def test_empty(self):
        assert normalize_tool_name("") == ""

    def test_whitespace_only(self):
        assert normalize_tool_name("   ") == ""
        assert normalize_tool_name("\t\n ") == ""

    def test_whitespace_padded_alias(self):
        assert normalize_tool_name("  cat  ") == "read"
        assert normalize_tool_name("  write_file\n") == "create"

    def test_uppercase_alias(self):
        assert normalize_tool_name("CAT") == "read"
        assert normalize_tool_name("Write_File") == "create"

    def test_uppercase_canonical(self):
        assert normalize_tool_name("ReAd") == "read"

    def test_unknown_fallback_identity(self):
        assert normalize_tool_name("no_such_tool_xyz") == "no_such_tool_xyz"

    def test_unicode(self):
        assert normalize_tool_name("чтение") == "чтение"

    def test_special_chars(self):
        assert normalize_tool_name("!@#$%^&*()") == "!@#$%^&*()"

    def test_dot_slash(self):
        assert normalize_tool_name("a.b/c") == "a.b/c"

    def test_numbers(self):
        assert normalize_tool_name("tool123") == "tool123"

    def test_very_long(self):
        long = "x" * 10_000
        assert normalize_tool_name(long) == long

    def test_alias_chain_fully_resolves(self):
        """BUG: alias->alias chains are only resolved one level.

        If ALIAS_MAP maps `zz_chain -> cat` and `cat -> read`, the correct
        canonical target is `read`, but the code does a single lookup and returns
        the intermediate alias `cat` (not in REGISTRY -> dispatch breaks).
        """
        ALIAS_MAP["zz_chain"] = "cat"
        try:
            assert normalize_tool_name("zz_chain") == "read"
        finally:
            del ALIAS_MAP["zz_chain"]

    def test_alias_self_loop_terminates(self):
        """A self-referential alias must resolve without an infinite loop."""
        ALIAS_MAP["zz_loop"] = "zz_loop"
        try:
            assert normalize_tool_name("zz_loop") == "zz_loop"
        finally:
            del ALIAS_MAP["zz_loop"]

    def test_alias_target_untracked(self):
        """BUG: alias pointing at another *alias key* should keep resolving rather
        than returning a dead name."""
        ALIAS_MAP["zz_ghost"] = "cat"
        try:
            assert normalize_tool_name("zz_ghost") == "read"
        finally:
            del ALIAS_MAP["zz_ghost"]

    def test_alias_with_empty_value(self):
        """BUG: an alias mapped to "" yields "" (dead name), not a fallback."""
        ALIAS_MAP["zz_emptyval"] = ""
        try:
            assert normalize_tool_name("zz_emptyval") != ""
        finally:
            del ALIAS_MAP["zz_emptyval"]

    def test_alias_with_none_value_no_crash(self):
        """BUG: an alias mapped to None returns None from a str->str function."""
        ALIAS_MAP["zz_noneval"] = None  # type: ignore[dict-item]
        try:
            assert normalize_tool_name("zz_noneval") is not None
        finally:
            del ALIAS_MAP["zz_noneval"]

    def test_all_alias_targets_are_registered(self):
        for target in set(ALIAS_MAP.values()):
            assert target in REGISTRY, f"alias target {target!r} not in REGISTRY"

    def test_no_alias_key_collides_with_canonical(self):
        for k in ALIAS_MAP:
            assert k not in REGISTRY, f"alias key {k!r} collides with canonical tool"


# --------------------------------------------------------------------------- #
# normalize_tool_args edge cases
# --------------------------------------------------------------------------- #
class TestNormalizeArgsEdge:
    def test_none_args(self):
        assert normalize_tool_args("shell", None) == {}

    def test_empty_args(self):
        assert normalize_tool_args("shell", {}) == {}

    def test_non_dict_args(self):
        assert normalize_tool_args("shell", "nope") == {}

    def test_unknown_tool_passthrough(self):
        args = {"cmd": "ls"}
        assert normalize_tool_args("zz_unknown", args) == args

    def test_none_tool_name(self):
        assert normalize_tool_args(None, {"cmd": "ls"}) == {"cmd": "ls"}

    def test_alias_key_not_duplicated(self):
        """NOTE: alias keys are kept alongside canonical keys (not removed)."""
        norm = normalize_tool_args("shell", {"cmd": "ls"})
        assert norm["command"] == "ls"
        assert "cmd" in norm  # documents current behavior

    def test_edits_non_dict_chunks_pass_through(self):
        norm = normalize_tool_args("multi_edit", {"edits": ["raw", {"search": "a", "replace": "b"}]})
        assert norm["edits"][0] == "raw"
        assert norm["edits"][1]["old_str"] == "a"

    def test_empty_chunk_key_no_crash(self):
        norm = normalize_tool_args("multi_edit", {"edits": [{"": "x"}]})
        assert norm["edits"][0] == {"": "x"}


# --------------------------------------------------------------------------- #
# REGISTRY register/get/reuse edge cases
# --------------------------------------------------------------------------- #
class _DummyTool(BaseTool):
    name = "zz_dummy"
    description = "dummy"
    schema = {"type": "function", "function": {"name": "zz_dummy", "description": "dummy"}}

    async def execute(self, args, ctx=None):
        return "DUMMY_OK"


class _SecondDummy(BaseTool):
    name = "zz_dummy"
    description = "second"
    schema = {"type": "function", "function": {"name": "zz_dummy", "description": "second"}}


class TestRegistryRegister:
    def test_register_and_get(self):
        REGISTRY["zz_dummy_1"] = _DummyTool
        try:
            assert REGISTRY["zz_dummy_1"] is _DummyTool
        finally:
            del REGISTRY["zz_dummy_1"]

    def test_duplicate_register_overwrites(self):
        REGISTRY["zz_dummy"] = _DummyTool
        REGISTRY["zz_dummy"] = _SecondDummy
        try:
            assert REGISTRY["zz_dummy"] is _SecondDummy
        finally:
            del REGISTRY["zz_dummy"]

    def test_register_none_name(self):
        """NOTE: no guard; empty-string key registers fine (questionable)."""
        class _NoName(BaseTool):
            name = ""

            async def execute(self, args, ctx=None):
                return "NONAME"

        REGISTRY[""] = _NoName
        try:
            assert "" in REGISTRY
        finally:
            del REGISTRY[""]

    def test_get_none_key(self):
        assert REGISTRY.get(None) is None

    def test_get_unknown_key(self):
        assert REGISTRY.get("zz_missing") is None

    def test_get_case_sensitive(self):
        assert REGISTRY.get("READ") is None
        assert REGISTRY.get("read") is not None

    def test_reuse_persists(self):
        REGISTRY["zz_persist"] = _DummyTool
        try:
            assert REGISTRY.get("zz_persist") is _DummyTool
            assert REGISTRY.get("zz_persist") is _DummyTool
        finally:
            del REGISTRY["zz_persist"]

    def test_get_default_tools_wellformed(self):
        tools = get_default_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0
        for t in tools:
            assert "function" in t


# --------------------------------------------------------------------------- #
# execute_tool degenerate names
# --------------------------------------------------------------------------- #
class TestExecuteToolEdge:
    @pytest.fixture(autouse=True)
    def no_mcp(self, monkeypatch):
        class _FakeMCP:
            def get_active_tools(self):
                return []

            def get_active_tools_async(self):
                return []

            def get_capabilities_for_exposed_tool(self, n):
                return None

        monkeypatch.setattr("core.mcp_manager.get_mcp_manager", lambda: _FakeMCP())

    async def test_execute_none_name(self):
        from tools.registry import execute_tool

        res = await execute_tool(None, None)
        assert res.startswith("ERR: unknown")

    async def test_execute_empty_name(self):
        from tools.registry import execute_tool

        res = await execute_tool("", None)
        assert res.startswith("ERR: unknown")

    async def test_execute_chained_alias_reaches_canonical(self):
        """BUG: chained alias (zz_chain -> cat -> read) is not fully resolved;
        dispatch reports it as unknown instead of routing to `read`."""
        from core.permission_manager import PermissionManager
        from tools.registry import execute_tool

        PermissionManager.get_instance().set_session_override("read", "allow")
        ALIAS_MAP["zz_chain"] = "cat"
        try:
            res = await execute_tool("zz_chain", {"path": "nonexistent_abc_123.txt"})
            assert "ERR: unknown" not in res
        finally:
            del ALIAS_MAP["zz_chain"]

    async def test_execute_register_added_tool(self):
        """A dynamically registered tool is dispatchable through execute_tool."""
        from core.permission_manager import PermissionManager
        from tools.registry import execute_tool

        PermissionManager.get_instance().set_session_override("zz_dummy", "allow")
        REGISTRY["zz_dummy"] = _DummyTool
        try:
            res = await execute_tool("zz_dummy", {})
            assert res == "DUMMY_OK"
        finally:
            del REGISTRY["zz_dummy"]

    async def test_execute_tool_that_raises(self):
        """A tool whose execute() raises is caught and reported as an ERR."""
        from core.permission_manager import PermissionManager
        from tools.registry import execute_tool

        class _Boom(BaseTool):
            name = "zz_boom"

            async def execute(self, args, ctx=None):
                raise RuntimeError("boom")

        PermissionManager.get_instance().set_session_override("zz_boom", "allow")
        REGISTRY["zz_boom"] = _Boom
        try:
            res = await execute_tool("zz_boom", {})
            assert "ERR: execute" in res and "boom" in res
        finally:
            del REGISTRY["zz_boom"]
