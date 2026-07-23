import unittest

from commands import COMMAND_REGISTRY, handle_slash_command
from widgets.chat_view import ChatView


class MockAgent:
    def __init__(self, mode="action"):
        self.mode = mode
        self.compact_called = False

    async def compact_history(self):
        self.compact_called = True
        return True, "History compacted"


class MockChatView:
    def __init__(self, children=None):
        self.children = children or []


class MockBotMessage:
    def __init__(self, content):
        self.content = content


class MockApp:
    def __init__(self, agent=None):
        self.agent = agent or MockAgent()
        self.notified = []
        self.status_refreshed = False
        self.ai_prompts = []
        self.chat_view = ChatView()

    def notify(self, msg: str, severity: str = "info"):
        self.notified.append((msg, severity))

    def refresh_status_footer(self):
        self.status_refreshed = True

    def generate_ai_response(self, prompt: str, show_in_ui: bool = True):
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

    async def test_unknown_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/unknowncommand123")
        self.assertFalse(handled)

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

    def test_registry_contains_all_commands(self):
        self.assertIn("/compact", COMMAND_REGISTRY)
        self.assertIn("/demo", COMMAND_REGISTRY)
        self.assertIn("/init", COMMAND_REGISTRY)
        self.assertIn("/help", COMMAND_REGISTRY)
        self.assertIn("/connect", COMMAND_REGISTRY)


if __name__ == "__main__":
    unittest.main()
