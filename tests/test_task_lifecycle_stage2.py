"""Regression tests for Stage 2: Task lifecycle, states, isolation, and subagent transactional spawn."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.session.subagent_service import (
    SubagentService,
    is_active_subagent,
    resolve_subagent_display_status,
)
from core.domain.entities.session import AgentSession, SessionStatus
from core.infrastructure.tasks.manage import extract_task_status_details
from core.infrastructure.tasks.manager import TaskManager
from core.infrastructure.tasks.shell_task import ShellTask
from core.infrastructure.tasks.task import BaseTask, TaskStatus
from tools.context import ToolContext
from tools.shell import ShellTool


class ConcreteTask(BaseTask):
    def __repr__(self) -> str:
        return f"ConcreteTask({self.id})"

    async def read(self) -> str:
        return ""

    async def tail(self, max_chars: int = 4000) -> str:
        return ""


    async def kill(self) -> None:
        self.status = TaskStatus.KILLED

    async def wait(self) -> None:
        pass


def test_task_status_and_is_running_and_is_active():
    task = ConcreteTask("test-1", status=TaskStatus.QUEUED)
    # 1. status property returns _status, does NOT masquerade QUEUED as RUNNING
    assert task.status == TaskStatus.QUEUED
    assert not task.is_running
    assert task.is_active

    task.status = TaskStatus.RUNNING
    assert task.status == TaskStatus.RUNNING
    assert task.is_running
    assert task.is_active

    task.status = TaskStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    assert not task.is_running
    assert not task.is_active


@pytest.mark.asyncio
async def test_shell_task_initial_queued_and_start_reading_running():
    mock_proc = MagicMock()
    mock_proc.returncode = None
    mock_proc.stdout = None

    task = ShellTask("sh-1", "echo hi", process=mock_proc)
    # Initial status must be QUEUED
    assert task.status == TaskStatus.QUEUED
    assert not task.is_running
    assert task.is_active

    # start_reading transitions to RUNNING if process is alive
    task.start_reading()
    assert task.status == TaskStatus.RUNNING
    assert task.is_running
    assert task.is_active


@pytest.mark.asyncio
async def test_shell_task_start_reading_without_live_process():
    task = ShellTask("sh-2", "echo hi", process=None)
    assert task.status == TaskStatus.QUEUED
    task.start_reading()
    # Process is None, so remains QUEUED until terminated
    assert task.status == TaskStatus.QUEUED


@pytest.mark.asyncio
async def test_foreground_sync_isolated_from_task_manager():
    tool = ShellTool()
    task_mgr = TaskManager()
    host_mock = MagicMock()
    host_mock.current_session_id = "sess-1"
    host_mock.current_tool_widget = None
    host_mock.task_manager = task_mgr
    ctx = ToolContext(app=host_mock)

    p = MagicMock()
    p.returncode = 0
    p.stdout = None
    wait_fut = asyncio.Future()
    wait_fut.set_result(0)
    p.wait = MagicMock(return_value=wait_fut)

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch("tools.shell.shell_executable", return_value="/bin/sh"),
    ):
        res = await tool.execute({"command": "echo sync"}, ctx=ctx)
        assert not res.is_error
        # Task manager must never have registered the foreground task!
        assert len([t for t in task_mgr]) == 0


@pytest.mark.asyncio
async def test_foreground_sync_moves_to_background_registers_in_task_manager():
    tool = ShellTool()
    task_mgr = TaskManager()
    host_mock = MagicMock()
    host_mock.current_session_id = "sess-1"
    host_mock.current_tool_widget = None
    host_mock.task_manager = task_mgr
    ctx = ToolContext(app=host_mock)

    p = MagicMock()
    p.returncode = None
    p.stdout = None
    p.wait = MagicMock(return_value=asyncio.Future())

    task_started = asyncio.Event()
    orig_start = ShellTask.start_reading

    def _start(self, *args, **kwargs):
        res = orig_start(self, *args, **kwargs)
        task_started.set()
        return res

    with (
        patch.object(ShellTool, "_create_std_process", return_value=p),
        patch.object(ShellTask, "start_reading", _start),
        patch("tools.shell.shell_executable", return_value="/bin/sh"),
        patch("tools.shell.terminate_process", new_callable=AsyncMock),
    ):
        exec_task = asyncio.create_task(tool.execute({"command": "tail -f x"}, ctx=ctx))
        await task_started.wait()

        # Before backgrounding: isolated from task_mgr
        assert len([t for t in task_mgr]) == 0
        fg_tasks = list(getattr(host_mock, "_foreground_shell_tasks", {}).values())
        assert len(fg_tasks) == 1
        fg_tasks[0].move_to_background()

        res = await exec_task
        assert "task backgrounded" in res.content
        # After backgrounding: registered in task_mgr!
        assert len([t for t in task_mgr]) == 1


@pytest.mark.asyncio
async def test_subagent_transactional_spawn_failure_leaves_no_zombie_session():
    mock_store = MagicMock()
    mock_store.children.return_value = []
    mock_store.list.return_value = []
    mock_store.generate_subagent_id.return_value = "sub-fail"

    mock_wt_mgr = MagicMock()
    mock_wt_mgr.is_git_repo.return_value = True
    # Worktree creation fails (returns None, None)
    mock_wt_mgr.create_worktree_async = AsyncMock(return_value=(None, None))

    host_mock = MagicMock()
    host_mock.current_session_id = "parent-1"
    ctx = MagicMock()
    ctx.host = host_mock
    ctx.session_id = "parent-1"
    ctx.project_dir = "/tmp/fake-repo"
    mock_agent = MagicMock()
    ctx.create_agent.return_value = mock_agent

    with patch("core.application.session.subagent_service.get_session_store", return_value=mock_store):
        with patch("core.application.session.subagent_service.record_subagent_session") as mock_record:
            res = await SubagentService.spawn_subagent(
                prompt="test prompt",
                title="test task",
                subagent_type="worker",
                ctx=ctx,
                worktree_manager_cls=mock_wt_mgr,
            )
            # Must return error
            assert res.is_error
            assert "Failed to create git worktree" in res.content
            # No session was created in store!
            mock_store.create_subagent.assert_not_called()
            # record_subagent_session was NOT called!
            mock_record.assert_not_called()


def test_canonical_status_extract_and_subagent_display():
    # extract_task_status_details tests
    t_queued = ConcreteTask("tq", status=TaskStatus.QUEUED)
    st, _ = extract_task_status_details(t_queued)
    assert st == "queued"

    t_running = ConcreteTask("tr", status=TaskStatus.RUNNING)
    st, _ = extract_task_status_details(t_running)
    assert st == "running"

    t_completed = ConcreteTask("tc", status=TaskStatus.COMPLETED)
    st, _ = extract_task_status_details(t_completed)
    assert st == "exit:0"

    t_error = ConcreteTask("te", status=TaskStatus.ERROR)
    st, _ = extract_task_status_details(t_error)
    assert st == "exit:1"

    t_killed = ConcreteTask("tk", status=TaskStatus.KILLED)
    st, _ = extract_task_status_details(t_killed)
    assert st == "killed"

    t_timeout = ConcreteTask("tt", status=TaskStatus.TIMEOUT)
    st, _ = extract_task_status_details(t_timeout)
    assert st == "timeout"

    # subagent display status tests
    s_comp = AgentSession(session_id="s1", status=SessionStatus.COMPLETED)
    assert resolve_subagent_display_status(s_comp) == "completed"
    assert not is_active_subagent(s_comp)

    s_canc = AgentSession(session_id="s2", status=SessionStatus.CANCELLED)
    assert resolve_subagent_display_status(s_canc) == "cancelled"
    assert not is_active_subagent(s_canc)

    s_err = AgentSession(session_id="s3", status=SessionStatus.ERROR)
    assert resolve_subagent_display_status(s_err) == "error"
    assert not is_active_subagent(s_err)

    s_run = AgentSession(session_id="s4", status=SessionStatus.RUNNING)
    assert resolve_subagent_display_status(s_run) == "running"
    assert is_active_subagent(s_run)
