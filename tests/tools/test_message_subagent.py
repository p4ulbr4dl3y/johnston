from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from johnston.core.domain.defaults.errors import ToolResult, ToolResultStatus
from johnston.core.tools.context import ToolContext
from johnston.core.tools.message_subagent import MessageSubagentTool


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
    monkeypatch.setattr("johnston.core.infrastructure.storage.session_store.get_session_store", lambda host: store)

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
    monkeypatch.setattr("johnston.core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    send_mock = AsyncMock(return_value=ToolResult.done(content="[resumed sub-123]"))
    monkeypatch.setattr("johnston.core.application.session.subagent_service.SubagentService.send_message", send_mock)

    ctx = ToolContext(app=MagicMock())

    res = await msg_tool.execute({"id": "sub-123", "message": "continue work"}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    assert "[resumed sub-123]" in res.content
    send_mock.assert_awaited_once_with(session, "continue work", ANY, store)


@pytest.mark.asyncio
async def test_message_subagent_rejects_legacy_session_id_alias(msg_tool, monkeypatch):
    ctx = ToolContext(app=MagicMock())
    res = await msg_tool.execute({"session_id": "sub-777", "message": "alias test"}, ctx=ctx)
    assert res.status == ToolResultStatus.ERROR
    assert "ERR: params 'id': required" in res.content


@pytest.mark.asyncio
async def test_send_subagent_followup_cancelled_session_rejected():
    from johnston.core.application.session.stream_followup import send_subagent_followup
    from johnston.core.domain.entities.session import AgentSession, SessionStatus

    session = AgentSession(session_id="sub-cancelled", kind="subagent", status=SessionStatus.CANCELLED)
    res = await send_subagent_followup(session, "try again", ctx=MagicMock(), store=MagicMock())
    assert res.status == ToolResultStatus.ERROR
    assert "cancelled" in res.content.lower()


@pytest.mark.asyncio
async def test_send_subagent_followup_returns_running_status():
    from johnston.core.application.session.stream_followup import send_subagent_followup
    from johnston.core.domain.entities.session import AgentSession, SessionStatus

    session = AgentSession(session_id="sub-active", kind="subagent", status=SessionStatus.COMPLETED)
    agent = MagicMock()
    session.agent = agent

    ctx = MagicMock()
    ctx.project_dir = "/tmp/fake"
    ctx.host = MagicMock()

    res = await send_subagent_followup(session, "continue", ctx=ctx, store=None)
    assert res.status == ToolResultStatus.RUNNING
    assert "[subagent resumed | id sub-active]" in res.content


def test_message_subagent_is_concurrency_safe():
    tool = MessageSubagentTool()
    assert not tool.is_concurrency_safe()


@pytest.mark.asyncio
async def test_message_subagent_blocked_for_subagents(msg_tool):
    ctx = MagicMock()
    ctx.is_subagent = True
    msg_tool._ensure_context = lambda app=None: ctx

    res = await msg_tool.execute({"id": "sub-1", "message": "hello"})
    assert res.is_error
    assert "subagents cannot message other subagents" in res.content


@pytest.mark.asyncio
async def test_message_subagent_non_string_args_coerced(msg_tool, monkeypatch):
    session = MagicMock()
    session.id = "123"

    store = MagicMock()
    store.find_session_by_title_or_id.return_value = session
    monkeypatch.setattr("johnston.core.infrastructure.storage.session_store.get_session_store", lambda host: store)

    send_mock = AsyncMock(return_value=ToolResult.done(content="[resumed 123]"))
    monkeypatch.setattr("johnston.core.application.session.subagent_service.SubagentService.send_message", send_mock)

    ctx = ToolContext(app=MagicMock())
    res = await msg_tool.execute({"id": 123, "message": 456}, ctx=ctx)
    assert res.status == ToolResultStatus.DONE
    send_mock.assert_awaited_once_with(session, "456", ANY, store)

