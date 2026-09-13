"""Tests for TaskWidgetRegistry and TaskWidgetRegistryMixin."""
from unittest.mock import MagicMock

from johnston.core.interfaces.host import HostProtocol
from johnston.tui.app.task_registry import TaskWidgetRegistry
from johnston.tui.mixins.task_widget_registry import TaskWidgetRegistryMixin


def test_task_widget_registry_standalone():
    reg = TaskWidgetRegistry()

    # Initial state
    assert reg.background_shell_widgets == {}
    assert reg.foreground_shell_tasks == {}
    assert reg.subagent_tools == {}

    # Attach shell widget sync
    w1 = MagicMock()
    reg.attach_shell_widget("t1", w1, is_background=False)
    assert reg.background_shell_widgets["t1"] is w1

    # Attach shell widget background with mark_background
    w2 = MagicMock()
    reg.attach_shell_widget("t2", w2, log_path="/path/to/log", is_background=True)
    w2.mark_background.assert_called_once_with("t2", "/path/to/log")
    assert reg.background_shell_widgets["t2"] is w2

    # Attach shell widget background without mark_background
    class SimpleWidget:
        pass

    w3 = SimpleWidget()
    reg.attach_shell_widget("t3", w3, log_path="/path/t3.log", is_background=True)
    assert w3.background_task_id == "t3"
    assert w3.task_id == "t3"
    assert w3.log_path == "/path/t3.log"

    # Attach None widget does nothing
    reg.attach_shell_widget("t_none", None)
    assert "t_none" not in reg.background_shell_widgets

    # Detach shell widget
    reg.detach_shell_widget("t1")
    assert "t1" not in reg.background_shell_widgets

    # Foreground shell tasks
    task1 = MagicMock()
    reg.register_foreground_shell_task("fg1", task1)
    assert reg.get_foreground_shell_task("fg1") is task1
    assert reg.get_foreground_shell_tasks() == [task1]
    reg.cleanup_foreground_shell_task("fg1")
    assert reg.get_foreground_shell_task("fg1") is None
    assert reg.get_foreground_shell_tasks() == []

    # Terminate task widget
    w_term = MagicMock()
    reg.attach_shell_widget("t_term", w_term)
    reg.register_subagent_tool("t_term", MagicMock())
    reg.terminate_task_widget("t_term", output="killed!", status="terminated")
    assert "t_term" not in reg.background_shell_widgets
    assert reg.get_subagent_tool("t_term") is None
    w_term.set_result.assert_called_once_with("killed!", status="terminated")

    # Subagent tools management
    tool_sub = MagicMock()
    reg.register_subagent_tool("sub1", tool_sub)
    assert reg.get_subagent_tool("sub1") is tool_sub
    assert reg.get_subagent_tools() == {"sub1": tool_sub}
    reg.cleanup_subagent_tool("sub1")
    assert reg.get_subagent_tool("sub1") is None

    # Clear
    reg.attach_shell_widget("t_clear", MagicMock())
    reg.register_foreground_shell_task("fg_clear", MagicMock())
    reg.register_subagent_tool("sub_clear", MagicMock())
    reg.clear()
    assert reg.background_shell_widgets == {}
    assert reg.foreground_shell_tasks == {}
    assert reg.subagent_tools == {}


def test_task_widget_registry_mixin_delegation():
    class TestHost(TaskWidgetRegistryMixin):
        pass

    host = TestHost()

    # Lazy initialization of registry
    assert isinstance(host.task_registry, TaskWidgetRegistry)
    assert host._task_registry is host.task_registry

    # Direct dict operations backward compatibility
    w1 = MagicMock()
    host.attach_shell_widget("t1", w1)
    assert host._background_shell_widgets["t1"] is w1
    assert "t1" in host._background_shell_widgets

    # Mutating via dict
    w2 = MagicMock()
    host._background_shell_widgets["t2"] = w2
    assert host.task_registry.background_shell_widgets["t2"] is w2

    # Foreground tasks delegation
    task = MagicMock()
    host.register_foreground_shell_task("fg1", task)
    assert host.get_foreground_shell_task("fg1") is task
    assert host.get_foreground_shell_tasks() == [task]
    assert host._foreground_shell_tasks["fg1"] is task

    host.cleanup_foreground_shell_task("fg1")
    assert host.get_foreground_shell_task("fg1") is None
    assert "fg1" not in host._foreground_shell_tasks

    # Terminate task widget delegation
    host.terminate_task_widget("t1")
    assert "t1" not in host._background_shell_widgets
    w1.set_result.assert_called_once_with("[killed]", status="done")

    # Reassigning dicts
    host._background_shell_widgets = {"new_t": w1}
    assert host._background_shell_widgets["new_t"] is w1
    assert host.task_registry.background_shell_widgets["new_t"] is w1

    host._foreground_shell_tasks = {"new_fg": task}
    assert host.get_foreground_shell_task("new_fg") is task

    # Subagent tools
    sub_tool = MagicMock()
    host._subagent_tools = {"s1": sub_tool}
    assert host._subagent_tools["s1"] is sub_tool

    # Deletion of properties
    del host._background_shell_widgets
    assert host._background_shell_widgets == {}
    del host._foreground_shell_tasks
    assert host._foreground_shell_tasks == {}
    del host._subagent_tools
    assert host._subagent_tools == {}


def test_task_widget_registry_mixin_subclass_init_compatibility():
    class CustomHost(TaskWidgetRegistryMixin):
        def __init__(self):
            self._background_shell_widgets = {}
            self._foreground_shell_tasks = {}
            self._subagent_tools = {}

    host = CustomHost()
    widget = MagicMock()
    host.attach_shell_widget("t1", widget)
    assert host._background_shell_widgets["t1"] is widget
    host.detach_shell_widget("t1")
    assert "t1" not in host._background_shell_widgets


def test_task_widget_registry_host_protocol_compatibility():
    class FullHost(TaskWidgetRegistryMixin):
        def __init__(self):
            self.task_manager = MagicMock()
            self.current_session_id = "s1"
            self.project_dir = "/tmp"
            self.pm = None
            self.sandbox_enabled = False
            self.is_read_only = False
            self.message_queue = []
            self.session = None

        async def ask_user(self, questions):
            return ""

        async def confirm_permission(self, tool_name, args, **kwargs):
            return True

        def trigger_ai_response(self, prompt, show_in_ui=False):
            pass

        def refresh_status_footer(self):
            pass

        def on_subagent_tool_completed(self, session_id, status, result=""):
            pass

        def on_plan_update(self, plan, status="", *args, **kwargs):
            pass

    host = FullHost()
    assert isinstance(host, HostProtocol)
