import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from core.infrastructure.tasks.manager import TaskManager
from widgets.app.dispatch import COMMAND_REGISTRY, handle_slash_command
from widgets.commands import (
    BaseCommand,
    CompactCommand,
    ModelsCommand,
    PermissionsCommand,
    ProvidersCommand,
    QuestionsCommand,
    ResumeCommand,
    RewindCommand,
    SkillsCommand,
    SubagentsCommand,
    ThinkingEffortCommand,
)
from widgets.presentation.widgets.chat_container import ChatView


class MockAgent:
    def __init__(self, role="action"):
        self.role = role
        self.compact_called = False
        self.history = []
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0

    async def compact_history(self):
        self.compact_called = True
        return True, "History compacted"

    def clear_history(self):
        self.history = []
        self.role = "worker"


class MockDivider:
    def __init__(self, title):
        self.divider_title = title

    def update_title(self, title):
        self.divider_title = title


class MockChatView:
    def __init__(self, children=None):
        self.children = children or []
        self.dividers = []
        self.user_messages = []

    async def add_user_message(self, text=""):
        self.user_messages.append(text)

    async def add_bot_message(self):
        msg = MockBotMessage("")
        self.children.append(msg)
        return msg

    async def add_event_divider(self, text="Session Compacted"):
        d = MockDivider(text)
        self.dividers.append(d)
        return d


class MockBotMessage:
    def __init__(self, content):
        self.content = content


class MockApp:
    def __init__(self, agent=None):
        self.agent = agent or MockAgent()
        self.role = self.agent.role
        self.notified = []
        self.status_refreshed = False
        self.ai_prompts = []
        self.ai_kwargs = []
        self.chat_view = MockChatView()
        self.task_manager = TaskManager()

    def notify(self, msg: str, severity: str = "info"):
        self.notified.append((msg, severity))

    def refresh_status_footer(self):
        self.status_refreshed = True

    def save_current_session(self):
        pass

    def generate_ai_response(self, prompt: str, show_in_ui: bool = True, **kwargs):
        self.ai_prompts.append((prompt, show_in_ui))
        if hasattr(self, "ai_kwargs"):
            self.ai_kwargs.append(kwargs)

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False, **kwargs):
        self.ai_prompts.append((prompt, show_in_ui))
        if hasattr(self, "ai_kwargs"):
            self.ai_kwargs.append(kwargs)

    def push_screen(self, screen, callback=None):
        self.pushed_screen = screen
        if callback:
            callback("Demo finished")

    def query_one(self, target, default=None):
        if target == ChatView or target == "#chat-view":
            return self.chat_view
        return None


class TestCommands(unittest.IsolatedAsyncioTestCase):
    async def test_homoglyph_normalization_and_routing(self):
        app = MockApp()
        # Cyrillic letter 'с' (c) in /mсp -> normalized to /mcp
        cyrillic_mcp = "/mсp"
        handled = await handle_slash_command(app, cyrillic_mcp)
        self.assertTrue(handled)

    async def test_homoglyph_parts_updated(self):
        app = MockApp()
        # Cyrillic letter 'с' (c) in /cоmpact -> normalized to /compact
        cyrillic_cmd = "/cоmpact"
        handled = await handle_slash_command(app, cyrillic_cmd)
        self.assertTrue(handled)
        self.assertTrue(app.agent.compact_called)

    async def test_rewind_command_selected_idx_zero(self):
        from widgets.commands import RewindCommand

        app = MockApp()
        app.agent.history = [{"role": "user", "content": "First message"}]
        app.agent.tokens_input = 4000
        app.agent.tokens_output = 3000
        app.agent.tokens_cache_read = 2000
        app.agent.last_context_tokens = 9000
        app.agent.total_tokens = 7000
        app.agent.cost_usd = 0.12
        app.chat_view.get_user_messages = lambda: [(0, "First message")]
        rolled_back_target = []
        app.chat_view.rollback_to = lambda target_idx: rolled_back_target.append(target_idx)

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: setattr(self, "text", txt),
                "text": "First message",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        # Simulate selecting user message at index 0 in on_rewind_selected
        async def simulate_on_rewind_selected(screen, callback):
            await callback(0)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        self.assertEqual(rolled_back_target, [-1])
        self.assertEqual(mock_input.text, "First message")
        self.assertEqual(app.agent.history, [])
        self.assertEqual(app.agent.tokens_input, 0)
        self.assertEqual(app.agent.tokens_output, 0)
        self.assertEqual(app.agent.tokens_cache_read, 0)
        self.assertEqual(app.agent.last_context_tokens, 0)
        self.assertEqual(app.agent.total_tokens, 0)
        self.assertEqual(app.agent.cost_usd, 0.0)
        self.assertTrue(app.status_refreshed)
        self.assertFalse(getattr(app, "is_generating", False))

    async def test_rewind_command_clears_queue_and_resets_generating(self):
        from widgets.commands import RewindCommand

        app = MockApp()
        app.is_generating = True
        app.message_queue = [("Queued msg", True)]
        app.agent.history = [{"role": "user", "content": "First"}]
        app.chat_view.get_user_messages = lambda: [(0, "First")]
        app.chat_view.rollback_to = lambda idx: None

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: None,
                "text": "First",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        async def simulate_on_rewind_selected(screen, callback):
            await callback(0)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        self.assertFalse(app.is_generating)
        self.assertEqual(app.message_queue, [])

    async def test_rewind_command_partial_history_preserved(self):
        from widgets.commands import RewindCommand

        app = MockApp()
        app.agent.history = [
            {"role": "user", "content": "Msg 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "Msg 1"},
            {"role": "assistant", "content": "Resp 1"},
        ]
        called_truncate = []
        app.agent.truncate_history_to_user_message = lambda idx: (
            called_truncate.append(idx),
            setattr(app.agent, "history", app.agent.history[:2]),
        )
        app.chat_view.get_user_messages = lambda: [(0, "Msg 0"), (2, "Msg 1")]
        rolled_back_target = []
        app.chat_view.rollback_to = lambda target_idx: rolled_back_target.append(target_idx)

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: setattr(self, "text", txt),
                "text": "Msg 1",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        async def simulate_on_rewind_selected(screen, callback):
            await callback(2)  # child_idx of Msg 1 (seq_idx = 1)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        self.assertEqual(rolled_back_target, [1])  # selected_idx - 1 = 1
        self.assertEqual(called_truncate, [1])  # seq_idx = 1
        self.assertEqual(len(app.agent.history), 2)
        self.assertEqual(app.agent.history[0]["content"], "Msg 0")

    async def test_rewind_command_truncates_store_transcript(self):
        from unittest.mock import MagicMock

        from widgets.commands import RewindCommand

        app = MockApp()
        app.current_session_id = "sess-a"
        app.sm = MagicMock()
        app.sm.project_path = None
        session = MagicMock()
        session.messages = [
            {"type": "user", "text": "First", "show_in_ui": True},
            {"type": "bot", "text": "Resp 0"},
            {"type": "user", "text": "[System Notification]: bg shell done", "show_in_ui": False},
            {"type": "user", "text": "Second", "show_in_ui": True},
            {"type": "bot", "text": "Resp 1"},
        ]
        app.sm.get.return_value = session
        app.agent.history = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "Second"},
            {"role": "assistant", "content": "Resp 1"},
        ]
        app.agent.truncate_history_to_user_message = lambda idx: setattr(app.agent, "history", [])
        app.chat_view.get_user_messages = lambda: [(0, "First"), (3, "Second")]
        rolled_back_target = []
        app.chat_view.rollback_to = lambda target_idx: rolled_back_target.append(target_idx)

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: setattr(self, "text", txt),
                "text": "",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        async def simulate_on_rewind_selected(screen, callback):
            await callback(3)  # rewind to "Second" (seq_idx = 1)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        # Transcript keeps events up to (but excluding) the selected turn; the
        # hidden notification user event predates the selection and survives.
        self.assertEqual(
            session.messages,
            [
                {"type": "user", "text": "First", "show_in_ui": True},
                {"type": "bot", "text": "Resp 0"},
                {"type": "user", "text": "[System Notification]: bg shell done", "show_in_ui": False},
            ],
        )

    async def test_rewind_command_kills_tasks_and_cancels_subagents(self):
        from unittest.mock import MagicMock

        from core.infrastructure.tasks.shell_task import ShellTask
        from widgets.commands import RewindCommand

        app = MockApp()
        app.current_session_id = "sess-a"
        app.sm = MagicMock()
        app.sm.project_path = None

        # Background shell task survives rewind unless killed.
        bg_task = ShellTask("t-bg", "sleep 100", None)
        bg_task.is_background = True
        app.task_manager.register(bg_task)

        # Running subagent session that must be cancelled.
        subagent = MagicMock()
        subagent.status = "running"
        subagent.async_task = MagicMock()
        subagent.async_task.done.return_value = False
        app.sm.children.return_value = [subagent]
        app.sm.save = MagicMock()

        session = MagicMock()
        session.messages = [{"type": "user", "text": "First", "show_in_ui": True}]
        app.sm.get.return_value = session
        app.agent.history = [{"role": "user", "content": "First"}]
        app.agent.truncate_history_to_user_message = lambda idx: None
        app.chat_view.get_user_messages = lambda: [(0, "First")]
        app.chat_view.rollback_to = lambda idx: None

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: None,
                "text": "",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        async def simulate_on_rewind_selected(screen, callback):
            await callback(0)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        self.assertFalse(bg_task.is_running)
        subagent.async_task.cancel.assert_called_once()
        subagent.finish.assert_called_once()

    async def test_rewind_awaits_generation_worker_before_rollback(self):
        from widgets.commands import RewindCommand

        class FakeWorker:
            """Minimal Textual-Worker stand-in: cleanup runs inside wait()."""

            def __init__(self, order):
                self.order = order
                self.is_running = True
                self.is_finished = False

            def cancel(self):
                self._cancelled = True

            async def wait(self):
                # Simulate the engine interruption teardown finishing before
                # the rollback applies.
                self.order.append("worker-wait")
                self.is_running = False
                self.is_finished = True

        app = MockApp()
        app.is_generating = True
        order = []
        app.workers = [FakeWorker(order)]
        app.agent.history = [{"role": "user", "content": "First"}]
        app.chat_view.get_user_messages = lambda: [(0, "First")]
        app.chat_view.rollback_to = lambda idx: order.append("rollback")

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: None,
                "text": "",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        async def simulate_on_rewind_selected(screen, callback):
            await callback(0)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        # The in-flight generation must fully settle before history/UI rollback
        # touches state, so the interruption teardown cannot re-pollute it.
        self.assertEqual(order, ["worker-wait", "rollback"])

    async def test_rewind_compacted_region_clears_history(self):
        from unittest.mock import MagicMock

        from widgets.commands import RewindCommand

        app = MockApp()
        app.current_session_id = "sess-a"
        app.sm = MagicMock()
        app.sm.project_path = None

        session = MagicMock()
        session.messages = [
            {"type": "user", "text": "A", "show_in_ui": True},
            {"type": "user", "text": "B", "show_in_ui": True},
            {"type": "event_divider"},
            {"type": "user", "text": "Tail 0", "show_in_ui": True},
            {"type": "bot", "text": "Resp"},
        ]
        app.sm.get.return_value = session
        # Compacted history: checkpoint replaced A+B; only Tail 0 survived.
        app.agent.history = [
            {"role": "user", "content": "<conversation-checkpoint>\n<summary>early</summary>\n</conversation-checkpoint>"},
            {"role": "user", "content": "Tail 0"},
            {"role": "assistant", "content": "Resp"},
        ]
        app.chat_view.get_user_messages = lambda: [(0, "A"), (1, "B"), (3, "Tail 0")]
        app.chat_view.rollback_to = lambda idx: None

        mock_input = type(
            "MockInput",
            (),
            {
                "load_text": lambda self, txt: None,
                "text": "",
                "move_cursor": lambda self, pos: None,
                "focus": lambda self: None,
            },
        )()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()

        async def simulate_on_rewind_selected(screen, callback):
            # Select "B" — a turn inside the compacted region.
            await callback(1)

        app.push_screen = simulate_on_rewind_selected
        await cmd.execute(app)

        # The model must not remember turns that were rolled back: history is
        # cleared because the selected turn predates the checkpoint.
        self.assertEqual(app.agent.history, [])
        # Transcript: everything from "B" onward (incl. divider + tail) drops.
        self.assertEqual(session.messages, [{"type": "user", "text": "A", "show_in_ui": True}])

    async def test_unknown_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/unknowncommand123")
        self.assertFalse(handled)

    async def test_compact_command(self):
        class DetailedMockAgent(MockAgent):
            async def compact_history(self):
                self.compact_called = True
                return True, "History compacted successfully (12k → 2k tokens)"

        agent = DetailedMockAgent()
        app = MockApp(agent=agent)
        handled = await handle_slash_command(app, "/compact")
        self.assertTrue(handled)
        self.assertTrue(agent.compact_called)
        self.assertEqual(len(app.chat_view.dividers), 1)
        self.assertEqual(app.chat_view.dividers[0].divider_title, "Session Compacted (12k → 2k tokens)")
        self.assertFalse(getattr(app, "is_generating", False))

    async def test_compact_command_queues_and_drains_input(self):
        class QueuingMockAgent(MockAgent):
            def __init__(self, app_ref):
                super().__init__()
                self.app_ref = app_ref

            async def compact_history(self):
                self.compact_called = True
                # Simulate user sending input during compact_history
                self.app_ref.message_queue.append(("Queued prompt during compact", True))
                return True, "History compacted"

        app = MockApp()
        agent = QueuingMockAgent(app)
        app.agent = agent
        app.message_queue = []
        triggered = []

        def mock_trigger(prompt, show_in_ui=True, **kwargs):
            triggered.append((prompt, show_in_ui))

        app.trigger_ai_response = mock_trigger

        handled = await handle_slash_command(app, "/compact")
        self.assertTrue(handled)
        self.assertTrue(agent.compact_called)
        self.assertFalse(app.is_generating)
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0], ("Queued prompt during compact", True))
        self.assertEqual(len(app.message_queue), 0)

    async def test_compact_command_cancellation_updates_divider(self):
        import asyncio

        class CancellingMockAgent(MockAgent):
            async def compact_history(self):
                raise asyncio.CancelledError()

        agent = CancellingMockAgent()
        app = MockApp(agent=agent)
        with self.assertRaises(asyncio.CancelledError):
            await handle_slash_command(app, "/compact")

        self.assertEqual(len(app.chat_view.dividers), 1)
        self.assertEqual(app.chat_view.dividers[0].divider_title, "Compaction Cancelled")

    async def test_johnston_guide_skill_slash_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/johnston-guide")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        prompt, show_in_ui = app.ai_prompts[0]
        self.assertTrue(show_in_ui)
        self.assertEqual(app.ai_kwargs[0].get("display_text"), "/johnston-guide")
        self.assertIn('<SKILL path=', prompt)

    async def test_multiple_skills_command(self):
        from unittest.mock import patch

        from core.application.skills.manager import Skill, SkillScope

        app = MockApp()
        skill_a = Skill(name="foo", description="Foo", location="/tmp/foo/SKILL.md", content="Foo body", scope=SkillScope.GLOBAL, hidden=False)
        skill_b = Skill(name="bar", description="Bar", location="/tmp/bar/SKILL.md", content="Bar body", scope=SkillScope.GLOBAL, hidden=False)
        with patch("core.application.skills.manager.SkillManager.get_skill", side_effect=lambda n: {"foo": skill_a, "bar": skill_b}.get(n)):
            handled = await handle_slash_command(app, "/foo /bar analyze project")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        prompt, show_in_ui = app.ai_prompts[0]
        self.assertTrue(show_in_ui)
        self.assertEqual(app.ai_kwargs[0].get("display_text"), "/foo /bar analyze project")
        self.assertIn('<SKILL path=', prompt)
        self.assertIn("User request: analyze project", prompt)

    async def test_models_command_non_vision_warning(self):
        from widgets.commands import ModelsCommand

        test_model_name = f"test-text-only-{int(time.time() * 1000)}"

        class MockPM:
            async def fetch_models_grouped(self):
                return {"custom": {"name": "Custom", "models": [test_model_name]}}

            def get_active_provider_key(self):
                return "custom"

            def set_provider_model(self, p, m):
                pass

            def set_active_provider_key(self, p):
                pass

            def create_active_agent(self):
                return MockAgent()

        app = MockApp()
        app.pm = MockPM()
        cmd = ModelsCommand()

        pushed_screens = []

        def simulate_push_screen(screen, callback=None):
            pushed_screens.append(screen)
            if callback:
                callback(("custom", test_model_name))

        app.push_screen = simulate_push_screen
        app.query_one = lambda target, default=None: type("MockInput", (), {"focus": lambda self: None})()

        await cmd.execute(app)
        self.assertEqual(len(pushed_screens), 1)

    async def test_models_command_preserves_mode_when_switching_provider(self):
        from widgets.commands import ModelsCommand

        class MockPM:
            def __init__(self):
                self.active_provider = "old"
                self.saved = []

            async def fetch_models_grouped(self):
                return {
                    "old": {"name": "Old", "models": ["old-model"]},
                    "new": {"name": "New", "models": ["new-model"]},
                }

            def get_active_provider_key(self):
                return self.active_provider

            def set_active_provider_key(self, provider):
                self.active_provider = provider

            def set_provider_model(self, provider, model):
                self.saved.append((provider, model))

            def create_active_agent(self):
                return MockAgent(role="action")

            def recreate_active_agent(self, app, provider_key=None):
                if provider_key:
                    self.set_active_provider_key(provider_key)
                app.agent = MockAgent(role=app.role)
                app.agent.app = app

        app = MockApp(agent=MockAgent(role="explorer"))
        app.role = "explorer"
        app.pm = MockPM()
        app.query_one = lambda target, default=None: type("Input", (), {"focus": lambda self: None})()
        app.push_screen = lambda screen, callback=None: callback(("new", "new-model")) if callback else None

        await ModelsCommand().execute(app)

        self.assertEqual(app.pm.active_provider, "new")
        self.assertEqual(app.agent.role, "explorer")
        self.assertEqual(app.role, "explorer")
        self.assertEqual(app.pm.saved, [("new", "new-model")])

    async def test_providers_command_preserves_role_when_connecting_provider(self):
        from widgets.commands import ProvidersCommand

        class MockPM:
            def __init__(self):
                self.active_provider = "old"
                self.saved_key = None

            def load_providers(self, include_disabled=False):
                return {
                    "old": {"key": "old", "name": "Old"},
                    "new": {"key": "new", "name": "New"},
                }

            def get_active_provider_key(self):
                return self.active_provider

            def get_api_key(self, provider):
                return ""

            def get_disabled_providers(self):
                return ["new"]

            def set_provider_api_key(self, provider, api_key):
                self.saved_key = (provider, api_key)

            def set_provider_disabled(self, provider, disabled):
                self.disabled = (provider, disabled)

            def set_active_provider_key(self, provider):
                self.active_provider = provider

            def create_active_agent(self):
                return MockAgent(role="action")

            def recreate_active_agent(self, app, provider_key=None):
                if provider_key:
                    self.set_active_provider_key(provider_key)
                app.agent = MockAgent(role=app.role)
                app.agent.app = app

        app = MockApp(agent=MockAgent(role="explorer"))
        app.role = "explorer"
        app.pm = MockPM()

        seen_provider_screen = False

        def push_screen(screen, callback=None):
            nonlocal seen_provider_screen
            if callback and screen.__class__.__name__ == "ProvidersScreen":
                if not seen_provider_screen:
                    seen_provider_screen = True
                    callback("new")
            elif callback and screen.__class__.__name__ == "ApiKeyInputScreen":
                callback("secret")

        app.push_screen = push_screen

        await ProvidersCommand().execute(app)

        self.assertEqual(app.pm.active_provider, "new")
        self.assertEqual(app.pm.saved_key, ("new", "secret"))
        self.assertEqual(app.agent.role, "explorer")
        self.assertEqual(app.role, "explorer")

    async def test_registry_contains_all_commands(self):
        self.assertIn("/compact", COMMAND_REGISTRY)
        self.assertIn("/help", COMMAND_REGISTRY)
        self.assertIn("/connect", COMMAND_REGISTRY)

    async def test_alias_suggestions_formatting(self):
        from widgets.app.command_provider import get_all_command_suggestions

        commands_dict = dict(await get_all_command_suggestions())
        self.assertIn("/providers", commands_dict)
        self.assertIn("/connect", commands_dict)
        self.assertEqual(commands_dict["/connect"], "Alias for /providers")
        self.assertEqual(commands_dict["/h"], "Alias for /help")
        self.assertEqual(commands_dict["/clear"], "Alias for /new")
        self.assertEqual(commands_dict["/undo"], "Alias for /rewind")
        self.assertEqual(commands_dict["/model"], "Alias for /models")
        self.assertIn("Manage AI providers", commands_dict["/providers"])

    async def test_johnston_guide_skill_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/johnston-guide")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        self.assertIn("johnston-guide", app.ai_prompts[0][0])

    async def test_new_command_clears_background_tasks(self):
        from unittest.mock import AsyncMock, MagicMock

        from core.infrastructure.tasks.shell_task import ShellTask
        from widgets.commands import NewCommand

        app = MockApp()
        app.message_queue = MagicMock()
        app.sm = MagicMock()
        app.sm.generate_session_id.return_value = "new-id"
        mock_chat = MagicMock()
        mock_chat.remove_children = AsyncMock()
        app.query_one = MagicMock(return_value=mock_chat)
        t1 = ShellTask("t1", "echo 1", None)
        app.task_manager.register(t1)
        cmd = NewCommand()
        await cmd.execute(app)
        self.assertFalse(t1.is_running)

    async def test_new_command_resets_role(self):
        from unittest.mock import AsyncMock, MagicMock

        from widgets.commands import NewCommand

        app = MockApp()
        app.message_queue = MagicMock()
        app.sm = MagicMock()
        app.sm.generate_session_id.return_value = "new-id"
        mock_chat = MagicMock()
        mock_chat.remove_children = AsyncMock()
        app.query_one = MagicMock(return_value=mock_chat)
        app.agent.role = "explorer"
        app.role = "explorer"

        cmd = NewCommand()
        await cmd.execute(app)

        self.assertEqual(app.agent.role, "worker")
        self.assertEqual(app.role, "worker")

    async def test_subagents_command_no_subagents(self):
        from unittest.mock import MagicMock

        from widgets.commands import SubagentsCommand

        app = MockApp()
        app.current_session_id = "sess-a"
        app.notify = MagicMock()
        app.push_screen = MagicMock()
        app.sm = MagicMock()
        app.sm.children.return_value = []

        cmd = SubagentsCommand()
        await cmd.execute(app)

        # No subagents for current session -> toast, no screen
        app.notify.assert_called_once_with("No active subagents", severity="warning")
        app.push_screen.assert_not_called()

    async def test_subagents_command_with_subagents(self):
        from unittest.mock import MagicMock

        from widgets.commands import SubagentsCommand

        app = MockApp()
        app.notify = MagicMock()
        app.push_screen = MagicMock()
        app.sm = MagicMock()
        app.sm.children.return_value = [MagicMock()]

        cmd = SubagentsCommand()
        await cmd.execute(app)
        app.notify.assert_not_called()
        app.push_screen.assert_called_once()

    async def test_shell_command_no_tasks(self):
        from unittest.mock import MagicMock

        from widgets.commands import ShellTasksCommand

        app = MockApp()
        app.current_session_id = "sess-a"
        app.notify = MagicMock()
        app.push_screen = MagicMock()

        cmd = ShellTasksCommand()
        await cmd.execute(app)
        app.notify.assert_called_once_with("No active shell tasks", severity="warning")
        app.push_screen.assert_not_called()

    async def test_shell_command_with_tasks(self):
        from unittest.mock import MagicMock

        from core.infrastructure.tasks.shell_task import ShellTask
        from widgets.commands import ShellTasksCommand

        app = MockApp()
        app.notify = MagicMock()
        app.push_screen = MagicMock()
        t_bg = ShellTask("t-bg", "sleep 100", None)
        t_bg.is_background = True
        app.task_manager.register(t_bg)

        cmd = ShellTasksCommand()
        await cmd.execute(app)
        app.notify.assert_not_called()
        app.push_screen.assert_called_once()

    async def test_resume_command_clears_queue_and_resets_generating(self):
        from unittest.mock import MagicMock

        from widgets.commands import ResumeCommand

        app = MockApp()
        app.is_generating = True
        app.message_queue = [("Queued prompt", True)]
        app.sm = MagicMock()
        app.sm.list_main_sessions.return_value = [{"id": "sess_1", "title": "Sess 1"}]
        app.load_session_ui = MagicMock()
        mock_input = MagicMock()
        app.query_one = lambda target, default=None: mock_input

        cmd = ResumeCommand()
        app.push_screen = lambda screen, callback: callback("sess_1")
        await cmd.execute(app)

        self.assertFalse(app.is_generating)
        self.assertEqual(app.message_queue, [])
        app.load_session_ui.assert_called_once_with("sess_1")

    async def test_mcp_command_pushes_screen(self):
        from unittest.mock import MagicMock, patch

        from widgets.commands import MCPCommand

        app = MockApp()
        app.push_screen = MagicMock()

        cmd = MCPCommand()
        with patch("core.infrastructure.mcp.MCPManager.load_servers", return_value=[{"name": "srv"}]):
            await cmd.execute(app)

        app.push_screen.assert_called_once()

    async def test_mcp_command_no_servers(self):
        from unittest.mock import MagicMock, patch

        from widgets.commands import MCPCommand

        app = MockApp()
        app.push_screen = MagicMock()

        cmd = MCPCommand()
        with patch("core.infrastructure.mcp.MCPManager.load_servers", return_value=[]):
            await cmd.execute(app)

        app.push_screen.assert_not_called()
        self.assertEqual(app.notified, [("No configured MCP servers found", "warning")])


if __name__ == "__main__":
    unittest.main()


class TestHandleSlashCommand(unittest.IsolatedAsyncioTestCase):
    async def _call(self, text, app=None):
        app = app or MagicMock()
        from widgets.app.dispatch import handle_slash_command

        return await handle_slash_command(app, text), app

    async def test_empty_command_returns_false(self):
        handled, _ = await self._call("")
        self.assertFalse(handled)

    async def test_whitespace_only_returns_false(self):
        handled, _ = await self._call("   \t  ")
        self.assertFalse(handled)

    async def test_none_command_returns_false(self):
        from widgets.app.dispatch import handle_slash_command

        self.assertFalse(await handle_slash_command(MagicMock(), None))

    async def test_unknown_command_returns_false(self):
        handled, _ = await self._call("/definitely_not_a_command")
        self.assertFalse(handled)

    async def test_registered_command_executes_with_args(self):
        app = MagicMock()
        with patch("widgets.app.dispatch.COMMAND_REGISTRY", {"/known": MagicMock()}) as registry:
            inst = AsyncMock()
            registry["/known"].return_value = inst
            handled, _ = await self._call("/known arg1 arg2", app)
        self.assertTrue(handled)
        inst.execute.assert_awaited_once()

    async def test_empty_word_after_slash_is_not_a_command(self):
        # "/ " (slash then space) has no command word; must not match registry.
        handled, _ = await self._call("/ ")
        self.assertFalse(handled)

    async def test_multiple_whitespace_between_args(self):
        # "cmd  arg" with double space must split to earliest command word.
        with patch("widgets.app.dispatch.COMMAND_REGISTRY", {}):
            handled, _ = await self._call("/xyz  arg")
        self.assertFalse(handled)


if __name__ == "__main__":
    unittest.main()


class MockInput:
    def __init__(self):
        self.text = ""

    def load_text(self, txt):
        self.text = txt

    def move_cursor(self, pos):
        self.cursor = pos

    def focus(self):
        self.focused = True


class SimpleApp:
    def __init__(self):
        self.agent = None
        self.is_generating = False
        self.notified = []
        self.pushed = []
        self.pm = None
        self.sm = None
        self.current_session_id = None
        self.message_queue = None
        self.workers = []
        self.refreshed = 0
        self.input = MockInput()

    def notify(self, msg, severity="info"):
        self.notified.append((msg, severity))

    def refresh_status_footer(self):
        self.refreshed += 1

    def query_one(self, target, default=None):
        return self.input

    def push_screen(self, screen, callback=None):
        self.pushed.append(screen)
        if callback:
            callback(None)


class TestCommandsCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_base_command_execute_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            await BaseCommand().execute(None)

    async def test_new_command_cancels_running_worker(self):
        from widgets.commands import NewCommand

        cancel_called = []

        class Worker:
            is_running = True

            def cancel(self):
                cancel_called.append(1)

        async def fake_new_session(sm, agent, **cb):
            cb["cancel_workers"]()
            await cb["kill_all_tasks"]()
            cb["cancel_subagents"]()
            return "new-id"

        app = SimpleApp()
        app.agent = SimpleNamespace()
        app.message_queue = MagicMock()
        app.task_manager = SimpleNamespace(kill_all=AsyncMock())
        app.workers = [Worker()]
        app.sm = MagicMock()
        chat = SimpleNamespace()
        chat.remove_children = AsyncMock()
        chat.check_welcome = MagicMock()
        app.query_one = lambda target, default=None: chat
        with patch(
            "widgets.commands.new_session", new=fake_new_session
        ), patch("core.application.session.stream.cancel_running_subagents"):
            await NewCommand().execute(app)
        self.assertEqual(len(cancel_called), 1)
        app.task_manager.kill_all.assert_awaited_once()
        app.message_queue.clear.assert_called_once()

    async def test_providers_command_load_raises_then_notifies(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.side_effect = Exception("boom")
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("No available providers configured", "warning")]
        )

    async def test_providers_command_no_providers(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {}
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("No available providers configured", "warning")]
        )

    async def test_providers_command_entered_key_opens_with_focus(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {"p": {"name": "P"}}
        cm.get_active_provider_key.return_value = "p"
        cm.get_api_key.return_value = ""
        cm.get_disabled_providers.return_value = []
        app.pm = cm

        entered_keys = []
        invoked_once = {"done": False}

        def push_screen(screen, callback=None):
            name = screen.__class__.__name__
            app.pushed.append(name)
            if not callback:
                return
            if name == "ApiKeyInputScreen":
                entered_keys.append(callback)
                callback("secret")
            elif not invoked_once["done"]:
                invoked_once["done"] = True
                callback("p")

        app.push_screen = push_screen
        with patch(
            "widgets.commands.fetch_api_key_and_provider_info",
            return_value=("P", ""),
        ), patch("widgets.commands.set_provider_credentials", return_value=""):
            await ProvidersCommand().execute(app)

        # Flush the asyncio.create_task(_open_with_key) scheduled on failure path.
        # Poll with a real delay: to_thread hops to a worker thread, so bare
        # sleep(0) does not guarantee the task completes under load.
        for _ in range(100):
            if app.pushed.count("ProvidersScreen") >= 2:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(len(entered_keys), 1)
        self.assertGreaterEqual(app.pushed.count("ProvidersScreen"), 2)

    async def test_open_with_key_normal_path(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {"p": {"name": "P"}}
        cm.get_active_provider_key.return_value = "p"
        cm.get_api_key.return_value = ""
        cm.get_disabled_providers.return_value = []
        app.pm = cm
        await ProvidersCommand()._open_with_key(app, "p", lambda k: None)
        self.assertTrue(
            any(getattr(s, "__class__", None).__name__ == "ProvidersScreen" for s in app.pushed)
        )

    async def test_open_with_key_load_raises(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.side_effect = Exception("boom")
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand()._open_with_key(app, "p", lambda k: None)
        ps.assert_not_called()

    async def test_open_with_key_no_providers(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {}
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand()._open_with_key(app, "p", lambda k: None)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("No available providers configured", "warning")]
        )

    async def test_models_command_disconnected_opens_providers(self):
        app = SimpleApp()
        app.pm = MagicMock()
        with patch("widgets.commands.fetch_grouped_models", return_value=([], True)), patch.object(
            ProvidersCommand, "execute", new=AsyncMock()
        ) as m_exec, patch.object(app, "push_screen") as ps:
            await ModelsCommand().execute(app)
        ps.assert_not_called()
        m_exec.assert_awaited_once()

    async def test_models_command_no_models_notify(self):
        app = SimpleApp()
        app.pm = MagicMock()
        with patch("widgets.commands.fetch_grouped_models", return_value=([], False)), patch.object(
            app, "push_screen"
        ) as ps:
            await ModelsCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("Failed to fetch models: check API key or network connection", "warning")]
        )

    async def test_models_command_provider_model_and_scalar_selection(self):
        app = SimpleApp()
        app.agent = MagicMock()
        app.agent.model = ""
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "p"
        cm.get_provider_model.return_value = "gpt-x"
        app.pm = cm
        selected = []

        def push_screen(screen, callback=None):
            if callback:
                callback("gpt-x")  # scalar selection -> use curr_provider

        app.push_screen = push_screen
        with patch(
            "widgets.commands.fetch_grouped_models", return_value=({"p": {"name": "P"}}, False)
        ), patch("widgets.commands.select_model", side_effect=lambda *a, **k: selected.append(a)):
            await ModelsCommand().execute(app)
        self.assertTrue(selected)

    async def test_thinking_effort_no_pm(self):
        app = SimpleApp()
        await ThinkingEffortCommand().execute(app)
        self.assertEqual(app.notified, [("Provider manager not available", "warning")])

    async def test_thinking_effort_empty_selection_focuses(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "p"
        app.pm = cm

        def push_screen(screen, callback=None):
            if callback:
                callback(None)  # empty effort

        app.push_screen = push_screen
        with patch("widgets.commands.get_current_thinking_effort", return_value=("p", "m", "auto")):
            await ThinkingEffortCommand().execute(app)
        self.assertIsNotNone(getattr(app.input, "focused", None))

    async def test_rewind_no_user_messages(self):
        app = SimpleApp()
        chat = MagicMock()
        chat.get_user_messages.return_value = []
        app.query_one = lambda target, default=None: chat
        await RewindCommand().execute(app)
        self.assertEqual(
            app.notified, [("History is empty: no messages to rollback", "warning")]
        )

    async def test_rewind_exception_paths(self):
        from core.application.session import stream

        app = SimpleApp()
        app.current_session_id = "sess-a"
        app.sm = MagicMock()
        app.sm.project_path = None
        app.message_queue = MagicMock()
        app.task_manager = simple_task_manager = SimpleNamespace()
        simple_task_manager.kill_all = AsyncMock(side_effect=Exception("kill"))
        app.agent = MagicMock()

        class BadCancelWorker:
            is_running = True
            is_finished = False

            def cancel(self):
                raise Exception("cancel-boom")

            async def wait(self):
                raise RuntimeError("wait-boom")

        from textual.worker import WorkerCancelled

        class CancelledWaitWorker(BadCancelWorker):
            async def wait(self):
                raise WorkerCancelled()

        app.workers = [BadCancelWorker(), CancelledWaitWorker()]
        app.is_generating = True
        app.save_current_session = MagicMock()

        chat = MagicMock()
        chat.get_user_messages.return_value = [(0, "First")]
        chat.rollback_to = MagicMock()
        app.input.load_text = app.input.load_text

        def query_one(target, default=None):
            if target == "#message-input":
                return app.input
            return chat

        app.query_one = query_one

        async def push_screen(screen, callback=None):
            if callback:
                await callback(0)
                return
            return None

        app.push_screen = push_screen
        with patch.object(stream, "cancel_running_subagents", side_effect=Exception("sub")):
            await RewindCommand().execute(app)
        self.assertFalse(app.is_generating)

    async def test_resume_no_sessions(self):
        app = SimpleApp()
        app.sm = MagicMock()
        app.sm.list_main_sessions.return_value = []
        await ResumeCommand().execute(app)
        self.assertEqual(app.notified, [("No saved sessions in this project", "warning")])

    async def test_resume_cancels_running_workers(self):
        app = SimpleApp()
        app.sm = MagicMock()
        app.sm.list_main_sessions.return_value = [{"id": "s1"}]
        app.is_generating = True
        app.message_queue = MagicMock()
        app.load_session_ui = MagicMock()

        class Worker:
            is_running = True

            def cancel(self):
                raise Exception("cancel-boom")

        app.workers = [Worker()]

        def push_screen(screen, callback=None):
            if callback:
                callback("s1")

        app.push_screen = push_screen
        await ResumeCommand().execute(app)
        app.load_session_ui.assert_called_once_with("s1")
        self.assertFalse(app.is_generating)
        app.message_queue.clear.assert_called_once()

    async def test_subagents_no_store(self):
        app = SimpleApp()
        # no app.sm -> _has_subagents returns False
        await SubagentsCommand().execute(app)
        self.assertEqual(app.notified, [("No active subagents", "warning")])

    async def test_skills_no_skills(self):
        app = SimpleApp()
        with patch("core.application.skills.manager.SkillManager.list_skills", return_value=[]), patch.object(
            app, "push_screen"
        ) as ps:
            await SkillsCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(app.notified, [("No available skills found", "warning")])

    async def test_skills_with_selection(self):
        app = SimpleApp()
        selected = []

        def push_screen(screen, callback=None):
            if callback:
                selected.append(callback)

        app.push_screen = push_screen

        class FakeSkill:
            hidden = False

            def __init__(self, name):
                self.name = name

            def to_dict(self):
                return {"name": self.name, "hidden": False}

        def fake_list_skills(self, *a, **k):
            return [FakeSkill("handoff")]

        with patch("core.application.skills.manager.SkillManager.list_skills", new=fake_list_skills):
            await SkillsCommand().execute(app)
        self.assertTrue(selected)
        selected[0]({"name": "handoff"})
        self.assertEqual(app.input.text, "/handoff ")
        # selection None -> focus only
        app.input.text = ""
        selected[0](None)
        self.assertTrue(getattr(app.input, "focused", None))

    async def test_compact_no_agent(self):
        app = SimpleApp()
        await CompactCommand().execute(app)
        self.assertEqual(app.notified, [("No active agent found", "error")])

    async def test_compact_divider_raises_and_save_raises(self):
        app = SimpleApp()
        app.agent = MagicMock()
        app.save_current_session = MagicMock(side_effect=Exception("save"))

        class BrokenDivider:
            async def add_event_divider(self, txt):
                raise Exception("divider")

        chat = BrokenDivider()
        app.query_one = lambda target, default=None: chat

        outcome = SimpleNamespace(success=False, message="boom")

        async def fake_compact(agent, **cb):
            cb["save_session_cb"]()
            cb["on_begin"]()
            return outcome

        with patch("widgets.commands.compact_session", new=fake_compact), patch.object(
            app, "push_screen", MagicMock()
        ):
            await CompactCommand().execute(app)
        self.assertEqual(app.notified, [("boom", "warning")])

    async def test_compact_success_with_queued_message(self):
        app = SimpleApp()
        app.agent = MagicMock()
        app.refresh_status_footer = MagicMock()
        queued = [("next-prompt", True, {})]
        processed = []

        def pop():
            return queued.pop(0)

        async def process(prompt, show, attachments):
            processed.append((prompt, show))

        app._pop_queued_for_current_session = pop
        app._process_queued_message = process
        app.query_one = lambda target, default=None: SimpleApp.query_one.__get__(app)(target, default)

        outcome = SimpleNamespace(success=True, message="ok")
        with patch("widgets.commands.compact_session", return_value=outcome):
            await CompactCommand().execute(app)
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertFalse(app.is_generating)
        self.assertEqual(processed, [("next-prompt", True)])

    async def test_permissions_command_pushes_screen(self):
        app = SimpleApp()
        with patch.object(app, "push_screen") as ps:
            await PermissionsCommand().execute(app)
        ps.assert_called_once()

    async def test_questions_wizard_active(self):
        app = SimpleApp()
        from widgets.presentation.screens.ask_user import AskUserWizardScreen

        app.screen = MagicMock(spec=AskUserWizardScreen)
        app.notify = MagicMock()
        await QuestionsCommand().execute(app)
        app.notify.assert_called_once_with("Question wizard is currently active", severity="info")

    async def test_questions_pending_func(self):
        app = SimpleApp()
        called = []
        app._pending_ask_user = lambda: called.append(1)
        await QuestionsCommand().execute(app)
        self.assertEqual(called, [1])

    async def test_questions_no_pending(self):
        app = SimpleApp()
        app.notify = MagicMock(side_effect=app.notify)
        await QuestionsCommand().execute(app)
        self.assertEqual(app.notified, [("No pending questions", "warning")])


# ---------------------------------------------------------------------------
# widgets/app/status_state.py
# ---------------------------------------------------------------------------
