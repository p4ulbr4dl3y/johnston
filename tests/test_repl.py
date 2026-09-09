"""Tests for Johnston REPL package (events, session, renderer, commands, mock engine, app)."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console
from textual.widgets import Input

from johnston_cli.repl import start_repl
from johnston_cli.repl.app import ReplApp
from johnston_cli.repl.commands import CommandHandler
from johnston_cli.repl.engine.events import (
    TextChunkEvent,
    ThinkingDoneEvent,
    ThinkingStartEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
    TurnDoneEvent,
)
from johnston_cli.repl.engine.mock import MockEngine
from johnston_cli.repl.input import ReplInput
from johnston_cli.repl.render import ReplRenderer
from johnston_cli.repl.session import ReplSession


def test_session_state():
    sess = ReplSession(model_name="test-model", role="coder")
    assert sess.model_name == "test-model"
    assert sess.role == "coder"
    assert sess.total_tokens == 0
    assert sess.total_cost_usd == 0.0

    sess.record_turn(prompt="hi", response="hello", tokens=100, cost=0.001)
    assert sess.total_tokens == 100
    assert sess.total_cost_usd == 0.001
    assert len(sess.history) == 2


@pytest.mark.asyncio
async def test_mock_engine_test_prompt():
    engine = MockEngine(fast=True)
    session = ReplSession()

    events = []
    async for event in engine.generate("run pytest tests", session):
        events.append(event)

    types = [type(e) for e in events]
    assert ThinkingStartEvent in types
    assert ThinkingDoneEvent in types
    assert ToolCallStartEvent in types
    assert ToolCallResultEvent in types
    assert TextChunkEvent in types
    assert TurnDoneEvent in types

    tool_results = [e for e in events if isinstance(e, ToolCallResultEvent)]
    assert any(tr.tool_name == "Shell" for tr in tool_results)


@pytest.mark.asyncio
async def test_mock_engine_edit_prompt():
    engine = MockEngine(fast=True)
    session = ReplSession()

    events = []
    async for event in engine.generate("почини баг в auth", session):
        events.append(event)

    tool_results = [e for e in events if isinstance(e, ToolCallResultEvent)]
    assert any(tr.tool_name == "Edit" and tr.diff is not None for tr in tool_results)


@pytest.mark.asyncio
async def test_mock_engine_general_prompt():
    engine = MockEngine(fast=True)
    session = ReplSession()

    events = []
    async for event in engine.generate("расскажи о проекте", session):
        events.append(event)

    tool_results = [e for e in events if isinstance(e, ToolCallResultEvent)]
    assert any(tr.tool_name == "Read" for tr in tool_results)


def test_commands_handler():
    console = Console(record=True)
    handler = CommandHandler(console)

    assert handler.is_command("/help")
    assert handler.is_command("/clear")
    assert not handler.is_command("hello")

    session = ReplSession()
    assert handler.handle("/help", session) is None
    assert handler.handle("/tokens", session) is None
    assert handler.handle("/model gpt-4o", session) is None
    assert session.model_name == "gpt-4o"
    assert handler.handle("/model", session) is None
    with patch("os.system") as mock_sys:
        assert handler.handle("/clear", session) is None
        mock_sys.assert_called_once()
    assert handler.handle("/foobar", session) is None
    assert handler.handle("/exit", session) is True
    assert handler.handle("/quit", session) is True


def test_renderer_outputs():
    console = Console(record=True, width=100)
    renderer = ReplRenderer(console)
    session = ReplSession()

    renderer.render_welcome(session, is_mock=True)
    renderer.render_welcome(session, is_mock=False)
    renderer.render_user_prompt("test prompt")

    box_panel = renderer.make_status_box("Thinking...", session)
    assert box_panel is not None

    tool_panel_read = renderer.make_tool_panel(
        ToolCallResultEvent(tool_name="Read", target="foo.py", summary="content")
    )
    assert tool_panel_read is not None
    assert "Read(foo.py)" in tool_panel_read.plain

    tool_panel_edit = renderer.make_tool_panel(
        ToolCallResultEvent(tool_name="Edit", target="foo.py", diff="--- a\n+++ b")
    )
    assert tool_panel_edit is not None
    assert "Edit(foo.py)" in tool_panel_edit.plain

    tool_panel_err = renderer.make_tool_panel(
        ToolCallResultEvent(tool_name="Shell", is_error=True, summary="failed")
    )
    assert tool_panel_err is not None
    assert "Shell" in tool_panel_err.plain


def test_tool_call_expansion():
    from johnston_cli.repl.render import is_tool_expandable, render_tool_call

    assert is_tool_expandable("Edit")
    assert is_tool_expandable("edit")
    assert is_tool_expandable("Shell")
    assert is_tool_expandable("shell")
    assert is_tool_expandable("Search")
    assert not is_tool_expandable("Read")
    assert not is_tool_expandable("Kill")
    assert not is_tool_expandable("ask_user")

    event_edit = ToolCallResultEvent(
        tool_name="Edit",
        target="core/auth.py",
        diff="@@ -1,1 +1,1 @@\n-old_line\n+new_line",
    )
    collapsed = render_tool_call(event_edit, expanded=False).plain
    assert "Edit(core/auth.py)" in collapsed
    assert "(ctrl+o to expand)" in collapsed
    assert "old_line" not in collapsed

    expanded = render_tool_call(event_edit, expanded=True).plain
    assert "Edit(core/auth.py)" in expanded
    assert "(ctrl+o to collapse)" in expanded
    assert "│" in expanded
    assert "-old_line" in expanded
    assert "+new_line" in expanded

    event_read = ToolCallResultEvent(
        tool_name="Read",
        target="AGENTS.md",
        summary="some content",
    )
    read_rendered = render_tool_call(event_read, expanded=False).plain
    assert "Read(AGENTS.md)" in read_rendered
    assert "(ctrl+o" not in read_rendered


def test_thinking_expansion():
    from johnston_cli.repl.render import render_thinking

    # Without content (non-expandable)
    evt_no_cot = ThinkingDoneEvent(duration_s=1.5, token_count=200)
    res = render_thinking(evt_no_cot, expanded=False).plain
    assert "Thought for 1.5s · 200 tokens" in res
    assert "(ctrl+o" not in res

    # With content (expandable)
    evt_cot = ThinkingDoneEvent(
        duration_s=2.0,
        token_count=350,
        content="line 1 of thinking\nline 2 of thinking",
    )
    collapsed = render_thinking(evt_cot, expanded=False).plain
    assert "Thought for 2.0s · 350 tokens" in collapsed
    assert "(ctrl+o to expand)" in collapsed
    assert "line 1" not in collapsed

    expanded = render_thinking(evt_cot, expanded=True).plain
    assert "Thought for 2.0s · 350 tokens" in expanded
    assert "(ctrl+o to collapse)" in expanded
    assert "│" in expanded
    assert "line 1 of thinking" in expanded
    assert "line 2 of thinking" in expanded


def test_input_boxed_app():
    session = ReplSession(total_cost_usd=0.015, total_tokens=5000)
    repl_input = ReplInput(session, ["/help", "/exit"])
    app = repl_input._create_app()
    assert app is not None
    assert app.erase_when_done is True


@pytest.mark.asyncio
async def test_repl_app_run_turn():
    engine = MockEngine(fast=True)
    app = ReplApp(engine=engine)
    await app._run_turn("почини auth")

    assert app.session.total_tokens > 0
    assert len(app.session.history) == 2


@pytest.mark.asyncio
async def test_repl_app_turn_cancel():
    async def cancelling_generator(prompt, session):
        yield ThinkingStartEvent()
        raise asyncio.CancelledError()

    mock_eng = MagicMock()
    mock_eng.generate = cancelling_generator
    app = ReplApp(engine=mock_eng)
    await app._run_turn("cancel me")


@pytest.mark.asyncio
async def test_repl_app_pilot():
    engine = MockEngine(fast=True)
    app = ReplApp(engine=engine)
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt-input", Input)
        inp.focus()
        inp.value = "/help"
        await inp.action_submit()
        inp.value = "тестовый запрос"
        await inp.action_submit()
        await pilot.pause(0.1)
        await app._prompt_queue.join()
        assert app.session.total_tokens > 0
        inp.value = "/exit"
        await inp.action_submit()


@pytest.mark.asyncio
async def test_repl_app_initial_prompt():
    engine = MockEngine(fast=True)
    app = ReplApp(engine=engine, initial_prompt="привет")
    async with app.run_test() as pilot:
        await pilot.pause(0.1)
        await app._prompt_queue.join()
        assert app.session.total_tokens > 0
        app.action_exit_app()


@pytest.mark.asyncio
async def test_repl_app_ctrl_c_and_actions():
    engine = MockEngine(fast=True)
    app = ReplApp(engine=engine)
    async with app.run_test():
        # When not generating, Ctrl+C exits
        app._is_generating = False
        app.action_handle_ctrl_c()
        # Test clear chat
        app._clear_chat()
        # Test command output
        app._on_command_output("test output")

@pytest.mark.asyncio
async def test_repl_app_toggle_tools():
    from johnston_cli.repl.app import ThinkingWidget, ToolCallWidget

    engine = MockEngine(fast=True)
    app = ReplApp(engine=engine)
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt-input", Input)
        inp.value = "почини баг в auth"
        await inp.action_submit()
        await pilot.pause(0.1)
        await app._prompt_queue.join()

        container = app.query_one("#chat-container")
        tool_widgets = list(container.query(ToolCallWidget))
        thinking_widgets = list(container.query(ThinkingWidget))
        assert len(tool_widgets) > 0
        assert len(thinking_widgets) == 1

        # Initially collapsed
        assert not app._tools_expanded
        edit_widgets = [w for w in tool_widgets if w.event.tool_name == "Edit"]
        assert len(edit_widgets) == 1
        assert not edit_widgets[0].expanded
        assert not thinking_widgets[0].expanded
        # Only last expandable widget (Edit) shows hint
        assert not thinking_widgets[0].show_hint
        assert edit_widgets[0].show_hint
        # Sequential class present when collapsed
        assert edit_widgets[0].is_sequential
        assert "-sequential" in edit_widgets[0].classes

        # Trigger Ctrl+O to expand
        app.action_toggle_tools()
        assert app._tools_expanded
        assert edit_widgets[0].expanded
        assert thinking_widgets[0].expanded
        # Sequential class removed when expanded
        assert "-sequential" not in edit_widgets[0].classes

        # Trigger Ctrl+O again to collapse
        app.action_toggle_tools()
        assert not app._tools_expanded
        assert not edit_widgets[0].expanded
        assert not thinking_widgets[0].expanded
        # Sequential class restored
        assert "-sequential" in edit_widgets[0].classes


@pytest.mark.asyncio
async def test_repl_app_scroll_actions():
    engine = MockEngine(fast=True)
    app = ReplApp(engine=engine)
    async with app.run_test() as pilot:
        inp = app.query_one("#prompt-input", Input)
        inp.value = "почини баг в auth"
        await inp.action_submit()
        await pilot.pause(0.1)
        await app._prompt_queue.join()

        # Test toggle tools scrolls to top and updates footer
        app.action_toggle_tools()
        assert app._tools_expanded
        assert "ctrl+o to collapse" in app._format_footer()

        # Test scroll actions do not raise
        app.action_scroll_page_up()
        app.action_scroll_page_down()
        app.action_scroll_line_up()
        app.action_scroll_line_down()
        app.action_scroll_home()
        app.action_scroll_end()

        # Collapse again
        app.action_toggle_tools()
        assert not app._tools_expanded


def test_start_repl_entrypoint():
    with patch.object(ReplApp, "run", return_value=0) as mock_run:
        args = MagicMock(model="claude-3-7-sonnet", role="code")
        code = start_repl(initial_prompt="hello", args=args)
        assert code == 0
        mock_run.assert_called_once()
