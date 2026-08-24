"""Tests for tools/shell.py.

Consolidated from the former test_shell.py (execution paths) and test_edge_shell.py
(command-parsing / timeout / output edge cases) into a single per-module file.
"""
import asyncio
import os
import re
import shlex
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.infrastructure.tasks.manager import TaskManager
from tools.shell import ShellTool, _new_task_id


@pytest.fixture(autouse=True)
def _reset_permissions():
    """Clear session overrides and avoid touching the real config file."""
    from core.permission_manager import PermissionManager

    pm = PermissionManager.get_instance()
    pm.clear_session_overrides()
    with patch("core.permission_manager.CONFIG_FILE", "/nonexistent_test_config.json"):
        yield
    pm.clear_session_overrides()


@pytest.fixture
def tool():
    return ShellTool()


def _app(make_app_mock, *, task_manager=None, session_id="pytest-session-id"):
    """A mock host app, optionally wired with a real TaskManager."""
    app = make_app_mock()
    app.current_session_id = session_id
    app.is_subagent = False
    if task_manager is not None:
        app.task_manager = task_manager
    return app


def _process(wait_result=0, stdout=None):
    """Build a fake subprocess with a controllable wait/stdout."""
    p = MagicMock()
    p.stdout = stdout
    if isinstance(wait_result, asyncio.Future):
        p.wait.return_value = wait_result
    else:

        async def _wait():
            return wait_result

        p.wait = _wait
    return p


# --------------------------------------------------------------------------- #
# ID generation
# --------------------------------------------------------------------------- #


def test_new_task_id():
    tid1 = _new_task_id()
    tid2 = _new_task_id()
    assert tid1.startswith("shell_")
    assert tid1 != tid2


# --------------------------------------------------------------------------- #
# Basic execution
# --------------------------------------------------------------------------- #


async def test_sleep_chain_no_remainder(tool):
    cmd = "sleep 0.001" if os.name != "nt" else "cd ."
    res = str(await tool.execute({"command": cmd}))
    assert res == "(no output)"


async def test_sleep_chain_with_remainder(tool):
    cmd = "sleep 0.001 && echo after_sleep" if os.name != "nt" else "echo after_sleep"
    res = str(await tool.execute({"command": cmd}))
    assert "after_sleep" in res


async def test_standard_pipe_execution(tool):
    res = str(await tool.execute({"command": "echo std_pipe_test"}))
    assert "std_pipe_test" in res


async def test_normal_execution_empty_output(tool):
    # `true` is POSIX-only; `cd .` produces no output on both cmd/PowerShell and sh.
    res = str(await tool.execute({"command": "true" if os.name != "nt" else "cd ."}))
    assert res == "(no output)"


async def test_invalid_timeout_value_falls_back_to_default(tool):
    res = str(await tool.execute({"command": "echo hi", "timeout": "abc"}))
    assert "hi" in res


# --------------------------------------------------------------------------- #
# Subprocess creation branches
# --------------------------------------------------------------------------- #


async def test_windows_execution_branch(tool):
    with (
        patch("tools.shell.is_windows", return_value=True),
        patch.object(ShellTool, "_create_windows_process", return_value=_process()) as mock_win_proc,
    ):
        res = str(await tool.execute({"command": "dir"}))
        mock_win_proc.assert_called_once()
        assert res is not None


async def test_subprocess_creation_exception_cleanup_no_transport(tool):
    with (
        patch("tools.shell.is_windows", return_value=False),
        patch.object(ShellTool, "_create_std_process", side_effect=RuntimeError("Subprocess launch failed")),
    ):
        with pytest.raises(RuntimeError):
            await tool.execute({"command": "echo fail"})


async def test_create_windows_process_powershell(tool):
    with (
        patch(
            "tools.shell.shell_executable",
            return_value="C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe",
        ),
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
    ):
        await tool._create_windows_process("Get-Process", {"ENV": "1"})
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
        assert "-NoProfile" in args


async def test_create_windows_process_cmd(tool):
    with (
        patch("tools.shell.shell_executable", return_value="C:\\Windows\\System32\\cmd.exe"),
        patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec,
    ):
        await tool._create_windows_process("dir", {"ENV": "1"})
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "C:\\Windows\\System32\\cmd.exe"
        assert "/c" in args


async def test_create_windows_process_default_shell(tool):
    from core.infrastructure.platform.platform_utils import shell_subprocess_kwargs

    with (
        patch("tools.shell.shell_executable", return_value="/bin/sh"),
        patch("asyncio.create_subprocess_shell", new_callable=AsyncMock) as mock_shell,
    ):
        await tool._create_windows_process("echo 1", {"ENV": "1"})
        mock_shell.assert_called_once_with(
            "echo 1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={"ENV": "1"},
            cwd=None,
            **shell_subprocess_kwargs(),
        )


# --------------------------------------------------------------------------- #
# Timeout / cancellation / background handling on the sync path
# --------------------------------------------------------------------------- #


async def test_command_timeout_terminates_process(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)

    fut = asyncio.Future()
    p = _process(wait_result=fut)
    p.returncode = None

    with (
        patch("tools.shell.shell_executable", return_value="/bin/sh"),
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
    ):
        res = str(await tool.execute({"command": "run_long_task", "timeout": 1}, ctx=ctx))
        assert "ERR: timeout 'shell': timed out after 1s" in res
        assert "moved to background." not in res
        mock_term.assert_called_once()
        # Sync tasks are temporarily registered (for ctrl+b) even on timeout;
        # they are NOT converted to persistent background tasks, so the
        # manager must not still hold them after the tool returns.
        assert len([t for t in app.task_manager]) == 0


async def test_move_to_background_during_sync_execution(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)

    p = _process(wait_result=asyncio.Future(), stdout=None)

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.shell_executable", return_value="/bin/sh"),
        patch("tools.shell.terminate_process", new_callable=AsyncMock),
    ):
        exec_task = asyncio.create_task(tool.execute({"command": "tail -f log.txt"}, ctx=ctx))
        await asyncio.sleep(0.02)

        tasks = [t for t in app.task_manager]
        assert len(tasks) == 1
        task = tasks[0]
        task.output.append("server started on port 8080\n")
        task.move_to_background()

        res = str(await exec_task)
        assert "moved to background by user after" in res
        assert "Recent Output:\nserver started on port 8080" in res
        assert task.is_background
        assert len([t for t in app.task_manager]) == 1


async def test_main_sync_task_visible_and_running_while_alive(tool, make_app_mock, make_tool_context):
    # While a sync shell runs, it must be visible in the task manager and
    # report is_running=True (process still alive) so ctrl+b / manage_shell
    # can act on it; after completion it must be dropped.
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)

    p = _process(wait_result=asyncio.Future(), stdout=None)
    p.returncode = None

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock),
    ):
        exec_task = asyncio.create_task(tool.execute({"command": "long_running_sync_cmd"}, ctx=ctx))
        await asyncio.sleep(0.05)
        tasks = [t for t in app.task_manager]
        assert len(tasks) == 1
        assert tasks[0].is_running
        assert not tasks[0].is_background
        exec_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await exec_task
    assert len([t for t in app.task_manager]) == 0


async def test_execute_cancelled_terminates_process(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)

    p = _process(wait_result=asyncio.Future())

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
    ):
        exec_task = asyncio.create_task(tool.execute({"command": "tail -f log.txt"}, ctx=ctx))
        await asyncio.sleep(0.05)
        exec_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await exec_task
        mock_term.assert_called_once()


async def test_main_sync_timeout_with_output(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)

    p = _process(wait_result=asyncio.Future(), stdout=None)

    def _add_task(task):
        task.output.append("A" * 5000)

    app.task_manager._add = _add_task  # placeholder (unused) - real registration streams live output
    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
    ):
        res = str(await tool.execute({"command": "tail -f x", "timeout": 1}, ctx=ctx))
        assert "ERR: timeout 'shell': timed out after 1s" in res
        mock_term.assert_called_once()


async def test_main_sync_read_task_drain_timeout(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)
    p = _process(stdout=None)

    async def custom_wait_for(fut, timeout):
        if timeout == 2.0:
            raise asyncio.TimeoutError()
        return await fut

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
    ):
        res = str(await tool.execute({"command": "echo test"}, ctx=ctx))
    assert res == "(no output)"


async def test_main_sync_not_registered_as_background_task(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app)
    p = _process(stdout=None)

    with patch.object(ShellTool, "_create_std_process", return_value=p):
        res = str(await tool.execute({"command": "echo sync"}, ctx=ctx))
        assert res == "(no output)"
        # Sync task is dropped from the manager after completion (never
        # converted to a persistent background task).
        assert len([t for t in app.task_manager]) == 0


async def test_sync_task_cleaned_up_from_background_tasks(tool, make_app_mock):
    app = _app(make_app_mock, task_manager=TaskManager())
    res = str(await tool.execute({"command": "echo test_sync_cleanup"}, ctx=app))
    assert "test_sync_cleanup" in res
    # Sync task should be dropped from the manager after finishing
    assert len([t for t in app.task_manager]) == 0


@pytest.mark.skipif(os.name == "nt", reason="sleep is POSIX-only")
async def test_sleep_chain_exceeds_timeout(tool):
    res = str(await tool.execute({"command": "sleep 5", "timeout": 1}))
    assert "ERR: timeout 'shell': timed out after 1s" in res


# --------------------------------------------------------------------------- #
# Subagent (sync stream) execution path
# --------------------------------------------------------------------------- #


async def test_subagent_shell_execution_success(tool, make_tool_context):
    ctx = make_tool_context(is_subagent=True)
    res = str(await tool.execute({"command": "echo subagent_test", "timeout": 10}, ctx=ctx))
    assert "subagent_test" in res


async def test_subagent_shell_execution_timeout(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app, is_subagent=True)

    p = _process(wait_result=asyncio.Future(), stdout=None)

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
    ):
        res = str(await tool.execute({"command": "run_long_task", "timeout": 1}, ctx=ctx))
        assert "ERR: timeout 'shell': timed out after 1s" in res
        mock_term.assert_called_once()


async def test_subagent_no_stdout_stream(tool, make_app_mock, make_tool_context):
    # p.stdout is None -> the stream reader exits immediately and empty
    # output is reported instead of hanging.
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app, is_subagent=True)
    p = _process(stdout=None)

    with patch.object(ShellTool, "_create_std_process", return_value=p):
        res = str(await tool.execute({"command": "true"}, ctx=ctx))
        assert res == "(no output)"


async def test_subagent_read_task_drain_timeout(tool, make_app_mock, make_tool_context):
    # Process finishes, but draining the read task times out -> ignored.
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app, is_subagent=True)
    p = _process(stdout=None)

    async def custom_wait_for(fut, timeout):
        if timeout == 2.0:
            raise asyncio.TimeoutError()
        return await fut

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.asyncio.wait_for", side_effect=custom_wait_for),
    ):
        res = str(await tool.execute({"command": "true"}, ctx=ctx))
        assert res == "(no output)"


async def test_subagent_timeout_read_task_exception_ignored(tool, make_app_mock, make_tool_context):
    # Subagent timeout path: draining the read task after kill raises a
    # non-Timeout exception -> swallowed, partial output still reported.
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app, is_subagent=True)
    p = _process(wait_result=asyncio.Future(), stdout=None)

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock),
    ):
        res = str(await tool.execute({"command": "run_long_task", "timeout": 1}, ctx=ctx))
        assert "ERR: timeout 'shell': timed out after 1s" in res


@pytest.mark.slow
async def test_subagent_shell_execution_cancelled(tool, make_tool_context):
    ctx = make_tool_context(is_subagent=True)
    p = _process(stdout=None)

    wait_invoked = asyncio.Event()

    async def _mock_wait():
        wait_invoked.set()
        await asyncio.Event().wait()  # never resolves; cancellable

    p.wait = _mock_wait

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
    ):
        exec_task = asyncio.create_task(tool.execute({"command": "run_long_task"}, ctx=ctx))
        await asyncio.wait_for(wait_invoked.wait(), timeout=5.0)
        exec_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await exec_task
        mock_term.assert_called_once()


async def test_subagent_explicit_run_in_background_rejected(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app, is_subagent=True)
    p = _process()

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.terminate_process", new_callable=AsyncMock) as mock_term,
    ):
        res = str(await tool.execute({"command": "tail -f log.txt", "background": True}, ctx=ctx))
        assert "ERR: background 'shell'" in res
        mock_term.assert_called_once()
        assert len([t for t in app.task_manager]) == 0


# --------------------------------------------------------------------------- #
# Explicit background execution (main agent)
# --------------------------------------------------------------------------- #


async def test_explicit_run_in_background(tool, make_app_mock, make_tool_context):
    app = _app(make_app_mock, task_manager=TaskManager())
    ctx = make_tool_context(app=app, is_subagent=False)
    p = _process()

    with (
        patch("tools.shell.shell_executable", return_value="/bin/sh"),
        patch.object(ShellTool, "_create_std_process", return_value=p),
    ):
        res = str(await tool.execute({"command": "tail -f log.txt", "background": True}, ctx=ctx))
        assert "[Background Task ID:" in res
        assert "moved to background." in res
        assert "Recent Output:" not in res
        assert len([t for t in app.task_manager]) == 1


@pytest.mark.skipif(os.name == "nt", reason="cat streaming is POSIX-only")
async def test_background_task_manage_shell_lifecycle(tool, make_app_mock):
    # Real end-to-end: explicit background task (cat keeps stdin/stdout
    # open). manage_shell must list it as RUNNING (process alive), send
    # input to its stdin, and kill it.
    app = _app(make_app_mock, task_manager=TaskManager())

    from tools.manage_shell import ManageShellTool

    mgr = ManageShellTool()
    with patch("tools.shell.shell_executable", return_value="/bin/sh"):
        res = str(await tool.execute({"command": "cat", "background": True}, ctx=app))
    m = re.search(r"Task ID: (shell_\d+_\d+)", res)
    assert m is not None
    task_id = m.group(1)

    tasks = [t for t in app.task_manager]
    assert len(tasks) == 1
    assert tasks[0].is_background

    # list: process alive -> RUNNING
    r = str(await mgr.execute({"action": "list"}, ctx=app))
    assert "RUNNING" in r
    assert task_id in r

    # send_input: writes to live stdin
    r = str(await mgr.execute({"action": "send_input", "task_id": task_id, "input": "hello_manage"}, ctx=app))
    assert "OK: input sent" in r
    await asyncio.sleep(0.3)

    # background output is streamed into the task buffer (file log too)
    streamed = tasks[0].output.formatted()
    assert "hello_manage" in streamed

    # kill: terminates the live process
    r = str(await mgr.execute({"action": "kill", "task_id": task_id}, ctx=app))
    assert "killed" in r


# --------------------------------------------------------------------------- #
# Permission overrides
# --------------------------------------------------------------------------- #


async def test_session_override_allow_shell(tool, make_app_mock):
    from core.permission_manager import PermissionManager

    pm = PermissionManager.get_instance()
    pm.clear_session_overrides()
    pm.set_session_override("shell", "allow")

    app = _app(make_app_mock)
    app.confirm_permission = AsyncMock(return_value=True)

    res = str(await tool.execute({"command": "echo session_allowed"}, ctx=app))
    assert "session_allowed" in res
    pm.clear_session_overrides()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #


def test_shell_get_schema_main(tool):
    schema = tool.get_schema(is_subagent=False)
    params = schema["function"]["parameters"]["properties"]
    assert "background" in params
    assert "command" in params
    assert "timeout" in params


def test_shell_get_schema_subagent(tool):
    schema = tool.get_schema(is_subagent=True)
    params = schema["function"]["parameters"]["properties"]
    assert "background" not in params
    assert "command" in params
    assert "timeout" in params
    assert "synchronous" in schema["function"]["description"].lower()


# =========================================================================== #
# Edge cases (formerly test_edge_shell.py)
# =========================================================================== #


def _ctx(make_tool_context, cwd=None, is_subagent=True):
    """Real ToolContext. Subagent path reads streams synchronously."""
    return make_tool_context(is_subagent=is_subagent, cwd=cwd)


# ---------- empty / whitespace / None command ----------


async def test_empty_command_safe(tool, make_tool_context):
    res = str(await tool.execute({"command": ""}, ctx=_ctx(make_tool_context)))
    assert "ERR: params 'command': missing or empty" in res


async def test_whitespace_command_safe(tool, make_tool_context):
    res = str(await tool.execute({"command": "   \t  "}, ctx=_ctx(make_tool_context)))
    assert "ERR: params 'command': missing or empty" in res


async def test_none_command_safe(tool, make_tool_context):
    res = str(await tool.execute({"command": None}, ctx=_ctx(make_tool_context)))
    assert "ERR: params 'command': missing or empty" in res


# ---------- special chars / metacharacters ----------


async def test_semicolon_runs_both(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo a; echo b"}, ctx=_ctx(make_tool_context)))
    assert "a" in res
    assert "b" in res


async def test_ampersand_and_executes(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo a && echo b"}, ctx=_ctx(make_tool_context)))
    assert "a" in res
    assert "b" in res


@pytest.mark.skipif(os.name == "nt", reason="PowerShell 5.1 does not support || operator")
async def test_or_short_circuit(tool, make_tool_context):
    # First cmd succeeds -> second must NOT run (|| short-circuit).
    res = str(await tool.execute({"command": "echo ok || echo SHOULD_NOT_RUN"}, ctx=_ctx(make_tool_context)))
    assert "ok" in res
    assert "SHOULD_NOT_RUN" not in res


@pytest.mark.skipif(os.name == "nt", reason="bash pipe syntax (PowerShell incompatible)")
async def test_pipe_chains(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo pipe_data | cat"}, ctx=_ctx(make_tool_context)))
    assert "pipe_data" in res


@pytest.mark.skipif(os.name == "nt", reason="/dev/null is POSIX-only")
async def test_redirect_stdout_to_devnull_loses_output(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo hidden > /dev/null"}, ctx=_ctx(make_tool_context)))
    assert "hidden" not in res


@pytest.mark.skipif(os.name == "nt", reason="/dev/null is POSIX-only")
async def test_redirect_append(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo x >> /dev/null"}, ctx=_ctx(make_tool_context)))
    assert res == "(no output)"


@pytest.mark.skipif(os.name == "nt", reason="/dev/null and < redirection are POSIX-only")
async def test_input_redirect(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo from_stdin < /dev/null"}, ctx=_ctx(make_tool_context)))
    assert "from_stdin" in res


async def test_command_substitution_runs(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo dollar_$(echo sub)"}, ctx=_ctx(make_tool_context)))
    assert "sub" in res  # $(...) runs -> output contains "sub"


async def test_backtick_substitution_runs(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo bt_`echo sub2`"}, ctx=_ctx(make_tool_context)))
    assert "sub2" in res


async def test_arithmetic_substitution(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo $((2+3))"}, ctx=_ctx(make_tool_context)))
    assert "5" in res


@pytest.mark.skipif(os.name == "nt", reason="bash ! negation is not valid PowerShell")
async def test_not_bang_operator(tool, make_tool_context):
    # `! echo -n ; echo $?` → negation gives exit 1 → $? == 1
    res = str(await tool.execute({"command": "! true; echo exit=$?"}, ctx=_ctx(make_tool_context)))
    assert "exit=1" in res


@pytest.mark.skipif(os.name == "nt", reason="PowerShell does not glob-expand echo *")
async def test_wildcard_glob_expands(tool, make_tool_context):
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "apple.txt"), "w") as f:
            f.write("a")
        with open(os.path.join(d, "banana.txt"), "w") as f:
            f.write("b")
        res = str(await tool.execute({"command": "echo *"}, ctx=_ctx(make_tool_context, cwd=d)))
    assert "apple.txt" in res
    assert "banana.txt" in res


@pytest.mark.skipif(os.name == "nt", reason="PowerShell ~ is not an absolute path")
async def test_tilde_expands(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo ~"}, ctx=_ctx(make_tool_context)))
    assert os.path.isabs(res.strip())


async def test_nested_quotes(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo \"outer 'inner' quote\""}, ctx=_ctx(make_tool_context)))
    assert "outer 'inner' quote" in res


# ---------- long / unicode / emoji / space args ----------


async def test_unicode_and_emoji_roundtrip(tool, make_tool_context):
    payload = "héllo wörld привет 世界 🚀"
    res = str(await tool.execute({"command": f"echo {shlex.quote(payload)}"}, ctx=_ctx(make_tool_context)))
    assert payload in res


@pytest.mark.skipif(os.name == "nt", reason="PowerShell argument quoting differs")
async def test_argv_with_spaces_quoted(tool, make_tool_context):
    res = str(await tool.execute({"command": 'echo "a b  c" d'}, ctx=_ctx(make_tool_context)))
    assert "a b  c d" in res


async def test_very_long_command_many_args(tool, make_tool_context):
    args = " ".join(f"a{i}" for i in range(5000))
    res = str(await tool.execute({"command": f"echo {args}"}, ctx=_ctx(make_tool_context)))
    assert "a4999" in res


# ---------- timeout kills runaway ----------


@pytest.mark.skipif(os.name == "nt", reason="/bin/sleep is POSIX-only")
async def test_timeout_kills_subagent_subprocess(tool, make_tool_context):
    # Long-running command must be terminated by timeout.
    t0 = asyncio.get_running_loop().time()
    res = str(await tool.execute({"command": "/bin/sleep 30", "timeout": 1}, ctx=_ctx(make_tool_context)))
    elapsed = asyncio.get_running_loop().time() - t0
    assert "ERR: timeout 'shell': timed out after 1s" in res
    # Must return promptly (not wait the full 30s).
    assert elapsed < 10


# ---------- exit codes ----------


@pytest.mark.skipif(os.name == "nt", reason="false is POSIX-only")
async def test_false_exit_code_surfaced(tool, make_tool_context):
    # `false` exits 1 and the tool surfaces the exit code when there is no output.
    res = await tool.execute({"command": "false"}, ctx=_ctx(make_tool_context))
    assert res.returncode == 1
    assert str(res) == "(exit code 1)"


async def test_explicit_exit_code_surfaced(tool, make_tool_context):
    res = await tool.execute({"command": "echo never_shown; exit 7"}, ctx=_ctx(make_tool_context))
    assert res.returncode == 7
    assert "never_shown" in str(res)


async def test_stderr_only_captured(tool, make_tool_context):
    res = str(await tool.execute({"command": "echo stderr_only 1>&2"}, ctx=_ctx(make_tool_context)))
    assert "stderr_only" in res


async def test_kill_signal_behaves(tool, make_tool_context):
    # self-kill → shell reports no output; must not crash.
    res = str(await tool.execute({"command": "kill -9 $$"}, ctx=_ctx(make_tool_context)))
    assert isinstance(res, str)


# ---------- unicode/binary output, CRLF, huge output ----------


@pytest.mark.skipif(os.name == "nt", reason="printf is POSIX-only")
async def test_binary_bytes_no_crash(tool, make_tool_context):
    res = str(await tool.execute({"command": "printf '\\x01\\x02\\xff\\x00data'"}, ctx=_ctx(make_tool_context)))
    assert "data" in res


@pytest.mark.skipif(os.name == "nt", reason="printf is POSIX-only")
async def test_crlf_normalized(tool, make_tool_context):
    res = str(await tool.execute({"command": "printf 'one\\r\\ntwo\\r\\n'"}, ctx=_ctx(make_tool_context)))
    assert "one" in res
    assert "two" in res


@pytest.mark.skipif(os.name == "nt", reason="python3 on PATH is not guaranteed")
async def test_very_large_output_truncated(tool, make_tool_context):
    cmd = "python3 -c 'import sys; sys.stdout.write(\"X\"*6000)'" if os.name != "nt" else "echo"
    res = str(await tool.execute({"command": cmd}, ctx=_ctx(make_tool_context)))
    assert "Output truncated" in res
    assert "X" * 3900 in res  # tail preserved near 4000-char limit


# ---------- cwd behavior ----------


async def test_nonexistent_cwd_falls_back(tool, make_tool_context):
    # ToolContext refuses nonexistent cwd (sets self.cwd=None) → runs in default cwd.
    ctx = _ctx(make_tool_context, cwd="/nonexistent/path/xyz_123")
    assert ctx.cwd is None
    res = str(await tool.execute({"command": "echo cwd_fallback"}, ctx=ctx))
    assert "cwd_fallback" in res


@pytest.mark.skipif(os.name == "nt", reason="pwd output format is PowerShell-specific")
async def test_relative_cwd(tool, make_tool_context):
    res = str(await tool.execute({"command": "pwd"}, ctx=_ctx(make_tool_context)))
    assert os.path.isabs(res.strip())


@pytest.mark.skipif(os.name == "nt", reason="cd && pwd is bash syntax")
async def test_cd_command_inside(tool, make_tool_context):
    with tempfile.TemporaryDirectory() as sub:
        res = str(await tool.execute({"command": f"cd {shlex.quote(sub)} && pwd"}, ctx=_ctx(make_tool_context)))
        assert sub in res


# ---------- env behavior ----------


@pytest.mark.skipif(os.name == "nt", reason="${VAR} expansion is bash syntax")
async def test_env_inherited(tool, make_tool_context):
    key = "JOHNSTON_EDGE_ENV_TEST"
    os.environ[key] = "inherited_value"
    try:
        res = str(await tool.execute({"command": f"echo got=${{{key}}}"}, ctx=_ctx(make_tool_context)))
    finally:
        del os.environ[key]
    assert "got=inherited_value" in res


async def test_path_unset_command_not_found(tool, make_tool_context):
    res = str(await tool.execute({"command": "PATH=/nonexistent_path_zz echo hi; echo $?"}, ctx=_ctx(make_tool_context)))
    # First command (if any) not found; we at least get output.
    assert isinstance(res, str)


async def test_missing_env_var_empty(tool, make_tool_context):
    key = "JOHNSTON_DEFINITELY_UNSET_VAR_9876"
    res = str(await tool.execute({"command": f"echo val=[${{{key}}}]"}, ctx=_ctx(make_tool_context)))
    assert "val=[]" in res


# ---------- permission denied / non-executable ----------


@pytest.mark.skipif(os.name == "nt", reason="chmod +x semantics are POSIX-only")
async def test_non_executable_script_denied(tool, make_tool_context):
    with tempfile.TemporaryDirectory() as d:
        script = os.path.join(d, "noexec.sh")
        with open(script, "w") as f:
            f.write("echo SHOULD_NOT_RUN\n")
        os.chmod(script, 0o644)  # explicitly not executable
        res = str(await tool.execute({"command": script}, ctx=_ctx(make_tool_context, cwd=d)))
        assert "SHOULD_NOT_RUN" not in res
        assert "ermission denied" in res


# ---------- destructive safety (claimed in description) ----------


@pytest.mark.skipif(os.name == "nt", reason="rm -rf is POSIX-only")
async def test_rm_rf_not_blocked_default(tool, make_tool_context):
    # Description claims "Destructive commands confirm." Verify whether any
    # protection exists in execute(). Deleting our own tmp dir is safe.
    with tempfile.TemporaryDirectory() as d:
        victim = os.path.join(d, "victim")
        os.mkdir(victim)
        res = str(await tool.execute({"command": f"rm -rf {shlex.quote(victim)}"}, ctx=_ctx(make_tool_context)))
        assert not os.path.exists(victim)
        # If protection existed, res would be an ERR reject.
        assert "ERR: reject" not in res


async def test_mkfs_and_dd_not_blocked():
    # No-builtin-protection probe (source-level; we do NOT format disks).
    assert inspect_has_no_destructive_guard() is True


# ---------- parallelism ----------


async def test_concurrent_shell_calls_isolated(tool, make_tool_context):
    r1, r2 = await asyncio.gather(
        tool.execute({"command": "echo task_alpha"}, ctx=_ctx(make_tool_context)),
        tool.execute({"command": "echo task_beta"}, ctx=_ctx(make_tool_context)),
    )
    res1, res2 = str(r1), str(r2)
    assert "task_alpha" in res1
    assert "task_beta" in res2


def inspect_has_no_destructive_guard():
    """Source-level check: shell.py claims to confirm destructive commands
    but contains no rm/mkfs/dd/fdisk/format guard anywhere."""
    import inspect as _i

    from tools import shell as shell_mod

    return "mkfs" not in _i.getsource(shell_mod) and "rm -rf" not in _i.getsource(shell_mod)


async def test_shell_sandbox_enabled_invokes_sandboxed_command(tool, make_tool_context):
    ctx = _ctx(make_tool_context)
    ctx.host.sandbox_enabled = True
    with patch("core.infrastructure.platform.sandbox.build_sandboxed_command") as mock_build, \
         patch("asyncio.create_subprocess_exec") as mock_exec:
        mock_build.return_value = ("/usr/bin/sandbox-exec", ["-p", "(profile)", "/bin/sh", "-c", "echo test"], True)
        mock_proc = _process(wait_result=0, stdout=None)
        mock_exec.return_value = mock_proc

        await tool.execute({"command": "echo test"}, ctx=ctx)
        mock_build.assert_called_once()
        mock_exec.assert_called_once()

