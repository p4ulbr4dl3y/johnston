"""Tests for tools/manage_shell.py.

Consolidated from the former test_manage_shell.py, test_manage_shell_input.py and
the manage_shell edge cases of test_edge_manage_shell_sub.py into a single
per-module file. Managing subagent sessions lives in test_manage_subagent.py.
"""
from unittest.mock import MagicMock

import pytest

from core.infrastructure.tasks.manager import TaskManager
from core.infrastructure.tasks.shell_task import ShellTask
from core.infrastructure.tasks.task import TaskStatus
from tools.manage_shell import ManageShellTool


@pytest.fixture
def tool():
    return ManageShellTool()


def _make_task(
    task_id,
    command="cmd",
    proc=None,
    status=None,
    output=None,
    session_id="sess-A",
    background=True,
    alive=True,
):
    t = ShellTask(task_id, command, proc)
    t.session_id = session_id
    t.is_background = background
    if proc is not None and alive:
        proc.returncode = None  # simulate a live process (returncode None while running)
    if status is not None:
        t.status = status
    if output:
        for line in output:
            t.output.append(line)
    return t


def _app(make_app_mock, tasks=None, session_id=None):
    app = make_app_mock()
    # None/empty session -> no scoping, all tasks considered (matches the UI).
    app.current_session_id = session_id
    app.is_subagent = False
    mgr = TaskManager()
    for t in tasks or []:
        mgr.register(t)
    app.task_manager = mgr
    return app


# --------------------------------------------------------------------------- #
# list
# --------------------------------------------------------------------------- #


async def test_list_no_tasks(tool, make_app_mock):
    app = _app(make_app_mock, tasks=[])
    res = await tool.execute({"action": "list"}, ctx=app)
    assert res.content == "[tasks 0]"
    assert res.display == ""


async def test_list_scoped_to_current_session(tool, make_app_mock):
    t1 = _make_task("t1", "echo hi", session_id="sess-A")
    t2 = _make_task("t2", "ls -la", session_id="sess-B")
    app = _app(make_app_mock, [t1, t2], session_id="sess-A")
    res = str(await tool.execute({"action": "list"}, ctx=app))
    assert "t1" in res
    assert "echo hi" in res
    assert "t2" not in res
    assert "ls -la" not in res


async def test_list_with_tasks(tool, make_app_mock):
    t1 = _make_task("t1", "echo hello", proc=MagicMock())
    t2 = _make_task("t2", "ls -la", status=TaskStatus.COMPLETED)
    t2.completed_at = t2.created_at + 2.5
    app = _app(make_app_mock, [t1, t2])
    res = await tool.execute({"action": "list"}, ctx=app)
    assert "[tasks 2 | id|status|duration|cmd|log]" in res.content
    assert "t1|running|" in res.content
    assert "|echo hello|" in res.content
    assert "t2|exit:0|2.5s|ls -la|" in res.content


async def test_list_many_tasks_preserves_input_order(tool, make_app_mock):
    # Mix of running/finished tasks, order preserved as registered.
    tasks = [
        _make_task(
            f"t{i}",
            status=None if i % 2 == 0 else TaskStatus.COMPLETED,
            proc=MagicMock() if i % 2 == 0 else None,
            session_id="s1",
        )
        for i in range(50)
    ]
    app = _app(make_app_mock, tasks, session_id="s1")
    res = str(await tool.execute({"action": "list"}, ctx=app))
    # order preserved as registered
    first_occ = [res.index(fid) for fid in ("t0", "t1", "t2")]
    assert first_occ == sorted(first_occ)


async def test_background_task_already_finished_is_excluded_from_list(tool, make_app_mock):
    """Race: a task that finished between registration and manage must not crash list."""
    t1 = _make_task("tbkg", "sleep 1", session_id="s1")
    t2 = _make_task("tbkg2", "sleep 1", proc=MagicMock(), session_id="s1")
    app = _app(make_app_mock, [t1, t2], session_id="s1")
    # Race: t1 finishes right before manage runs.
    t1.status = TaskStatus.COMPLETED
    res = await tool.execute({"action": "list"}, ctx=app)
    assert "tbkg|exit:0|" in res.content
    assert "|sleep 1|" in res.content


async def test_list_task_status_variants(tool, make_app_mock):
    t_killed = _make_task("tk", "sleep 10", status=TaskStatus.KILLED)
    t_err = _make_task("terr", "bad cmd", status=TaskStatus.ERROR)
    t_err.exit_code = 127
    t_err.completed_at = t_err.created_at + 0.05
    app = _app(make_app_mock, [t_killed, t_err])
    res = await tool.execute({"action": "list"}, ctx=app)
    assert "tk|killed|" in res.content
    assert "terr|exit:127|<0.1s|bad cmd|" in res.content


async def test_no_task_manager_no_app(tool):
    res = str(await tool.execute({"action": "list"}))
    assert "ERR: manager 'none'" in res


# --------------------------------------------------------------------------- #
# kill
# --------------------------------------------------------------------------- #


async def test_kill_missing_task_id(tool, make_app_mock):
    app = _app(make_app_mock, [])
    res = str(await tool.execute({"action": "kill"}, ctx=app))
    assert "ERR" in res
    assert "task_id" in res


async def test_kill_task_not_found(tool, make_app_mock):
    app = _app(make_app_mock, [])
    res = str(await tool.execute({"action": "kill", "task_id": "ghost"}, ctx=app))
    assert "ERR: notfound 'ghost'" in res


async def test_kill_running_task(tool, make_app_mock):
    t = _make_task("t-kill", "sleep 100", proc=MagicMock())

    async def _fake_kill():
        t.status = TaskStatus.KILLED
        # A real kill sets the backing process returncode; the task must
        # then report not running even though status was replaced.
        if t.process is not None:
            t.process.returncode = 1

    t.kill = _fake_kill
    app = _app(make_app_mock, [t])
    res = await tool.execute({"action": "kill", "task_id": "t-kill"}, ctx=app)
    assert "t-kill" in res.content
    assert "killed" in res.content
    assert not t.is_running


async def test_kill_not_running_task(tool, make_app_mock):
    t = _make_task("t-done", "echo hi", status=TaskStatus.COMPLETED)
    app = _app(make_app_mock, [t])
    res = str(await tool.execute({"action": "kill", "task_id": "t-done"}, ctx=app))
    assert "ERR: notrunning" in res


async def test_double_kill_running_task_is_idempotent(tool, make_app_mock):
    """Second kill on a task already killed must not crash; returns notrunning."""
    t = _make_task("tk2", "sleep 5", proc=MagicMock(), session_id="s1")
    called = {"n": 0}

    async def fake_kill():
        called["n"] += 1
        t.status = TaskStatus.KILLED

    t.kill = fake_kill
    app = _app(make_app_mock, [t], session_id="s1")
    r1 = str(await tool.execute({"action": "kill", "task_id": "tk2"}, ctx=app))
    assert "killed" in r1
    # Simulate engine marking it dead.
    t.status = TaskStatus.COMPLETED
    t.process.returncode = 0  # process also gone -> not running
    r2 = str(await tool.execute({"action": "kill", "task_id": "tk2"}, ctx=app))
    assert "notrunning" in r2
    assert called["n"] == 1


async def test_kill_task_whose_process_already_exited_no_crash(tool, make_app_mock):
    """Kill a running task whose underlying proc.returncode is set (already exited)."""
    proc = MagicMock()
    proc.returncode = 0

    async def fake_kill():
        t.status = TaskStatus.KILLED

    t = _make_task("tk3", "ls", proc=proc, session_id="s1", alive=False)
    t.kill = fake_kill
    app = _app(make_app_mock, [t], session_id="s1")
    res = str(await tool.execute({"action": "kill", "task_id": "tk3"}, ctx=app))
    assert "killed" in res
    assert not t.is_running


async def test_kill_exception_is_soft_error(tool, make_app_mock):
    t = _make_task("tk4", "sleep 5", proc=MagicMock(), session_id="s1")

    async def boom():
        raise RuntimeError("kill denied")

    t.kill = boom
    app = _app(make_app_mock, [t], session_id="s1")
    res = str(await tool.execute({"action": "kill", "task_id": "tk4"}, ctx=app))
    assert "ERR" in res
    assert "kill denied" in res
    # tool leaves is_running alone on failure
    assert t.is_running


# --------------------------------------------------------------------------- #
# send_input
# --------------------------------------------------------------------------- #


async def test_manage_shell_send_input(tool, make_app_mock):
    async def dummy_drain():
        pass

    mock_stdin = MagicMock()
    mock_stdin.drain = dummy_drain
    mock_proc = MagicMock()
    mock_proc.stdin = mock_stdin

    t = _make_task("task_interactive", "read name", proc=mock_proc, session_id="s1")
    app = _app(make_app_mock, [t], session_id="s1")

    res = await tool.execute(
        {"action": "send_input", "task_id": "task_interactive", "input": "John Doe"}, ctx=app
    )
    assert "sent" in res.content
    mock_stdin.write.assert_called_once_with(b"John Doe\n")


async def test_manage_shell_send_input_not_running(tool, make_app_mock):
    t = _make_task("task_finished", "echo hello", status=TaskStatus.COMPLETED)
    app = _app(make_app_mock, [t])
    res = str(await tool.execute({"action": "send_input", "task_id": "task_finished", "input": "test"}, ctx=app))
    assert "ERR: notrunning 'task_finished'" in res


async def test_send_input_empty_input_still_writes_newline(tool, make_app_mock):
    mock_stdin = MagicMock()

    async def drain():
        pass

    mock_stdin.drain = drain
    proc = MagicMock()
    proc.stdin = mock_stdin
    t = _make_task("tsempty", "read name", proc=proc, session_id="s1")
    app = _app(make_app_mock, [t], session_id="s1")
    res = await tool.execute({"action": "send_input", "task_id": "tsempty", "input": ""}, ctx=app)
    assert "sent" in res.content
    mock_stdin.write.assert_called_once_with(b"\n")


async def test_send_input_task_without_stdin(tool, make_app_mock):
    """Tasks without writable stdin route through their own send_input."""
    t = _make_task("tsnoproc", "weird", session_id="s1")

    async def _send(text):
        assert text == "x"
        return "HANDLED"

    t.send_input = _send
    app = _app(make_app_mock, [t], session_id="s1")
    res = await tool.execute({"action": "send_input", "task_id": "tsnoproc", "input": "x"}, ctx=app)
    assert res.content == "HANDLED"


# --------------------------------------------------------------------------- #
# invalid / None task_id handling
# --------------------------------------------------------------------------- #


async def test_unknown_action(tool, make_app_mock):
    app = _app(make_app_mock, [])
    res = str(await tool.execute({"action": "bogus"}, ctx=app))
    assert "ERR: action 'bogus'" in res
    assert "bogus" in res


async def test_unknown_action_none_task_id_should_not_crash(tool, make_app_mock):
    """Bug B1: task_id=None -> AttributeError on .strip() (tools/manage_shell.py:28)."""
    app = _app(make_app_mock, [])
    try:
        res = str(await tool.execute({"action": "bogus", "task_id": None}, ctx=app))
    except AttributeError as exc:
        import inspect

        src = inspect.getsource(ManageShellTool.execute).splitlines()
        line = "manage_shell.py:28"
        for i, ln in enumerate(src):
            if ".strip()" in ln:
                line = f"manage_shell.py:{28 + i}"
                break
        pytest.fail(f"BUG B1: manage_shell crashed on task_id=None -> AttributeError ({line}): {exc}")
        return
    assert isinstance(res, str)


async def test_send_input_none_task_id_should_not_crash(tool, make_app_mock):
    app = _app(make_app_mock, [])
    try:
        res = str(await tool.execute({"action": "send_input", "task_id": None, "input": "x"}, ctx=app))
    except AttributeError as exc:
        pytest.fail(f"BUG: send_input task_id=None crashed: {exc}")
    assert isinstance(res, str)


async def test_kill_none_task_id_should_not_crash(tool, make_app_mock):
    app = _app(make_app_mock, [])
    try:
        res = str(await tool.execute({"action": "kill", "task_id": None}, ctx=app))
    except AttributeError as exc:
        pytest.fail(f"BUG: kill task_id=None crashed: {exc}")
    assert isinstance(res, str)


async def test_status_action_removed(tool, make_app_mock):
    # 'status' was dropped from manage_shell: full/tail output now lives in
    # the file log, so a dedicated status branch is redundant with 'list'.
    assert "status" not in ManageShellTool.schema["function"]["parameters"]["properties"]["action"]["enum"]
    t = _make_task("t-run", "npm build", output=["Building...\n", "Done\n"])
    app = _app(make_app_mock, [t])
    for kwargs in ({"action": "status", "task_id": "t-run"}, {"action": "status"}):
        res = str(await tool.execute(kwargs, ctx=app))
        assert "ERR: action 'status'" in res


async def test_manage_shell_missing_task_id_self_healing(tool, make_app_mock):
    t1 = _make_task("t1", "echo hello", proc=MagicMock())
    app = _app(make_app_mock, [t1])

    res_kill = str(await tool.execute({"action": "kill"}, ctx=app))
    assert "required for 'kill'" in res_kill
    assert "manage_shell(action='list')" in res_kill

    res_send = str(await tool.execute({"action": "send_input", "input": "yes"}, ctx=app))
    assert "required for 'send_input'" in res_send
    assert "manage_shell(action='list')" in res_send

