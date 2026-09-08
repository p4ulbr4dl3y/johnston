import asyncio
import gc
from unittest.mock import MagicMock

import pytest

from johnston_core.application.session.stream_runner import run_subagent_stream_bg
from johnston_core.domain.entities.session import AgentSession, SessionStatus
from johnston_core.domain.entities.theme import Theme
from johnston_core.infrastructure.tasks.manager import TaskManager
from johnston_core.infrastructure.tasks.shell_task import ShellTask
from johnston_core.infrastructure.tasks.task import BaseTask, TaskStatus
from johnston_core.theme_manager import ThemeManager
from johnston_core.tools.context import ToolContext
from johnston_core.tools.kill import KillTool
from johnston_tui.chat_toolcall import ToolCallWidget
from johnston_tui.mixins.message_flow_background import on_background_shell_completed, update_background_shell_widget
from johnston_tui.mixins.resize_debounce import ResizeDebounceMixin
from johnston_tui.presentation.screens.subagent_screen import SessionChatScreen
from johnston_tui.presentation.screens.tasks import ShellTasksScreen


class DummyTask(BaseTask):
    def __init__(self, task_id: str, status: TaskStatus = TaskStatus.RUNNING, is_running_val: bool = True):
        super().__init__(task_id, kind="shell", status=status)
        self._is_running_val = is_running_val
        self._done = asyncio.get_event_loop().create_future()

    def __repr__(self) -> str:
        return f"DummyTask({self.id})"

    @property
    def is_running(self) -> bool:
        return self._is_running_val

    async def read(self) -> str:
        return ""

    async def tail(self, max_chars: int = 4000) -> str:
        return ""

    async def kill(self) -> None:
        self._is_running_val = False
        self._status = TaskStatus.KILLED
        if not self._done.done():
            self._done.set_result(True)

    async def wait(self) -> None:
        await self._done


@pytest.mark.asyncio
async def test_shell_task_listeners_cleared_on_completion():
    """ShellTask._listeners should be cleared in _read finally."""
    task = ShellTask(task_id="t_test", command="echo 1", process=None)
    listener = MagicMock()
    task.add_listener(listener)
    assert listener in task._listeners

    # start_reading with mock process that exits immediately
    read_task = task.start_reading()
    await read_task
    assert len(task._listeners) == 0


@pytest.mark.asyncio
async def test_shell_task_listeners_cleared_on_kill():
    """ShellTask._listeners should be cleared in kill and kill_sync."""
    task = ShellTask(task_id="t_kill", command="sleep 10", process=None)
    listener = MagicMock()
    task.add_listener(listener)
    assert len(task._listeners) == 1
    await task.kill()
    assert len(task._listeners) == 0

    task2 = ShellTask(task_id="t_kill_sync", command="sleep 10", process=None)
    task2.add_listener(listener)
    assert len(task2._listeners) == 1
    task2.kill_sync()
    assert len(task2._listeners) == 0


@pytest.mark.asyncio
async def test_task_manager_prune_completed():
    """TaskManager limits completed tasks and prunes oldest when limit is exceeded."""
    mgr = TaskManager(max_completed=3)

    # Register 5 finished tasks
    tasks = []
    for i in range(5):
        t = DummyTask(f"t_{i}", status=TaskStatus.COMPLETED, is_running_val=False)
        t.completed_at = 100.0 + i
        tasks.append(t)
        mgr.register(t)

    # Should only keep the newest 3 completed tasks: t_2, t_3, t_4
    retained_ids = {t.id for t in mgr}
    assert retained_ids == {"t_2", "t_3", "t_4"}


@pytest.mark.asyncio
async def test_task_manager_auto_prunes_on_task_wait():
    """TaskManager._schedule_task_cleanup watches task and prunes when it finishes."""
    mgr = TaskManager(max_completed=1)
    t1 = DummyTask("t_done1", status=TaskStatus.RUNNING, is_running_val=True)
    t2 = DummyTask("t_done2", status=TaskStatus.RUNNING, is_running_val=True)
    mgr.register(t1)
    mgr.register(t2)

    # Finish t1
    await t1.kill()
    await asyncio.sleep(0.01)
    assert "t_done1" in mgr._tasks

    # Finish t2
    await t2.kill()
    await asyncio.sleep(0.01)
    # Max completed is 1, so t_done1 should have been dropped, t_done2 kept
    assert "t_done1" not in mgr._tasks
    assert "t_done2" in mgr._tasks


@pytest.mark.asyncio
async def test_kill_tool_teardown_widget():
    """kill tool ensures _background_shell_widgets is popped."""
    tool = KillTool()
    app = MagicMock()
    app._background_shell_widgets = {}

    widget = MagicMock()
    app._background_shell_widgets["t_bg"] = widget

    task = DummyTask("t_bg", status=TaskStatus.RUNNING, is_running_val=True)
    ctx = ToolContext(app=app)
    app.task_manager = [task]

    res = await tool.execute({"id": "t_bg"}, ctx=ctx)
    assert not res.is_error
    assert "t_bg" not in app._background_shell_widgets
    widget.set_result.assert_called_once()


def test_toolcall_widget_on_unmount_teardown():
    """ToolCallWidget.on_unmount removes self from host._background_shell_widgets."""
    app = MagicMock()
    w = ToolCallWidget(tool_type="shell", target="echo 1", background_task_id="bg_123")
    w._app = app
    app._background_shell_widgets = {"bg_123": w, "other": MagicMock()}

    w.on_unmount()
    assert "bg_123" not in app._background_shell_widgets
    assert "other" in app._background_shell_widgets


def test_update_background_shell_widget_always_pops():
    """update_background_shell_widget and on_background_shell_completed pop widget even on errors."""
    app = MagicMock()
    w = MagicMock()
    w.set_result.side_effect = RuntimeError("widget explode")
    app._background_shell_widgets = {"t_err": w}

    update_background_shell_widget(app, "t_err", "some output")
    assert "t_err" not in app._background_shell_widgets

    # on_background_shell_completed finally block
    app._background_shell_widgets = {"t_err2": w}
    app.is_app_active = False
    on_background_shell_completed(app, "t_err2", "cmd", "result")
    assert "t_err2" not in app._background_shell_widgets


@pytest.mark.asyncio
async def test_stream_runner_finally_cleanup_and_break_cycles():
    """stream_runner cleans _subagent_tools and nulls circular references even when suppressed."""
    subagent = MagicMock()

    async def fake_stream(_msg):
        if False:
            yield

    subagent.stream_steps = fake_stream
    subagent.is_subagent = True

    session = AgentSession(session_id="sub_sess_1", title="sub", prompt="p", status=SessionStatus.RUNNING)
    session.suppress_notification = True
    session.async_task = MagicMock()
    session.agent = subagent

    app = MagicMock()
    app._subagent_tools = {"sub_sess_1": MagicMock()}
    ctx = MagicMock()
    ctx.host = app

    store = MagicMock()

    await run_subagent_stream_bg(
        subagent=subagent,
        prompt_or_message="run",
        session=session,
        ctx=ctx,
        store=store,
        session_id="sub_sess_1",
    )

    # Verified _subagent_tools popped
    assert "sub_sess_1" not in app._subagent_tools
    # Verified cycles broken
    assert session.async_task is None
    assert session.agent is None
    assert getattr(subagent, "session", None) is None


def test_subagent_screen_expand_state_bounded():
    """SessionChatScreen bounds _subagent_expand_state and _subagent_plan_state to 50 items."""
    screen = SessionChatScreen("desc")
    app = MagicMock()
    app._subagent_expand_state = {f"sess_{i}": {1, 2} for i in range(60)}
    app._subagent_plan_state = {f"sess_{i}": {"is_expanded": True} for i in range(60)}
    screen._app = app
    screen.session = MagicMock()
    screen.session.id = "sess_current"

    screen._save_expand_state()
    assert len(app._subagent_expand_state) <= 50
    assert len(app._subagent_plan_state) <= 50


def test_subagent_screen_cancels_notch_task_on_unmount():
    """SessionChatScreen cancels _notch_task in on_unmount."""
    screen = SessionChatScreen("desc")
    mock_task = MagicMock()
    mock_task.done.return_value = False
    screen._notch_task = mock_task

    screen.on_unmount()
    mock_task.cancel.assert_called_once()
    assert screen._notch_task is None


def test_theme_manager_weakref_listener():
    """ThemeManager uses weakref and does not keep listener instances alive."""
    tm = ThemeManager(load_config=False, load_custom_themes=False)

    class ListenerWidget:
        def __init__(self):
            self.calls = 0

        def on_theme(self, _theme: Theme):
            self.calls += 1

    obj = ListenerWidget()
    tm.add_listener(obj.on_theme)
    tm.set_theme("charcoal", persist=False)
    assert obj.calls == 1

    # Delete obj and run garbage collection
    del obj
    gc.collect()

    # Listener should be automatically pruned
    tm.set_theme("zinc", persist=False)
    assert len([ref for ref in tm._listeners if tm._unwrap_listener(ref) is not None]) == 0


def test_theme_manager_safe_unsubscription():
    """ThemeManager.remove_listener is safe and does not raise on dead or missing listeners."""
    tm = ThemeManager(load_config=False, load_custom_themes=False)
    # Should not raise for unknown listener
    tm.remove_listener(lambda t: None)

    called = []
    def fn(t):
        called.append(t)

    tm.add_listener(fn)
    tm.remove_listener(fn)
    tm.set_theme("nord", persist=False)
    assert len(called) == 0


def test_resize_debounce_mixin_on_unmount_cancels_timer():
    """ResizeDebounceMixin.on_unmount cancels the pending resize timer."""
    class DebouncedWidget(ResizeDebounceMixin):
        def render_for_size(self):
            pass

    w = DebouncedWidget()
    mock_timer = MagicMock()
    w._resize_timer = mock_timer

    w.on_unmount()
    mock_timer.stop.assert_called_once()
    assert w._resize_timer is None


def test_shell_tasks_screen_sync_task_listeners_removes_completed():
    """ShellTasksScreen._sync_task_listeners unsubscribes and removes finished tasks from _observed_tasks."""
    screen = ShellTasksScreen()
    t_running = MagicMock()
    t_running.is_running = True
    t_finished = MagicMock()
    t_finished.is_running = False

    # Start with both observed
    screen._observed_tasks.add(t_running)
    screen._observed_tasks.add(t_finished)

    screen._sync_task_listeners([t_running, t_finished])

    # t_finished should have remove_listener called and removed from _observed_tasks
    t_finished.remove_listener.assert_called_once_with(screen._on_task_event)
    assert t_finished not in screen._observed_tasks
    assert t_running in screen._observed_tasks
