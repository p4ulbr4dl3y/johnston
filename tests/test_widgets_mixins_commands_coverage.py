"""Unit tests for UI commands, SessionPersistenceMixin, LifecycleMixin, and GitMetricsMixin."""

import asyncio
import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.app import App

from core.infrastructure.tasks.manager import TaskManager
from widgets.chat_input import DEFAULT_PLACEHOLDER
from widgets.git_metrics_mixin import GitMetricsMixin
from widgets.mixins.lifecycle import LifecycleMixin
from widgets.mixins.session_persistence import SessionPersistenceMixin
from widgets.presentation.commands.ui_commands import (
    CommandsCommand,
    CopyCommand,
    HelpCommand,
    KeybindsCommand,
    ThemeCommand,
)
from widgets.presentation.screens.help import HelpScreen
from widgets.presentation.screens.theme import ThemeScreen

# ============================================================================
# 1. UI Commands Tests
# ============================================================================


@pytest.mark.asyncio
async def test_help_command():
    cmd = HelpCommand()
    assert cmd.name == "/help"
    assert "/h" in cmd.aliases
    assert "/?" in cmd.aliases

    app = MagicMock()
    await cmd.execute(app)
    app.push_screen.assert_called_once()
    screen = app.push_screen.call_args[0][0]
    assert isinstance(screen, HelpScreen)
    assert screen.active_tab == 0


@pytest.mark.asyncio
async def test_commands_command():
    cmd = CommandsCommand()
    assert cmd.name == "/commands"
    assert "/cmds" in cmd.aliases

    app = MagicMock()
    await cmd.execute(app)
    app.push_screen.assert_called_once()
    screen = app.push_screen.call_args[0][0]
    assert isinstance(screen, HelpScreen)
    assert screen.active_tab == 0


@pytest.mark.asyncio
async def test_keybinds_command():
    cmd = KeybindsCommand()
    assert cmd.name == "/keybinds"
    assert "/keys" in cmd.aliases
    assert "/keybindings" in cmd.aliases
    assert "/shortcuts" in cmd.aliases

    app = MagicMock()
    await cmd.execute(app)
    app.push_screen.assert_called_once()
    screen = app.push_screen.call_args[0][0]
    assert isinstance(screen, HelpScreen)
    assert screen.active_tab == 1


@pytest.mark.asyncio
async def test_copy_command_success():
    cmd = CopyCommand()
    assert cmd.name == "/copy"
    assert "/cp" in cmd.aliases
    assert "/yank" in cmd.aliases

    app = MagicMock()
    chat_view = MagicMock()
    chat_view.get_last_bot_message_text.return_value = "Assistant response"
    app.query_one.return_value = chat_view

    await cmd.execute(app)
    app.copy_to_clipboard.assert_called_once_with("Assistant response")
    app.notify.assert_called_once_with("Copied to clipboard", severity="information", timeout=1.5)


@pytest.mark.asyncio
async def test_copy_command_no_text():
    cmd = CopyCommand()
    app = MagicMock()
    chat_view = MagicMock()
    chat_view.get_last_bot_message_text.return_value = ""
    app.query_one.return_value = chat_view

    await cmd.execute(app)
    app.notify.assert_called_once_with("No assistant response to copy", severity="warning")


@pytest.mark.asyncio
async def test_copy_command_exception():
    cmd = CopyCommand()
    app = MagicMock()
    app.query_one.side_effect = RuntimeError("chat view missing")

    await cmd.execute(app)
    app.notify.assert_called_once_with("Failed to copy assistant response", severity="error")


@pytest.mark.asyncio
async def test_copy_command_no_notify_attr():
    cmd = CopyCommand()
    app = MagicMock(spec=["query_one", "copy_to_clipboard"])
    chat_view = MagicMock()
    chat_view.get_last_bot_message_text.return_value = "Hello"
    app.query_one.return_value = chat_view

    await cmd.execute(app)
    app.copy_to_clipboard.assert_called_once_with("Hello")

    # Empty text without notify attr
    chat_view.get_last_bot_message_text.return_value = ""
    await cmd.execute(app)

    # Exception without notify attr
    app.query_one.side_effect = RuntimeError("fail")
    await cmd.execute(app)


@pytest.mark.asyncio
async def test_theme_command_execution_and_callbacks():
    cmd = ThemeCommand()
    assert cmd.name == "/theme"
    assert "/themes" in cmd.aliases
    assert "/color" in cmd.aliases
    assert "/colors" in cmd.aliases

    app = MagicMock()
    input_mock = MagicMock()
    app.query_one.return_value = input_mock

    await cmd.execute(app)
    assert app.push_screen.called
    screen, kwargs = app.push_screen.call_args[0][0], app.push_screen.call_args[1]
    assert isinstance(screen, ThemeScreen)
    callback = kwargs["callback"]

    # 1. Selected is None
    callback(None)
    input_mock.focus.assert_called_once()

    # 2. Selected is None and query_one raises Exception
    app.query_one.side_effect = RuntimeError("input missing")
    callback(None)  # Should not raise

    # Reset query_one
    app.query_one.side_effect = None
    app.query_one.return_value = input_mock

    # 3. Selected valid theme with set_app_theme on app
    from widgets.app.theme_manager import theme_manager

    valid_theme_name = theme_manager.current_theme.name
    callback(valid_theme_name)
    app.set_app_theme.assert_called_once_with(valid_theme_name, persist=True)

    # 4. Selected valid theme WITHOUT set_app_theme on app
    app_no_set = MagicMock(spec=["query_one", "theme", "refresh_css", "push_screen"])
    app_no_set.query_one.return_value = input_mock
    await cmd.execute(app_no_set)
    callback2 = app_no_set.push_screen.call_args[1]["callback"]
    callback2(valid_theme_name)
    assert app_no_set.theme == valid_theme_name
    app_no_set.refresh_css.assert_called_once()

    # 5. Selected unknown theme (theme_manager.get returns None)
    callback2("non_existent_theme_xyz")

    # 6. Selected with query_one raising exception at end
    app_no_set.query_one.side_effect = RuntimeError("focus failed")
    callback2(valid_theme_name)  # Should not raise


# ============================================================================
# 2. SessionPersistenceMixin Tests
# ============================================================================


class DummySessionPersistenceApp(SessionPersistenceMixin):
    def __init__(self):
        self.sm = MagicMock()
        self.pm = MagicMock()
        self.agent = None
        self.role = "worker"
        self.current_session_id = None
        self.is_read_only = False
        self.task_manager = TaskManager()
        self._last_session_save_time = 0.0
        self._notified = []
        self._status_refreshed = False
        self._workers = []

    def notify(self, message: str, severity: str = "information"):
        self._notified.append((message, severity))

    def refresh_status_footer(self):
        self._status_refreshed = True

    def run_worker(self, coro):
        self._workers.append(coro)
        return coro


@pytest.mark.asyncio
async def test_session_persistence_load_ui_not_found():
    app = DummySessionPersistenceApp()
    app.sm.get.return_value = None
    app.load_session_ui("missing_session")
    assert app.current_session_id is None


@pytest.mark.asyncio
async def test_session_persistence_load_ui_full_flow():
    app = DummySessionPersistenceApp()
    app.current_session_id = "old_session"

    session = MagicMock()
    session.role = "tester"
    session.messages = [
        {"type": "user", "text": "hello"},
        {"type": "bot", "text": "world"},
        "invalid_msg_type",  # To test if not isinstance(msg, dict): continue
    ]
    session.agent_history = [{"role": "user", "content": "hi"}]
    session.tokens_input = 10
    session.tokens_output = 20
    session.total_tokens = 30
    session.cost_usd = 0.05
    session.tokens_cache_read = 5
    session.last_context_tokens = 50

    app.sm.get.return_value = session
    chat_input = MagicMock()
    chat_view = MagicMock()
    chat_view.children = [MagicMock(), MagicMock()]
    chat_view.PAGE_SIZE = 50
    chat_view.call_after_refresh = lambda cb: cb()

    def mock_query(target, default=None):
        if target == "#message-input":
            return chat_input
        return chat_view

    app.query_one = mock_query

    with patch(
        "widgets.presentation.widgets.chat_container.restore_message_item",
        new_callable=AsyncMock,
    ) as mock_restore:
        # Load session UI (read_only=False)
        app.load_session_ui("new_session", read_only=False)

        app.sm.release_session_lock.assert_called_once_with("old_session")
        app.sm.acquire_session_lock.assert_called_once_with("new_session")
        app.sm.set_active_session_id.assert_called_once_with("new_session")
        assert chat_input.placeholder == DEFAULT_PLACEHOLDER
        assert app.current_session_id == "new_session"

        # Agent was created
        assert app.agent is not None
        assert app.agent.role == "tester"
        assert app.role == "tester"
        assert app.agent.history == session.agent_history
        assert app.agent.last_context_tokens == 50

        # Run the restoration worker coroutine
        assert len(app._workers) == 1
        worker_coro = app._workers[0]
        await worker_coro
        assert mock_restore.call_count == 2
        chat_view.check_welcome.assert_called_once()
        chat_view.scroll_end.assert_called_once_with(animate=False)


@pytest.mark.asyncio
async def test_session_persistence_load_ui_read_only_and_pagination():
    app = DummySessionPersistenceApp()
    app.current_session_id = None

    session = MagicMock()
    session.role = None
    session.messages = [{"type": "user", "text": f"msg_{i}"} for i in range(60)]
    session.agent_history = []
    session.tokens_input = 0
    session.tokens_output = 0
    session.total_tokens = 0
    session.cost_usd = 0.0
    session.tokens_cache_read = 0
    session.last_context_tokens = 0

    app.sm.get.return_value = session
    chat_input = MagicMock()
    chat_view = MagicMock()
    chat_view.children = []
    chat_view.PAGE_SIZE = 50

    def mock_query(target, default=None):
        if target == "#message-input":
            return chat_input
        return chat_view

    app.query_one = mock_query

    # Test create_active_agent exception handling
    app.pm.create_active_agent.side_effect = RuntimeError("agent creation failed")

    with patch(
        "widgets.presentation.widgets.chat_container.restore_message_item",
        new_callable=AsyncMock,
    ) as mock_restore:
        app.load_session_ui("ro_session", read_only=True)

        assert app.is_read_only is True
        assert chat_input.placeholder == "Type a message to fork & continue..."
        assert app.agent is None

        worker_coro = app._workers[0]
        await worker_coro
        assert len(chat_view._unloaded_messages) == 10
        assert mock_restore.call_count == 50


@pytest.mark.asyncio
async def test_session_persistence_load_ui_recompute_context_tokens_and_call_after_refresh():
    app = DummySessionPersistenceApp()
    session = MagicMock()
    session.role = None
    session.messages = []
    session.agent_history = [{"role": "user", "content": "hi"}]
    session.last_context_tokens = 0

    app.sm.get.return_value = session
    agent = MagicMock()
    agent.history = session.agent_history
    app.pm.create_active_agent.return_value = agent
    app.agent = None

    chat_input = MagicMock()
    chat_view = MagicMock()
    chat_view.children = []
    chat_view.PAGE_SIZE = 50
    finish_callbacks = []
    chat_view.call_after_refresh = lambda cb: finish_callbacks.append(cb)

    def mock_query(target, default=None):
        if target == "#message-input":
            return chat_input
        return chat_view

    app.query_one = mock_query

    with patch("widgets.app.session_state.recompute_context_tokens", return_value=42) as mock_recompute:
        with patch("widgets.presentation.widgets.chat_container.restore_message_item", new_callable=AsyncMock):
            app.load_session_ui("ctx_session")
            assert mock_recompute.called
            assert app.agent.last_context_tokens == 42
            assert app.agent.role == "worker"
            assert app.role == "worker"

    worker_coro = app._workers[0]
    await worker_coro
    assert len(finish_callbacks) == 1
    finish_callbacks[0]()
    assert chat_view._is_loading_session is False


@pytest.mark.asyncio
async def test_session_persistence_load_ui_item_restore_error_and_outer_error():
    app = DummySessionPersistenceApp()
    session = MagicMock()
    session.messages = [{"type": "bad"}]
    session.agent_history = []
    app.sm.get.return_value = session

    chat_view = MagicMock()
    chat_view.children = []
    app.query_one = lambda target, default=None: chat_view if target != "#message-input" else MagicMock()

    # Item restore raises exception
    with patch(
        "widgets.presentation.widgets.chat_container.restore_message_item",
        side_effect=RuntimeError("item error"),
    ):
        app.load_session_ui("err_session")
        worker_coro = app._workers[0]
        await worker_coro  # Logs warning, does not crash

    # Outer error in _restore_messages (e.g. msgs generator raises)
    app._workers.clear()

    class BadMessages:
        def __iter__(self):
            raise RuntimeError("bad iterable")

    session.messages = BadMessages()
    app.load_session_ui("bad_msgs_session")
    worker_coro = app._workers[0]
    await worker_coro
    assert any("UI restoration failed" in n[0] for n in app._notified)


def test_session_persistence_write_session_data_new_and_modified():
    app = DummySessionPersistenceApp()
    app.current_session_id = "sess_write"
    app.is_read_only = False

    session_mock = MagicMock()
    session_mock.title = "Old Title"
    session_mock.role = "worker"
    session_mock.messages = []
    session_mock.agent_history = []
    session_mock.tokens_input = 0
    session_mock.tokens_output = 0
    session_mock.total_tokens = 0
    session_mock.cost_usd = 0.0
    session_mock.last_context_tokens = 0
    session_mock.tokens_cache_read = 0

    app.sm.get.return_value = session_mock

    data = {
        "title": "New Title",
        "role": "tester",
        "messages": [{"type": "user", "text": "hi"}],
        "agent_history": [{"role": "user", "content": "hi"}],
        "tokens_input": 100,
        "tokens_output": 200,
        "total_tokens": 300,
        "cost_usd": 0.01,
        "last_context_tokens": 150,
        "tokens_cache_read": 50,
    }

    app._write_session_data(data)

    assert session_mock.title == "New Title"
    assert session_mock.role == "tester"
    assert session_mock.tokens_input == 100
    assert session_mock.tokens_output == 200
    assert session_mock.total_tokens == 300
    assert session_mock.cost_usd == 0.01
    assert session_mock.last_context_tokens == 150
    assert session_mock.tokens_cache_read == 50
    session_mock.touch.assert_called_once()
    app.sm.save.assert_called_once_with(session_mock)
    app.sm.set_active_session_id.assert_called_once_with("sess_write")


def test_session_persistence_write_session_data_read_only_and_unchanged():
    app = DummySessionPersistenceApp()
    app.current_session_id = "sess_ro"
    app.is_read_only = True

    # When read_only is True, _write_session_data should return immediately
    app._write_session_data({"title": "Test"})
    app.sm.save.assert_not_called()

    # When not read_only, and nothing changed
    app.is_read_only = False
    session_mock = MagicMock()
    session_mock.title = "Same Title"
    session_mock.role = "worker"
    session_mock.messages = []
    session_mock.agent_history = []
    session_mock.tokens_input = 0
    session_mock.tokens_output = 0
    session_mock.total_tokens = 0
    session_mock.cost_usd = 0.0
    session_mock.last_context_tokens = 0
    session_mock.tokens_cache_read = 0

    app.sm.get.return_value = session_mock
    app._write_session_data(
        {
            "title": "Same Title",
            "role": "worker",
            "messages": [],
            "agent_history": [],
            "tokens_input": 0,
            "tokens_output": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
            "last_context_tokens": 0,
            "tokens_cache_read": 0,
        }
    )
    session_mock.touch.assert_not_called()
    app.sm.save.assert_not_called()


def test_session_persistence_save_current_session():
    app = DummySessionPersistenceApp()
    app.current_session_id = "sess_save"
    data = {"title": "Saved"}

    with patch.object(app, "_get_current_session_data", return_value=data):
        with patch.object(app, "_write_session_data") as mock_write:
            app.save_current_session()
            mock_write.assert_called_once_with(data)
            assert app._status_refreshed is True


@pytest.mark.asyncio
async def test_session_persistence_save_current_session_async():
    app = DummySessionPersistenceApp()
    app.current_session_id = "sess_async"
    app._last_session_save_time = time.time()

    # Throttled when not forced
    with patch.object(app, "_get_current_session_data", return_value={"title": "Async"}):
        with patch.object(app, "_write_session_data") as mock_write:
            await app.save_current_session_async(force=False)
            mock_write.assert_not_called()

            # Forced save
            await app.save_current_session_async(force=True)
            mock_write.assert_called_once_with({"title": "Async"})
            assert app._status_refreshed is True


def test_session_persistence_get_resume_hint():
    app = DummySessionPersistenceApp()

    # No current session
    app.current_session_id = None
    assert app.get_resume_hint() is None

    # No SM
    app.current_session_id = "s1"
    app.sm = None
    assert app.get_resume_hint() is None

    # Session with messages
    app.sm = MagicMock()
    sess = MagicMock()
    sess.messages = ["msg1"]
    sess.agent_history = []
    app.sm.get.return_value = sess
    assert app.get_resume_hint() == "johnston --resume s1"

    # Session with agent history
    sess.messages = []
    sess.agent_history = [{"role": "user"}]
    assert app.get_resume_hint() == "johnston --resume s1"

    # Empty session
    sess.messages = []
    sess.agent_history = []
    assert app.get_resume_hint() is None

    # SM exception
    app.sm.get.side_effect = RuntimeError("db error")
    assert app.get_resume_hint() is None


# ============================================================================
# 3. LifecycleMixin Tests
# ============================================================================


class DummyLifecycleApp(LifecycleMixin):
    def __init__(self):
        self.sm = MagicMock()
        self.pm = MagicMock()
        self.agent = MagicMock()
        self.task_manager = TaskManager()
        self.current_session_id = None
        self.resume_session_id = None
        self.is_app_active = False
        self._tracked_tasks = []
        self._pushed_screens = []
        self._status_refreshed = False
        self.available_themes = {}
        self.theme = "default"

    def register_theme(self, theme):
        self.available_themes[theme.name] = theme

    def query_one(self, target, default=None):
        return MagicMock()

    def push_screen(self, screen, callback=None):
        self._pushed_screens.append((screen, callback))
        if callback:
            callback(None)

    def load_session_ui(self, session_id: str, read_only: bool = False):
        pass

    def save_current_session(self):
        pass

    def refresh_status_footer(self):
        self._status_refreshed = True

    def create_tracked_task(self, coro):
        self._tracked_tasks.append(coro)
        return coro


class AppForCompose(LifecycleMixin, App):
    """App subclass with bypassed on_mount to test compose()."""

    def on_mount(self) -> None:
        pass


@pytest.mark.asyncio
async def test_lifecycle_compose():
    app = AppForCompose()
    async with app.run_test():
        assert app.query_one("#app-container") is not None
        assert app.query_one("#chat-view") is not None
        assert app.query_one("#command-suggestions") is not None
        assert app.query_one("#attachment-bar") is not None
        assert app.query_one("#message-input") is not None
        assert app.query_one("#status-footer") is not None


def test_lifecycle_on_mount_normal_flow():
    app = DummyLifecycleApp()
    app.current_session_id = "curr_1"

    with patch("widgets.mixins.lifecycle.install_asyncio_exception_handler") as mock_install:
        with patch("core.models_catalog.catalog.load_cache") as mock_cache:
            with patch("core.infrastructure.mcp.get_mcp_manager") as mock_mcp:
                mcp_mock = MagicMock()
                mcp_mock.ensure_tools_ready_async.return_value = AsyncMock()()
                mock_mcp.return_value = mcp_mock

                app.on_mount()

                mock_install.assert_called_once()
                mock_cache.assert_called_once()
                assert app.is_app_active is True
                app.sm.acquire_session_lock.assert_called_once_with("curr_1")
                assert app._status_refreshed is True
                assert len(app._tracked_tasks) == 2

                # Trigger theme listener
                app._theme_listener(None)


def test_lifecycle_on_mount_resume_session_locked_steal_and_readonly():
    from widgets.presentation.screens.session_conflict import SessionConflictScreen

    app = DummyLifecycleApp()
    app.resume_session_id = "res_1"
    app.sm.is_session_locked.return_value = True

    with patch.object(app, "load_session_ui") as mock_load_ui:
        with patch("widgets.mixins.lifecycle.install_asyncio_exception_handler"):
            with patch("core.models_catalog.catalog.load_cache"):
                with patch("core.infrastructure.mcp.get_mcp_manager"):
                    # Custom push_screen to capture callback
                    callbacks = []
                    app.push_screen = lambda s, callback=None: callbacks.append((s, callback))

                    app.on_mount()

                    assert len(callbacks) == 1
                    screen, callback = callbacks[0]
                    assert isinstance(screen, SessionConflictScreen)

                    # 1. Steal choice
                    callback("steal")
                    app.sm.steal_session_lock.assert_called_once_with("res_1")
                    mock_load_ui.assert_called_with("res_1")

                    # 2. Readonly choice
                    callback("readonly")
                    mock_load_ui.assert_called_with("res_1", read_only=True)

                    # 3. None / other choice (cancel/esc)
                    app.notify = MagicMock()
                    app.sm.generate_session_id.return_value = "new_sess_fallback"
                    callback(None)
                    assert app.current_session_id == "new_sess_fallback"
                    assert app.is_read_only is False
                    app.sm.acquire_session_lock.assert_called_with("new_sess_fallback")
                    app.sm.set_active_session_id.assert_called_with("new_sess_fallback")


def test_lifecycle_on_mount_resume_session_empty_picker():
    app = DummyLifecycleApp()
    app.resume_session_id = ""
    app.current_session_id = "curr_1"

    with patch("widgets.presentation.commands.ResumeCommand.execute") as mock_resume_exec:
        with patch("widgets.mixins.lifecycle.install_asyncio_exception_handler"):
            with patch("core.models_catalog.catalog.load_cache"):
                with patch("core.infrastructure.mcp.get_mcp_manager"):
                    app.on_mount()
                    app.sm.acquire_session_lock.assert_called_with("curr_1")
                    assert len(app._tracked_tasks) >= 1
                    mock_resume_exec.assert_called_once_with(app)


def test_lifecycle_on_mount_resume_session_unlocked():
    app = DummyLifecycleApp()
    app.resume_session_id = "res_2"
    app.sm.is_session_locked.return_value = False

    with patch.object(app, "load_session_ui") as mock_load_ui:
        with patch("widgets.mixins.lifecycle.install_asyncio_exception_handler"):
            with patch("core.models_catalog.catalog.load_cache"):
                with patch("core.infrastructure.mcp.get_mcp_manager"):
                    app.on_mount()
                    mock_load_ui.assert_called_once_with("res_2")


@pytest.mark.asyncio
async def test_lifecycle_check_initial_setup_variations():
    app = DummyLifecycleApp()
    app.is_app_active = True

    # 1. If resume_session_id is set -> skips
    app.resume_session_id = "some_id"
    await app._check_initial_setup()

    app.resume_session_id = None

    # 2. In pytest env without patch -> skips
    await app._check_initial_setup()

    # Unset PYTEST_CURRENT_TEST to test setup triggers
    with patch.dict(os.environ, {}, clear=True):
        # 3. No active key or disconnected provider -> triggers ProvidersCommand
        app.pm.get_active_provider_key.return_value = "anthropic"
        app.pm.is_provider_connected.return_value = False

        with patch("widgets.presentation.commands.ProvidersCommand.execute", new_callable=AsyncMock) as mock_prov_cmd:
            await app._check_initial_setup()
            mock_prov_cmd.assert_called_once_with(app)

        # App became inactive during check
        app.is_app_active = False
        with patch("widgets.presentation.commands.ProvidersCommand.execute", new_callable=AsyncMock) as mock_prov_cmd:
            await app._check_initial_setup()
            mock_prov_cmd.assert_not_called()

        app.is_app_active = True
        app.pm.is_provider_connected.return_value = True

        # 4. Connected but no agent model -> triggers ModelsCommand
        app.agent.model = ""
        with patch("widgets.presentation.commands.ModelsCommand.execute", new_callable=AsyncMock) as mock_models_cmd:
            await app._check_initial_setup()
            mock_models_cmd.assert_called_once_with(app)

        # 5. Connected and has agent model -> does nothing
        app.agent.model = "claude-3-opus"
        with patch("widgets.presentation.commands.ModelsCommand.execute", new_callable=AsyncMock) as mock_models_cmd:
            await app._check_initial_setup()
            mock_models_cmd.assert_not_called()


def test_lifecycle_on_unmount_full_flow():
    app = DummyLifecycleApp()
    app.is_app_active = True
    app._theme_listener = MagicMock()

    # In-flight git restore task
    git_task = MagicMock()
    git_task.done.return_value = False
    app.agent.rewind_git_restore_task = git_task

    with patch("widgets.app.theme_manager.theme_manager.remove_listener") as mock_rm_listener:
        with patch("core.application.session.stream.cancel_running_subagents") as mock_subagents:
            with patch.object(app, "save_current_session") as mock_save:
                with patch("core.infrastructure.mcp.get_mcp_manager") as mock_mcp:
                    with patch("core.models_catalog.catalog.close", new_callable=AsyncMock):
                        with patch("tools.registry.aclose_tools", return_value=AsyncMock()()):
                            app.on_unmount()

                            assert app.is_app_active is False
                            mock_rm_listener.assert_called_once_with(app._theme_listener)
                            git_task.cancel.assert_called_once()
                            mock_subagents.assert_called_once_with(app.sm)
                            mock_save.assert_called_once()
                            mock_mcp.return_value.stop_all.assert_called_once()
                            app.sm.release_all_locks.assert_called_once()


@pytest.mark.asyncio
async def test_lifecycle_kill_all_tasks():
    app = DummyLifecycleApp()
    app.task_manager = MagicMock()
    app.task_manager.kill_all = AsyncMock()

    await app._kill_all_tasks()
    app.task_manager.kill_all.assert_called_once()

    # Exception handled
    app.task_manager.kill_all.side_effect = RuntimeError("kill failed")
    await app._kill_all_tasks()  # Should not raise


def test_lifecycle_kill_all_tasks_sync():
    app = DummyLifecycleApp()

    class DummySyncTask:
        def __init__(self):
            self.killed = False

        def kill_sync(self):
            self.killed = True

    class DummyAsyncTask:
        def __init__(self):
            self.killed = False

        async def kill(self):
            self.killed = True

    class DummyCallableTask:
        def __init__(self):
            self.killed = False

        def kill(self):
            self.killed = True

    class DummyErrorTask:
        def kill_sync(self):
            raise RuntimeError("err")

    t1 = DummySyncTask()
    t2 = DummyCallableTask()
    t3 = DummyAsyncTask()
    t4 = DummyErrorTask()

    app.task_manager = [t1, t2, t3, t4]

    app._kill_all_tasks_sync()
    assert t1.killed is True
    assert t2.killed is True


def test_lifecycle_refresh_status_footer_exception():
    app = DummyLifecycleApp()
    app.query_one = MagicMock(side_effect=RuntimeError("footer missing"))
    app.refresh_status_footer()  # Should not raise


# ============================================================================
# 4. GitMetricsMixin Tests
# ============================================================================


class DummyGitWidget(GitMetricsMixin):
    def __init__(self):
        self.is_mounted = True
        self._diff_updated_called = 0

    def _on_diff_updated(self):
        super()._on_diff_updated()
        self._diff_updated_called += 1


def test_git_metrics_branch_cached_and_sync():
    widget = DummyGitWidget()

    # Cached value valid
    widget._branch_text = "main"
    widget._branch_cwd = "/repo"
    widget._branch_time = time.time()
    assert widget._git_branch("/repo") == "main"

    # Branch currently loading -> returns last known or empty string
    widget._branch_loading = True
    assert widget._git_branch("/repo") == "main"
    widget._branch_text = None
    assert widget._git_branch("/repo") == ""
    widget._branch_loading = False

    # Sync branch computation fallback (RuntimeError on loop)
    with patch("asyncio.get_running_loop", side_effect=RuntimeError):
        with patch.object(widget, "_compute_branch_sync", return_value="feature-x"):
            branch = widget._git_branch("/repo2")
            assert branch == "feature-x"
            assert widget._branch_text == "feature-x"
            assert widget._branch_loading is False


@pytest.mark.asyncio
async def test_git_metrics_branch_async_flow():
    widget = DummyGitWidget()

    with patch.object(widget, "_compute_branch_sync", return_value="detached (abc1234)"):
        await widget._compute_branch_async("/repo")
        assert widget._branch_text == "detached (abc1234)"
        assert widget._branch_loading is False
        assert widget._diff_updated_called == 1


def test_git_metrics_compute_branch_sync_variants():
    widget = DummyGitWidget()

    with patch("core.application.generation.prompt_builder.get_git_info", return_value="detached HEAD (1234567)"):
        assert widget._compute_branch_sync() == "detached (1234567)"

    with patch("core.application.generation.prompt_builder.get_git_info", return_value="main\n"):
        assert widget._compute_branch_sync() == "main"

    with patch("core.application.generation.prompt_builder.get_git_info", side_effect=Exception("git error")):
        assert widget._compute_branch_sync() == ""


def test_git_metrics_diff_stats_cached_and_sync():
    widget = DummyGitWidget()

    # Cached value valid
    widget._diff_text = "+10 / -5"
    widget._diff_cwd = "/repo"
    widget._diff_time = time.time()
    assert widget._git_diff_stats("/repo") == "+10 / -5"

    # Diff currently loading -> returns last known or empty string
    widget._diff_loading = True
    assert widget._git_diff_stats("/repo") == "+10 / -5"
    widget._diff_text = None
    assert widget._git_diff_stats("/repo") == ""
    widget._diff_loading = False

    # Sync diff computation fallback (RuntimeError on loop)
    with patch("asyncio.get_running_loop", side_effect=RuntimeError):
        with patch.object(widget, "_compute_diff_sync", return_value="+2 / -1"):
            diff = widget._git_diff_stats("/repo2")
            assert diff == "+2 / -1"
            assert widget._diff_text == "+2 / -1"
            assert widget._diff_loading is False


@pytest.mark.asyncio
async def test_git_metrics_diff_async_flow():
    widget = DummyGitWidget()

    with patch.object(widget, "_compute_diff_sync", return_value="+8 / -3"):
        await widget._compute_diff_async("/repo")
        assert widget._diff_text == "+8 / -3"
        assert widget._diff_loading is False
        assert widget._diff_updated_called == 1


def test_git_metrics_compute_diff_sync_subprocess():
    widget = DummyGitWidget()

    # 1. git diff HEAD succeeds
    res_head = MagicMock()
    res_head.returncode = 0
    res_head.stdout = "5\t2\tfile.py\ninvalid_line\nfoo\tbar\tfile2.py\n3\t0\tfile3.py\n"

    with patch("subprocess.run", return_value=res_head):
        diff = widget._compute_diff_sync("/repo")
        assert diff == "+8 / -2"

    # 2. git diff HEAD fails (returncode!=0), git diff fallback succeeds
    res_fail = MagicMock(returncode=1, stdout="")
    res_fallback = MagicMock(returncode=0, stdout="1\t4\tfile.py\n")

    with patch("subprocess.run", side_effect=[res_fail, res_fallback]):
        diff = widget._compute_diff_sync("/repo")
        assert diff == "+1 / -4"

    # 3. Both fail or no output
    with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="")):
        assert widget._compute_diff_sync("/repo") == ""

    # 4. Subprocess raises Exception
    with patch("subprocess.run", side_effect=Exception("subp error")):
        assert widget._compute_diff_sync("/repo") == ""


# ============================================================================
# 5. Additional Edge Cases & Uncovered Branches
# ============================================================================


@pytest.mark.asyncio
async def test_session_persistence_edge_cases():
    app = DummySessionPersistenceApp()

    # 1. query_one for input raises Exception in load_session_ui
    session = MagicMock()
    session.role = "admin"
    session.messages = []
    session.agent_history = []
    session.last_context_tokens = 0
    app.sm.get.return_value = session

    chat_view = MagicMock()
    chat_view.children = []
    chat_view.PAGE_SIZE = 50

    def mock_query(target, default=None):
        if target == "#message-input":
            raise RuntimeError("input not found")
        return chat_view

    app.query_one = mock_query

    with patch("widgets.presentation.widgets.chat_container.restore_message_item", new_callable=AsyncMock):
        # agent is None and session has role
        app.agent = None
        app.pm = None
        app.load_session_ui("s_no_input")
        assert app.role == "admin"

    # 2. _finish_session_load when scroll_end and call_after_refresh raise
    chat_view.scroll_end.side_effect = RuntimeError("scroll error")
    chat_view.call_after_refresh.side_effect = RuntimeError("refresh error")
    worker_coro = app._workers[-1]
    await worker_coro

    # 3. _finish_session_load when chat_view has no call_after_refresh
    chat_view_no_refresh = MagicMock(spec=["scroll_end", "children", "PAGE_SIZE", "loading", "_is_loading_session", "check_welcome"])
    chat_view_no_refresh.children = []
    chat_view_no_refresh.PAGE_SIZE = 50
    app.query_one = lambda target, default=None: chat_view_no_refresh
    app.load_session_ui("s_no_refresh")
    worker_coro2 = app._workers[-1]
    await worker_coro2
    assert chat_view_no_refresh._is_loading_session is False

    # 4. _restore_messages outer exception when notify also raises
    class BadIterable:
        def __iter__(self):
            raise RuntimeError("iteration failed")

    session.messages = BadIterable()
    app.notify = MagicMock(side_effect=RuntimeError("notify failed"))
    app.load_session_ui("s_bad_iter")
    worker_coro3 = app._workers[-1]
    await worker_coro3  # Should not raise

    # 5. _get_current_session_data
    with patch("widgets.app.session_state.collect_session_data", return_value={"test": 123}) as mock_collect:
        data = app._get_current_session_data()
        assert data == {"test": 123}
        mock_collect.assert_called_once_with(app)


def test_lifecycle_on_unmount_sync_and_error_handling():
    app = DummyLifecycleApp()
    app.is_app_active = True
    app._theme_listener = MagicMock()

    # 1. No running event loop fallback
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        with patch.object(app, "_kill_all_tasks_sync") as mock_kill_sync:
            with patch("widgets.app.theme_manager.theme_manager.remove_listener", side_effect=RuntimeError("theme err")):
                with patch("core.application.session.stream.cancel_running_subagents", side_effect=RuntimeError("subagent err")):
                    with patch.object(app, "save_current_session", side_effect=RuntimeError("save err")):
                        with patch("core.infrastructure.mcp.get_mcp_manager", side_effect=RuntimeError("mcp err")):
                            with patch("core.models_catalog.catalog.close", new_callable=AsyncMock):
                                with patch("tools.registry.aclose_tools") as mock_aclose:
                                    mock_aclose.return_value = AsyncMock()()
                                    app.sm.release_all_locks.side_effect = RuntimeError("locks err")

                                    app.on_unmount()
                                    mock_kill_sync.assert_called_once()


def test_lifecycle_on_unmount_tools_close_scheduling_failure():
    app = DummyLifecycleApp()
    app.is_app_active = True

    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        with patch("widgets.mixins.lifecycle._close_tools_sync", side_effect=RuntimeError("close error")) as mock_close:
            app.on_unmount()
            mock_close.assert_called_once()


def test_lifecycle_remaining_branches():
    app = DummyLifecycleApp()

    # 1. line 84: is_app_active becomes False right inside get_active_provider_key
    app.is_app_active = True

    def toggle_inactive():
        app.is_app_active = False
        return None

    app.pm.get_active_provider_key.side_effect = toggle_inactive

    async def run_setup_inactive():
        with patch.dict(os.environ, {}, clear=True):
            await LifecycleMixin._check_initial_setup(app)

    asyncio.run(run_setup_inactive())

    # 2. lines 119-120: _kill_all_tasks_sync raises exception during on_unmount
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        with patch.object(app, "_kill_all_tasks_sync", side_effect=RuntimeError("kill err")):
            app.on_unmount()

    # 3. lines 150-151: catalog cleanup outer error when loop is running but close fails
    mock_loop = MagicMock()
    mock_loop.is_running.return_value = True
    mock_loop.create_task.side_effect = RuntimeError("task creation failed")
    with patch("asyncio.get_running_loop", return_value=mock_loop):
        app.on_unmount()

    # 4. lines 194-195: task with _mock_return_value and kill_sync
    mock_task = MagicMock()
    mock_task.kill = None
    del mock_task.kill  # Ensure kill is not callable
    mock_task._mock_return_value = True
    app.task_manager = [mock_task]
    LifecycleMixin._kill_all_tasks_sync(app)
    mock_task.kill_sync.assert_called_once()

    # 5. lines 204-205: footer.refresh_footer raises Exception
    footer_mock = MagicMock()
    footer_mock.refresh_footer.side_effect = RuntimeError("footer error")
    app.query_one = MagicMock(return_value=footer_mock)
    LifecycleMixin.refresh_status_footer(app)



def test_git_metrics_diff_and_branch_update_exceptions():
    widget = DummyGitWidget()

    # _on_diff_updated raises exception during _compute_branch_async
    widget._on_diff_updated = MagicMock(side_effect=RuntimeError("update error"))

    async def run_branch_and_diff():
        with patch.object(widget, "_compute_branch_sync", return_value="main"):
            await widget._compute_branch_async("/repo")

        with patch.object(widget, "_compute_diff_sync", return_value="+1 / -1"):
            await widget._compute_diff_async("/repo")

    asyncio.run(run_branch_and_diff())
    assert widget._branch_text == "main"
    assert widget._diff_text == "+1 / -1"

    # When widget is not mounted -> does not call _on_diff_updated
    widget.is_mounted = False
    widget._on_diff_updated.reset_mock()
    asyncio.run(run_branch_and_diff())
    widget._on_diff_updated.assert_not_called()

