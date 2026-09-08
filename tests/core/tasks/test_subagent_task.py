import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from johnston_core.domain.entities.session import AgentSession, SessionKind, SessionStatus
from johnston_core.infrastructure.tasks.manager import TaskManager
from johnston_core.infrastructure.tasks.shell_task import ShellTask
from johnston_core.infrastructure.tasks.subagent_task import SubagentTask
from johnston_core.infrastructure.tasks.task import TASK_KINDS, TaskStatus


def _create_mock_session(
    session_id: str = "sub_123",
    status: str = SessionStatus.RUNNING,
    title: str = "Test Task",
    prompt: str = "Test Prompt",
    parent_id: str = "parent_456",
    role: str = "worker",
) -> AgentSession:
    sess = AgentSession(
        session_id=session_id,
        kind=SessionKind.SUBAGENT,
        parent_id=parent_id,
        title=title,
        prompt=prompt,
        status=status,
        role=role,
    )
    sess.async_task = None
    sess.pending_messages = []
    return sess


def test_task_kinds_contains_subagent():
    assert "subagent" in TASK_KINDS
    assert "shell" in TASK_KINDS


def test_subagent_task_init():
    session = _create_mock_session(role="researcher", title="Research codebase")
    task = SubagentTask(session)

    assert task.id == "sub_123"
    assert task.task_id == "sub_123"
    assert task.kind == "subagent"
    assert task.command == "[researcher] Research codebase"
    assert task.session == session
    assert task.session_id == "parent_456"
    assert task.is_running is True
    assert task.status == TaskStatus.RUNNING
    assert repr(task) == "SubagentTask(id='sub_123', status=running)"


def test_subagent_task_status_mapping():
    session = _create_mock_session()
    task = SubagentTask(session)

    # 1. Cancelled -> KILLED
    session.status = SessionStatus.CANCELLED
    assert task.status == TaskStatus.KILLED
    session.status = "canceled"
    assert task.status == TaskStatus.KILLED
    session.status = "killed"
    assert task.status == TaskStatus.KILLED

    # 2. Error -> ERROR
    session.status = SessionStatus.ERROR
    assert task.status == TaskStatus.ERROR
    session.status = "failed"
    assert task.status == TaskStatus.ERROR

    # 3. Completed -> COMPLETED
    session.status = SessionStatus.COMPLETED
    assert task.status == TaskStatus.COMPLETED
    session.status = "done"
    assert task.status == TaskStatus.COMPLETED

    # 4. async_task not done -> RUNNING
    session.status = "idle"
    mock_async_task = MagicMock()
    mock_async_task.done.return_value = False
    task.async_task = mock_async_task
    assert task.status == TaskStatus.RUNNING

    # async_task done, session active -> RUNNING
    mock_async_task.done.return_value = True
    session.status = SessionStatus.ACTIVE
    assert task.status == TaskStatus.RUNNING
    session.status = SessionStatus.RUNNING
    assert task.status == TaskStatus.RUNNING
    session.status = "running"
    assert task.status == TaskStatus.RUNNING
    session.status = "active"
    assert task.status == TaskStatus.RUNNING

    # 5. Fallback -> COMPLETED
    session.status = "other_unknown"
    assert task.status == TaskStatus.COMPLETED

    # status setter
    task.status = TaskStatus.COMPLETED
    assert task._status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_subagent_task_kill():
    session = _create_mock_session()
    store = MagicMock()
    task = SubagentTask(session, store=store)

    with patch("johnston_core.application.session.subagent_service.SubagentService.kill_subagent") as mock_kill:
        await task.kill()
        mock_kill.assert_called_once_with(session, store)

    assert task.was_killed is True
    assert task.status == TaskStatus.KILLED
    assert task.completed_at is not None


def test_subagent_task_kill_sync():
    session = _create_mock_session()
    store = MagicMock()
    task = SubagentTask(session, store=store)

    with patch("johnston_core.application.session.subagent_service.SubagentService.kill_subagent") as mock_kill:
        task.kill_sync()
        mock_kill.assert_called_once_with(session, store)

    assert task.was_killed is True
    assert task.status == TaskStatus.KILLED


@pytest.mark.asyncio
async def test_subagent_task_wait():
    session = _create_mock_session()
    done_event = asyncio.Event()

    async def _dummy_task():
        await done_event.wait()
        session.status = SessionStatus.COMPLETED

    bg_task = asyncio.create_task(_dummy_task())
    task = SubagentTask(session, async_task=bg_task)

    wait_coro = asyncio.create_task(task.wait())
    await asyncio.sleep(0.01)
    assert not wait_coro.done()

    done_event.set()
    await wait_coro
    assert task.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_subagent_task_read_and_tail():
    session = _create_mock_session()
    session.messages = [
        {"type": "user", "text": "inspect logs"},
        {"type": "bot", "text": "checking files"},
        {"type": "tool", "result_text": "log output"},
    ]

    task = SubagentTask(session)
    content = await task.read()
    assert "inspect logs" in content
    assert "checking files" in content
    assert "log output" in content

    tail_content = await task.tail(max_chars=10)
    assert len(tail_content) <= 10
    assert tail_content == content[-10:]


@pytest.mark.asyncio
async def test_subagent_task_read_fallback_to_assistant_history():
    session = _create_mock_session()
    session.messages = []
    session.agent_history = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "latest assistant response"},
    ]

    task = SubagentTask(session)
    content = await task.read()
    assert content == "latest assistant response"


@pytest.mark.asyncio
async def test_task_manager_subagent_support():
    mgr = TaskManager()

    shell_task = ShellTask("sh_1", "sleep 10")
    shell_task.kill = AsyncMock()

    sub_session = _create_mock_session("sub_1")
    sub_task = SubagentTask(sub_session)
    sub_task.kill = AsyncMock()

    mgr.register(shell_task)
    mgr.register(sub_task)

    assert mgr.get("sh_1") == shell_task
    assert mgr.get("sub_1") == sub_task
    assert len(mgr.list()) == 2
    assert mgr.list("shell") == [shell_task]
    assert mgr.list("subagent") == [sub_task]

    # Iteration
    tasks = list(mgr)
    assert shell_task in tasks
    assert sub_task in tasks

    # Kill all
    await mgr.kill_all()
    shell_task.kill.assert_awaited_once()
    sub_task.kill.assert_awaited_once()

    # Drop
    mgr.drop("sh_1")
    assert mgr.get("sh_1") is None
    assert len(mgr.list()) == 1


@pytest.mark.asyncio
async def test_task_manager_pruning_subagent():
    mgr = TaskManager(max_completed=1)

    sess1 = _create_mock_session("sub_1", status=SessionStatus.COMPLETED)
    task1 = SubagentTask(sess1)
    task1.completed_at = 100.0

    sess2 = _create_mock_session("sub_2", status=SessionStatus.COMPLETED)
    task2 = SubagentTask(sess2)
    task2.completed_at = 200.0

    mgr.register(task1)
    mgr.register(task2)

    # limit is 1 completed, so the oldest (task1) should be pruned
    assert mgr.get("sub_1") is None
    assert mgr.get("sub_2") == task2
