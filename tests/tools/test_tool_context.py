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

        ctx.add_background_task("task1")
        self.assertIn("task1", ctx.background_tasks)

    def test_context_without_app(self):
        ctx = ToolContext(None)
        ctx.notify("noop")
        ctx.refresh_status()
        self.assertEqual(ctx.background_tasks, [])
        self.assertIsNone(ctx.create_agent())

class TestToolContextAdvanced(unittest.TestCase):
    def test_trigger_ai_response_with_method(self):
        class RespApp:
            def __init__(self):
                self.called_with = None
                self.show_in_ui = None
            def trigger_ai_response(self, prompt, show_in_ui=True):
                self.called_with = prompt
                self.show_in_ui = show_in_ui
        app = RespApp()
        ctx = ToolContext(app)
        ctx.trigger_ai_response("test prompt")
        self.assertEqual(app.called_with, "test prompt")
        self.assertFalse(app.show_in_ui)

    def test_trigger_ai_response_generating(self):
        class GenApp:
            def __init__(self):
                self.is_generating = True
                self.message_queue = []
                self.gen_called = False
            def generate_ai_response(self, prompt, show_in_ui=True):
                self.gen_called = True
        app = GenApp()
        ctx = ToolContext(app)
        ctx.trigger_ai_response("queued prompt")
        self.assertIn(("queued prompt", False), app.message_queue)
        self.assertFalse(app.gen_called)

    def test_trigger_ai_response_not_generating(self):
        class GenApp:
            def __init__(self):
                self.is_generating = False
                self.message_queue = []
                self.gen_args = None
            def generate_ai_response(self, prompt, show_in_ui=True):
                self.gen_args = (prompt, show_in_ui)
        app = GenApp()
        ctx = ToolContext(app)
        ctx.trigger_ai_response("direct prompt")
        self.assertEqual(app.gen_args, ("direct prompt", False))

    def test_trigger_ai_response_no_app(self):
        ctx = ToolContext(None)
        ctx.trigger_ai_response("noop")  # should not raise

    def test_create_agent_with_pm(self):
        app = MockApp()
        ctx = ToolContext(app)
        agent = ctx.create_agent()
        self.assertIsInstance(agent, MockAgent)

    def test_create_agent_no_pm(self):
        class NoPmApp:
            pass
        ctx = ToolContext(NoPmApp())
        self.assertIsNone(ctx.create_agent())


if __name__ == "__main__":
    unittest.main()
