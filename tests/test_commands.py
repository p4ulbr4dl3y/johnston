import unittest

from commands import COMMAND_REGISTRY, handle_slash_command
from widgets.chat_view import ChatView


class MockAgent:
    def __init__(self, mode="build"):
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

    def query_one(self, target, default=None):
        if target == ChatView or target == "#chat-view":
            return self.chat_view
        return None


class TestCommands(unittest.IsolatedAsyncioTestCase):
    async def test_homoglyph_normalization_and_routing(self):
        app = MockApp()
        # Cyrillic letters 'р' (p) and 'а' (a) in /plan -> /рlаn
        cyrillic_plan = "/рlаn"
        handled = await handle_slash_command(app, cyrillic_plan)
        self.assertTrue(handled)
        self.assertEqual(app.agent.mode, "plan")
        self.assertTrue(app.status_refreshed)

    async def test_unknown_command(self):
        app = MockApp()
        handled = await handle_slash_command(app, "/unknowncommand123")
        self.assertFalse(handled)

    async def test_plan_and_build_and_mode_commands(self):
        app = MockApp()

        # Switch to plan
        await handle_slash_command(app, "/plan")
        self.assertEqual(app.agent.mode, "plan")

        # Switch to build
        await handle_slash_command(app, "/build")
        self.assertEqual(app.agent.mode, "build")

        # Toggle mode
        await handle_slash_command(app, "/mode")
        self.assertEqual(app.agent.mode, "plan")
        await handle_slash_command(app, "/mode")
        self.assertEqual(app.agent.mode, "build")

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
        self.assertIn("/plan", COMMAND_REGISTRY)
        self.assertIn("/build", COMMAND_REGISTRY)
        self.assertIn("/mode", COMMAND_REGISTRY)
        self.assertIn("/compact", COMMAND_REGISTRY)
        self.assertIn("/init", COMMAND_REGISTRY)
        self.assertIn("/help", COMMAND_REGISTRY)
        self.assertIn("/connect", COMMAND_REGISTRY)


if __name__ == "__main__":
    unittest.main()
