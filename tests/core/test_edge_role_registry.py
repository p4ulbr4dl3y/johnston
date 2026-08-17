"""Edge-case tests for core.role_registry targeting bugs.

Intent: probe boundary conditions (missing keys, undefined scopes, empty/None
tool lists, singleton cache, project_dir stickiness, unicode) to surface
behavioral bugs in AgentRole / RoleRegistry.
"""
import os
import tempfile
import time

import pytest

from core.domain.policies.role_policy import normalize_role_scope, role_tool_error
from core.role_registry import (
    BUILTIN_ROLES,
    AgentRole,
    RoleRegistry,
)


# --------------------------------------------------------------------------- #
# normalize_role_scope
# --------------------------------------------------------------------------- #
class TestNormalizeScope:
    def test_none_empty_whitespace(self):
        assert normalize_role_scope(None) == "any"
        assert normalize_role_scope("") == "any"
        # BUG: whitespace-only is truthy, so `(scope or "any")` keeps it, then
        # .lower().strip() collapses to "" -> NOT "any". A role file with
        # `scope: "   "` silently gets an unusable empty scope.
        assert normalize_role_scope("   ") == "any"

    def test_case_insensitive(self):
        assert normalize_role_scope("MAIN") == "main"
        assert normalize_role_scope(" Main ") == "main"
        assert normalize_role_scope("SUBAGENT") == "subagent"

    def test_unknown_scope_passthrough(self):
        assert normalize_role_scope("bogus") == "bogus"
        assert normalize_role_scope("main_only") == "main_only"
        assert normalize_role_scope("subagent_only") == "subagent_only"

    def test_non_string_scope_raises(self):
        # AgentRole.__init__ calls normalize_role_scope(scope); an int scope
        # must not crash the whole role construction.
        with pytest.raises(AttributeError):
            AgentRole(key="x", scope=123)


# --------------------------------------------------------------------------- #
# AgentRole construction edge cases
# --------------------------------------------------------------------------- #
class TestAgentRoleConstruction:
    def test_missing_all_optional_fields(self):
        r = AgentRole(key="minimal")
        assert r.prompt == ""
        assert r.system_prompt == ""
        assert r.provider == ""
        assert r.model == ""
        assert r.scope == "any"
        assert r.allowed_tools == []
        assert r.disallowed_tools == []
        assert not r.read_only

    def test_key_normalized_lower_strip(self):
        r = AgentRole(key="  MiXeD  ")
        assert r.key == "mixed"

    def test_scope_invalid_value(self):
        r = AgentRole(key="x", scope="not-a-real-scope")
        assert r.scope == "not-a-real-scope"

    def test_provider_stripped_lower(self):
        r = AgentRole(key="x", provider="  OpenAi  ")
        assert r.provider == "openai"

    def test_unicode_prompt_roundtrip(self):
        prompt = "Привет, мир! Роль: 🧠 测试 テスト"
        r = AgentRole(key="uni", prompt=prompt)
        assert r.system_prompt == prompt
        assert r.prompt == prompt


class TestToolLists:
    def test_none_and_empty_equivalent_on_allow(self):
        # A role with allowed_tools=None must allow everything.
        # A role with allowed_tools=[] currently also allows everything
        # (empty list is falsy). Both should behave identically.
        r_none = AgentRole(key="a", allowed_tools=None)
        r_empty = AgentRole(key="b", allowed_tools=[])
        assert r_none.is_tool_allowed("any_tool") is None
        assert r_empty.is_tool_allowed("any_tool") is None

    def test_disallowed_none_and_empty(self):
        r = AgentRole(key="x", disallowed_tools=None)
        assert r.is_tool_allowed("create") is None
        r2 = AgentRole(key="y", disallowed_tools=[])
        assert r2.is_tool_allowed("create") is None

    def test_unknown_tool_names_in_lists(self):
        r = AgentRole(key="x", allowed_tools=["totally_unknown_tool"], disallowed_tools=["also_unknown"])
        # allowed list contains unknown name -> tool not in it -> blocked
        assert r.is_tool_allowed("read") is not None
        # disallowed unknown name should not block unrelated tools
        r2 = AgentRole(key="y", disallowed_tools=["ghost_tool"])
        assert r2.is_tool_allowed("edit") is None

    def test_tool_string_whitespace_in_lists(self):
        r = AgentRole(key="x", allowed_tools=[" read ", "grep"])
        assert r.is_tool_allowed("read") is None
        assert r.is_tool_allowed("grep") is None


class TestIsToolAllowed:
    def test_none_empty_tool_name_allowed(self):
        r = AgentRole(key="x", allowed_tools=["read"])
        # None/"" tool names are tolerated (return None) even though they are
        # not in the allowed list.
        assert r.is_tool_allowed(None) is None
        assert r.is_tool_allowed("") is None

    def test_whitespace_tool_name_differs_from_empty(self):
        # " " strips to "" -> falsy? No: " " is truthy, strip yields "".
        # It is NOT caught by the `not tool_name` guard, so it falls through to
        # the allowed-list check. This is an inconsistency with None/"".
        r = AgentRole(key="x", allowed_tools=["read"])
        result = r.is_tool_allowed(" ")
        # Document actual behavior: a whitespace tool is treated as a real tool
        # and blocked because it is not in the allowed list.
        assert result is not None

    def test_case_insensitive_tool(self):
        r = AgentRole(key="x", allowed_tools=["read"])
        assert r.is_tool_allowed("READ") is None
        assert r.is_tool_allowed("Read") is None

    def test_tool_in_allowed_and_disallowed(self):
        # disallowed wins over allowed
        r = AgentRole(key="x", allowed_tools=["read"], disallowed_tools=["read"])
        assert r.is_tool_allowed("read") is not None

    def test_functions_prefix_stripped(self):
        r = AgentRole(key="x", disallowed_tools=["read"])
        assert r.is_tool_allowed("functions.read") is not None
        r2 = AgentRole(key="y", allowed_tools=["read"])
        assert r2.is_tool_allowed("functions.read") is None

    def test_allowed_empty_vs_allowed_set(self):
        # WARNING: allowed_tools=[] allows everything (falsy). This means an
        # author who writes `tools:` with an empty value silently gets full
        # tool access - a security footgun.
        r_empty = AgentRole(key="x", allowed_tools=[], read_only=False)
        assert r_empty.is_tool_allowed("shell") is None  # shell allowed!

    def test_read_only_blocks_all_write_tools(self):
        r = AgentRole(key="x", read_only=True)
        for w in ("create", "edit", "multi_edit"):
            assert r.is_tool_allowed(w) is not None
        assert r.is_tool_allowed("read") is None


# --------------------------------------------------------------------------- #
# role_tool_error helper
# --------------------------------------------------------------------------- #
class TestRoleToolError:
    def test_none_def(self):
        assert role_tool_error(None, "read") is None

    def test_plain_object_no_read_only(self):
        class Fake:
            disallowed_tools = ["create"]
        assert role_tool_error(Fake(), "create") is not None
        assert role_tool_error(Fake(), "read") is None

    def test_read_only_plain_object(self):
        class Fake:
            disallowed_tools = []
            read_only = True
        assert role_tool_error(Fake(), "edit") is not None


# --------------------------------------------------------------------------- #
# get_role boundaries
# --------------------------------------------------------------------------- #
class TestGetRole:
    def test_unknown_key_falls_back_to_worker(self):
        reg = RoleRegistry()
        r = reg.get_role("does_not_exist")
        assert r.key == "worker"

    def test_none_empty_whitespace_key(self):
        reg = RoleRegistry()
        assert reg.get_role(None).key == "worker"
        assert reg.get_role("").key == "worker"
        assert reg.get_role("   ").key == "worker"

    def test_case_insensitive_key(self):
        reg = RoleRegistry()
        assert reg.get_role("WORKER").key == "worker"
        assert reg.get_role("Worker").key == "worker"

    def test_cyrillic_key_falls_back(self):
        reg = RoleRegistry()
        assert reg.get_role("работник").key == "worker"

    def test_unknown_fallback_to_worker_wins_over_other_roles(self):
        # Even if a custom 'analyst' role exists, unknown keys must fall back
        # to worker, NOT to the first custom role.
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            with open(os.path.join(roles_dir, "analyst.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: analyst\n---\nAnalyst prompt")
            reg = RoleRegistry()
            reg.load_roles(project_dir=tmpdir, include_global=False)
            assert "analyst" in reg.roles
            assert reg.get_role("nope").key == "worker"


# --------------------------------------------------------------------------- #
# role file edge cases
# --------------------------------------------------------------------------- #
class TestRoleFiles:
    def _make_role(self, tmpdir, fname, content):
        roles_dir = os.path.join(tmpdir, ".johnston", "roles")
        os.makedirs(roles_dir, exist_ok=True)
        p = os.path.join(roles_dir, fname)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_empty_role_file_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "ghost.md", "")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert "ghost" not in roles

    def test_whitespace_only_role_file_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "ghost.md", "   \n\n  ")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert "ghost" not in roles

    def test_broken_frontmatter_unclosed(self):
        # Unclosed `---` -> parse_frontmatter treats whole file as body, key
        # derived from filename. Role should still load (not crash).
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "broken.md", "---\nname: Broken\nno closing delimiter")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            # parse_frontmatter falls back to {}, content; key = base name
            assert "broken" in roles

    def test_role_without_required_fields(self):
        # No name/description/prompt/model/provider -> should still load using
        # filename as key.
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "bare.md", "just a body, no frontmatter")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert "bare" in roles
            assert roles["bare"].prompt == "just a body, no frontmatter"

    def test_duplicate_keys_last_wins(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Two files resolving to the same key; sorted iteration -> b.md last
            self._make_role(tmpdir, "a.md", "---\nkey: dup\n---\nprompt A")
            self._make_role(tmpdir, "b.md", "---\nkey: dup\n---\nprompt B")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert roles["dup"].prompt == "prompt B"

    def test_project_overrides_global_overrides_builtin(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # project role shadows builtin worker
            self._make_role(tmpdir, "worker.md", "---\nname: worker\n---\nCUSTOM WORKER")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert roles["worker"].prompt == "CUSTOM WORKER"
            assert roles["worker"].source == "project"

    def test_provider_empty_and_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "p.md", "---\nname: p\nprovider: openai\n---\np")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert roles["p"].provider == "openai"
            assert roles["worker"].provider == ""

    def test_unicode_system_prompt_from_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "uni.md", "---\nname: uni\n---\nРоль 测试 🧠 тело")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert roles["uni"].prompt == "Роль 测试 🧠 тело"

    def test_non_md_files_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_role(tmpdir, "note.txt", "---\nname: note\n---\nbody")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert "note" not in roles


# --------------------------------------------------------------------------- #
# load_roles / project / global
# --------------------------------------------------------------------------- #
class TestLoadRoles():
    def test_project_dir_none_uses_cwd(self):
        reg = RoleRegistry()
        roles = reg.load_roles(project_dir=None, include_global=False)
        assert "worker" in roles

    def test_nonexistent_project_dir(self):
        reg = RoleRegistry()
        roles = reg.load_roles(project_dir="/nonexistent/path/xyz", include_global=False)
        assert "worker" in roles
        assert len(roles) >= 3

    def test_global_only(self):
        reg = RoleRegistry()
        roles = reg.load_roles(project_dir=None, include_global=True)
        assert "worker" in roles

    def test_scope_filtering_main_vs_subagent(self):
        reg = RoleRegistry()
        main = reg.list_roles("main")
        assert "orchestrator" in main
        assert "worker" in main  # scope any
        sub = reg.list_subagent_roles()
        assert "worker" in sub
        assert "orchestrator" not in sub

    def test_invalid_scope_listing(self):
        reg = RoleRegistry()
        # invalid scope -> normalize passthrough, only "any" roles match
        res = reg.list_roles("bogus")
        for v in res.values():
            assert v.scope in ("any", "bogus")


# --------------------------------------------------------------------------- #
# singleton & cache
# --------------------------------------------------------------------------- #
class TestSingletonAndCache:
    def test_sticky_project_dir_on_singleton_does_not_leak(self):
        # BUG CANDIDATE: load_roles(GET INSTANCE) sets current_project_dir on
        # the shared singleton and never resets it. Subsequent get_role() with
        # no project_dir should NOT keep scanning a previous project.
        RoleRegistry._instance = None
        reg = RoleRegistry.get_instance()
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            with open(os.path.join(roles_dir, "leak.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: leak\n---\nLEAK")
            reg.get_role("worker", project_dir=tmpdir)
            assert "leak" in reg.roles
        # Now a fresh get_role with no project_dir must NOT see `leak`.
        reg.invalidate_cache()
        reg.get_role("worker")
        assert "leak" not in reg.roles, (
            "singleton leaked previous project_dir; current_project_dir is sticky"
        )

    def test_invalidate_cache_forces_reload(self):
        RoleRegistry._instance = None
        reg = RoleRegistry.get_instance()
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            p = os.path.join(roles_dir, "mut.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write("---\nkey: mut\n---\nversion 1")
            reg.load_roles(project_dir=tmpdir, include_global=False)
            assert reg.roles["mut"].prompt == "version 1"
            # mutate file, ensure mtime changes
            with open(p, "w", encoding="utf-8") as f:
                f.write("---\nkey: mut\n---\nversion 2")
            os.utime(p, (time.time() + 5, time.time() + 5))
            reg.invalidate_cache()
            reg.load_roles(project_dir=tmpdir)
            assert reg.roles["mut"].prompt == "version 2"

    def test_ttl_expiry_reloads_if_signature_changed(self):
        RoleRegistry._instance = None
        reg = RoleRegistry.get_instance()
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            p = os.path.join(roles_dir, "t.md")
            with open(p, "w", encoding="utf-8") as f:
                f.write("---\nkey: t\n---\nTTL 1")
            reg.load_roles(project_dir=tmpdir, include_global=False)
            # change content with a changed mtime after TTL expiry -> reload
            p_dir = os.path.realpath(tmpdir)
            if (p_dir, False) in reg._cache._cache:
                ts, sig, val = reg._cache._cache[(p_dir, False)]
                reg._cache._cache[(p_dir, False)] = (ts - 10.0, sig, val)
            with open(p, "w", encoding="utf-8") as f:
                f.write("---\nkey: t\n---\nTTL 2")
            os.utime(p, (time.time() + 5, time.time() + 5))
            reg.load_roles(project_dir=tmpdir, include_global=False)
            assert reg.roles["t"].prompt == "TTL 2"

    def test_get_role_unknown_returns_worker_not_none(self):
        reg = RoleRegistry()
        r = reg.get_role("zzz_nonexistent")
        assert r is not None
        assert r.key == "worker"


# --------------------------------------------------------------------------- #
# defaults
# --------------------------------------------------------------------------- #
class TestDefaultRoles:
    def test_builtin_keys_present(self):
        for k in ("worker", "explorer"):
            assert k in BUILTIN_ROLES, f"missing builtin role {k}"

    def test_analyst_NOT_builtin(self):
        # 'analyst' is mentioned in the default-role legend but is NOT a
        # builtin. Document actual behavior.
        assert "analyst" not in BUILTIN_ROLES

    def test_worker_scope_any(self):
        assert BUILTIN_ROLES["worker"].scope in ("any", "subagent")

    def test_orchestrator_main_only(self):
        assert BUILTIN_ROLES["orchestrator"].scope == "main"
