"""Tests for AgentMode execution contexts (interactive, headless, subagent)."""
import unittest
from unittest.mock import MagicMock

from johnston_core.domain.defaults.tools import NON_INTERACTIVE_EXCLUDED_TOOLS
from johnston_core.domain.policies.role_policy import (
    AgentMode,
    AgentRole,
    RoleScope,
    is_role_scope_compatible,
    role_tool_error,
)
from johnston_core.roles.apply import apply_role
from johnston_core.roles.prompt import apply_prompt
from johnston_core.roles.resolve import resolve_role
from johnston_core.roles.tools import HARDENED_SHELL_DESCRIPTION, apply_role_tools


class TestAgentMode(unittest.TestCase):
    def test_agent_mode_properties(self):
        self.assertTrue(AgentMode.INTERACTIVE.is_interactive)
        self.assertFalse(AgentMode.INTERACTIVE.is_subagent)
        self.assertEqual(AgentMode.INTERACTIVE.target_scope, RoleScope.MAIN)

        self.assertFalse(AgentMode.HEADLESS.is_interactive)
        self.assertFalse(AgentMode.HEADLESS.is_subagent)
        self.assertEqual(AgentMode.HEADLESS.target_scope, RoleScope.MAIN)

        self.assertFalse(AgentMode.SUBAGENT.is_interactive)
        self.assertTrue(AgentMode.SUBAGENT.is_subagent)
        self.assertEqual(AgentMode.SUBAGENT.target_scope, RoleScope.SUBAGENT)

    def test_is_role_scope_compatible(self):
        # any
        self.assertTrue(is_role_scope_compatible("any", AgentMode.INTERACTIVE))
        self.assertTrue(is_role_scope_compatible("any", AgentMode.HEADLESS))
        self.assertTrue(is_role_scope_compatible("any", AgentMode.SUBAGENT))

        # main
        self.assertTrue(is_role_scope_compatible("main", AgentMode.INTERACTIVE))
        self.assertTrue(is_role_scope_compatible("main", AgentMode.HEADLESS))
        self.assertFalse(is_role_scope_compatible("main", AgentMode.SUBAGENT))

        # subagent
        self.assertFalse(is_role_scope_compatible("subagent", AgentMode.INTERACTIVE))
        self.assertFalse(is_role_scope_compatible("subagent", AgentMode.HEADLESS))
        self.assertTrue(is_role_scope_compatible("subagent", AgentMode.SUBAGENT))

        # headless
        self.assertFalse(is_role_scope_compatible("headless", AgentMode.INTERACTIVE))
        self.assertTrue(is_role_scope_compatible("headless", AgentMode.HEADLESS))
        self.assertFalse(is_role_scope_compatible("headless", AgentMode.SUBAGENT))

    def test_role_tool_error_mode_restrictions(self):
        role_def = AgentRole(key="worker")

        for tool in NON_INTERACTIVE_EXCLUDED_TOOLS:
            # Interactive: allowed
            self.assertIsNone(role_tool_error(role_def, tool, mode=AgentMode.INTERACTIVE))

            # Headless: denied
            err_headless = role_tool_error(role_def, tool, mode=AgentMode.HEADLESS)
            self.assertIsNotNone(err_headless)
            self.assertIn("disabled", err_headless.content)

            # Subagent: denied
            err_sub = role_tool_error(role_def, tool, mode=AgentMode.SUBAGENT)
            self.assertIsNotNone(err_sub)
            self.assertIn("disabled", err_sub.content)

    def test_apply_role_tools_headless_hardening(self):
        agent = MagicMock()
        agent.tools = [
            {
                "type": "function",
                "function": {
                    "name": "shell",
                    "description": "Standard shell",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string"},
                            "wait_seconds": {"type": "integer"},
                            "timeout": {"type": "integer"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {"name": "ask_user", "description": "Ask user"},
            },
            {
                "type": "function",
                "function": {"name": "read", "description": "Read file"},
            },
        ]
        role_def = AgentRole(key="worker")

        apply_role_tools(agent, role_def, mode=AgentMode.HEADLESS)

        self.assertFalse(agent.allow_task)
        tool_names = [t["function"]["name"] for t in agent.tools]
        self.assertIn("shell", tool_names)
        self.assertIn("read", tool_names)
        self.assertNotIn("ask_user", tool_names)

        # Check shell tool hardening
        shell_tool = next(t for t in agent.tools if t["function"]["name"] == "shell")
        self.assertEqual(shell_tool["function"]["description"], HARDENED_SHELL_DESCRIPTION)
        params = shell_tool["function"]["parameters"]["properties"]
        self.assertNotIn("wait_seconds", params)
        self.assertIn("timeout", params)

    def test_apply_prompt_modes(self):
        agent = MagicMock()
        role_def = AgentRole(key="worker", prompt="Do worker tasks.")

        # 1. Headless mode
        apply_prompt(agent, role_def, mode=AgentMode.HEADLESS)
        self.assertIn("headless run mode", agent.system_prompt)
        self.assertNotIn("Outcome: completed", agent.system_prompt)
        self.assertNotIn("Use `ask_user` with concrete choices", agent.system_prompt)

        # 2. Interactive mode
        apply_prompt(agent, role_def, mode=AgentMode.INTERACTIVE)
        self.assertIn("Johnston CLI. Solve coding", agent.system_prompt)
        self.assertNotIn("headless run mode", agent.system_prompt)

        # 3. Subagent mode
        apply_prompt(agent, role_def, mode=AgentMode.SUBAGENT)
        self.assertIn("as autonomous subagent", agent.system_prompt)
        self.assertIn("**Outcome**: completed", agent.system_prompt)

    def test_apply_role_headless(self):
        agent = MagicMock()
        agent.tools = [
            {"function": {"name": "read"}},
            {"function": {"name": "ask_user"}},
        ]
        resolved = apply_role(agent, "worker", mode=AgentMode.HEADLESS)
        self.assertEqual(resolved.key, "worker")
        self.assertEqual(agent.mode, AgentMode.HEADLESS)
        self.assertTrue(agent.is_headless)
        self.assertFalse(agent.is_subagent)
        self.assertIn("headless run mode", agent.system_prompt)

    def test_resolve_role_fallback_for_incompatible_mode(self):
        registry = MagicMock()
        subagent_only_role = AgentRole(key="explorer", scope="subagent")
        worker_role = AgentRole(key="worker", scope="any")

        def mock_get(key, project_dir=None):
            if key == "explorer":
                return subagent_only_role
            return worker_role

        registry.get_role.side_effect = mock_get

        # When resolving subagent-only role in HEADLESS mode -> fallback to worker
        resolved = resolve_role(registry, "explorer", mode=AgentMode.HEADLESS)
        self.assertEqual(resolved.key, "worker")

        # In SUBAGENT mode -> keeps explorer
        resolved_sub = resolve_role(registry, "explorer", mode=AgentMode.SUBAGENT)
        self.assertEqual(resolved_sub.key, "explorer")

    def test_tool_context_and_shell_wait_seconds_headless(self):
        import asyncio

        from johnston_core.tools.context import ToolContext
        from johnston_core.tools.shell import ShellTool

        # Headless agent target
        agent = MagicMock()
        agent.is_headless = True
        agent.is_subagent = False

        ctx = ToolContext(agent)
        self.assertTrue(ctx.is_headless)
        self.assertFalse(ctx.is_interactive)
        self.assertFalse(ctx.is_subagent)

        # Execute shell tool with wait_seconds in headless context -> rejected
        tool = ShellTool()
        result = asyncio.run(tool.execute({"command": "echo test", "wait_seconds": 0}, ctx=ctx))
        self.assertIn("wait_seconds", str(result))

    def test_agent_tool_policy_error_honors_mode(self):
        from johnston_core.base_provider.agent import BaseAgent

        class DummyAgent(BaseAgent):
            def _create_client(self, *args, **kwargs):
                return MagicMock()

            def _get_model_name(self):
                return "test"

            async def _run_stream(self, *args, **kwargs):
                if False:
                    yield

        role_def = AgentRole(key="worker")

        # Headless agent
        agent_headless = DummyAgent(provider_key="anthropic", api_key="k")
        agent_headless.mode = AgentMode.HEADLESS
        err_headless = agent_headless._tool_policy_error("invoke_subagent", role_def)
        self.assertIsNotNone(err_headless)
        self.assertIn("disabled for headless mode", err_headless.content)

        # Subagent
        agent_sub = DummyAgent(provider_key="anthropic", api_key="k")
        agent_sub.mode = AgentMode.SUBAGENT
        err_sub = agent_sub._tool_policy_error("kill", role_def)
        self.assertIsNotNone(err_sub)
        self.assertIn("disabled for subagent roles", err_sub.content)

        # Interactive agent
        agent_interactive = DummyAgent(provider_key="anthropic", api_key="k")
        agent_interactive.mode = AgentMode.INTERACTIVE
        err_interactive = agent_interactive._tool_policy_error("invoke_subagent", role_def)
        self.assertIsNone(err_interactive)

    def test_interactive_only_tools_context_guards(self):
        import asyncio

        from johnston_core.tools.ask_user import AskUserTool
        from johnston_core.tools.context import ToolContext
        from johnston_core.tools.invoke_subagent import InvokeSubagentTool
        from johnston_core.tools.kill import KillTool
        from johnston_core.tools.message_subagent import MessageSubagentTool

        tools = [
            (InvokeSubagentTool(), {"task": "t", "title": "tit"}),
            (MessageSubagentTool(), {"id": "sub-1", "message": "msg"}),
            (KillTool(), {"id": "sub-1"}),
            (AskUserTool(), {"questions": [{"question": "q?", "options": [{"label": "opt"}]}]}),
        ]

        # 1. Subagent context
        sub_agent = MagicMock()
        sub_agent.is_subagent = True
        sub_agent.is_headless = False
        sub_ctx = ToolContext(sub_agent)

        for tool_inst, args in tools:
            self.assertTrue(tool_inst.interactive_only)
            res = asyncio.run(tool_inst.execute(args, ctx=sub_ctx))
            self.assertTrue(res.is_error)
            self.assertIn("subagent", res.content.lower())

        # 2. Headless context
        headless_agent = MagicMock()
        headless_agent.is_subagent = False
        headless_agent.is_headless = True
        headless_ctx = ToolContext(headless_agent)

        for tool_inst, args in tools:
            res = asyncio.run(tool_inst.execute(args, ctx=headless_ctx))
            self.assertTrue(res.is_error)
            self.assertIn("headless", res.content.lower())


