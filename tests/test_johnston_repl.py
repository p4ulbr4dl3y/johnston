"""Tests for johnston_cli.repl package (session, runner, terminal, loop)."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from johnston_cli.repl.loop import run_repl_loop, start_repl
from johnston_cli.repl.runner import AgentReplRunner
from johnston_cli.repl.session import create_repl_prompt_session, get_current_git_branch
from johnston_cli.repl.terminal import (
    format_turn_footer,
    get_term_width,
    print_banner,
    print_top_separator,
)


def test_terminal_helpers():
    width = get_term_width()
    assert width >= 40

    footer = format_turn_footer("test-model", 1500, 2.5)
    assert "test-model" in footer
    assert "1,500 tokens" in footer
    assert "2.5s" in footer

    # Banner
    f = io.StringIO()
    with patch("sys.stdout", f):
        print_banner("1.0.0", "openai/gpt-4o", "main")
    out = f.getvalue()
    assert "Johnston" in out
    assert "1.0.0" in out
    assert "openai/gpt-4o" in out
    assert "main" in out

    # Top separator
    f2 = io.StringIO()
    with patch("sys.stdout", f2):
        print_top_separator()
    assert "─" in f2.getvalue()


def test_git_branch_detection():
    branch = get_current_git_branch()
    assert isinstance(branch, str)
    assert len(branch) > 0


def test_create_repl_prompt_session():
    def _status():
        return "openai/gpt-4o", 1200

    session = create_repl_prompt_session(_status)
    assert session.multiline is True
    layout = session._create_layout()
    assert layout is not None


def test_agent_repl_runner_init():
    mock_pm = MagicMock()
    mock_pm.get_active_provider_key.return_value = "openai"
    mock_agent = MagicMock()
    mock_agent.model = "gpt-4o"
    mock_pm.create_agent_for_provider.return_value = mock_agent

    runner = AgentReplRunner(pm=mock_pm)
    assert runner.provider_key == "openai"
    assert runner.model_name == "gpt-4o"
    assert runner.agent is mock_agent


@pytest.mark.asyncio
async def test_agent_repl_runner_run_turn():
    mock_pm = MagicMock()
    mock_pm.get_active_provider_key.return_value = "test_prov"
    mock_agent = MagicMock()
    mock_agent.model = "test_mod"

    async def _fake_stream(prompt):
        yield ("delta", "Hello, ", "", "", "")
        yield ("delta", "world!", "", "", "")
        yield ("bot_text", "Hello, world!", "", "", "")

    mock_agent.stream_steps = _fake_stream
    mock_agent.last_context_tokens = 50
    mock_agent.total_tokens = 50
    mock_pm.create_agent_for_provider.return_value = mock_agent

    runner = AgentReplRunner(pm=mock_pm)
    f = io.StringIO()
    with patch("sys.stdout", f):
        await runner.run_turn("hi")
    val = f.getvalue()
    assert "Hello, world!" in val
    assert "test_prov/test_mod" in val
    assert runner.total_session_tokens == 50


@pytest.mark.asyncio
async def test_run_repl_loop_exit():
    with patch("johnston_cli.repl.loop.AgentReplRunner") as mock_runner_cls, \
         patch("johnston_cli.repl.loop.create_repl_prompt_session") as mock_sess_cls:

        mock_runner = MagicMock()
        mock_runner.provider_key = "test"
        mock_runner.model_name = "test"
        mock_runner.total_session_tokens = 0
        mock_runner_cls.return_value = mock_runner

        mock_sess = MagicMock()
        mock_sess.prompt_async = AsyncMock(side_effect=["exit"])
        mock_sess_cls.return_value = mock_sess

        code = await run_repl_loop(initial_prompt=None)
        assert code == 0


@pytest.mark.asyncio
async def test_run_repl_loop_initial_prompt():
    with patch("johnston_cli.repl.loop.AgentReplRunner") as mock_runner_cls, \
         patch("johnston_cli.repl.loop.create_repl_prompt_session") as mock_sess_cls:

        mock_runner = MagicMock()
        mock_runner.provider_key = "test"
        mock_runner.model_name = "test"
        mock_runner.total_session_tokens = 0
        mock_runner.run_turn = AsyncMock()
        mock_runner_cls.return_value = mock_runner

        mock_sess = MagicMock()
        mock_sess.prompt_async = AsyncMock(side_effect=["quit"])
        mock_sess_cls.return_value = mock_sess

        code = await run_repl_loop(initial_prompt="do task")
        assert code == 0
        mock_runner.run_turn.assert_awaited_once_with("do task")


def test_start_repl_sync():
    with patch("johnston_cli.repl.loop.run_repl_loop", return_value=0):
        code = start_repl()
        assert code == 0
