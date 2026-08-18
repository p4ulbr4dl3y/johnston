"""Compaction tests for core.base_provider (compaction area).

Split out of the former test_base_provider monolith: compact_history / truncation
behavior, the /compact command, auto-compaction triggering (sys overhead, error
warnings, in-loop), and history-shrink edge cases.
"""
import unittest
import unittest.mock

from core.base_provider import BaseAgent
from tests.core._base_provider_helpers import _MockStream, _text_chunk, _tool_call_chunk, make_agent


class TestCompactionHistory(unittest.IsolatedAsyncioTestCase):
    def test_compact_command_registered(self):
        from widgets.app.dispatch import COMMAND_REGISTRY

        self.assertIn("/compact", COMMAND_REGISTRY)

    async def test_compact_history_short(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        success, msg = await agent.compact_history()
        self.assertFalse(success)
        self.assertIn("too short", msg)

    async def test_compact_history_opencode_template(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "Fix bug in auth.py"},
            {
                "role": "assistant",
                "content": "Checking auth.py",
                "tool_calls": [{"function": {"name": "read", "arguments": "auth.py"}}],
            },
            {"role": "tool", "content": "def login(): return False"},
            {"role": "user", "content": "Change to return True"},
            {"role": "assistant", "content": "Updated auth.py"},
            {"role": "user", "content": "Run tests"},
        ]

        # Mock OpenAI chat completion call
        mock_response = unittest.mock.MagicMock()
        mock_choice = unittest.mock.MagicMock()
        mock_choice.message.content = "## Objective\n- Fix auth.py\n\n## Work State\n### Completed\n- Updated login\n\n## Next Move\n1. Run tests\n\n## Relevant Files\n- auth.py"
        mock_response.choices = [mock_choice]

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            success, msg = await agent.compact_history()

            self.assertTrue(success)
            self.assertIn("compacted successfully", msg)
            self.assertEqual(len(agent.history), 4)  # 1 summary + 3 tail messages starting at user turn
            self.assertIn("<conversation-checkpoint>", agent.history[0]["content"])
            self.assertIn("## Objective", agent.history[0]["content"])
            self.assertIn("auth.py", agent.history[0]["content"])

    async def test_compact_history_drops_empty_tool_content(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        # A tool message with empty content serializes to a user message with
        # empty content, which OpenAI/DeepSeek reject with 400. It must be dropped.
        agent.history = [
            {"role": "user", "content": "Run the build"},
            {"role": "assistant", "content": "Running"},
            {"role": "tool", "content": ""},
            {"role": "user", "content": "Keep going"},
            {"role": "assistant", "content": "Done"},
            {"role": "user", "content": "Final check"},
        ]

        mock_response = unittest.mock.MagicMock()
        mock_choice = unittest.mock.MagicMock()
        mock_choice.message.content = "## Objective\n- Build\n\n## Next Move\n1. Continue"
        mock_response.choices = [mock_choice]

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            success, msg = await agent.compact_history()
            self.assertTrue(success)
            # The empty tool message must not produce an empty user message.
            self.assertNotIn(
                {"role": "user", "content": ""},
                agent.history,
            )

    async def test_compact_history_bounds_long_in_turn_tool_cascade(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)

        # Simulate 1 user message followed by 50 tool execution steps within the same turn
        history = [{"role": "user", "content": "Fix all 50 issues"}]
        for i in range(25):
            tc_id = f"call_{i}"
            history.append({
                "role": "assistant",
                "content": f"Step {i}",
                "tool_calls": [{"id": tc_id, "type": "function", "function": {"name": "edit", "arguments": "{}"}}],
            })
            history.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "name": "edit",
                "content": f"File {i} edited successfully with lots of diff text " * 10,
            })
        agent.history = history
        self.assertEqual(len(agent.history), 51)

        mock_response = unittest.mock.MagicMock()
        mock_choice = unittest.mock.MagicMock()
        mock_choice.message.content = (
            "## Objective\n- Fix 50 issues\n\n"
            "## Key Decisions & User Constraints\n- (none)\n\n"
            "## Work State\n### Completed\n- Fixed 25 files\n\n"
            "## Next Move\n1. Run pytest\n\n"
            "## Relevant Files & Context\n- All edited files"
        )
        mock_response.choices = [mock_choice]

        with unittest.mock.patch.object(
            agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
        ) as mock_create:
            mock_create.return_value = mock_response
            success, msg = await agent.compact_history()

            self.assertTrue(success)
            self.assertIn("compacted successfully", msg)
            # The 50-step cascade must be compacted down to checkpoint + bounded recent tail (<= 5 messages)
            self.assertLessEqual(len(agent.history), 5)
            self.assertIn("<conversation-checkpoint>", agent.history[0]["content"])
            self.assertIn("## Key Decisions & User Constraints", agent.history[0]["content"])
            self.assertIn("## Relevant Files & Context", agent.history[0]["content"])

    async def test_auto_compaction_trigger(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
            {"role": "user", "content": "e" * 200},
        ]
        compacted = False

        async def mock_compact():
            nonlocal compacted
            compacted = True
            return True, "compacted"

        with unittest.mock.patch(
            "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
        ) as mock_limit:
            mock_limit.return_value = 100
            with unittest.mock.patch.object(
                agent, "compact_history", new_callable=unittest.mock.AsyncMock
            ) as mock_comp:
                mock_comp.return_value = (True, "compacted")
                with unittest.mock.patch.object(
                    agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                ) as mock_create:
                    mock_create.side_effect = Exception("Stop stream")
                    try:
                        async for _ in agent.stream_steps("trigger"):
                            pass
                    except Exception:
                        pass
                    mock_comp.assert_called_once()

    def test_truncate_history_to_user_message(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        agent.history = [
            {"role": "user", "content": "Msg 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "Msg 1"},
            {"role": "assistant", "content": "Resp 1"},
            {"role": "user", "content": "Msg 2"},
            {"role": "assistant", "content": "Resp 2"},
        ]

        # Truncate to index 1 (keep Msg 0 and Resp 0, drop Msg 1 and later)
        agent.truncate_history_to_user_message(1)
        self.assertEqual(len(agent.history), 2)
        self.assertEqual(agent.history[0]["content"], "Msg 0")
        self.assertEqual(agent.history[1]["content"], "Resp 0")

        # Truncate to index 0 (clears all)
        agent.truncate_history_to_user_message(0)
        self.assertEqual(len(agent.history), 0)

    def test_truncate_skips_checkpoint_and_interruption_notes(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        agent.history = [
            {"role": "user", "content": "<conversation-checkpoint>\n<summary>earlier work</summary>\n</conversation-checkpoint>"},
            {"role": "user", "content": "Tail 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "[System Note: Response interrupted by user]"},
            {"role": "user", "content": "Tail 1"},
            {"role": "assistant", "content": "Resp 1"},
        ]

        # History has only two real user turns (checkpoint + interruption note
        # are not user turns). Truncate to the 2nd real user turn -> keep Tail 0.
        agent.truncate_history_to_user_message(1)
        contents = [m["content"] for m in agent.history]
        self.assertEqual(contents, ["<conversation-checkpoint>\n<summary>earlier work</summary>\n</conversation-checkpoint>", "Tail 0", "Resp 0"])

        # Truncate to the 1st real user turn -> drops the checkpoint too.
        agent.truncate_history_to_user_message(0)
        self.assertEqual(agent.history, [])

    def test_truncate_clears_when_user_turn_is_compacted(self):
        agent = BaseAgent(
            api_key="test", model="test-model", base_url="http://test", system_prompt="test", provider_key="test_prov"
        )
        agent.history = [
            {"role": "user", "content": "<conversation-checkpoint>\n<summary>earlier work</summary>\n</conversation-checkpoint>"},
            {"role": "user", "content": "Tail 0"},
            {"role": "assistant", "content": "Resp 0"},
        ]

        # UI shows 3 user turns, but only 1 survived in history: requesting a
        # rollback to the compacted region must clear history so the model
        # cannot remember rolled-back turns.
        agent.truncate_history_to_user_message(2)
        self.assertEqual(agent.history, [])


class TestAutoCompactionSysOverhead(unittest.IsolatedAsyncioTestCase):
    """The compaction threshold must count system prompt + tool schema overhead, not
    history alone — otherwise a large system prompt can overflow the context window
    before history ever reaches the 75% threshold."""

    async def test_compaction_triggers_when_sys_overhead_exceeds_threshold(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        agent.history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]

        def fake_estimate(val):
            if isinstance(val, str):
                return 100  # system prompt
            if isinstance(val, list):
                first = val[0] if val else None
                if isinstance(first, dict) and first.get("type") == "function":
                    return 0  # tools schema
                return 10  # history
            return 0

        with unittest.mock.patch("core.base_provider.agent.estimate_tokens", side_effect=fake_estimate):
            with unittest.mock.patch(
                "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
            ) as mock_limit:
                mock_limit.return_value = 100  # threshold = 75
                with unittest.mock.patch.object(
                    agent, "compact_history", new_callable=unittest.mock.AsyncMock
                ) as mock_comp:
                    mock_comp.return_value = (True, "compacted")
                    with unittest.mock.patch.object(
                        agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                    ) as mock_create:
                        mock_create.side_effect = Exception("Stop stream")
                        try:
                            async for _ in agent.stream_steps("trigger"):
                                pass
                        except Exception:
                            pass
                        mock_comp.assert_called_once()


class TestCompactionStreamEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Auto-compaction behavior inside the stream_steps loop."""

    def _make_agent(self, **kwargs):
        agent = make_agent(**kwargs)
        self.addAsyncCleanup(agent.close)
        return agent

    async def test_auto_compaction_error_yields_warning(self):
        agent = self._make_agent()
        agent.history = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
            {"role": "assistant", "content": "d"},
            {"role": "user", "content": "e"},
        ]

        def fake_estimate(val):
            if isinstance(val, str):
                return 100
            if isinstance(val, list):
                first = val[0] if val else None
                if isinstance(first, dict) and first.get("type") == "function":
                    return 0
                return 10
            return 0

        with unittest.mock.patch("core.base_provider.agent.estimate_tokens", side_effect=fake_estimate):
            with unittest.mock.patch(
                "core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock
            ) as mock_limit:
                mock_limit.return_value = 100  # threshold = 75
                with unittest.mock.patch.object(
                    agent, "compact_history", new_callable=unittest.mock.AsyncMock
                ) as mock_comp:
                    mock_comp.side_effect = Exception("ctx overflow")
                    with unittest.mock.patch.object(
                        agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
                    ) as mock_create:
                        mock_create.side_effect = Exception("Stop stream")
                        events = []
                        try:
                            async for evt in agent.stream_steps("trigger"):
                                events.append(evt)
                        except Exception:
                            pass

        warnings = [e for e in events if e[0] == "thinking" and "Auto-compaction warning" in e[1]]
        self.assertEqual(len(warnings), 1)
        self.assertIn("ctx overflow", warnings[0][1])

    async def test_compaction_in_loop_after_tool_turn(self):
        agent = self._make_agent()

        async def fake_compact(messages, sys_overhead, threshold):
            return (messages, True)

        first = _MockStream([_tool_call_chunk(0, "tc_1", "read", '{"path": "a.txt"}')])
        second = _MockStream([_text_chunk("ok")])
        with unittest.mock.patch.object(agent, "_compact_messages_if_needed", side_effect=fake_compact):
            with unittest.mock.patch.object(
                agent.client.chat.completions, "create", new_callable=unittest.mock.AsyncMock
            ) as mock_create:
                mock_create.side_effect = [first, second]
                agent.tool_executor = unittest.mock.AsyncMock(return_value="tool ok")
                events = []
                async for evt in agent.stream_steps("run tool"):
                    events.append(evt)

        notices = [e for e in events if e[0] == "thinking" and "Context budget reached" in e[1]]
        dividers = [e for e in events if e[0] == "event_divider" and e[1] == "Session Compacted"]
        self.assertEqual(len(notices), 1)
        self.assertEqual(len(dividers), 1)
        self.assertEqual(events[-1], ("bot_text", "ok", ""))
