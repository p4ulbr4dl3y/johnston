import unittest

from tools.context import ToolContext


class MockAgent:
    def __init__(self):
        self.mode = "action"

class MockProviderManager:
    def create_active_agent(self):
        return MockAgent()

class MockApp:
    def __init__(self):
        self.notified = []
        self.status_refreshed = False
        self.background_tasks = []
        self.agent = MockAgent()
        self.pm = MockProviderManager()

    def notify(self, msg: str):
        self.notified.append(msg)

    def refresh_status_footer(self):
        self.status_refreshed = True

class TestToolContext(unittest.TestCase):
    def test_context_delegates_to_app(self):
        app = MockApp()
        ctx = ToolContext(app)

        ctx.notify("test notification")
        self.assertEqual(app.notified, ["test notification"])

        ctx.set_agent_mode("plan")
        self.assertEqual(app.agent.mode, "plan")
        self.assertTrue(app.status_refreshed)

        ctx.add_background_task("task1")
        self.assertIn("task1", ctx.background_tasks)

    def test_context_without_app(self):
        ctx = ToolContext(None)
        ctx.notify("noop")
        ctx.refresh_status()
        self.assertEqual(ctx.background_tasks, [])
        self.assertIsNone(ctx.create_agent())

if __name__ == "__main__":
    unittest.main()
