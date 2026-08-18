import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from core.application.rules.rules import RuleDefinition, RulesManager
from core.infrastructure.runtime.git_utils import run_git
from core.infrastructure.storage.git_checkpoint import GitCheckpointManager


def _write_rule(project_dir, fname, content):
    rules_dir = os.path.join(project_dir, ".johnston", "rules")
    os.makedirs(rules_dir, exist_ok=True)
    path = os.path.join(rules_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


class TestRulesManagerEdge(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rm = RulesManager()

    def tearDown(self):
        self.rm.invalidate_cache()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_frontmatter_uses_filename_and_no_roles(self):
        _write_rule(self.tmpdir, "my_rule.md", "Just text with no frontmatter")
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, "my_rule")
        self.assertEqual(rules[0].roles, [])
        self.assertTrue(rules[0].is_active_for_roles("worker"))

    def test_empty_content_after_frontmatter(self):
        _write_rule(self.tmpdir, "empty.md", "---\nname: Empty\nrole: worker\n---\n")
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].name, "Empty")
        self.assertEqual(rules[0].content, "")

    def test_role_formats(self):
        # bracket list
        _write_rule(self.tmpdir, "a.md", "---\nrole: [alpha, beta]\n---\ncontent a")
        # comma separated
        _write_rule(self.tmpdir, "b.md", "---\nrole: gamma, delta\n---\ncontent b")
        # single role
        _write_rule(self.tmpdir, "c.md", "---\nrole: epsilon\n---\ncontent c")
        # no role
        _write_rule(self.tmpdir, "d.md", "---\nname: NoRole\n---\ncontent d")
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        # sorted filenames a.md,b.md,c.md,d.md map to rules[0..3]
        self.assertEqual(sorted(rules[0].roles), ["alpha", "beta"])
        self.assertEqual(sorted(rules[1].roles), ["delta", "gamma"])
        self.assertEqual(rules[2].roles, ["epsilon"])
        self.assertEqual(rules[3].roles, [])

    def test_is_active_for_roles_none_and_case(self):
        self.assertTrue(RuleDefinition("r", "c").is_active_for_roles(None))
        rule = RuleDefinition("r", "c", roles=["Worker"])
        # roles are lowercased at construction; case-insensitive lookup
        self.assertTrue(rule.is_active_for_roles("worker"))
        self.assertTrue(rule.is_active_for_roles("WORKER"))
        self.assertTrue(rule.is_active_for_roles("  Worker  "))

    def test_get_formatted_rules_no_match_empty(self):
        _write_rule(self.tmpdir, "a.md", "---\nrole: worker\n---\nx")
        with mock.patch("core.infrastructure.runtime.markdown_scanner.CONFIG_DIR", self.tmpdir):
            rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
            self.assertEqual(len(rules), 1)
            self.assertEqual(self.rm.get_formatted_rules(role="explorer", project_dir=self.tmpdir), "")

    def test_load_rules_include_global_false(self):
        with mock.patch("core.infrastructure.runtime.markdown_scanner.CONFIG_DIR", self.tmpdir):
            # global rule
            global_rules = os.path.join(self.tmpdir, "rules")
            os.makedirs(global_rules, exist_ok=True)
            with open(os.path.join(global_rules, "g.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: Global\n---\nglobal content")
            # project rule
            _write_rule(self.tmpdir, "p.md", "---\nname: Project\n---\nproj content")
            rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
            self.assertEqual([r.name for r in rules], ["Project"])

    def test_cache_ttl_and_invalidate(self):
        _write_rule(self.tmpdir, "a.md", "---\nname: One\n---\nfirst")
        self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        path = os.path.join(self.tmpdir, ".johnston", "rules", "a.md")
        st = os.stat(path)

        # change within TTL with same byte length AND preserved mtime ->
        # signature unchanged -> stale content (by design)
        _write_rule(self.tmpdir, "a.md", "---\nname: One\n---\nfirse")
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(rules[0].content, "first")

        # invalidate_cache forces re-scan even with same signature
        self.rm.invalidate_cache()
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(rules[0].content, "firse")

    def test_cache_same_size_same_mtime_not_detected(self):
        # Content changes but file size stays identical and mtime is preserved ->
        # signature unchanged, within TTL -> stale content (known limitation).
        _write_rule(self.tmpdir, "a.md", "---\nname: One\n---\nfirst")
        self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        path = os.path.join(self.tmpdir, ".johnston", "rules", "a.md")
        st = os.stat(path)
        # rewrite with identical byte length (5 chars) and preserved mtime so
        # signature (mtime_ns, size) is unchanged -> stale content within TTL.
        with open(path, "w", encoding="utf-8") as f:
            f.write("---\nname: One\n---\nsecon")
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(rules[0].content, "first")

    def test_broken_frontmatter_returns_none(self):
        # unclosed frontmatter -> parse returns meta {}, content still parsed
        _write_rule(self.tmpdir, "broken.md", "---\nname: Broken\nrole: worker\n")
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(len(rules), 1)
        # name falls back to base name
        self.assertEqual(rules[0].name, "broken")

    def test_unreadable_file_returns_none(self):
        if not hasattr(os, "geteuid"):
            self.skipTest("POSIX-only (os.geteuid)")
        if os.geteuid() == 0:
            self.skipTest("running as root, chmod ineffective")
        _write_rule(self.tmpdir, "a.md", "---\nname: A\n---\ncontent")
        path = os.path.join(self.tmpdir, ".johnston", "rules", "a.md")
        os.chmod(path, 0)
        try:
            rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
            self.assertEqual(len(rules), 0)
        finally:
            os.chmod(path, 0o644)

    def test_duplicate_rule_names(self):
        _write_rule(self.tmpdir, "a.md", "---\nname: Dup\n---\nfirst")
        _write_rule(self.tmpdir, "b.md", "---\nname: Dup\n---\nsecond")
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(len(rules), 2)
        self.assertEqual(rules[0].name, "Dup")
        self.assertEqual(rules[1].name, "Dup")

    def test_cyrillic_role_names(self):
        # roles lowercased at construction (by design), so cyrillic case is lost
        rule = RuleDefinition("r", "c", roles=["Рабочий"])
        self.assertEqual(rule.roles, ["рабочий"])
        self.assertTrue(rule.is_active_for_roles("Рабочий"))
        _write_rule(self.tmpdir, "a.md", "---\nrole: Рабочий, Исследователь\n---\ncontent")
        rules = self.rm.load_rules(project_dir=self.tmpdir, include_global=False)
        self.assertEqual(sorted(rules[0].roles), ["исследователь", "рабочий"])


class TestGitCheckpointEdge(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _init_git_repo(self, path=None):
        target = path or self.tmpdir
        subprocess.run(["git", "init"], cwd=target, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "TestUser"], cwd=target, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=target, capture_output=True, check=True)
        with open(os.path.join(target, "initial.txt"), "w") as f:
            f.write("initial\n")
        subprocess.run(["git", "add", "initial.txt"], cwd=target, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=target, capture_output=True, check=True)
        return target

    def test_invalid_target_paths(self):
        self.assertFalse(GitCheckpointManager.is_valid_checkpoint_target(os.path.expanduser("~")))
        self.assertFalse(GitCheckpointManager.is_valid_checkpoint_target("/"))
        # path outside any git repo
        outside = os.path.join(self.tmpdir, "no_repo")
        os.makedirs(outside, exist_ok=True)
        self.assertFalse(GitCheckpointManager.is_valid_checkpoint_target(outside))

    def test_path_with_dots_is_valid_inside_repo(self):
        repo = self._init_git_repo()
        sub = os.path.join(repo, "sub", "dir")
        os.makedirs(sub, exist_ok=True)
        # realpath resolves .. and . to the repo dir
        dotted = os.path.join(repo, "sub", "..", ".")
        self.assertTrue(GitCheckpointManager.is_valid_checkpoint_target(dotted))

    def test_create_checkpoint_auto_init_false_non_git(self):
        outside = os.path.join(self.tmpdir, "no_repo")
        os.makedirs(outside, exist_ok=True)
        sha = GitCheckpointManager.create_checkpoint("s", 0, project_path=outside, auto_init=False)
        self.assertIsNone(sha)

    def test_create_checkpoint_nonexistent_path(self):
        missing = os.path.join(self.tmpdir, "does_not_exist")
        sha = GitCheckpointManager.create_checkpoint("s", 0, project_path=missing, auto_init=True)
        self.assertIsNone(sha)

    def test_get_ref_name_slash_and_spaces(self):
        # session_id with "/" produces nested ref path but still a valid ref string
        ref = GitCheckpointManager.get_ref_name("a/b c", 0)
        self.assertIn("a/b c/0", ref)
        self.assertTrue(ref.startswith(GitCheckpointManager.REF_PREFIX))

    def test_purge_non_numeric_index_valueerror_caught(self):
        repo = self._init_git_repo()
        GitCheckpointManager.create_checkpoint("s", 0, project_path=repo)
        shadow_dir, _ = GitCheckpointManager._get_shadow_dir(repo)
        # create a ref with non-numeric trailing component in the session namespace
        bad_ref = f"{GitCheckpointManager.REF_PREFIX}/s/notnum"
        sha = run_git(["rev-parse", "HEAD"], cwd=shadow_dir).stdout.strip()
        run_git(["update-ref", bad_ref, sha], cwd=shadow_dir)
        # should not raise ValueError
        GitCheckpointManager.purge_checkpoints_after("s", 0, project_path=repo)
        # numeric checkpoint 0 survives purge
        self.assertTrue(GitCheckpointManager.restore_checkpoint("s", 0, project_path=repo))

    def test_purge_checkpoints_after_non_git_no_error(self):
        outside = os.path.join(self.tmpdir, "no_repo")
        os.makedirs(outside, exist_ok=True)
        GitCheckpointManager.purge_checkpoints_after("s", 0, project_path=outside)

    def test_restore_checkpoint_nonexistent_ref(self):
        repo = self._init_git_repo()
        self.assertFalse(GitCheckpointManager.restore_checkpoint("ghost", 0, project_path=repo))

    def test_user_name_email_set(self):
        repo = self._init_git_repo()
        GitCheckpointManager.ensure_git_repo(repo)
        shadow, _ = GitCheckpointManager._get_shadow_dir(repo)
        name = run_git(["config", "user.name"], cwd=shadow).stdout.strip()
        email = run_git(["config", "user.email"], cwd=shadow).stdout.strip()
        self.assertEqual(name, "Johnston AI")
        self.assertEqual(email, "johnston@local")

    def test_ensure_git_repo_idempotent(self):
        repo = self._init_git_repo()
        self.assertTrue(GitCheckpointManager.ensure_git_repo(repo))
        self.assertTrue(GitCheckpointManager.ensure_git_repo(repo))
        self.assertTrue(GitCheckpointManager.is_git_repo(repo))

    def test_get_diff_stats_batch_empty_indices(self):
        repo = self._init_git_repo()
        self.assertEqual(GitCheckpointManager.get_diff_stats_batch("s", [], project_path=repo), {})

    def test_session_id_special_chars_ref(self):
        repo = self._init_git_repo()
        sid = "sess#1_@x"
        sha = GitCheckpointManager.create_checkpoint(sid, 0, project_path=repo)
        self.assertIsNotNone(sha)
        self.assertTrue(GitCheckpointManager.restore_checkpoint(sid, 0, project_path=repo))


if __name__ == "__main__":
    unittest.main()
