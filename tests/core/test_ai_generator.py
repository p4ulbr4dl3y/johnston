"""Focused unit tests for the Textual-free AI generation engine core/ai_generator.py."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from core.ai_generator import GenCanvas, generate_ai_response


class _FakeAgent:
    def __init__(self, steps):
        self.stream_steps = steps
        self.history = []
        self._last_sys_tokens = 0
        self.last_context_tokens = 0
        self.model = "gpt-4o"


def _fake_session():
    session = MagicMock()
    session.events = []
    session.add_event = session.events.append
    return session


def _canvas(**overrides):
    c = GenCanvas(
        add_user_message=AsyncMock(),
        add_thinking_widget=AsyncMock(return_value=MagicMock()),
        add_tool_call=AsyncMock(return_value=MagicMock()),
        add_bot_message=AsyncMock(return_value=MagicMock(content="")),
        add_event_divider=AsyncMock(),
        get_user_messages=MagicMock(return_value=[("0", "hi")]),
        refresh_status_footer=MagicMock(),
        notify=MagicMock(),
        save_session=AsyncMock(),
    )
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


async def _ag():
    agent = _FakeAgent(lambda *a, **k: _ag_step())
    agent.history = []
    return agent


async def _ag_step():
    # placeholder generator never used directly
    yield ("bot_text", "done", "")


@pytest.mark.asyncio
async def test_user_message_recorded_and_rendered():
    seen = []

    async def stream(prompt, attachments=None):
        seen.append(prompt)
        yield ("bot_text", "hello", "")

    agent = _FakeAgent(stream)
    session = _fake_session()
    canvas = _canvas()
    await generate_ai_response(
        agent, session, canvas, session_id="s1", user_text="hi", show_in_ui=True, attachments=None
    )
    assert seen == ["hi"]
    canvas.add_user_message.assert_awaited_once_with("hi", None)
    assert {"type": "user", "text": "hi", "show_in_ui": True} in session.events


@pytest.mark.asyncio
async def test_user_message_not_rendered_when_hidden():
    session = _fake_session()
    canvas = _canvas()

    async def stream(prompt, attachments=None):
        yield ("bot_text", "ok", "")

    await generate_ai_response(
        _FakeAgent(stream), session, canvas, session_id="s1", user_text="hi", show_in_ui=False
    )
    canvas.add_user_message.assert_not_called()
    assert {"type": "user", "text": "hi", "show_in_ui": False} in session.events


@pytest.mark.asyncio
async def test_git_checkpoint_called_for_queued_message():
    from core import git_checkpoint

    created = []
    real_create = git_checkpoint.GitCheckpointManager.create_checkpoint

    def fake_create(sid, idx, project_path=None, **kw):
        created.append((sid, idx, project_path))
        return "sha"

    git_checkpoint.GitCheckpointManager.create_checkpoint = staticmethod(fake_create)
    try:
        session = _fake_session()
        canvas = _canvas()

        async def stream(prompt, attachments=None):
            yield ("queued_user_message", "Mid-turn", None, True)

        await generate_ai_response(
            _FakeAgent(stream), session, canvas, session_id="sid1", user_text="hi", project_path="/proj"
        )
    finally:
        git_checkpoint.GitCheckpointManager.create_checkpoint = staticmethod(real_create)

    assert created, "checkpoint should have been created for queued user message"
    assert "Mid-turn" in [e["text"] for e in session.events if e.get("type") == "user"]


@pytest.mark.asyncio
async def test_save_session_called_after_tool_result():
    session = _fake_session()
    canvas = _canvas()

    async def stream(prompt, attachments=None):
        yield ("tool", "bash", "run", {"cmd": "ls"})
        yield ("tool_result", "output", "")

    await generate_ai_response(
        _FakeAgent(stream), session, canvas, session_id="s1", user_text="hi"
    )
    assert canvas.save_session.awoken


    assert canvas.save_session.call_count >= 1


@pytest.mark.asyncio
async def test_bot_message_streamed_and_finalized():
    class Bot:
        def __init__(self):
            self.content = ""

        def append_stream_content(self, c):
            self.content += c

    bot = Bot()
    canvas = _canvas(add_bot_message=AsyncMock(return_value=bot))

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "hel", "")
        yield ("bot_delta", "lo", "")
        yield ("bot_text", "world", "")

    await generate_ai_response(
        _FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi"
    )
    assert bot.content == "hello"


@pytest.mark.asyncio
async def test_event_divider_refreshes_footer():
    canvas = _canvas()

    async def stream(prompt, attachments=None):
        yield ("event_divider", "Compacted", "")

    await generate_ai_response(
        _FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi"
    )
    canvas.add_event_divider.assert_awaited_once_with("Compacted")
    canvas.refresh_status_footer.assert_called_once()
