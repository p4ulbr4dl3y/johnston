"""Edge-case tests for tools/shell.py. Looks for bugs in command handling,
timeout/termination, output decoding/truncation, cwd/env behavior, and
whether the claimed destructive-command protection actually exists."""
import asyncio
import os
import shlex
import tempfile
import unittest

from tools.context import ToolContext
from tools.shell import ShellTool


class TestShellEdge(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from core.permission_manager import PermissionManager

        PermissionManager.get_instance().clear_session_overrides()
        self.tool = ShellTool()

    def _ctx(self, cwd=None, is_subagent=True):
        """Real ToolContext. Subagent path reads streams synchronously."""
        return ToolContext(app=None, is_subagent=is_subagent, cwd=cwd)

    # ---------- empty / whitespace / None command ----------

    async def test_empty_command_safe(self):
        res = await self.tool.execute({"command": ""}, ctx=self._ctx())
        self.assertEqual(res, "(no output)")

    async def test_whitespace_command_safe(self):
        res = await self.tool.execute({"command": "   \t  "}, ctx=self._ctx())
        self.assertEqual(res, "(no output)")

    async def test_none_command_safe(self):
        res = await self.tool.execute({"command": None}, ctx=self._ctx())
        self.assertEqual(res, "(no output)")

    # ---------- special chars / metacharacters -------------

    async def test_semicolon_runs_both(self):
        res = await self.tool.execute({"command": "echo a; echo b"}, ctx=self._ctx())
        self.assertIn("a", res)
        self.assertIn("b", res)

    async def test_ampersand_and_executes(self):
        res = await self.tool.execute({"command": "echo a && echo b"}, ctx=self._ctx())
        self.assertIn("a", res)
        self.assertIn("b", res)

    async def test_or_short_circuit(self):
        # First cmd succeeds -> second must NOT run (|| short-circuit).
        res = await self.tool.execute({"command": "echo ok || echo SHOULD_NOT_RUN"}, ctx=self._ctx())
        self.assertIn("ok", res)
        self.assertNotIn("SHOULD_NOT_RUN", res)

    async def test_pipe_chains(self):
        res = await self.tool.execute({"command": "echo pipe_data | cat"}, ctx=self._ctx())
        self.assertIn("pipe_data", res)

    async def test_redirect_stdout_to_devnull_loses_output(self):
        res = await self.tool.execute({"command": "echo hidden > /dev/null"}, ctx=self._ctx())
        self.assertNotIn("hidden", res)

    async def test_redirect_append(self):
        res = await self.tool.execute({"command": "echo x >> /dev/null"}, ctx=self._ctx())
        self.assertEqual(res, "(no output)")

    async def test_input_redirect(self):
        res = await self.tool.execute({"command": "echo from_stdin < /dev/null"}, ctx=self._ctx())
        self.assertIn("from_stdin", res)

    async def test_command_substitution_runs(self):
        res = await self.tool.execute({"command": "echo dollar_$(echo sub)"}, ctx=self._ctx())
        # $(...) runs -> output contains "sub"
        self.assertIn("sub", res)

    async def test_backtick_substitution_runs(self):
        res = await self.tool.execute({"command": "echo bt_`echo sub2`"}, ctx=self._ctx())
        self.assertIn("sub2", res)

    async def test_arithmetic_substitution(self):
        res = await self.tool.execute({"command": "echo $((2+3))"}, ctx=self._ctx())
        self.assertIn("5", res)

    async def test_not_bang_operator(self):
        # `! echo -n ; echo $?` → negation gives exit 1 → $? == 1
        res = await self.tool.execute(
            {"command": "! true; echo exit=$?"}, ctx=self._ctx()
        )
        self.assertIn("exit=1", res)

    async def test_wildcard_glob_expands(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "apple.txt"), "w") as f:
                f.write("a")
            with open(os.path.join(d, "banana.txt"), "w") as f:
                f.write("b")
            res = await self.tool.execute({"command": "echo *"}, ctx=self._ctx(cwd=d))
        self.assertIn("apple.txt", res)
        self.assertIn("banana.txt", res)

    async def test_tilde_expands(self):
        res = await self.tool.execute({"command": "echo ~"}, ctx=self._ctx())
        self.assertTrue(os.path.isabs(res.strip()))

    async def test_nested_quotes(self):
        res = await self.tool.execute({"command": "echo \"outer 'inner' quote\""}, ctx=self._ctx())
        self.assertIn("outer 'inner' quote", res)

    # ---------- long / unicode / emoji / space args ----------

    async def test_unicode_and_emoji_roundtrip(self):
        payload = "héllo wörld привет 世界 🚀"
        res = await self.tool.execute({"command": f"echo {shlex.quote(payload)}"}, ctx=self._ctx())
        self.assertIn(payload, res)

    async def test_argv_with_spaces_quoted(self):
        res = await self.tool.execute({"command": 'echo "a b  c" d'}, ctx=self._ctx())
        self.assertIn("a b  c d", res)

    async def test_very_long_command_many_args(self):
        args = " ".join(f"a{i}" for i in range(5000))
        res = await self.tool.execute({"command": f"echo {args}"}, ctx=self._ctx())
        self.assertIn("a4999", res)

    # ---------- timeout kills runaway ----------

    async def test_timeout_kills_subagent_subprocess(self):
        # /bin/sleep bypasses SLEEP_CHAIN_REGEX; must be terminated by timeout.
        t0 = asyncio.get_running_loop().time()
        res = await self.tool.execute(
            {"command": "/bin/sleep 30", "timeout": 1}, ctx=self._ctx()
        )
        elapsed = asyncio.get_running_loop().time() - t0
        self.assertIn("ERR: timeout 'shell': timed out after 1s", res)
        # Must return promptly (not wait the full 30s).
        self.assertLess(elapsed, 10)

    # ---------- exit codes ----------

    async def test_false_exit_code_is_lost(self):
        # `false` exits 1 but the tool never surfaces the exit code.
        res = await self.tool.execute({"command": "false"}, ctx=self._ctx())
        self.assertEqual(res, "(no output)")

    async def test_explicit_exit_code_is_lost(self):
        # Never-reached output + non-zero exit → tool reports nothing, no code.
        res = await self.tool.execute({"command": "echo never_shown; exit 7"}, ctx=self._ctx())
        # Exit code discarded and nonzero treated identically to success.
        self.assertIn("never_shown", res)

    async def test_stderr_only_captured(self):
        res = await self.tool.execute({"command": "echo stderr_only 1>&2"}, ctx=self._ctx())
        self.assertIn("stderr_only", res)

    async def test_kill_signal_behaves(self):
        # self-kill → shell reports no output; must not crash.
        res = await self.tool.execute({"command": "kill -9 $$"}, ctx=self._ctx())
        self.assertIsInstance(res, str)

    # ---------- unicode/binary output, CRLF, huge output ----------

    async def test_binary_bytes_no_crash(self):
        res = await self.tool.execute({"command": "printf '\\x01\\x02\\xff\\x00data'"}, ctx=self._ctx())
        self.assertIn("data", res)

    async def test_crlf_normalized(self):
        res = await self.tool.execute({"command": "printf 'one\\r\\ntwo\\r\\n'"}, ctx=self._ctx())
        self.assertIn("one", res)
        self.assertIn("two", res)

    async def test_very_large_output_truncated(self):
        cmd = "python3 -c 'import sys; sys.stdout.write(\"X\"*6000)'" if os.name != "nt" else "echo"
        res = await self.tool.execute({"command": cmd}, ctx=self._ctx())
        self.assertIn("Output truncated", res)
        self.assertIn("X" * 3900, res)  # tail preserved near 4000-char limit

    # ---------- cwd behavior ----------

    async def test_nonexistent_cwd_falls_back(self):
        # ToolContext refuses nonexistent cwd (sets self.cwd=None) → runs in default cwd.
        ctx = self._ctx(cwd="/nonexistent/path/xyz_123")
        self.assertIsNone(ctx.cwd)
        res = await self.tool.execute({"command": "echo cwd_fallback"}, ctx=ctx)
        self.assertIn("cwd_fallback", res)

    async def test_relative_cwd(self):
        res = await self.tool.execute({"command": "pwd"}, ctx=self._ctx())
        self.assertTrue(os.path.isabs(res.strip()))

    async def test_cd_command_inside(self):
        with tempfile.TemporaryDirectory() as sub:
            res = await self.tool.execute(
                {"command": f"cd {shlex.quote(sub)} && pwd"}, ctx=self._ctx()
            )
            self.assertIn(sub, res)

    # ---------- env behavior ----------

    async def test_env_inherited(self):
        key = "JOHNSTON_EDGE_ENV_TEST"
        os.environ[key] = "inherited_value"
        try:
            res = await self.tool.execute({"command": f"echo got=${{{key}}}"}, ctx=self._ctx())
        finally:
            del os.environ[key]
        self.assertIn("got=inherited_value", res)

    async def test_path_unset_command_not_found(self):
        res = await self.tool.execute({"command": "PATH=/nonexistent_path_zz echo hi; echo $?"}, ctx=self._ctx())
        # First command (if any) not found; we at least get output.
        self.assertIsInstance(res, str)

    async def test_missing_env_var_empty(self):
        key = "JOHNSTON_DEFINITELY_UNSET_VAR_9876"
        res = await self.tool.execute({"command": f"echo val=[${{{key}}}]"}, ctx=self._ctx())
        self.assertIn("val=[]", res)

    # ---------- permission denied / non-executable ----------

    async def test_non_executable_script_denied(self):
        with tempfile.TemporaryDirectory() as d:
            script = os.path.join(d, "noexec.sh")
            with open(script, "w") as f:
                f.write("echo SHOULD_NOT_RUN\n")
            os.chmod(script, 0o644)  # explicitly not executable
            res = await self.tool.execute({"command": script}, ctx=self._ctx(cwd=d))
            self.assertNotIn("SHOULD_NOT_RUN", res)
            self.assertIn("ermission denied", res)

    # ---------- destructive safety (claimed in description) ----------

    async def test_rm_rf_not_blocked_default(self):
        # Description claims "Destructive commands confirm." Verify whether any
        # protection exists in execute(). Deleting our own tmp dir is safe.
        with tempfile.TemporaryDirectory() as d:
            victim = os.path.join(d, "victim")
            os.mkdir(victim)
            res = await self.tool.execute({"command": f"rm -rf {shlex.quote(victim)}"}, ctx=self._ctx())
            self.assertFalse(os.path.exists(victim))
            # If protection existed, res would be an ERR reject.
            self.assertNotIn("ERR: reject", res)

    async def test_mkfs_and_dd_not_blocked(self):
        # No-builtin-protection probe (source-level; we do NOT format disks).
        self.assertEqual(inspect_has_no_destructive_guard(), True)

    # ---------- parallelism ----------

    async def test_concurrent_shell_calls_isolated(self):
        res1, res2 = await asyncio.gather(
            self.tool.execute({"command": "echo task_alpha"}, ctx=self._ctx()),
            self.tool.execute({"command": "echo task_beta"}, ctx=self._ctx()),
        )
        self.assertIn("task_alpha", res1)
        self.assertIn("task_beta", res2)


def inspect_has_no_destructive_guard():
    """Source-level check: shell.py claims to confirm destructive commands
    but contains no rm/mkfs/dd/fdisk/format guard anywhere."""
    import inspect as _i

    from tools import shell as shell_mod

    return "mkfs" not in _i.getsource(shell_mod) and "rm -rf" not in _i.getsource(shell_mod)


if __name__ == "__main__":
    unittest.main()
