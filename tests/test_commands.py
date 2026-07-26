import time
import unittest
from unittest.mock import patch

from core.commands import COMMAND_REGISTRY, handle_slash_command
from widgets.chat_view import ChatView


class MockAgent:
    def __init__(self, mode="action"):
        self.mode = mode
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


class MockChatView:
    def __init__(self, children=None):
        self.children = children or []


class MockBotMessage:
    def __init__(self, content):
        self.content = content


class MockApp:
    def __init__(self, agent=None):
        self.agent = agent or MockAgent()
        self.mode = self.agent.mode
        self.notified = []
        self.status_refreshed = False
        self.ai_prompts = []
        self.chat_view = ChatView()

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
        from core.commands import RewindCommand
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

        mock_input = type("MockInput", (), {
            "load_text": lambda self, txt: setattr(self, "text", txt),
            "text": "First message",
            "move_cursor": lambda self, pos: None,
            "focus": lambda self: None
        })()
        app.query_one = lambda target, default=None: mock_input if target == "#message-input" else app.chat_view

        cmd = RewindCommand()
        # Simulate selecting user message at index 0 in on_rewind_selected
        def simulate_on_rewind_selected(screen, callback):
            callback(0)
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

    async def test_unknown_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/unknowncommand123")
        self.assertFalse(handled)

    async def test_mode_commands_sync_app_and_agent_mode(self):
        app = MockApp()

        handled = await handle_slash_command(app, "/explore")
        self.assertTrue(handled)
        self.assertEqual(app.agent.mode, "explore")
        self.assertEqual(app.mode, "explore")
        self.assertTrue(app.status_refreshed)

        app.status_refreshed = False
        handled = await handle_slash_command(app, "/action")
        self.assertTrue(handled)
        self.assertEqual(app.agent.mode, "action")
        self.assertEqual(app.mode, "action")
        self.assertTrue(app.status_refreshed)

    async def test_compact_command(self):
        agent = MockAgent()
        app = MockApp(agent=agent)
        handled = await handle_slash_command(app, "/compact")
        self.assertTrue(handled)
        self.assertTrue(agent.compact_called)

    async def test_init_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/init")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        self.assertIn("AGENTS.md", app.ai_prompts[0][0])

    async def test_handoff_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/handoff")
        self.assertTrue(handled)
        self.assertEqual(len(app.ai_prompts), 1)
        self.assertIn("handoff note", app.ai_prompts[0][0])
        self.assertIn("Do not create, edit, or delete files", app.ai_prompts[0][0])
        self.assertIn("little or no prior session context", app.ai_prompts[0][0])

    async def test_models_command_non_vision_warning(self):
        from core.commands import ModelsCommand
        from core.models_catalog import catalog
        from widgets.screens.model import VisionWarningScreen

        test_model_name = f"test-non-vision-{int(time.time() * 1000)}"

        class MockPM:
            async def fetch_models_grouped(self): return {"custom": {"name": "Custom", "models": [test_model_name]}}
            def get_active_provider_key(self): return "custom"
            def set_provider_model(self, p, m): pass
            def set_active_provider_key(self, p): pass
            def create_active_agent(self): return MockAgent()

        app = MockApp()
        app.pm = MockPM()
        cmd = ModelsCommand()

        pushed_screens = []
        def simulate_push_screen(screen, callback=None):
            pushed_screens.append(screen)
            if isinstance(screen, VisionWarningScreen) and callback:
                callback("force_vision")
            elif callback:
                callback(("custom", test_model_name))

        app.push_screen = simulate_push_screen
        app.query_one = lambda target, default=None: type("MockInput", (), {"focus": lambda self: None})()

        with patch.object(catalog, "save_cache"):
            await cmd.execute(app)
            warning_screens = [s for s in pushed_screens if isinstance(s, VisionWarningScreen)]
            self.assertTrue(len(warning_screens) > 0)
            self.assertTrue(catalog.supports_vision("custom", test_model_name))
        catalog.remove_vision_override(test_model_name)
        catalog.set_fallback_vision_model("", "")

    async def test_models_command_preserves_mode_when_switching_provider(self):
        from core.commands import ModelsCommand

        class MockPM:
            def __init__(self):
                self.active_provider = "old"
                self.saved = []

            async def fetch_models_grouped(self):
                return {"old": {"name": "Old", "models": ["old-model"]}, "new": {"name": "New", "models": ["new-model"]}}

            def get_active_provider_key(self):
                return self.active_provider

            def set_active_provider_key(self, provider):
                self.active_provider = provider

            def set_provider_model(self, provider, model):
                self.saved.append((provider, model))

            def create_active_agent(self):
                return MockAgent(mode="action")

        app = MockApp(agent=MockAgent(mode="explore"))
        app.mode = "explore"
        app.pm = MockPM()
        app.query_one = lambda target, default=None: type("Input", (), {"focus": lambda self: None})()
        app.push_screen = lambda screen, callback=None: callback(("new", "new-model")) if callback else None

        await ModelsCommand().execute(app)

        self.assertEqual(app.pm.active_provider, "new")
        self.assertEqual(app.agent.mode, "explore")
        self.assertEqual(app.mode, "explore")
        self.assertEqual(app.pm.saved, [("new", "new-model")])

    async def test_providers_command_preserves_mode_when_connecting_provider(self):
        from core.commands import ProvidersCommand

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
                return MockAgent(mode="action")

        app = MockApp(agent=MockAgent(mode="explore"))
        app.mode = "explore"
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
        self.assertEqual(app.agent.mode, "explore")
        self.assertEqual(app.mode, "explore")

    def test_registry_contains_all_commands(self):
        self.assertIn("/compact", COMMAND_REGISTRY)
        self.assertIn("/init", COMMAND_REGISTRY)
        self.assertIn("/help", COMMAND_REGISTRY)
        self.assertIn("/connect", COMMAND_REGISTRY)

    def test_alias_suggestions_formatting(self):
        from widgets.command_suggestions import get_all_command_suggestions
        commands_dict = dict(get_all_command_suggestions())
        self.assertIn("/providers", commands_dict)
        self.assertIn("/connect", commands_dict)
        self.assertEqual(commands_dict["/connect"], "Alias for /providers")
        self.assertEqual(commands_dict["/h"], "Alias for /help")
        self.assertEqual(commands_dict["/clear"], "Alias for /new")
        self.assertEqual(commands_dict["/undo"], "Alias for /rewind")
        self.assertEqual(commands_dict["/model"], "Alias for /models")
        self.assertIn("Manage AI providers", commands_dict["/providers"])


if __name__ == "__main__":
    unittest.main()
