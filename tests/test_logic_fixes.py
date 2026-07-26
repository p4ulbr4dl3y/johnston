import json
import os
import tempfile
import unittest
import unittest.mock
from unittest.mock import AsyncMock, MagicMock, patch

from core.base_provider import BaseAgent
from core.mode_manager import ModeDefinition
from core.subagent_tracker import SubagentTracker
from tools.ask_user import AskUserTool


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

        with patch("core.base_provider.estimate_tokens", side_effect=fake_estimate):
            with patch("core.base_provider.BaseAgent.context_limit", new_callable=unittest.mock.PropertyMock) as mock_limit:
                mock_limit.return_value = 100  # threshold = 75
                with patch.object(agent, "compact_history", new_callable=AsyncMock) as mock_comp:
                    mock_comp.return_value = (True, "compacted")
                    with patch.object(agent.client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
                        mock_create.side_effect = Exception("Stop stream")
                        try:
                            async for _ in agent.stream_steps("trigger"):
                                pass
                        except Exception:
                            pass
                        # history(10) + sys_overhead(100) = 110 > 75 => compaction fires.
                        # Without the fix, history(10) > 75 is False and it never fires.
                        mock_comp.assert_called_once()


class TestImagePayloadPreservation(unittest.IsolatedAsyncioTestCase):
    """base64 image payloads must be optimized only on the API copy, not destroyed in
    self.history — otherwise /rewind and session resume lose image data permanently."""

    async def test_optimize_does_not_mutate_self_history(self):
        import copy

        agent = BaseAgent(api_key="m", model="m", base_url="http://t", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)

        original_content = json.dumps([
            {"type": "text", "text": "screenshot of bug"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,ABCDEF"}},
        ])
        agent.history = [{"role": "tool", "tool_call_id": "tc1", "content": original_content}]

        # Replicate the snapshot stream_steps takes at the start of a turn.
        agent._image_payload_map = {}
        for msg in agent.history:
            if msg.get("role") == "tool" and isinstance(msg.get("content"), str) and '"image_url"' in msg["content"]:
                tid = msg.get("tool_call_id")
                if tid and tid not in agent._image_payload_map:
                    agent._image_payload_map[tid] = msg["content"]

        copy_history = copy.deepcopy(agent.history)
        agent._optimize_history_images(copy_history)

        # The API copy is optimized ...
        self.assertIn("History token optimized", copy_history[0]["content"])
        # ... but self.history still holds the original base64 payload.
        self.assertNotIn("History token optimized", agent.history[0]["content"])
        self.assertEqual(agent.history[0]["content"], original_content)

        # After the API call self.history is rebuilt from the optimized messages list;
        # _restore_image_payloads must put the original payload back.
        agent.history = copy_history + [{"role": "user", "content": "next turn"}]
        agent._restore_image_payloads()
        self.assertEqual(agent.history[0]["content"], original_content)


class TestRuntimeToolPolicy(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_blocks_write_aliases(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        mode_def = ModeDefinition("explore", "Explore", read_only=True)
        err = agent._tool_policy_error("write_file", {"path": "core/example.py"}, mode_def)
        self.assertIsNotNone(err)
        self.assertIn("disabled", err)

    async def test_disallowed_tools_blocks_aliases(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com", system_prompt="s", tools=[])
        self.addAsyncCleanup(agent.close)
        mode_def = ModeDefinition("locked", "Locked", disallowed_tools=["shell"])
        err = agent._tool_policy_error("shell", {"command": "pwd"}, mode_def)
        self.assertEqual(err, "Error: Tool 'shell' is disabled in Locked mode.")


class TestFallbackMetricsMerge(unittest.IsolatedAsyncioTestCase):
    """When the primary provider fails and a fallback provider handles the turn, the
    fallback's token/cost metrics must be merged into the primary agent so the status
    footer and persisted session reflect the real total spent."""

    async def test_fallback_tokens_merged_into_primary(self):
        class FakeFbAgent:
            def __init__(self):
                self.tokens_input = 500
                self.tokens_output = 100
                self.total_tokens = 600
                self.cost_usd = 0.05
                self.history = []
                self.mode = "action"

            async def stream_steps(self, prompt):
                yield ("bot_text", "fallback response", "")

            async def close(self):
                pass

        agent = BaseAgent(
            api_key="m", model="m", base_url="http://t", system_prompt="s",
            tools=[], provider_key="badprov", api_type="openai", fallback_provider="fbprov",
        )
        self.addAsyncCleanup(agent.close)
        fb = FakeFbAgent()

        with patch("core.provider_manager.ProviderManager") as MockPM:
            MockPM.return_value.create_agent_for_provider.return_value = fb
            with patch.object(agent.client.chat.completions, "create", new_callable=AsyncMock) as mock_create:
                mock_create.side_effect = Exception("primary provider down")
                async for _ in agent.stream_steps("hi"):
                    pass

        self.assertEqual(agent.tokens_input, 500)
        self.assertEqual(agent.tokens_output, 100)
        self.assertEqual(agent.total_tokens, 600)
        self.assertAlmostEqual(agent.cost_usd, 0.05)


class TestAskUserUnknownStatus(unittest.IsolatedAsyncioTestCase):
    """An unrecognized screen status must cancel instead of looping forever."""

    async def test_unknown_status_cancels(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        def fake_push(screen, callback=None):
            if callback:
                callback({"status": "unknown_garbage"})

        mock_app.push_screen.side_effect = fake_push
        res = await tool.execute({"questions": [{"question_text": "Q?", "options": ["a"]}]}, app=mock_app)
        self.assertIn("Cancelled by user", res)


class TestSessionManagerPureReader(unittest.TestCase):
    """list_sessions must be a pure reader (no destructive side effects); empty-file
    cleanup is a separate explicit purge_empty_sessions operation."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p1 = patch("core.session_manager.PROJECTS_DIR", self.test_dir)
        self.p2 = patch("core.session_manager.CONFIG_DIR", self.test_dir)
        self.p1.start()
        self.p2.start()
        self.project_path = os.path.join(self.test_dir, "proj")
        os.makedirs(self.project_path, exist_ok=True)
        from core.session_manager import SessionManager
        self.sm = SessionManager(project_path=self.project_path)

    def tearDown(self):
        self.p1.stop()
        self.p2.stop()
        import shutil
        shutil.rmtree(self.test_dir)

    def test_list_sessions_does_not_delete_empty_files(self):
        empty_path = os.path.join(self.sm.sessions_dir, "empty.json")
        with open(empty_path, "w") as f:
            json.dump({"id": "empty", "ui_messages": [], "agent_history": []}, f)

        sid = self.sm.generate_session_id()
        self.sm.save_session(sid, {"id": sid, "ui_messages": [{"type": "user", "text": "real"}]})

        sessions = self.sm.list_sessions()
        self.assertTrue(os.path.exists(empty_path))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], sid)

    def test_purge_empty_sessions_removes_files(self):
        empty_path = os.path.join(self.sm.sessions_dir, "empty.json")
        with open(empty_path, "w") as f:
            json.dump({"id": "empty", "ui_messages": [], "agent_history": []}, f)

        removed = self.sm.purge_empty_sessions()
        self.assertEqual(removed, 1)
        self.assertFalse(os.path.exists(empty_path))


class TestSubagentTrackerStrictMatch(unittest.IsolatedAsyncioTestCase):
    """A vague/non-matching identifier must NOT fall back to the last session — that
    would risk killing or inspecting the wrong subagent."""

    def setUp(self):
        self.tracker = SubagentTracker.get_instance()
        self.tracker.sessions.clear()

    def tearDown(self):
        self.tracker.sessions.clear()

    async def test_no_loose_fallback_for_unknown_id(self):
        self.tracker.create_session("task-1", "Important task", "p1", "general", False)
        self.tracker.create_session("task-2", "Other task", "p2", "general", False)

        # A single letter that previously matched via substring must now return None.
        self.assertIsNone(self.tracker.find_session_by_description_or_id("a"))
        # A totally unknown id must return None, not the last session.
        self.assertIsNone(self.tracker.find_session_by_description_or_id("nonexistent-xyz"))

    async def test_exact_match_still_works(self):
        self.tracker.create_session("task-1", "Important task", "p1", "general", False)
        res = self.tracker.find_session_by_description_or_id("task-1")
        self.assertIsNotNone(res)
        self.assertEqual(res.task_id, "task-1")
        res = self.tracker.find_session_by_description_or_id("Important task")
        self.assertIsNotNone(res)
        self.assertEqual(res.task_id, "task-1")


if __name__ == "__main__":
    unittest.main()
