"""Tests for HostProtocol, NullHost, and host decoupling."""
import os
import unittest
from unittest.mock import MagicMock

from johnston.core.infrastructure.llm.base.agent import BaseAgent
from johnston.core.infrastructure.llm.base.message_queue import drain_queued_messages, has_queued_messages
from johnston.core.infrastructure.runtime.subagent_tracker import mark_subagent_running, record_subagent_session
from johnston.core.interfaces.host import HostProtocol, NullHost
from johnston.core.tools.context import ToolContext


class TestHostProtocol(unittest.IsolatedAsyncioTestCase):
    def test_null_host_implements_host_protocol(self):
        host = NullHost()
        self.assertTrue(isinstance(host, HostProtocol))

    def test_null_host_properties_and_defaults(self):
        host = NullHost(project_dir="/test/pdir", current_session_id="sess-1")
        self.assertEqual(host.project_dir, "/test/pdir")
        self.assertEqual(host.current_session_id, "sess-1")
        self.assertIsNone(host.task_manager)
        self.assertEqual(host.message_queue, [])

    async def test_null_host_methods(self):
        host = NullHost()
        self.assertEqual(await host.ask_user([{"question": "Q"}]), "")
        self.assertFalse(await host.confirm_permission("shell", {"command": "ls"}))
        # Fire-and-forget sync methods should not raise
        host.trigger_ai_response("hello", show_in_ui=False)
        host.refresh_status_footer()
        host.on_subagent_tool_completed("sess-1", "done", "result")
        host.on_plan_update([{"step": "step 1", "status": "pending"}], "in_progress")


class TestToolContextWithHost(unittest.IsolatedAsyncioTestCase):
    def test_tool_context_accepts_host_kwarg(self):
        host = NullHost(project_dir="/custom/dir", current_session_id="sess-42")
        ctx = ToolContext(host=host)
        self.assertIs(ctx.host, host)
        self.assertIs(ctx.app, host)
        self.assertEqual(ctx.session_id, "sess-42")

    def test_tool_context_app_property_setter(self):
        ctx = ToolContext(None)
        self.assertIsNone(ctx.host)
        self.assertIsNone(ctx.app)
        host = NullHost()
        ctx.app = host
        self.assertIs(ctx.host, host)
        self.assertIs(ctx.app, host)

    def test_tool_context_shell_widget_operations_with_null_host(self):
        host = NullHost()
        ctx = ToolContext(host=host)
        widget = MagicMock()

        # attach / detach
        ctx.attach_shell_widget("t1", widget, is_background=True)
        self.assertEqual(host._background_shell_widgets.get("t1"), widget)
        ctx.detach_shell_widget("t1")
        self.assertNotIn("t1", host._background_shell_widgets)

        # foreground tasks
        task_mock = MagicMock()
        ctx.register_foreground_shell_task("t2", task_mock)
        self.assertEqual(ctx.find_task("t2"), task_mock)
        ctx.cleanup_foreground_shell_task("t2")
        self.assertIsNone(ctx.find_task("t2"))

        # terminate widget
        ctx.attach_shell_widget("t3", widget)
        ctx.terminate_task_widget("t3", output="done", status="done")
        widget.set_result.assert_called_once_with("done", status="done")

    def test_tool_context_widget_operations_with_none_host(self):
        ctx = ToolContext(None)
        ctx.attach_shell_widget("t1", MagicMock(), is_background=True)
        ctx.detach_shell_widget("t1")
        ctx.register_foreground_shell_task("t2", MagicMock())
        ctx.cleanup_foreground_shell_task("t2")
        ctx.terminate_task_widget("t3")
        self.assertIsNone(ctx.find_task("nonexistent"))

    def test_tool_context_widget_operations_with_immutable_host(self):
        class FrozenHost:
            __slots__ = ()

        ctx = ToolContext(FrozenHost())
        ctx.attach_shell_widget("t1", MagicMock(), is_background=True)
        ctx.detach_shell_widget("t1")
        ctx.register_foreground_shell_task("t2", MagicMock())
        ctx.cleanup_foreground_shell_task("t2")
        ctx.terminate_task_widget("t3")
        self.assertIsNone(ctx.find_task("nonexistent"))

    def test_tool_context_on_plan_update(self):
        host = MagicMock()
        ctx = ToolContext(host=host)
        ctx.on_plan_update([{"step": "s1"}], "running")
        host.on_plan_update.assert_called_once_with([{"step": "s1"}], "running")


class TestAgentHostDelegation(unittest.TestCase):
    def test_agent_host_and_app_properties(self):
        agent = BaseAgent()
        self.assertIsNone(agent.host)
        self.assertIsNone(agent.app)

        host = NullHost(project_dir="/custom/project")
        agent.host = host
        self.assertIs(agent.host, host)
        self.assertIs(agent.app, host)

        agent.app = "other"
        self.assertEqual(agent.host, "other")
        self.assertEqual(agent.app, "other")

    def test_agent_role_name_with_host(self):
        agent = BaseAgent()
        agent.role = "architect"
        agent.host = NullHost(project_dir=os.getcwd())
        self.assertIn("Architect", agent.role_name)


class TestMessageQueueHostHandling(unittest.TestCase):
    def test_has_and_drain_queued_messages_with_null_host(self):
        agent = BaseAgent()
        agent.host = NullHost(current_session_id="s1")
        self.assertFalse(has_queued_messages(agent))
        self.assertEqual(drain_queued_messages(agent), [])

    def test_has_and_drain_queued_messages_with_host_queue(self):
        agent = BaseAgent()
        host = NullHost(current_session_id="s1")
        host.message_queue = [("msg1", True, None, "s1", None)]
        agent.host = host

        self.assertTrue(has_queued_messages(agent))
        drained = drain_queued_messages(agent)
        self.assertEqual(len(drained), 1)
        self.assertEqual(drained[0][0], "msg1")
        self.assertEqual(host.message_queue, [])


class TestSubagentTrackerGuards(unittest.TestCase):
    def test_subagent_tracker_with_none_or_headless_app(self):
        record_subagent_session(None, "sess-1")
        mark_subagent_running(None, "sess-1")

        host = NullHost()
        record_subagent_session(host, "sess-1")
        mark_subagent_running(host, "sess-1")

    def test_subagent_tracker_with_immutable_host(self):
        class FrozenHost:
            __slots__ = ()

        host = FrozenHost()
        record_subagent_session(host, "sess-1")
        mark_subagent_running(host, "sess-1")
