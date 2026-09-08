from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from core.domain.defaults.errors import ToolResult, ToolResultStatus
from tools.context import ToolContext
from tools.message_subagent import MessageSubagentTool


@pytest.fixture
def msg_tool():
    return MessageSubagentTool()


@pytest.mark.asyncio
async def test_message_subagent_missing_id(msg_tool):
    ctx = ToolContext(app=MagicMock())
    res = await msg_tool.execute({"message": "hello"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "required" in res.content.lower()


@pytest.mark.asyncio
async def test_message_subagent_missing_message(msg_tool):
    ctx = ToolContext(app=MagicMock())
    res = await msg_tool.execute({"id": "sub-123"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "required" in res.content.lower()


@pytest.mark.asyncio
async def test_message_subagent_not_found(msg_tool, monkeypatch):
    store = MagicMock()
    store.find_session_by_title_or_id.return_value = None
    monkeypatch.setattr("core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    ctx = ToolContext(app=MagicMock())

    res = await msg_tool.execute({"id": "ghost", "message": "hello"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "not found" in res.content.lower() or "notfound" in str(res).lower()


@pytest.mark.asyncio
async def test_message_subagent_success(msg_tool, monkeypatch):
    session = MagicMock()
    session.id = "sub-123"

    store = MagicMock()
    store.find_session_by_title_or_id.return_value = session
    monkeypatch.setattr("core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    send_mock = AsyncMock(return_value=ToolResult.done(content="[resumed sub-123]"))
    monkeypatch.setattr("core.application.session.subagent_service.SubagentService.send_message", send_mock)

    ctx = ToolContext(app=MagicMock())

    res = await msg_tool.execute({"id": "sub-123", "message": "continue work"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    assert "[resumed sub-123]" in res.content
    send_mock.assert_awaited_once_with(session, "continue work", ANY, store)


@pytest.mark.asyncio
async def test_message_subagent_accepts_session_id_alias(msg_tool, monkeypatch):
    session = MagicMock()
    session.id = "sub-777"

    store = MagicMock()
    store.find_session_by_title_or_id.return_value = session
    monkeypatch.setattr("core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    send_mock = AsyncMock(return_value=ToolResult.done(content="[resumed sub-777]"))
    monkeypatch.setattr("core.application.session.subagent_service.SubagentService.send_message", send_mock)

    ctx = ToolContext(app=MagicMock())

    res = await msg_tool.execute({"session_id": "sub-777", "message": "alias test"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    send_mock.assert_awaited_once_with(session, "alias test", ANY, store)


@pytest.mark.asyncio
async def test_send_subagent_followup_cancelled_session_rejected():
    from core.application.session.stream_followup import send_subagent_followup
    from core.domain.entities.session import AgentSession, SessionStatus

    session = AgentSession(session_id="sub-cancelled", kind="subagent", status=SessionStatus.CANCELLED)
    res = await send_subagent_followup(session, "try again", ctx=MagicMock(), store=MagicMock())
    assert res.status == ToolResultStatus.ERROR
    assert "cancelled" in res.content.lower()


@pytest.mark.asyncio
async def test_send_subagent_followup_returns_running_status():
    from core.application.session.stream_followup import send_subagent_followup
    from core.domain.entities.session import AgentSession, SessionStatus

    session = AgentSession(session_id="sub-active", kind="subagent", status=SessionStatus.COMPLETED)
    agent = MagicMock()
    session.agent = agent

    ctx = MagicMock()
    ctx.project_dir = "/tmp/fake"
    ctx.host = MagicMock()

    res = await send_subagent_followup(session, "continue", ctx=ctx, store=None)
    assert res.status == ToolResultStatus.RUNNING
    assert "[subagent resumed | id sub-active]" in res.content
