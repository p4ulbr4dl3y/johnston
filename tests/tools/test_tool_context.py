import unittest
from unittest.mock import MagicMock

from core.infrastructure.tasks.manager import TaskManager
from tools.context import ToolContext


class DummyAgent:
    def __init__(self):
        self.role = "action"


class MockProviderManager:
    def create_active_agent(self):
        return DummyAgent()


class DummyApp:
    def __init__(self):
        self.status_refreshed = False
        self.task_manager = TaskManager()
        self.agent = DummyAgent()
        self.pm = MockProviderManager()

    def refresh_status_footer(self):
        self.status_refreshed = True


class TestToolContext(unittest.TestCase):
    def test_context_delegates_to_app(self):
        app = DummyApp()
        ctx = ToolContext(app)

        task = MagicMock()
        task.task_id = "task1"
        task.id = "task1"
        task.kind = "shell"
        ctx.add_background_task(task)
        self.assertIn(task, ctx.background_tasks)

    def test_context_without_app(self):
        ctx = ToolContext(None)
        ctx.refresh_status()
        self.assertEqual(ctx.background_tasks, [])
        self.assertIsNone(ctx.create_agent())

    def test_add_background_task_registers_in_manager(self):
        app = DummyApp()
        ctx = ToolContext(app)
        task = MagicMock()
        task.task_id = "task_new"
        task.id = "task_new"
        task.kind = "shell"
        ctx.add_background_task(task)
        self.assertIn("task_new", [t.id for t in app.task_manager])


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

    def test_trigger_ai_response_no_app(self):
        ctx = ToolContext(None)
        ctx.trigger_ai_response("noop")  # should not raise

    def test_create_agent_with_pm(self):
        app = DummyApp()
        ctx = ToolContext(app)
        agent = ctx.create_agent()
        self.assertIsInstance(agent, DummyAgent)

    def test_create_agent_no_pm(self):
        class NoPmApp:
            pass

        ctx = ToolContext(NoPmApp())
        self.assertIsNone(ctx.create_agent())

    def test_sandbox_enabled_inherited_from_app_for_subagent(self):
        app = DummyApp()
        app.sandbox_enabled = False
        ctx = ToolContext(app, is_subagent=True)
        self.assertFalse(ctx.sandbox_enabled)

        app.sandbox_enabled = True
        ctx_on = ToolContext(app, is_subagent=True)
        self.assertTrue(ctx_on.sandbox_enabled)

    def test_sandbox_enabled_from_agent_app_wrapper(self):
        app = DummyApp()
        app.sandbox_enabled = True
        agent = DummyAgent()
        agent.app = app
        agent.is_subagent = True
        ctx = ToolContext(agent)
        self.assertTrue(ctx.sandbox_enabled)
        self.assertTrue(ctx.is_subagent)

        app.sandbox_enabled = False
        ctx_off = ToolContext(agent)
        self.assertFalse(ctx_off.sandbox_enabled)

    def test_session_and_session_id_resolution(self):
        app = DummyApp()
        app.current_session_id = "parent-123"

        # Direct app
        ctx1 = ToolContext(app)
        self.assertEqual(ctx1.session_id, "parent-123")

        # Subagent agent with its own session
        subagent = DummyAgent()
        subagent.app = app
        subagent.is_subagent = True
        sub_sess = MagicMock()
        sub_sess.id = "subagent-session-456"
        subagent.session = sub_sess

        ctx2 = ToolContext(subagent)
        self.assertEqual(ctx2.session, sub_sess)
        self.assertEqual(ctx2.session_id, "subagent-session-456")


if __name__ == "__main__":

    unittest.main()

