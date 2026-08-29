import os
import tempfile
import time
import unittest

import pytest

from core.domain.policies.role_policy import AgentRole, normalize_role_scope, role_tool_error
from core.role_registry import BUILTIN_ROLES, RoleRegistry


class TestRoleRegistry(unittest.TestCase):
    def test_builtin_roles(self):
        reg = RoleRegistry.get_instance()
        roles = reg.load_roles(include_global=False)

        self.assertIn("worker", roles)
        self.assertIn("explorer", roles)
        self.assertNotIn("orchestrator", roles)

        self.assertTrue(roles["explorer"].read_only)
        self.assertEqual(roles["worker"].name, "Worker")
        self.assertEqual(roles["worker"].scope, "any")
        self.assertEqual(normalize_role_scope("main_only"), "main_only")
        self.assertEqual(normalize_role_scope("subagent_only"), "subagent_only")
        self.assertEqual(normalize_role_scope("any"), "any")

    def test_custom_role_parsing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            role_path = os.path.join(roles_dir, "reviewer.md")

            with open(role_path, "w", encoding="utf-8") as f:
                f.write("""---
name: Reviewer
description: Code reviewer role
allowed_tools: read, grep, glob
model: clinepass/deepseek-chat
scope: subagent
read_only: true
---
You are a senior code reviewer role.""")

            reg = RoleRegistry.get_instance()
            roles = reg.load_roles(project_dir=tmpdir)

            self.assertIn("reviewer", roles)
            rev = roles["reviewer"]

            self.assertEqual(rev.name, "Reviewer")
            self.assertEqual(rev.description, "Code reviewer role")
            self.assertEqual(rev.allowed_tools, ["read", "grep", "glob"])
            self.assertEqual(rev.model, "deepseek-chat")
            self.assertEqual(rev.provider, "clinepass")
            self.assertEqual(rev.scope, "subagent")
            self.assertTrue(rev.read_only)
            self.assertIn("senior code reviewer role", rev.prompt)

    def test_project_roles_folder(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            sa_path = os.path.join(roles_dir, "tester.md")

            with open(sa_path, "w", encoding="utf-8") as f:
                f.write("""---
name: tester
description: Automated testing role
allowed_tools: shell
model: gpt-4o
---
You run tests and report coverage.""")

            reg = RoleRegistry()
            reg.load_roles(project_dir=tmpdir)
            defs = reg.list_subagent_roles()

            self.assertIn("tester", defs)
            tester = reg.get_role("tester")
            self.assertEqual(tester.description, "Automated testing role")
            self.assertEqual(tester.allowed_tools, ["shell"])

    def test_is_tool_allowed_validation(self):
        role_ro = AgentRole(key="reviewer", name="Reviewer", disallowed_tools=["edit"], allowed_tools=["read", "grep"])

        # Read tool in allowed list -> ok
        self.assertIsNone(role_tool_error(role_ro, "read"))
        # Shell not in allowed list -> blocked
        self.assertIsNotNone(role_tool_error(role_ro, "shell"))
        # Edit in disallowed list -> blocked
        self.assertIsNotNone(role_tool_error(role_ro, "edit"))

    def test_tool_name_normalizer_no_alias_resolution(self):
        from core.infrastructure.runtime.tool_name import normalize_tool_name

        role_ro = AgentRole(
            key="reviewer",
            name="Reviewer",
            disallowed_tools=["invoke_subagent", "create"],
            tool_name_normalizer=normalize_tool_name,
        )

        # normalize_tool_name no longer resolves aliases: 'subagent' is not in the
        # disallowed list (which holds 'invoke_subagent'), so it is allowed.
        self.assertIsNone(role_tool_error(role_ro, "subagent"))
        # Without a normalizer the result is the same (identity on lowercase).
        role_no_norm = AgentRole(key="reviewer", name="Reviewer", disallowed_tools=["invoke_subagent", "create"])
        self.assertIsNone(role_tool_error(role_no_norm, "subagent"))
        # Canonical 'invoke_subagent' is blocked by the disallowed list.
        self.assertIsNotNone(role_tool_error(role_ro, "invoke_subagent"))
        self.assertIsNone(role_tool_error(role_ro, "write_file"))
        self.assertIsNotNone(role_tool_error(role_ro, "create"))

    def test_scope_filtering(self):
        reg = RoleRegistry.get_instance()
        main_roles = reg.list_roles(scope="main")
        self.assertIn("worker", main_roles)
        self.assertIn("explorer", main_roles)

        subagent_roles = reg.list_subagent_roles()
        self.assertIn("worker", subagent_roles)
        self.assertIn("explorer", subagent_roles)

    def test_custom_md_role_with_list_disallowed_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            md_path = os.path.join(roles_dir, "architect.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write("""---
name: Architect
description: High-level design role
disallowed_tools: [create, edit]
---
Architect prompt content""")

            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            self.assertIn("architect", roles)
            arch = roles["architect"]
            self.assertEqual(arch.name, "Architect")
            self.assertEqual(arch.prompt, "Architect prompt content")
            self.assertIn("create", arch.disallowed_tools)

    def test_role_tool_error_disallowed_enforced(self):
        reg = RoleRegistry.get_instance()
        explorer = reg.get_role("explorer")

        # disallowed_tools enforced
        self.assertIsNotNone(role_tool_error(explorer, "create"))
        self.assertIsNotNone(role_tool_error(explorer, "edit"))
        # read tools allowed
        self.assertIsNone(role_tool_error(explorer, "read"))
        self.assertIsNone(role_tool_error(explorer, "shell"))
        # worker mode allows everything
        worker = reg.get_role("worker")
        self.assertIsNone(role_tool_error(worker, "create"))

    def test_role_tool_error_allowed_tools_enforced(self):
        restricted = AgentRole(key="limited", name="Limited", allowed_tools=["read", "grep"])
        self.assertIsNone(role_tool_error(restricted, "read"))
        self.assertIsNotNone(role_tool_error(restricted, "shell"))
        self.assertIsNotNone(role_tool_error(restricted, "edit"))

        mode = type("Mode", (), {
            "name": "Limited",
            "allowed_tools": ["read", "grep"],
            "disallowed_tools": [],
        })()
        self.assertIsNone(role_tool_error(mode, "read"))
        self.assertIsNotNone(role_tool_error(mode, "shell"))


# --------------------------------------------------------------------------- #
# Edge-case tests (was test_edge_role_registry.py)
# --------------------------------------------------------------------------- #

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
        assert r.provider == ""
        assert r.model == ""
        assert r.scope == "any"
        assert r.allowed_tools == []
        assert r.disallowed_tools == []

    def test_key_normalized_lower_strip(self):
        r = AgentRole(key="  MiXeD  ")
        assert r.key == "mixed"

    def test_scope_invalid_value(self):
        r = AgentRole(key="x", scope="not-a-real-scope")
        assert r.scope == "not-a-real-scope"

    def test_provider_stripped_lower(self):
        r = AgentRole(key="x", provider="  OpenAi  ")
        assert r.provider == "openai"

    def test_model_with_provider_prefix_splits(self):
        r = AgentRole(key="x", model="anthropic/claude-3-5-sonnet")
        assert r.provider == "anthropic"
        assert r.model == "claude-3-5-sonnet"

    def test_model_without_provider_prefix_leaves_provider_empty(self):
        r = AgentRole(key="x", model="gpt-4o")
        assert r.provider == ""
        assert r.model == "gpt-4o"

    def test_explicit_provider_takes_precedence_over_model_slash(self):
        r = AgentRole(key="x", provider="openrouter", model="meta-llama/llama-3")
        assert r.provider == "openrouter"
        assert r.model == "meta-llama/llama-3"

    def test_unicode_prompt_roundtrip(self):
        prompt = "Привет, мир! Роль: 🧠 测试 テスト"
        r = AgentRole(key="uni", prompt=prompt)
        assert r.prompt == prompt


class TestToolLists:
    def test_none_and_empty_equivalent_on_allow(self):
        # A role with allowed_tools=None must allow everything.
        # A role with allowed_tools=[] currently also allows everything
        # (empty list is falsy). Both should behave identically.
        r_none = AgentRole(key="a", allowed_tools=None)
        r_empty = AgentRole(key="b", allowed_tools=[])
        assert role_tool_error(r_none, "any_tool") is None
        assert role_tool_error(r_empty, "any_tool") is None

    def test_disallowed_none_and_empty(self):
        r = AgentRole(key="x", disallowed_tools=None)
        assert role_tool_error(r, "create") is None
        r2 = AgentRole(key="y", disallowed_tools=[])
        assert role_tool_error(r2, "create") is None

    def test_unknown_tool_names_in_lists(self):
        r = AgentRole(key="x", allowed_tools=["totally_unknown_tool"], disallowed_tools=["also_unknown"])
        # allowed list contains unknown name -> tool not in it -> blocked
        assert role_tool_error(r, "read") is not None
        # disallowed unknown name should not block unrelated tools
        r2 = AgentRole(key="y", disallowed_tools=["ghost_tool"])
        assert role_tool_error(r2, "edit") is None

    def test_tool_string_whitespace_in_lists(self):
        r = AgentRole(key="x", allowed_tools=[" read ", "grep"])
        assert role_tool_error(r, "read") is None
        assert role_tool_error(r, "grep") is None


class TestIsToolAllowed:
    def test_none_empty_tool_name_allowed(self):
        r = AgentRole(key="x", allowed_tools=["read"])
        # None/"" tool names are tolerated (return None) even though they are
        # not in the allowed list.
        assert role_tool_error(r, None) is None
        assert role_tool_error(r, "") is None

    def test_whitespace_tool_name_differs_from_empty(self):
        # " " strips to "" -> falsy? No: " " is truthy, strip yields "".
        # It is NOT caught by the `not tool_name` guard, so it falls through to
        # the allowed-list check. This is an inconsistency with None/"".
        r = AgentRole(key="x", allowed_tools=["read"])
        result = role_tool_error(r, " ")
        # Document actual behavior: a whitespace tool is treated as a real tool
        # and blocked because it is not in the allowed list.
        assert result is not None

    def test_case_insensitive_tool(self):
        r = AgentRole(key="x", allowed_tools=["read"])
        assert role_tool_error(r, "READ") is None
        assert role_tool_error(r, "Read") is None

    def test_tool_in_allowed_and_disallowed(self):
        # disallowed wins over allowed
        r = AgentRole(key="x", allowed_tools=["read"], disallowed_tools=["read"])
        assert role_tool_error(r, "read") is not None

    def test_allowed_empty_vs_allowed_set(self):
        # WARNING: allowed_tools=[] allows everything (falsy). This means an
        # author who writes `tools:` with an empty value silently gets full
        # tool access - a security footgun.
        r_empty = AgentRole(key="x", allowed_tools=[])
        assert role_tool_error(r_empty, "shell") is None  # shell allowed!

    def test_disallowed_blocks_specified_tools(self):
        r = AgentRole(key="x", disallowed_tools=["create", "edit"])
        for w in ("create", "edit"):
            assert role_tool_error(r, w) is not None
        assert role_tool_error(r, "read") is None


# --------------------------------------------------------------------------- #
# role_tool_error helper
# --------------------------------------------------------------------------- #
class TestRoleToolError:
    def test_none_def(self):
        assert role_tool_error(None, "read") is None

    def test_plain_object_disallowed(self):
        class Fake:
            disallowed_tools = ["create"]
        assert role_tool_error(Fake(), "create") is not None
        assert role_tool_error(Fake(), "read") is None


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
            self._make_role(tmpdir, "p.md", "---\nname: p\nmodel: openai/gpt-4o\n---\np")
            reg = RoleRegistry()
            roles = reg.load_roles(project_dir=tmpdir, include_global=False)
            assert roles["p"].provider == "openai"
            assert roles["p"].model == "gpt-4o"
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
        assert len(roles) >= 2

    def test_global_only(self):
        reg = RoleRegistry()
        roles = reg.load_roles(project_dir=None, include_global=True)
        assert "worker" in roles

    def test_scope_filtering_main_vs_subagent(self):
        reg = RoleRegistry()
        main = reg.list_roles("main")
        assert "worker" in main  # scope any
        assert "explorer" in main  # scope any
        sub = reg.list_subagent_roles()
        assert "worker" in sub
        assert "explorer" in sub

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

    def test_explorer_scope_any(self):
        assert BUILTIN_ROLES["explorer"].scope in ("any", "subagent")


class TestRoleToolWildcards:
    def test_allowed_tools_wildcard(self):
        role = AgentRole(key="mcp_only", allowed_tools=["mcp__*", "read"])
        assert role_tool_error(role, "read") is None
        assert role_tool_error(role, "mcp__github__create_issue") is None
        assert role_tool_error(role, "mcp__slack__post") is None
        assert role_tool_error(role, "shell") is not None
        assert role_tool_error(role, "edit") is not None

    def test_disallowed_tools_wildcard(self):
        role = AgentRole(key="no_mcp", disallowed_tools=["mcp__*", "*delete*"])
        assert role_tool_error(role, "read") is None
        assert role_tool_error(role, "shell") is None
        assert role_tool_error(role, "mcp__github__create_issue") is not None
        assert role_tool_error(role, "delete_file") is not None
        assert role_tool_error(role, "safe_delete") is not None

    def test_wildcard_with_normalizer(self):
        def normalizer(name: str) -> str:
            return f"mcp__{name}" if name.startswith("ext_") else name

        role = AgentRole(key="ext", allowed_tools=["mcp__*"], tool_name_normalizer=normalizer)
        assert role_tool_error(role, "ext_tool") is None
        assert role_tool_error(role, "other_tool") is not None

