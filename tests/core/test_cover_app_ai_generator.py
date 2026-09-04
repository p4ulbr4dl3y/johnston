"""Coverage-focused unit tests for core/application/generation/ai_generator.py.

Covers the debounce-save error/edge paths and the interruption handler branches
that existing test_ai_generator.py does not exercise. No network calls.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.application.generation.ai_generator import (
    GenCanvas,
    _SessionSaveDebounce,
    generate_ai_response,
)


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


# --- _SessionSaveDebounce edge paths ---------------------------------------


def test_debounce_ensure_loop_returns_false_without_running_loop():
    # Not an asyncio test: no running loop -> RuntimeError -> returns False.
    deb = _SessionSaveDebounce(lambda: None)
    assert deb._ensure_loop() is False


def test_debounce_schedule_no_save_returns_early():
    deb = _SessionSaveDebounce(None)
    deb.schedule()  # must not raise, no task created
    assert deb._task is None


def test_debounce_schedule_without_loop_returns_early():
    deb = _SessionSaveDebounce(lambda: None)
    # No running loop (patched) -> _ensure_loop() False -> no task scheduled.
    deb._ensure_loop = lambda: False
    deb.schedule()
    assert deb._task is None


def test_debounce_flush_no_save_returns_early():
    deb = _SessionSaveDebounce(None)
    asyncio.run(deb.flush())  # must not raise
    deb._save = None
    deb._task = None
    asyncio.run(deb.flush())


def test_debounce_flush_without_loop_returns_early():
    deb = _SessionSaveDebounce(lambda: None)
    deb._ensure_loop = lambda: False
    asyncio.run(deb.flush())


@pytest.mark.asyncio
async def test_debounce_schedule_cancels_pending_task_and_saves():
    saved = []
    deb = _SessionSaveDebounce(lambda: saved.append(1), settle_time=0.05)
    deb.schedule()
    first = deb._task
    assert first is not None
    # Second schedule while first task is still sleeping must cancel it.
    deb.schedule()
    assert deb._task is not None
    assert deb._task is not first
    try:
        await first
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.1)
    assert saved == [1]  # the _run() save fired


# --- generate_ai_response edge paths ---------------------------------------


@pytest.mark.asyncio
async def test_stream_ignores_empty_step():
    async def stream(prompt, attachments=None):
        yield None
        yield ("bot_text", "done", "")

    canvas = _canvas()
    await generate_ai_response(_FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi")
    canvas.add_bot_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_queued_user_message_with_attachments_records_count():
    canvas = _canvas()
    session = _fake_session()

    async def stream(prompt, attachments=None):
        yield ("queued_user_message", "Mid-turn", ["a.png"], True)
        yield ("bot_text", "done", "")

    await generate_ai_response(_FakeAgent(stream), session, canvas, session_id="sid1", user_text="hi")
    event = [e for e in session.events if e.get("type") == "user" and e.get("text") == "Mid-turn"]
    assert event[0].get("attachments_count") == 1


@pytest.mark.asyncio
async def test_queued_user_message_with_display_text_renders_command():
    """Mid-generation skill queue item must render its short display_text in the UI."""
    canvas = _canvas()
    session = _fake_session()

    async def stream(prompt, attachments=None):
        yield ("queued_user_message", "<skill path='/tmp/s/SKILL.md'>full body</skill>", None, True, "/johnston-guide")
        yield ("bot_text", "done", "")

    await generate_ai_response(_FakeAgent(stream), session, canvas, session_id="sid1", user_text="hi")

    # UI renders the short command, not the expanded skill block. The initial
    # "hi" prompt and the queued item each produce one add_user_message call.
    rendered_texts = [c.args[0] for c in canvas.add_user_message.await_args_list]
    assert "/johnston-guide" in rendered_texts
    assert "<skill path='/tmp/s/SKILL.md'>full body</skill>" not in rendered_texts

    # Transcript keeps both the full prompt text and the display_text override.
    event = [
        e
        for e in session.events
        if e.get("type") == "user" and e.get("text") == "<skill path='/tmp/s/SKILL.md'>full body</skill>"
    ]
    assert event
    assert event[0].get("display_text") == "/johnston-guide"


@pytest.mark.asyncio
async def test_queued_user_message_without_display_text_renders_full_text():
    """Legacy 4-element queue item keeps rendering its full prompt text (no display_text)."""
    canvas = _canvas()
    session = _fake_session()

    async def stream(prompt, attachments=None):
        yield ("queued_user_message", "<skill path='/tmp/s/SKILL.md'>full body</skill>", None, True)
        yield ("bot_text", "done", "")

    await generate_ai_response(_FakeAgent(stream), session, canvas, session_id="sid1", user_text="hi")

    rendered_texts = [c.args[0] for c in canvas.add_user_message.await_args_list]
    assert "<skill path='/tmp/s/SKILL.md'>full body</skill>" in rendered_texts


@pytest.mark.asyncio
async def test_schedule_exceptions_swallowed_on_save_points():
    # Force _SessionSaveDebounce.schedule to raise: every schedule() call site
    # is guarded by try/except and must be swallowed.
    canvas = _canvas()

    async def stream(prompt, attachments=None):
        yield ("tool", "shell", "run", {"cmd": "ls"})
        yield ("tool_result", "output", "")
        yield ("bot_text", "done", "")
        yield ("event_divider", "Compacted", "")

    with patch("core.application.generation.ai_generator._SessionSaveDebounce.schedule", side_effect=RuntimeError("x")), patch(
        "core.application.generation.ai_generator._SessionSaveDebounce.flush", side_effect=RuntimeError("f")
    ):
        await generate_ai_response(_FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi")
    canvas.add_event_divider.assert_awaited_once_with("Compacted")


@pytest.mark.asyncio
async def test_bot_reset_stream_error_swallowed():
    canvas = _canvas(add_bot_message=AsyncMock(return_value=MagicMock(reset_stream=AsyncMock(side_effect=Exception("e")))))

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "partial", "")
        yield ("bot_reset", "", "")
        yield ("bot_text", "done", "")

    await generate_ai_response(_FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi")


@pytest.mark.asyncio
async def test_retry_reset_and_notify_errors_swallowed():
    bot = MagicMock(
        reset_stream=AsyncMock(side_effect=Exception("reset fail")),
        content="",
        flush_pending_stream=MagicMock(),
        finalize_stream=AsyncMock(),
    )
    canvas = _canvas(add_bot_message=AsyncMock(return_value=bot), notify=MagicMock(side_effect=RuntimeError("n")))

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "partial", "")
        yield ("retry", 1, 3, 5.0, Exception("rate limit"))
        yield ("bot_text", "done", "")

    await generate_ai_response(_FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi")


class _BotRemoveRaises:
    def __init__(self):
        self.content = ""

    def append_stream_content(self, c):
        """No-op: keep content empty so the finally branch removes the widget."""

    def remove(self):
        raise RuntimeError("remove failed")

    async def finalize_stream(self, *a):
        pass

    async def reset_stream(self):
        pass

    def flush_pending_stream(self):
        pass


@pytest.mark.asyncio
async def test_finally_remove_error_swallowed():
    bot = _BotRemoveRaises()
    canvas = _canvas(add_bot_message=AsyncMock(return_value=bot))

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "x", "")

    # bot_handle.content is empty (append_stream_content only sets during bot_delta
    # but this fake holds it) -> finally branch calls remove() which raises.
    await generate_ai_response(_FakeAgent(stream), _fake_session(), canvas, session_id="s1", user_text="hi")


# --- interruption handler --------------------------------------------------


class _StatefulBot:
    """Tracks method calls for assertion but fails specific ones on demand."""

    def __init__(self, content="", fail_finalize=False, fail_remove=False):
        self.content = content
        self._fail_finalize = fail_finalize
        self._fail_remove = fail_remove
        self.finalized = False
        self.removed = False

    def append_stream_content(self, c):
        self.content += c

    def flush_pending_stream(self):
        pass

    async def finalize_stream(self, *a):
        if self._fail_finalize:
            raise RuntimeError("finalize fail")
        self.finalized = True

    def remove(self):
        if self._fail_remove:
            raise RuntimeError("remove fail")
        self.removed = True

    def _join_stream_content(self):
        return self.content


@pytest.mark.asyncio
async def test_interruption_appends_partial_and_handles_callbacks():
    class Bot:
        def __init__(self):
            self.content = "partial reply"
            self._fail_finalize = False

        async def finalize_stream(self, *a):
            if self._fail_finalize:
                raise RuntimeError("f")
            self.finalized = True

        def append_stream_content(self, c):
            self.content += c

        def flush_pending_stream(self):
            pass

        def _join_stream_content(self):
            return self.content

    bot = _StatefulBot(content="")
    canvas = _canvas(
        add_bot_message=AsyncMock(return_value=bot),
        add_event_divider=AsyncMock(side_effect=RuntimeError("divider fail")),
        refresh_status_footer=MagicMock(side_effect=RuntimeError("footer fail")),
    )
    agent = _FakeAgent(lambda *a, **k: stream_agent())
    with pytest.raises(asyncio.CancelledError):
        await generate_ai_response(agent, _fake_session(), canvas, session_id="s1", user_text="hi")
    # Partial assistant reply + interruption note recorded.
    assert any(m.get("content") == "partial reply" for m in agent.history if m.get("role") == "assistant")
    assert any(
        '<system_note kind="interrupted"' in m.get("content", "")
        for m in agent.history
    )


async def stream_agent():
    yield ("bot_delta", "partial reply", "")
    raise asyncio.CancelledError


@pytest.mark.asyncio
async def test_interruption_handles_thinking_tool_and_mark_cancelled_errors():
    thinking = MagicMock(finish_thinking=MagicMock(side_effect=RuntimeError("think fail")))
    tool_handle = MagicMock(mark_cancelled=MagicMock(side_effect=RuntimeError("mark fail")))
    bot = _StatefulBot(content="some text", fail_finalize=False)
    canvas = _canvas(
        add_bot_message=AsyncMock(return_value=bot),
        add_tool_call=AsyncMock(return_value=tool_handle),
        add_thinking_widget=AsyncMock(return_value=thinking),
        add_event_divider=AsyncMock(side_effect=RuntimeError("divider fail")),
    )

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "some text", "")
        yield ("thinking_start", "let me")
        yield ("tool", "shell", "run", {"cmd": "ls"})
        raise asyncio.CancelledError

    agent = _FakeAgent(stream)
    with pytest.raises(asyncio.CancelledError):
        await generate_ai_response(agent, _fake_session(), canvas, session_id="s1", user_text="hi")
    tool_handle.mark_cancelled.assert_called_once()


@pytest.mark.asyncio
async def test_interruption_finalize_stream_error_swallowed():
    bot = _StatefulBot(content="some text", fail_finalize=True)
    canvas = _canvas(add_bot_message=AsyncMock(return_value=bot))

    async def stream(prompt, attachments=None):
        yield ("bot_delta", "some text", "")
        raise asyncio.CancelledError

    agent = _FakeAgent(stream)
    with pytest.raises(asyncio.CancelledError):
        await generate_ai_response(agent, _fake_session(), canvas, session_id="s1", user_text="hi")


@pytest.mark.asyncio
async def test_generation_failure_during_thinking_finishes_thinking_widget():
    thinking = MagicMock(is_thinking=True, finish_thinking=MagicMock())
    canvas = _canvas(
        add_thinking_widget=AsyncMock(return_value=thinking),
    )

    async def stream(prompt, attachments=None):
        yield ("thinking_start", "thinking...")
        yield ("thinking_delta", "analyzing...")
        raise ConnectionError("connection dropped")

    agent = _FakeAgent(stream)
    session = _fake_session()
    await generate_ai_response(agent, session, canvas, session_id="s1", user_text="hi")

    thinking.finish_thinking.assert_called_once()
    canvas.notify.assert_called_once()


@pytest.mark.asyncio
async def test_generation_failure_cleans_up_unfinalized_tools():
    tool_handle = MagicMock(status="generating", remove=MagicMock())
    canvas = _canvas(
        add_tool_call=AsyncMock(return_value=tool_handle),
    )

    async def stream(prompt, attachments=None):
        yield ("tool_generating", "read", "foo.py", {"id": "c1"})
        raise ConnectionError("connection dropped")

    agent = _FakeAgent(stream)
    session = _fake_session()
    await generate_ai_response(agent, session, canvas, session_id="s1", user_text="hi")

    tool_handle.remove.assert_called_once()
    canvas.notify.assert_called_once()


