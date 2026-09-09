from unittest.mock import AsyncMock, MagicMock

import pytest

from johnston.core.domain.defaults.errors import ToolResultStatus
from johnston.core.tools.context import ToolContext
from johnston.core.tools.kill import KillTool


@pytest.fixture
def kill_tool():
    return KillTool()


@pytest.mark.asyncio
async def test_kill_missing_id(kill_tool):
    app = MagicMock()
    app.task_manager = []
    app.current_session_id = "sess-1"
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "required" in res.content.lower()


@pytest.mark.asyncio
async def test_kill_shell_task_success(kill_tool):
    task = MagicMock()
    task.id = "shell-123"
    task.task_id = "shell-123"
    task.session_id = "sess-1"
    task.kind = "shell"
    task.is_active = True
    task.is_running = True
    task.kill = AsyncMock()
    task.get_formatted_output = MagicMock(return_value="output before kill")

    widget = MagicMock()

    app = MagicMock()
    app.task_manager = [task]
    app.current_session_id = "sess-1"
    app._background_shell_widgets = {"shell-123": widget}
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": "shell-123"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    assert "[killed shell-123]" in res.content
    task.kill.assert_awaited_once()
    assert task.suppress_notification is True
    assert "shell-123" not in app._background_shell_widgets
    widget.set_result.assert_called_once_with("output before kill", status="done")


@pytest.mark.asyncio
async def test_kill_shell_task_not_running(kill_tool):
    task = MagicMock()
    task.id = "shell-123"
    task.task_id = "shell-123"
    task.session_id = "sess-1"
    task.kind = "shell"
    task.is_active = False
    task.is_running = False

    app = MagicMock()
    app.task_manager = [task]
    app.current_session_id = "sess-1"
    app._background_shell_widgets = {}
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": "shell-123"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "not running" in res.content.lower() or "notrunning" in str(res).lower()


@pytest.mark.asyncio
async def test_kill_subagent_success(kill_tool, monkeypatch):
    subagent_session = MagicMock()
    subagent_session.id = "sub-456"

    store = MagicMock()
    store.find_session_by_title_or_id.return_value = subagent_session

    monkeypatch.setattr("johnston.core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    kill_mock = MagicMock(return_value=MagicMock(status=ToolResultStatus.DONE, content="[killed sub-456]"))
    monkeypatch.setattr("johnston.core.application.session.subagent_service.SubagentService.kill_subagent", kill_mock)

    app = MagicMock()
    app.task_manager = []
    app.current_session_id = "sess-1"
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": "sub-456"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    assert "[killed sub-456]" in res.content
    kill_mock.assert_called_once_with(subagent_session, store)


@pytest.mark.asyncio
async def test_kill_target_not_found(kill_tool, monkeypatch):
    store = MagicMock()
    store.find_session_by_title_or_id.return_value = None

    monkeypatch.setattr("johnston.core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    app = MagicMock()
    app.task_manager = []
    app.current_session_id = "sess-1"
    app._background_shell_widgets = {}
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": "nonexistent"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "not found" in res.content.lower() or "notfound" in str(res).lower()


@pytest.mark.asyncio
async def test_kill_rejects_legacy_task_id_alias(kill_tool):
    ctx = ToolContext(app=MagicMock())
    res = await kill_tool.execute({"task_id": "shell-999"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "ERR: params 'id': required" in res.content


@pytest.mark.asyncio
async def test_kill_foreground_shell_task(kill_tool):
    fg_task = MagicMock()
    fg_task.task_id = "shell-fg1"
    fg_task.is_active = True
    fg_task.kill = AsyncMock()
    fg_task.get_formatted_output = MagicMock(return_value="fg output")

    app = MagicMock()
    app.task_manager = []
    app.current_session_id = "sess-1"
    app._foreground_shell_tasks = {"shell-fg1": fg_task}
    app._background_shell_widgets = {}
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": "shell-fg1"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    assert "[killed shell-fg1]" in res.content
    fg_task.kill.assert_awaited_once()


@pytest.mark.asyncio
async def test_kill_process_fallback(kill_tool, monkeypatch):
    proc = MagicMock()
    proc.returncode = None
    task = MagicMock(spec=["task_id", "is_active", "process", "session_id"])
    task.task_id = "shell-p1"
    task.session_id = "sess-1"
    task.is_active = True
    task.process = proc

    term_mock = AsyncMock()
    monkeypatch.setattr("johnston.core.infrastructure.platform.process.terminate_process_tree", term_mock)

    app = MagicMock()
    app.task_manager = [task]
    app.current_session_id = "sess-1"
    app._background_shell_widgets = {}
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": "shell-p1"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    term_mock.assert_awaited_once_with(proc)


def test_kill_is_concurrency_safe():
    tool = KillTool()
    assert not tool.is_concurrency_safe()


@pytest.mark.asyncio
async def test_kill_blocked_for_subagents(kill_tool):
    ctx = MagicMock()
    ctx.is_subagent = True
    kill_tool._ensure_context = lambda app=None: ctx

    res = await kill_tool.execute({"id": "shell-1"})
    assert res.is_error
    assert "subagents cannot terminate tasks or subagents" in res.content


@pytest.mark.asyncio
async def test_kill_coerces_non_string_id(kill_tool):
    task = MagicMock()
    task.id = "123"
    task.task_id = "123"
    task.session_id = "sess-1"
    task.is_active = True
    task.is_running = True
    task.kill = AsyncMock()

    app = MagicMock()
    app.task_manager = [task]
    app.current_session_id = "sess-1"
    app._background_shell_widgets = {}
    ctx = ToolContext(app=app)

    res = await kill_tool.execute({"id": 123}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    assert "[killed 123]" in res.content


