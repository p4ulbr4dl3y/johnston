import time
import unittest

from core.infrastructure.tasks.manager import TaskManager
from widgets.app.dispatch import COMMAND_REGISTRY, handle_slash_command
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
        self.chat_view = MockChatView()
        self.task_manager = TaskManager()

    def notify(self, msg: str, severity: str = "info"):
        self.notified.append((msg, severity))

    def refresh_status_footer(self):
        self.status_refreshed = True

    def save_current_session(self):
        pass

    def generate_ai_response(self, prompt: str, show_in_ui: bool = True):
        self.ai_prompts.append((prompt, show_in_ui))

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False):
        self.ai_prompts.append((prompt, show_in_ui))

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

    async def test_init_skill_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/init")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        prompt, show_in_ui = app.ai_prompts[0]
        self.assertFalse(show_in_ui)
        self.assertIn('<SKILL path=', prompt)

    async def test_multiple_skills_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/init /handoff analyze project")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        prompt, show_in_ui = app.ai_prompts[0]
        self.assertFalse(show_in_ui)
        self.assertIn('<SKILL path=', prompt)
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

    async def test_handoff_skill_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/handoff")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        self.assertIn("handoff", app.ai_prompts[0][0])

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


if __name__ == "__main__":
    unittest.main()
