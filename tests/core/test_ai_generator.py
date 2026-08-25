"""Focused unit tests for the Textual-free AI generation engine core/application/generation/ai_generator.py."""

import asyncio
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.application.generation import ai_generator as ai_generator_module
from core.application.generation.ai_generator import GenCanvas, generate_ai_response


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
        add_bot_message=AsyncMock(
            return_value=MagicMock(
                content="", finalize_stream=AsyncMock(), reset_stream=AsyncMock(), flush_pending_stream=MagicMock()
            )
        ),
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
    from core.infrastructure.storage import git_checkpoint

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
        yield ("tool", "shell", "run", {"cmd": "ls"})
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
async def test_bot_message_preserved_when_tool_call_emitted():
    class Bot:
        def __init__(self):
            self.content = ""
            self._stream_parts = []
            self.removed = False
            self.finalized = False

        def append_stream_content(self, c):
            self._stream_parts.append(c)

        def _join_stream_content(self):
            return "".join(self._stream_parts)

        def flush_pending_stream(self):
            self.content = self._join_stream_content()

        async def finalize_stream(self):
            self.finalized = True

        def remove(self):
            self.removed = True

    bot = Bot()
    canvas = _canvas(add_bot_message=AsyncMock(return_value=bot))

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "I will run a command:", "")
        yield ("tool", "shell", "echo hi", {"command": "echo hi"})
        yield ("tool_result", "hi\n", "")
        yield ("bot_delta", " Done.", "")
        yield ("bot_text", "final text", "")

    await generate_ai_response(
        _FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi"
    )
    assert not bot.removed, "Bot message before tool call must NOT be removed"
    assert bot.finalized, "Bot message before tool call must be finalized"


@pytest.mark.asyncio
async def test_event_divider_refreshes_footer():
    canvas = _canvas()
    sess = _fake_session()

    async def stream(prompt, attachments=None):
        yield ("event_divider", "Compacted", "")

    await generate_ai_response(
        _FakeAgent(stream), sess, canvas, session_id="s1", user_text="hi"
    )
    canvas.add_event_divider.assert_awaited_once_with("Compacted")
    canvas.refresh_status_footer.assert_called_once()
    assert len(sess.events) == 2
    assert sess.events[1] == {"type": "event_divider", "text": "Compacted"}


@pytest.mark.asyncio
async def test_retry_notifies_canvas_with_warning():
    canvas = _canvas()

    async def stream(prompt, attachments=None):
        yield ("retry", 1, 3, 5.0, Exception("Rate limit exceeded"))
        yield ("bot_text", "done", "")

    await generate_ai_response(
        _FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi"
    )
    canvas.notify.assert_called_once()
    msg, kw = canvas.notify.call_args[0][0], canvas.notify.call_args[1]
    assert "Rate limit reached" in msg
    assert "retrying in 5s (attempt 1/3)" in msg
    assert kw.get("severity") == "warning"


@pytest.mark.asyncio
async def test_user_message_recorded_with_attachments():
    async def stream(prompt, attachments=None):
        yield ("bot_text", "ok", "")

    session = _fake_session()
    canvas = _canvas()
    await generate_ai_response(
        _FakeAgent(stream),
        session,
        canvas,
        session_id="s1",
        user_text="hi",
        show_in_ui=True,
        attachments=["a.png", "b.png"],
    )
    canvas.add_user_message.assert_awaited_once_with("hi", ["a.png", "b.png"])
    assert {"type": "user", "text": "hi", "show_in_ui": True, "attachments_count": 2} in session.events


@pytest.mark.asyncio
async def test_user_message_with_display_text():
    seen = []

    async def stream(prompt, attachments=None):
        seen.append(prompt)
        yield ("bot_text", "ok", "")

    session = _fake_session()
    canvas = _canvas()
    await generate_ai_response(
        _FakeAgent(stream),
        session,
        canvas,
        session_id="s1",
        user_text="full prompt with skill <SKILL>...",
        show_in_ui=True,
        display_text="/caveman test",
    )
    assert seen == ["full prompt with skill <SKILL>..."]
    canvas.add_user_message.assert_awaited_once_with("/caveman test", None)
    assert {
        "type": "user",
        "text": "full prompt with skill <SKILL>...",
        "display_text": "/caveman test",
        "show_in_ui": True,
    } in session.events


# --- rewind restore barrier --------------------------------------------------

async def test_await_pending_git_restore_barrier():
    from types import SimpleNamespace

    from core.application.generation.ai_generator import _await_pending_git_restore

    # Agent without the attribute: no-op.
    await _await_pending_git_restore(object())

    # Done task: no-op.
    done_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)
    await _await_pending_git_restore(SimpleNamespace(rewind_git_restore_task=done_task))

    # Pending task: awaited; its failure is swallowed (restore errors are logged
    # downstream and must never abort the new turn).
    started = []

    async def failing_restore():
        started.append(True)
        raise RuntimeError("restore boom")

    task = asyncio.create_task(failing_restore())
    await asyncio.sleep(0)  # let the task start
    await _await_pending_git_restore(SimpleNamespace(rewind_git_restore_task=task))
    assert started == [True]
    assert task.done()


async def test_generate_waits_for_pending_restore_before_checkpoint():
    """The turn snapshot must happen only after the previous rewind restore finished."""

    order = []

    async def stream(prompt, attachments=None):
        yield ("bot_text", "ok", "")

    async def pending_restore():
        order.append("restore")

    pending = asyncio.create_task(pending_restore())
    agent = _FakeAgent(stream)
    agent.rewind_git_restore_task = pending

    real_checkpoint = ai_generator_module._create_git_checkpoint_async

    async def spy_checkpoint(canvas, session_id, project_path):
        order.append("checkpoint")
        return await real_checkpoint(canvas, session_id, project_path)

    with mock.patch.object(ai_generator_module, "_create_git_checkpoint_async", side_effect=spy_checkpoint):
        await generate_ai_response(
            agent, _fake_session(), _canvas(get_user_messages=mock.MagicMock(return_value=[])), session_id="s1", user_text="hi"
        )

    assert order == ["restore", "checkpoint"]



