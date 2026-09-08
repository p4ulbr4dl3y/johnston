"""Tests for Johnston CLI run command (headless execution)."""
from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, AsyncGenerator
from unittest.mock import MagicMock, patch

from johnston_core.domain.entities.provider import ProviderDef
from johnston_core.domain.policies.role_policy import AgentMode
from johnston_core.interfaces.cli.commands.run_cmd import (
    format_args_summary,
    format_meta_footer,
    format_result_summary,
    resolve_prompt,
    run_headless,
    run_headless_async,
)
from johnston_core.interfaces.cli.entrypoint import build_parser, main


class MockAgent:
    """Mock agent producing async generator steps."""

    def __init__(self, steps: list[Any] | None = None):
        self.steps = steps or []
        self.model = "default-model"
        self.role = "worker"
        self.tokens_input = 10
        self.tokens_output = 20
        self.total_tokens = 30
        self.cost_usd = 0.001
        self.received_prompt: str | None = None

    async def stream_steps(self, prompt: str) -> AsyncGenerator[Any, None]:
        self.received_prompt = prompt
        for step in self.steps:
            yield step


class TestCLIRun(unittest.IsolatedAsyncioTestCase):
    """Unit tests for headless run command."""

    def test_parser_run_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["run", "test prompt", "--provider", "openai", "--model", "gpt-4o", "-q", "--json", "-s", "caveman", "--skill", "debugger"])
        self.assertEqual(args.subcommand, "run")
        self.assertEqual(args.prompt, "test prompt")
        self.assertEqual(args.provider, "openai")
        self.assertEqual(args.model, "gpt-4o")
        self.assertEqual(args.role, "worker")
        self.assertTrue(args.quiet)
        self.assertTrue(args.json)
        self.assertEqual(args.skills, ["caveman", "debugger"])

    def test_resolve_prompt_direct(self):
        prompt = resolve_prompt("hello world")
        self.assertEqual(prompt, "hello world")

    def test_resolve_prompt_stdin_dash(self):
        with patch.object(sys, "stdin", io.StringIO("piped prompt via dash")):
            prompt = resolve_prompt("-")
            self.assertEqual(prompt, "piped prompt via dash")

    def test_resolve_prompt_stdin_piped(self):
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False
        mock_stdin.read.return_value = "piped prompt without dash"
        with patch.object(sys, "stdin", mock_stdin):
            prompt = resolve_prompt(None)
            self.assertEqual(prompt, "piped prompt without dash")

    def test_resolve_prompt_atty_empty(self):
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        err_buf = io.StringIO()
        with patch.object(sys, "stdin", mock_stdin), redirect_stderr(err_buf):
            prompt = resolve_prompt(None)
            self.assertIsNone(prompt)
            self.assertIn("No prompt provided", err_buf.getvalue())

    def test_resolve_prompt_whitespace_only(self):
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            prompt = resolve_prompt("   ")
            self.assertIsNone(prompt)
            self.assertIn("No prompt provided", err_buf.getvalue())

    def test_resolve_prompt_stdin_read_error(self):
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = False
        mock_stdin.read.side_effect = OSError("read error")
        err_buf = io.StringIO()
        with patch.object(sys, "stdin", mock_stdin), redirect_stderr(err_buf):
            prompt = resolve_prompt("-")
            self.assertIsNone(prompt)
            self.assertIn("Error reading from stdin", err_buf.getvalue())

    def test_format_args_summary(self):
        self.assertEqual(format_args_summary(None), "")
        self.assertEqual(format_args_summary({}), "")
        self.assertEqual(format_args_summary({"cmd": "ls -l"}), "cmd='ls -l'")
        self.assertEqual(format_args_summary('{"cmd": "pwd"}'), "cmd='pwd'")
        self.assertEqual(format_args_summary("not-json"), "not-json")

        long_val = "x" * 100
        summary = format_args_summary({"key": long_val})
        self.assertTrue(summary.endswith("..."))

    def test_format_result_summary(self):
        self.assertEqual(format_result_summary(None), "")
        self.assertEqual(format_result_summary(""), "")
        self.assertEqual(format_result_summary("simple result"), "simple result")
        self.assertEqual(format_result_summary("line1\nline2\nline3"), "line1 (+2 lines)")

        long_res = "a" * 150
        summary = format_result_summary(long_res)
        self.assertTrue(summary.endswith("..."))

    async def test_run_headless_async_basic_streaming(self):
        agent = MockAgent(steps=[
            ("content", "Hello ", ""),
            ("bot_delta", "world!", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=True)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = True
        pm.get_api_key.return_value = "sk-test"
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="say hi", provider=None, model=None, role="worker", quiet=False, json=False)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(out_buf.getvalue(), "Hello world!\n")

    async def test_run_headless_async_bot_text_fallback(self):
        agent = MockAgent(steps=[
            ("bot_text", "Full response text", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="test", provider=None, model=None, role=None, quiet=False, json=False)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(out_buf.getvalue(), "Full response text\n")

    async def test_run_headless_async_override_model_and_role(self):
        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(
            prompt="test",
            provider="openai",
            model="gpt-4-turbo",
            role="explorer",
            quiet=False,
            json=False,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(agent.model, "gpt-4-turbo")
        self.assertEqual(agent.role, "explorer")

    async def test_run_headless_async_json_flag(self):
        agent = MockAgent(steps=[
            ("content", "First chunk ", ""),
            ("tool", "search", "query", {"query": "python"}, "call_1"),
            ("tool_result", "found 3 docs", "", False, None, None, "call_1"),
            ("content", "final answer", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="search python", provider=None, model=None, role="worker", quiet=False, json=True)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        raw_output = out_buf.getvalue()
        self.assertNotIn("[tool]", raw_output)
        self.assertNotIn("[result]", raw_output)

        data = json.loads(raw_output)
        self.assertEqual(data["response"], "First chunk final answer")
        self.assertEqual(len(data["tool_calls"]), 1)
        self.assertEqual(data["tool_calls"][0]["name"], "search")
        self.assertEqual(data["tool_calls"][0]["args"], {"query": "python"})
        self.assertEqual(data["tool_calls"][0]["result"], "found 3 docs")
        self.assertEqual(data["usage"]["tokens_input"], 10)
        self.assertEqual(data["usage"]["tokens_output"], 20)
        self.assertEqual(data["usage"]["total_tokens"], 30)

    async def test_run_headless_async_quiet_flag(self):
        agent = MockAgent(steps=[
            ("tool_call", "bash", {"command": "echo hi"}),
            ("tool_result", "hi", ""),
            ("content", "Command output: hi", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="run echo", provider=None, model=None, role="worker", quiet=True, json=False)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        raw_output = out_buf.getvalue()
        self.assertNotIn("[tool]", raw_output)
        self.assertNotIn("[result]", raw_output)
        self.assertEqual(raw_output, "Command output: hi\n")

    async def test_run_headless_async_tool_call_printing(self):
        agent = MockAgent(steps=[
            ("tool", "grep", "foo", {"query": "foo"}, "tc1"),
            ("tool_result", "matches found", "", False, None, None, "tc1"),
            ("content", "search complete", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="find foo", provider=None, model=None, role="worker", quiet=False, json=False, stream_json=False)
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertIn("[tool] grep(query='foo')", err_buf.getvalue())
        self.assertIn("[result] matches found", err_buf.getvalue())
        self.assertEqual(out_buf.getvalue(), "search complete\n")

    async def test_run_headless_async_empty_tool_result_suppressed(self):
        agent = MockAgent(steps=[
            ("tool", "read", "/path", {"path": "/path"}, "tc1"),
            ("tool_result", "", "", False, None, None, "tc1"),
            ("content", "finished reading", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="read file", provider=None, model=None, role="worker", quiet=False, json=False, stream_json=False)
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertIn("[tool] read(path='/path')", err_buf.getvalue())
        self.assertNotIn("[result]", err_buf.getvalue())
        self.assertEqual(out_buf.getvalue(), "finished reading\n")

    async def test_run_headless_async_leading_whitespace_suppressed(self):
        agent = MockAgent(steps=[
            ("content", "\n\n", ""),
            ("tool", "read", "/path", {"path": "/path"}, "tc1"),
            ("tool_result", "ok", "", False, None, None, "tc1"),
            ("content", "\nActual answer", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="read file", provider=None, model=None, role="worker", quiet=False, json=False, stream_json=False)
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(out_buf.getvalue(), "Actual answer\n")

    async def test_run_headless_async_stream_json_flag(self):
        agent = MockAgent(steps=[
            ("tool", "grep", "foo", {"query": "foo"}, "tc1"),
            ("tool_result", "matches found", "", False, None, None, "tc1"),
            ("content", "search complete", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="find foo", provider=None, model=None, role="worker", quiet=False, json=False, stream_json=True)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out_buf.getvalue().strip().splitlines()]
        self.assertEqual(lines[0]["event"], "tool_call")
        self.assertEqual(lines[0]["name"], "grep")
        self.assertEqual(lines[1]["event"], "tool_result")
        self.assertEqual(lines[1]["result"], "matches found")
        self.assertEqual(lines[2]["event"], "delta")
        self.assertEqual(lines[2]["text"], "search complete")
        self.assertEqual(lines[3]["event"], "done")

    async def test_run_headless_async_missing_provider(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = ""
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("No active provider configured", err_buf.getvalue())

    async def test_run_headless_async_unknown_provider(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "unknown"
        pm.load_provider_def.return_value = None
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("Provider 'unknown' not found", err_buf.getvalue())

    async def test_run_headless_async_disabled_provider(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=False, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("Provider 'openai' is disabled", err_buf.getvalue())

    async def test_run_headless_async_missing_api_key(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "anthropic"
        pdef = ProviderDef(key="anthropic", name="Anthropic", model="claude-3-5", enabled=True, requires_key=True)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = True
        pm.get_api_key.return_value = ""
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("No API key configured for provider 'anthropic'", err_buf.getvalue())

    async def test_run_headless_async_agent_creation_failure(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = None
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("Failed to create agent for provider 'openai'", err_buf.getvalue())

    async def test_run_headless_async_stream_error_event(self):
        agent = MockAgent(steps=[
            ("content", "Starting...", ""),
            ("error", "Rate limit exceeded", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        out_buf = io.StringIO()
        with redirect_stderr(err_buf), redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("Rate limit exceeded", err_buf.getvalue())

    async def test_run_headless_async_stream_exception(self):
        class BrokenAgent:
            model = "m"
            role = "r"

            async def stream_steps(self, prompt: str):
                yield ("content", "Part 1", "")
                raise RuntimeError("Unexpected API crash")

        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = BrokenAgent()
        pm.close = MagicMock()

        args = MagicMock(prompt="hi", provider=None, model=None, role="worker", quiet=False, json=False)
        err_buf = io.StringIO()
        out_buf = io.StringIO()
        with redirect_stderr(err_buf), redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("Unexpected API crash", err_buf.getvalue())

    async def test_run_headless_async_role_not_found(self):
        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="test",
            provider="openai",
            model="gpt-4o",
            role="nonexistent_role_xyz",
            quiet=False,
            json=False,
        )
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 1)
        self.assertIn("Role 'nonexistent_role_xyz' not found", err_buf.getvalue())

    async def test_run_headless_async_apply_role_called(self):
        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="test",
            provider="openai",
            model="gpt-4o",
            role="worker",
            quiet=False,
            json=False,
        )
        with patch("johnston_core.interfaces.cli.commands.run_cmd.apply_role") as mock_apply:
            out_buf = io.StringIO()
            with redirect_stdout(out_buf):
                code = await run_headless_async(args, pm=pm)
            self.assertEqual(code, 0)
            mock_apply.assert_called_once_with(agent, "worker", mode=AgentMode.HEADLESS)

    async def test_run_headless_async_closes_agent(self):
        agent = MockAgent(steps=[("content", "done", "")])
        closed = False

        async def fake_close():
            nonlocal closed
            closed = True

        agent.close = fake_close
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="test",
            provider="openai",
            model="gpt-4o",
            role="worker",
            quiet=False,
            json=False,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)
        self.assertEqual(code, 0)
        self.assertTrue(closed)

    @patch("johnston_core.application.skills.manager.get_skill_manager")
    async def test_run_headless_async_slash_skill_injection(self, mock_get_sm):
        skill = MagicMock()
        skill.name = "caveman"
        skill.location = None
        skill.content = "Be concise."
        sm = MagicMock()
        sm.get_skill.side_effect = lambda n: skill if n == "caveman" else None
        mock_get_sm.return_value = sm

        agent = MockAgent(steps=[("content", "grunt done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="/caveman write poem",
            skills=[],
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=False,
            stream_json=False,
        )
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertIsNotNone(agent.received_prompt)
        self.assertIn('<skill name="caveman">', agent.received_prompt)
        self.assertIn("write poem", agent.received_prompt)
        self.assertIn("[skills] activated: caveman", err_buf.getvalue())

    @patch("johnston_core.application.skills.manager.get_skill_manager")
    async def test_run_headless_async_explicit_skill_flag_json(self, mock_get_sm):
        skill = MagicMock()
        skill.name = "caveman"
        skill.location = None
        skill.content = "Be concise."
        sm = MagicMock()
        sm.get_skill.side_effect = lambda n: skill if n == "caveman" else None
        mock_get_sm.return_value = sm

        agent = MockAgent(steps=[("content", "grunt done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="write poem",
            skills=["caveman"],
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=True,
            stream_json=False,
        )
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertIsNotNone(agent.received_prompt)
        self.assertIn('<skill name="caveman">', agent.received_prompt)
        self.assertNotIn("[skills]", err_buf.getvalue())
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data["skills"], ["caveman"])

    @patch("johnston_core.application.skills.manager.get_skill_manager")
    async def test_run_headless_async_skills_stream_json(self, mock_get_sm):
        skill = MagicMock()
        skill.name = "caveman"
        skill.location = None
        skill.content = "Be concise."
        sm = MagicMock()
        sm.get_skill.side_effect = lambda n: skill if n == "caveman" else None
        mock_get_sm.return_value = sm

        agent = MockAgent(steps=[("content", "grunt done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="write poem",
            skills=["caveman"],
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=False,
            stream_json=True,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out_buf.getvalue().strip().splitlines()]
        self.assertEqual(lines[0]["event"], "skills")
        self.assertEqual(lines[0]["skills"], ["caveman"])

    async def test_run_headless_async_compaction_event(self):
        agent = MockAgent(steps=[
            ("event_divider", "Session Compacted", ""),
            ("content", "resumed after compaction", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="long task", provider=None, model=None, role="worker", quiet=False, json=False, stream_json=False)
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertIn("[compaction] Session Compacted", err_buf.getvalue())
        self.assertIn("compacted", err_buf.getvalue())
        self.assertEqual(out_buf.getvalue(), "resumed after compaction\n")

    async def test_run_headless_async_compaction_json(self):
        agent = MockAgent(steps=[
            ("event_divider", "Session Compacted", ""),
            ("content", "resumed after compaction", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="long task", provider=None, model=None, role="worker", quiet=False, json=True, stream_json=False)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        data = json.loads(out_buf.getvalue())
        self.assertTrue(data.get("compacted"))
        self.assertTrue(data["usage"].get("compacted"))

    async def test_run_headless_async_compaction_stream_json(self):
        agent = MockAgent(steps=[
            ("event_divider", "Session Compacted", ""),
            ("content", "resumed after compaction", ""),
        ])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(prompt="long task", provider=None, model=None, role="worker", quiet=False, json=False, stream_json=True)
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out_buf.getvalue().strip().splitlines()]
        self.assertEqual(lines[0]["event"], "compaction")
        self.assertEqual(lines[0]["title"], "Session Compacted")
        self.assertTrue(lines[-1]["usage"].get("compacted"))

    @patch("johnston_core.infrastructure.mcp.get_mcp_manager")
    async def test_run_headless_async_mcp_warmup_and_shutdown(self, mock_get_mm):
        mock_mm = MagicMock()
        mock_mm.load_servers.return_value = [{"name": "my-mcp"}]
        mock_mm.server_enabled.return_value = True

        async def fake_tools():
            return [{"type": "function", "function": {"name": "tool1"}}, {"type": "function", "function": {"name": "tool2"}}]

        mock_mm.get_active_tools_async = fake_tools
        mock_mm.stop_all_async = MagicMock()

        async def fake_stop():
            pass

        mock_mm.stop_all_async.side_effect = fake_stop
        mock_get_mm.return_value = mock_mm

        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(
            prompt="use mcp",
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=False,
            stream_json=False,
            _test_mcp_warmup=True,
        )
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertIn("[mcp] active: my-mcp (2 tools)", err_buf.getvalue())
        self.assertTrue(mock_mm.stop_all_async.called)

    @patch("johnston_core.infrastructure.mcp.get_mcp_manager")
    async def test_run_headless_async_mcp_json(self, mock_get_mm):
        mock_mm = MagicMock()
        mock_mm.load_servers.return_value = [{"name": "my-mcp"}]
        mock_mm.server_enabled.return_value = True

        async def fake_tools():
            return [{"type": "function", "function": {"name": "tool1"}}]

        mock_mm.get_active_tools_async = fake_tools
        mock_mm.stop_all_async = MagicMock()

        async def fake_stop():
            pass

        mock_mm.stop_all_async.side_effect = fake_stop
        mock_get_mm.return_value = mock_mm

        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(
            prompt="use mcp",
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=True,
            stream_json=False,
            _test_mcp_warmup=True,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data.get("mcp"), {"servers": ["my-mcp"], "tools": 1})

    @patch("johnston_core.infrastructure.mcp.get_mcp_manager")
    async def test_run_headless_async_mcp_stream_json(self, mock_get_mm):
        mock_mm = MagicMock()
        mock_mm.load_servers.return_value = [{"name": "my-mcp"}]
        mock_mm.server_enabled.return_value = True

        async def fake_tools():
            return [{"type": "function", "function": {"name": "tool1"}}]

        mock_mm.get_active_tools_async = fake_tools
        mock_mm.stop_all_async = MagicMock()

        async def fake_stop():
            pass

        mock_mm.stop_all_async.side_effect = fake_stop
        mock_get_mm.return_value = mock_mm

        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent
        pm.close = MagicMock()

        args = MagicMock(
            prompt="use mcp",
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=False,
            stream_json=True,
            _test_mcp_warmup=True,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out_buf.getvalue().strip().splitlines()]
        self.assertEqual(lines[0]["event"], "mcp")
        self.assertEqual(lines[0]["servers"], ["my-mcp"])
        self.assertEqual(lines[0]["tools"], 1)

    async def test_run_headless_async_yolo_mode(self):
        from johnston_core.domain.policies.permission_policy import ExecutionMode
        from johnston_core.permission_manager import PermissionManager

        agent = MockAgent(steps=[("content", "hello", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="create file",
            skills=[],
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=False,
            stream_json=False,
            yolo=True,
            mode=None,
        )
        err_buf = io.StringIO()
        out_buf = io.StringIO()

        observed_mode = None

        original_stream = agent.stream_steps

        async def spy_stream(p):
            nonlocal observed_mode
            observed_mode = PermissionManager.get_instance().execution_mode
            async for s in original_stream(p):
                yield s

        agent.stream_steps = spy_stream

        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(observed_mode, ExecutionMode.YOLO)
        self.assertIn("yolo", err_buf.getvalue())
        # Verify session mode was cleaned up after run
        self.assertIsNone(PermissionManager.get_instance().session_mode)

    async def test_run_headless_async_mode_flag_json(self):
        agent = MockAgent(steps=[("content", "done", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="edit code",
            skills=[],
            provider=None,
            model=None,
            role="worker",
            quiet=False,
            json=True,
            stream_json=False,
            yolo=False,
            mode="edits",
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data.get("mode"), "edits")

    @patch("johnston_core.infrastructure.storage.session_store.SessionStore.get_instance")
    async def test_run_headless_async_resume_and_save(self, mock_get_store):
        mock_store = MagicMock()
        mock_session = MagicMock()
        mock_session.agent_history = [{"role": "user", "content": "prior"}]
        mock_session.messages = []
        mock_session.tokens_input = 10
        mock_session.tokens_output = 5
        mock_session.total_tokens = 15
        mock_session.cost_usd = 0.001
        mock_store.get.return_value = mock_session
        mock_store.list_main_sessions.return_value = [{"id": "sess-123"}]
        mock_get_store.return_value = mock_store

        agent = MockAgent(steps=[("content", "resumed reply", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="next question",
            skills=[],
            provider=None,
            model=None,
            role="worker",
            quiet=True,
            json=False,
            stream_json=False,
            continue_latest=True,
            resume="",
            yolo=False,
            mode=None,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(agent.history, [{"role": "user", "content": "prior"}])
        mock_store.save.assert_called_once_with(mock_session)

    async def test_early_error_json_output(self):
        args = MagicMock(
            prompt="   ",
            json=True,
            stream_json=False,
            quiet=False,
            cwd=None,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args)
        self.assertEqual(code, 1)
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data.get("status"), "error")
        self.assertIn("No prompt provided", data.get("error", ""))

    async def test_early_error_stream_json_output(self):
        args = MagicMock(
            prompt="   ",
            json=False,
            stream_json=True,
            quiet=False,
            cwd=None,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args)
        self.assertEqual(code, 1)
        data = json.loads(out_buf.getvalue())
        self.assertEqual(data.get("event"), "error")
        self.assertIn("No prompt provided", data.get("error", ""))

    async def test_model_override_precedence_over_role(self):
        agent = MockAgent(steps=[("content", "hello", "")])
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pdef = ProviderDef(key="openai", name="OpenAI", model="gpt-4o", enabled=True, requires_key=False)
        pm.load_provider_def.return_value = pdef
        pm.provider_needs_key.return_value = False
        pm.create_agent_for_provider.return_value = agent

        args = MagicMock(
            prompt="hi",
            skills=[],
            provider=None,
            model="override-model-123",
            effort="high",
            role="worker",
            quiet=True,
            json=False,
            stream_json=False,
            continue_latest=False,
            resume=None,
            yolo=False,
            mode=None,
            sandbox=False,
            no_sandbox=True,
        )
        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            code = await run_headless_async(args, pm=pm)

        self.assertEqual(code, 0)
        self.assertEqual(agent.model, "override-model-123")
        self.assertEqual(agent.thinking_effort, "high")


class TestCLIRunSyncWrapper(unittest.TestCase):
    """Unit tests for synchronous run_headless wrapper."""

    @patch("johnston_core.interfaces.cli.commands.run_cmd.run_headless_async")
    def test_run_headless_sync_success(self, mock_async):
        async def fake_run(*args, **kwargs):
            return 0

        mock_async.side_effect = fake_run
        args = MagicMock(prompt="hi")
        code = run_headless(args)
        self.assertEqual(code, 0)

    @patch("johnston_core.interfaces.cli.commands.run_cmd.run_headless_async")
    def test_run_headless_sync_keyboard_interrupt(self, mock_async):
        async def fake_interrupt(*args, **kwargs):
            raise KeyboardInterrupt()

        mock_async.side_effect = fake_interrupt
        args = MagicMock(prompt="hi")
        code = run_headless(args)
        self.assertEqual(code, 130)

    @patch("johnston_core.interfaces.cli.commands.run_cmd.run_headless_async")
    def test_run_headless_sync_generic_exception(self, mock_async):
        async def fake_crash(*args, **kwargs):
            raise ValueError("Fatal crash")

        mock_async.side_effect = fake_crash
        args = MagicMock(prompt="hi")
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            code = run_headless(args)
        self.assertEqual(code, 1)
        self.assertIn("Fatal crash", err_buf.getvalue())

    @patch("johnston_core.interfaces.cli.commands.run_cmd.run_headless_async")
    def test_run_headless_sync_running_loop_fallback(self, mock_async):
        async def fake_run(*args, **kwargs):
            return 0

        mock_async.side_effect = fake_run
        mock_loop = MagicMock()
        mock_loop.is_running.return_value = True

        with patch("asyncio.get_running_loop", return_value=mock_loop):
            args = MagicMock(prompt="hi", debug=False, cwd=None, json=False, stream_json=False)
            code = run_headless(args)
            self.assertEqual(code, 0)

    @patch("johnston_core.interfaces.cli.commands.run_cmd.run_headless", return_value=0)
    def test_entrypoint_main_run_dispatch(self, mock_run_headless):
        with self.assertRaises(SystemExit) as cm:
            main(["run", "hello", "--quiet"])
        self.assertEqual(cm.exception.code, 0)
    def test_format_meta_footer(self):
        footer = format_meta_footer("openai", "gpt-4o", 2.345, 1200, 300, 1500, cost_usd=0.0025, role="worker")
        self.assertIn("openai/gpt-4o", footer)
        self.assertNotIn("worker:", footer)
        self.assertIn("2.35s", footer)
        self.assertIn("127.9 tok/s", footer)
        self.assertIn("in: 1.2k", footer)
        self.assertIn("out: 300", footer)
        self.assertIn("total: 1.5k tok", footer)
        self.assertIn("$0.0025", footer)

        footer_custom = format_meta_footer(
            "opencode",
            "big-pickle",
            10.0,
            1000,
            500,
            1500,
            cost_usd=0.0,
            role="Explorer",
            sandbox=True,
            effort="high",
            compacted=True,
        )
        self.assertIn("explorer: opencode/big-pickle (high)", footer_custom)
        self.assertIn("sandbox", footer_custom)
        self.assertIn("compacted", footer_custom)
        self.assertIn("50.0 tok/s", footer_custom)
        self.assertNotIn("$", footer_custom)

        footer_yolo = format_meta_footer("openai", "gpt-4o", 1.0, 100, 50, 150, mode="yolo")
        self.assertIn("openai/gpt-4o | yolo | 1.00s", footer_yolo)

        footer_edits = format_meta_footer("openai", "gpt-4o", 1.0, 100, 50, 150, mode="edits")
        self.assertIn("openai/gpt-4o | edits | 1.00s", footer_edits)

        footer_review = format_meta_footer("openai", "gpt-4o", 1.0, 100, 50, 150, mode="review")
        self.assertNotIn("review", footer_review)

    @patch("johnston_core.interfaces.cli.commands.run_cmd.run_headless", return_value=0)
    def test_main_run_with_yolo_and_mode_flags(self, mock_run):
        from johnston_core.interfaces.cli.entrypoint import main

        with self.assertRaises(SystemExit) as cm:
            main(["run", "hello", "-y"])
        self.assertEqual(cm.exception.code, 0)
        parsed_args = mock_run.call_args[0][0]
        self.assertTrue(parsed_args.yolo)

        with self.assertRaises(SystemExit) as cm2:
            main(["run", "hello", "--mode", "edits"])
        self.assertEqual(cm2.exception.code, 0)
        parsed_args2 = mock_run.call_args[0][0]
        self.assertEqual(parsed_args2.mode, "edits")


if __name__ == "__main__":
    unittest.main()

