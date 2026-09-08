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
