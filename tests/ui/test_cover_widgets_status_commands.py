"""Coverage-focused pure unit tests for widgets/commands.py, status_state.py,
patch.py, status_footer.py and command_suggestions.py.

These tests target branch/exception paths that the general UI suites skip.
They use lightweight fakes/harnesses and avoid mounting Textual apps unless a
code path (e.g. patch.py monkeypatching) genuinely requires real Textual types.
"""
import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from rich.console import Console
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.app import App, ComposeResult
from textual.geometry import Offset
from textual.screen import Screen
from textual.selection import Selection
from textual.strip import Strip
from textual.visual import RichVisual
from textual.widget import Widget
from textual.widgets import Static

from widgets.app.status_state import (
    _ensure_cache,
    build_status_kwargs,
    build_subagent_status_kwargs,
    refresh_footer_cache,
)
from widgets.command_suggestions import CommandSuggestions
from widgets.commands import (
    BaseCommand,
    CompactCommand,
    ModelsCommand,
    PermissionsCommand,
    ProvidersCommand,
    QuestionsCommand,
    ResumeCommand,
    RewindCommand,
    SkillsCommand,
    SubagentsCommand,
    ThinkingEffortCommand,
)
from widgets.patch import apply_textual_patches
from widgets.status_footer import StatusFooter, SubagentStatusFooter, format_display_path


# ---------------------------------------------------------------------------
# widgets/commands.py
# ---------------------------------------------------------------------------
class MockInput:
    def __init__(self):
        self.text = ""

    def load_text(self, txt):
        self.text = txt

    def move_cursor(self, pos):
        self.cursor = pos

    def focus(self):
        self.focused = True


class SimpleApp:
    def __init__(self):
        self.agent = None
        self.is_generating = False
        self.notified = []
        self.pushed = []
        self.pm = None
        self.sm = None
        self.current_session_id = None
        self.message_queue = None
        self.workers = []
        self.refreshed = 0
        self.input = MockInput()

    def notify(self, msg, severity="info"):
        self.notified.append((msg, severity))

    def refresh_status_footer(self):
        self.refreshed += 1

    def query_one(self, target, default=None):
        return self.input

    def push_screen(self, screen, callback=None):
        self.pushed.append(screen)
        if callback:
            callback(None)


class TestCommandsCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_base_command_execute_raises_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            await BaseCommand().execute(None)

    async def test_new_command_cancels_running_worker(self):
        from widgets.commands import NewCommand

        cancel_called = []

        class Worker:
            is_running = True

            def cancel(self):
                cancel_called.append(1)

        async def fake_new_session(sm, agent, **cb):
            cb["cancel_workers"]()
            await cb["kill_all_tasks"]()
            cb["cancel_subagents"]()
            return "new-id"

        app = SimpleApp()
        app.agent = SimpleNamespace()
        app.message_queue = MagicMock()
        app.task_manager = SimpleNamespace(kill_all=AsyncMock())
        app.workers = [Worker()]
        app.sm = MagicMock()
        chat = SimpleNamespace()
        chat.remove_children = AsyncMock()
        chat.check_welcome = MagicMock()
        app.query_one = lambda target, default=None: chat
        with patch(
            "widgets.commands.new_session", new=fake_new_session
        ), patch("core.application.session.stream.cancel_running_subagents"):
            await NewCommand().execute(app)
        self.assertEqual(len(cancel_called), 1)
        app.task_manager.kill_all.assert_awaited_once()
        app.message_queue.clear.assert_called_once()

    async def test_providers_command_load_raises_then_notifies(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.side_effect = Exception("boom")
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("No available providers configured", "warning")]
        )

    async def test_providers_command_no_providers(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {}
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("No available providers configured", "warning")]
        )

    async def test_providers_command_entered_key_opens_with_focus(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {"p": {"name": "P"}}
        cm.get_active_provider_key.return_value = "p"
        cm.get_api_key.return_value = ""
        cm.get_disabled_providers.return_value = []
        app.pm = cm

        entered_keys = []
        invoked_once = {"done": False}

        def push_screen(screen, callback=None):
            name = screen.__class__.__name__
            app.pushed.append(name)
            if not callback:
                return
            if name == "ApiKeyInputScreen":
                entered_keys.append(callback)
                callback("secret")
            elif not invoked_once["done"]:
                invoked_once["done"] = True
                callback("p")

        app.push_screen = push_screen
        with patch(
            "widgets.commands.fetch_api_key_and_provider_info",
            return_value=("P", ""),
        ), patch("widgets.commands.set_provider_credentials", return_value=""):
            await ProvidersCommand().execute(app)

        # Flush the asyncio.create_task(_open_with_key) scheduled on failure path.
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(len(entered_keys), 1)
        self.assertGreaterEqual(app.pushed.count("ProvidersScreen"), 2)

    async def test_open_with_key_normal_path(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {"p": {"name": "P"}}
        cm.get_active_provider_key.return_value = "p"
        cm.get_api_key.return_value = ""
        cm.get_disabled_providers.return_value = []
        app.pm = cm
        await ProvidersCommand()._open_with_key(app, "p", lambda k: None)
        self.assertTrue(
            any(getattr(s, "__class__", None).__name__ == "ProvidersScreen" for s in app.pushed)
        )

    async def test_open_with_key_load_raises(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.side_effect = Exception("boom")
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand()._open_with_key(app, "p", lambda k: None)
        ps.assert_not_called()

    async def test_open_with_key_no_providers(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.load_providers.return_value = {}
        app.pm = cm
        with patch.object(app, "push_screen") as ps:
            await ProvidersCommand()._open_with_key(app, "p", lambda k: None)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("No available providers configured", "warning")]
        )

    async def test_models_command_disconnected_opens_providers(self):
        app = SimpleApp()
        app.pm = MagicMock()
        with patch("widgets.commands.fetch_grouped_models", return_value=([], True)), patch.object(
            ProvidersCommand, "execute", new=AsyncMock()
        ) as m_exec, patch.object(app, "push_screen") as ps:
            await ModelsCommand().execute(app)
        ps.assert_not_called()
        m_exec.assert_awaited_once()

    async def test_models_command_no_models_notify(self):
        app = SimpleApp()
        app.pm = MagicMock()
        with patch("widgets.commands.fetch_grouped_models", return_value=([], False)), patch.object(
            app, "push_screen"
        ) as ps:
            await ModelsCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(
            app.notified, [("Failed to fetch models: check API key or network connection", "warning")]
        )

    async def test_models_command_provider_model_and_scalar_selection(self):
        app = SimpleApp()
        app.agent = MagicMock()
        app.agent.model = ""
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "p"
        cm.get_provider_model.return_value = "gpt-x"
        app.pm = cm
        selected = []

        def push_screen(screen, callback=None):
            if callback:
                callback("gpt-x")  # scalar selection -> use curr_provider

        app.push_screen = push_screen
        with patch(
            "widgets.commands.fetch_grouped_models", return_value=({"p": {"name": "P"}}, False)
        ), patch("widgets.commands.select_model", side_effect=lambda *a, **k: selected.append(a)):
            await ModelsCommand().execute(app)
        self.assertTrue(selected)

    async def test_thinking_effort_no_pm(self):
        app = SimpleApp()
        await ThinkingEffortCommand().execute(app)
        self.assertEqual(app.notified, [("Provider manager not available", "warning")])

    async def test_thinking_effort_empty_selection_focuses(self):
        app = SimpleApp()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "p"
        app.pm = cm

        def push_screen(screen, callback=None):
            if callback:
                callback(None)  # empty effort

        app.push_screen = push_screen
        with patch("widgets.commands.get_current_thinking_effort", return_value=("p", "m", "auto")):
            await ThinkingEffortCommand().execute(app)
        self.assertIsNotNone(getattr(app.input, "focused", None))

    async def test_rewind_no_user_messages(self):
        app = SimpleApp()
        chat = MagicMock()
        chat.get_user_messages.return_value = []
        app.query_one = lambda target, default=None: chat
        await RewindCommand().execute(app)
        self.assertEqual(
            app.notified, [("History is empty: no messages to rollback", "warning")]
        )

    async def test_rewind_exception_paths(self):
        from core.application.session import stream

        app = SimpleApp()
        app.current_session_id = "sess-a"
        app.sm = MagicMock()
        app.sm.project_path = None
        app.message_queue = MagicMock()
        app.task_manager = simple_task_manager = SimpleNamespace()
        simple_task_manager.kill_all = AsyncMock(side_effect=Exception("kill"))
        app.agent = MagicMock()

        class BadCancelWorker:
            is_running = True
            is_finished = False

            def cancel(self):
                raise Exception("cancel-boom")

            async def wait(self):
                raise RuntimeError("wait-boom")

        from textual.worker import WorkerCancelled

        class CancelledWaitWorker(BadCancelWorker):
            async def wait(self):
                raise WorkerCancelled()

        app.workers = [BadCancelWorker(), CancelledWaitWorker()]
        app.is_generating = True
        app.save_current_session = MagicMock()

        chat = MagicMock()
        chat.get_user_messages.return_value = [(0, "First")]
        chat.rollback_to = MagicMock()
        app.input.load_text = app.input.load_text

        def query_one(target, default=None):
            if target == "#message-input":
                return app.input
            return chat

        app.query_one = query_one

        async def push_screen(screen, callback=None):
            if callback:
                await callback(0)
                return
            return None

        app.push_screen = push_screen
        with patch.object(stream, "cancel_running_subagents", side_effect=Exception("sub")):
            await RewindCommand().execute(app)
        self.assertFalse(app.is_generating)

    async def test_resume_no_sessions(self):
        app = SimpleApp()
        app.sm = MagicMock()
        app.sm.list_main_sessions.return_value = []
        await ResumeCommand().execute(app)
        self.assertEqual(app.notified, [("No saved sessions in this project", "warning")])

    async def test_resume_cancels_running_workers(self):
        app = SimpleApp()
        app.sm = MagicMock()
        app.sm.list_main_sessions.return_value = [{"id": "s1"}]
        app.is_generating = True
        app.message_queue = MagicMock()
        app.load_session_ui = MagicMock()

        class Worker:
            is_running = True

            def cancel(self):
                raise Exception("cancel-boom")

        app.workers = [Worker()]

        def push_screen(screen, callback=None):
            if callback:
                callback("s1")

        app.push_screen = push_screen
        await ResumeCommand().execute(app)
        app.load_session_ui.assert_called_once_with("s1")
        self.assertFalse(app.is_generating)
        app.message_queue.clear.assert_called_once()

    async def test_subagents_no_store(self):
        app = SimpleApp()
        # no app.sm -> _has_subagents returns False
        await SubagentsCommand().execute(app)
        self.assertEqual(app.notified, [("No active subagents", "warning")])

    async def test_skills_no_skills(self):
        app = SimpleApp()
        with patch("core.application.skills.manager.SkillManager.list_skills", return_value=[]), patch.object(
            app, "push_screen"
        ) as ps:
            await SkillsCommand().execute(app)
        ps.assert_not_called()
        self.assertEqual(app.notified, [("No available skills found", "warning")])

    async def test_skills_with_selection(self):
        app = SimpleApp()
        selected = []

        def push_screen(screen, callback=None):
            if callback:
                selected.append(callback)

        app.push_screen = push_screen

        class FakeSkill:
            hidden = False

            def __init__(self, name):
                self.name = name

            def to_dict(self):
                return {"name": self.name, "hidden": False}

        def fake_list_skills(self, *a, **k):
            return [FakeSkill("handoff")]

        with patch("core.application.skills.manager.SkillManager.list_skills", new=fake_list_skills):
            await SkillsCommand().execute(app)
        self.assertTrue(selected)
        selected[0]({"name": "handoff"})
        self.assertEqual(app.input.text, "/handoff ")
        # selection None -> focus only
        app.input.text = ""
        selected[0](None)
        self.assertTrue(getattr(app.input, "focused", None))

    async def test_compact_no_agent(self):
        app = SimpleApp()
        await CompactCommand().execute(app)
        self.assertEqual(app.notified, [("No active agent found", "error")])

    async def test_compact_divider_raises_and_save_raises(self):
        app = SimpleApp()
        app.agent = MagicMock()
        app.save_current_session = MagicMock(side_effect=Exception("save"))

        class BrokenDivider:
            async def add_event_divider(self, txt):
                raise Exception("divider")

        chat = BrokenDivider()
        app.query_one = lambda target, default=None: chat

        outcome = SimpleNamespace(success=False, message="boom")

        async def fake_compact(agent, **cb):
            cb["save_session_cb"]()
            cb["on_begin"]()
            return outcome

        with patch("widgets.commands.compact_session", new=fake_compact), patch.object(
            app, "push_screen", MagicMock()
        ):
            await CompactCommand().execute(app)
        self.assertEqual(app.notified, [("boom", "warning")])

    async def test_compact_success_with_queued_message(self):
        app = SimpleApp()
        app.agent = MagicMock()
        app.refresh_status_footer = MagicMock()
        queued = [("next-prompt", True, {})]
        processed = []

        def pop():
            return queued.pop(0)

        async def process(prompt, show, attachments):
            processed.append((prompt, show))

        app._pop_queued_for_current_session = pop
        app._process_queued_message = process
        app.query_one = lambda target, default=None: SimpleApp.query_one.__get__(app)(target, default)

        outcome = SimpleNamespace(success=True, message="ok")
        with patch("widgets.commands.compact_session", return_value=outcome):
            await CompactCommand().execute(app)
        for _ in range(5):
            await asyncio.sleep(0)
        self.assertFalse(app.is_generating)
        self.assertEqual(processed, [("next-prompt", True)])

    async def test_permissions_command_pushes_screen(self):
        app = SimpleApp()
        with patch.object(app, "push_screen") as ps:
            await PermissionsCommand().execute(app)
        ps.assert_called_once()

    async def test_questions_wizard_active(self):
        app = SimpleApp()
        from widgets.presentation.screens.ask_user import AskUserWizardScreen

        app.screen = MagicMock(spec=AskUserWizardScreen)
        app.notify = MagicMock()
        await QuestionsCommand().execute(app)
        app.notify.assert_called_once_with("Question wizard is currently active", severity="info")

    async def test_questions_pending_func(self):
        app = SimpleApp()
        called = []
        app._pending_ask_user = lambda: called.append(1)
        await QuestionsCommand().execute(app)
        self.assertEqual(called, [1])

    async def test_questions_no_pending(self):
        app = SimpleApp()
        app.notify = MagicMock(side_effect=app.notify)
        await QuestionsCommand().execute(app)
        self.assertEqual(app.notified, [("No pending questions", "warning")])


# ---------------------------------------------------------------------------
# widgets/app/status_state.py
# ---------------------------------------------------------------------------
class TestStatusState(unittest.IsolatedAsyncioTestCase):
    def _status_app(self):
        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {"openai": {"name": "OpenAI"}}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        agent = MagicMock()
        agent.model = "gpt"
        agent.get_metrics.return_value = {}
        app.agent = agent
        return app

    async def test_collect_cache_load_providers_raises(self):
        from widgets.app import status_state as ss

        pm = MagicMock()
        pm.load_providers.side_effect = Exception("boom")
        app = MagicMock(pm=pm)
        with patch("core.application.skills.manager.SkillManager.list_skills"), patch(
            "core.infrastructure.mcp.get_mcp_manager"
        ):
            providers, vis, total, mcp = ss._collect_cache(app)
        self.assertEqual(providers, {})

    async def test_collect_cache_skills_raises(self):
        from widgets.app import status_state as ss

        with patch(
            "core.application.skills.manager.SkillManager.list_skills", side_effect=Exception("boom")
        ), patch("core.infrastructure.mcp.get_mcp_manager"):
            vis, total = ss._collect_cache(MagicMock(pm=None))[1:3]
        self.assertEqual((vis, total), (0, 0))

    async def test_collect_cache_mcp_raises(self):
        from widgets.app import status_state as ss

        with patch("core.infrastructure.mcp.get_mcp_manager", side_effect=Exception("boom")):
            mcp = ss._collect_cache(MagicMock(pm=None))[3]
        self.assertEqual(mcp, [])

    async def test_refresh_footer_cache_collect_raises(self):
        from widgets.app import status_state as ss

        with patch.object(ss, "_collect_cache", side_effect=Exception("boom")):
            await refresh_footer_cache(MagicMock(), MagicMock())

    async def test_refresh_footer_cache_widget_refresh_raises(self):
        app = MagicMock()
        widget = MagicMock()
        widget._st_cache_time = 0
        widget.is_mounted = True
        widget.refresh_footer = MagicMock(side_effect=Exception("boom"))
        await refresh_footer_cache(app, widget)
        self.assertGreater(widget._st_cache_time, 0)

    def test_ensure_cache_sync_fallback_collect_raises(self):
        # No running loop + _collect_cache raises -> swallowed, loading cleared.
        from widgets.app import status_state as ss

        app = MagicMock()
        widget = MagicMock()
        widget._st_cache_time = 0
        widget._st_cache_loading = False
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")), patch.object(
            ss, "_collect_cache", side_effect=Exception("boom")
        ):
            _ensure_cache(app, widget)
        self.assertFalse(widget._st_cache_loading)

    def test_ensure_cache_no_widget_returns(self):
        _ensure_cache(MagicMock(), None)

    async def test_ensure_cache_no_loop_sync_fallback(self):
        app = MagicMock()
        widget = MagicMock()
        widget._st_cache_time = 0
        widget._st_cache_loading = False
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            _ensure_cache(app, widget)
        self.assertFalse(widget._st_cache_loading)

    async def test_build_status_kwargs_no_widget_collect_raises(self):
        from widgets.app import status_state as ss

        app = self._status_app()
        with patch.object(ss, "_collect_cache", side_effect=Exception("boom")):
            kwargs = build_status_kwargs(app, widget=None)
        self.assertIn("provider_key", kwargs)

    async def test_build_status_kwargs_no_widget_loads_providers_and_mcp(self):
        app = self._status_app()
        with patch("widgets.app.status_state.get_mcp_manager") as gm:
            mgr = MagicMock()
            mgr.load_servers.return_value = [{"command": "python"}]
            gm.return_value = mgr
            kwargs = build_status_kwargs(app, widget=None)
        self.assertEqual(kwargs["provider_key"], "openai")
        self.assertEqual(kwargs["mcp_total"], 1)

    def test_build_subagent_kwargs_with_agent(self):
        app = self._status_app()
        agent = MagicMock()
        agent.role = "explorer"
        agent.thinking_effort = "high"
        agent.provider_key = "openai"
        agent.model = "gpt-4o"
        agent.get_metrics.return_value = {
            "context_used": 10,
            "total_tokens": 20,
            "context": "128k",
            "context_limit": 128000,
            "cost_usd": 0.1,
        }
        session = MagicMock()
        session.agent = agent
        session.project_dir = "/tmp/sub"
        session.branch_name = "feat"
        app.pm.is_provider_connected.return_value = True
        with patch("widgets.app.status_state.catalog.get_model_display_name", return_value="GPT-4o"):
            kwargs = build_subagent_status_kwargs(
                app, session, spinner_running=True, spinner_idx=1
            )
        self.assertIn("Explorer", kwargs[0])
        self.assertEqual(kwargs[3], True)

    def test_build_subagent_kwargs_app_agent_fallback(self):
        app = self._status_app()
        app.agent = None
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.project_dir = "worktrees"
        session.branch_name = ""
        with patch("widgets.app.status_state.catalog.get_model_display_name", return_value=""):
            kwargs = build_subagent_status_kwargs(
                app, session, spinner_running=False, spinner_idx=0
            )
        self.assertIn("Worker", kwargs[0])


# ---------------------------------------------------------------------------
# widgets/patch.py
# ---------------------------------------------------------------------------
class TestPatchCoverage(unittest.TestCase):
    def setUp(self):
        self._orig_forward = Screen._forward_event
        self._orig_gpos = Screen.get_widget_and_offset_at
        self._orig_getsel = Static.get_selection
        self._orig_rend = RichVisual.render_strips
        self._orig_allow = Widget.allow_select

    def tearDown(self):
        Screen._forward_event = self._orig_forward
        Screen.get_widget_and_offset_at = self._orig_gpos
        Static.get_selection = self._orig_getsel
        RichVisual.render_strips = self._orig_rend
        Widget.allow_select = self._orig_allow
        for cls, attr in (
            (Screen, "_original_forward_event"),
            (Screen, "_original_get_widget_and_offset_at"),
            (Static, "_original_get_selection"),
            (RichVisual, "_original_render_strips"),
        ):
            if hasattr(cls, attr):
                delattr(cls, attr)

    def _apply(self, base_forward=None, base_gpos=None, base_getsel=None, base_rend=None):
        # Clear saved originals so apply() re-captures injected bases.
        for cls, attr in (
            (Screen, "_original_forward_event"),
            (Screen, "_original_get_widget_and_offset_at"),
            (Static, "_original_get_selection"),
            (RichVisual, "_original_render_strips"),
        ):
            if hasattr(cls, attr):
                delattr(cls, attr)
        if base_forward is not None:
            Screen._forward_event = base_forward
        if base_gpos is not None:
            Screen.get_widget_and_offset_at = base_gpos
        if base_getsel is not None:
            Static.get_selection = base_getsel
        if base_rend is not None:
            RichVisual.render_strips = base_rend
        apply_textual_patches()

    def test_safe_forward_event_region_error(self):
        def raiser(self, evt):
            raise AttributeError("'NoneType' object has no attribute 'region'")

        self._apply(base_forward=raiser)
        screen = SimpleNamespace()
        Screen._forward_event(screen, object())  # region attr -> handled
        self.assertIsNone(screen._select_state)

        # re-raise branch: any other AttributeError propagates
        def raiser2(self, evt):
            raise AttributeError("other problem")

        self._apply(base_forward=raiser2)
        screen2 = SimpleNamespace()
        with self.assertRaises(AttributeError):
            Screen._forward_event(screen2, object())

    def test_get_widget_and_offset_at_success_and_exception(self):
        class FakeWidget:
            is_container = False
            allow_select = True
            region = SimpleNamespace(x=5, y=6)

        def base(self, x, y):
            return FakeWidget(), None

        self._apply(base_gpos=base)
        w, off = Screen.get_widget_and_offset_at(object(), 10, 10)
        self.assertIsInstance(off, Offset)
        self.assertEqual(w.region.x, 5)

        class RaiseWidget:
            is_container = False
            allow_select = True

            @property
            def region(self):
                raise Exception("no region")

        def base_err(self, x, y):
            return RaiseWidget(), None

        self._apply(base_gpos=base_err)
        w, off = Screen.get_widget_and_offset_at(object(), 1, 1)
        self.assertIsNone(off)

    def test_static_get_selection_skip_when_result_not_none(self):
        def base(self, selection):
            return ("a", "\n")

        self._apply(base_getsel=base)
        result = Static.get_selection(object(), object())
        self.assertEqual(result, ("a", "\n"))

    def test_static_get_selection_success_and_exception(self):
        class FakeVisual:
            _renderable = "hello world"

        class SuccessStatic(Static):
            def _render(self):
                return FakeVisual()

            @property
            def app(self):
                return SimpleNamespace(console=Console())

            @property
            def size(self):
                return SimpleNamespace(width=20, height=1)

        def base_none(self, selection):
            return None

        self._apply(base_getsel=base_none)
        sel = Selection(Offset(0, 0), Offset(5, 0))
        result = Static.get_selection(SuccessStatic(), sel)
        self.assertEqual(result, ("hello", "\n"))

        class RaiseStatic(SuccessStatic):
            def _render(self):
                raise Exception("render boom")

        result = Static.get_selection(RaiseStatic(), sel)
        self.assertIsNone(result)

    def test_rich_visual_render_strips_selection_styling(self):
        segments = [Segment("hello")]
        strips = [Strip(segments, cell_length=5), Strip(segments, cell_length=5), Strip(segments, cell_length=5)]
        span_map = {0: (0, 2), 1: (0, -1), 2: None}

        def base_rend(self, width, height, style, options):
            return strips

        self._apply(base_rend=base_rend)
        selection = MagicMock()
        selection.get_span.side_effect = lambda y: span_map.get(y)
        options = SimpleNamespace(selection=selection, selection_style=None, width=10)
        result = list(RichVisual.render_strips(object(), 10, 1, None, options))
        self.assertEqual(len(result), 3)

        # sel_style with rich_style attribute (no fallback construction)
        options2 = SimpleNamespace(
            selection=selection, selection_style=SimpleNamespace(rich_style=RichStyle(reverse=True)), width=10
        )
        result2 = list(RichVisual.render_strips(object(), 10, 1, None, options2))
        self.assertEqual(len(result2), 3)

        # options.selection is None -> strips returned unchanged
        options3 = SimpleNamespace(selection=None, selection_style=None, width=10)
        result3 = list(RichVisual.render_strips(object(), 10, 1, None, options3))
        self.assertEqual(len(result3), 3)


# ---------------------------------------------------------------------------
# widgets/status_footer.py
# ---------------------------------------------------------------------------
class FooterHarness(StatusFooter):
    def __init__(self, is_subagent=False, width=120, app=None):
        super().__init__(is_subagent=is_subagent)
        self._harness_app = app
        self._harness_width = width
        self.last_update = None

    @property
    def app(self):
        return self._harness_app

    @property
    def size(self):
        return SimpleNamespace(width=self._harness_width, height=2)

    def update(self, markup):
        self.last_update = markup


_mcp_mgr_patch = "core.infrastructure.mcp.get_mcp_manager"


class TestStatusFooterCoverage(unittest.TestCase):
    def test_format_display_path_symlink_into_home(self):
        home = os.path.realpath(os.path.expanduser("~"))
        target = os.path.join(home, "johnston")
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "link")
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("symlink not supported")
            res = format_display_path(link)
            self.assertEqual(res, "~/johnston")

    def test_format_display_path_len_three_parts(self):
        self.assertEqual(format_display_path("/aa/bb", max_length=3), "/.../bb")

    def test_format_display_path_exception_returns_raw(self):
        with patch("os.path.abspath", side_effect=Exception("boom")):
            self.assertEqual(format_display_path("/my/path"), "/my/path")

    def test_status_footer_no_pm_and_bad_app_size(self):
        footer = FooterHarness()
        footer._harness_app = None
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value=""):
            footer.update_status(provider_key="openai", is_connected=None, model_name="")
        self.assertIsNotNone(footer.last_update)
        self.assertIsNotNone(footer._last_grid_rows)

        # app.size raises -> fallback app_width
        class BadApp:
            @property
            def size(self):
                raise Exception("no size")

        footer._harness_app = BadApp()
        footer.update_status(provider_key="openai", is_connected=True, model_name="")

    def test_set_generating_toggle_off(self):
        footer = FooterHarness()
        timer = MagicMock()
        footer._spinner_timer = timer
        footer.is_generating = True
        with patch.object(footer, "refresh_footer") as rf:
            footer.set_generating(False)
        timer.stop.assert_called_once()
        self.assertEqual(footer._spinner_idx, 0)
        rf.assert_called_once()

    def test_poll_mcp_refresh_exception(self):
        footer = FooterHarness()
        with patch(_mcp_mgr_patch, side_effect=Exception("boom")):
            footer._poll_mcp_refresh()  # must not raise

    def test_active_mcp_count_exception(self):
        footer = FooterHarness()
        mgr = MagicMock()
        mgr.active_server_count.side_effect = Exception("boom")
        with patch(_mcp_mgr_patch, return_value=mgr):
            self.assertEqual(footer._active_mcp_count([]), 0)

    def test_on_unmount_timer_stop_raises(self):
        footer = FooterHarness()
        stop_err = MagicMock()
        stop_err.stop.side_effect = Exception("boom")
        footer._spinner_timer = stop_err
        footer._mcp_poll_timer = stop_err
        footer._resize_timer = stop_err
        footer.on_unmount()
        self.assertIsNone(footer._spinner_timer)
        self.assertIsNone(footer._mcp_poll_timer)
        self.assertIsNone(footer._resize_timer)

    def test_on_resize_same_and_different(self):
        footer = FooterHarness()
        with patch.object(footer, "refresh_footer") as rf:
            footer._last_resize_size = "S"
            footer.on_resize(SimpleNamespace(size="S"))
            rf.assert_not_called()

        timer = MagicMock()
        footer._resize_timer = timer
        new_timer = MagicMock()
        footer.set_timer = MagicMock(return_value=new_timer)
        footer.on_resize(SimpleNamespace(size="T"))
        timer.stop.assert_called_once()
        self.assertIs(footer._resize_timer, new_timer)
        footer.set_timer.assert_called_once()

    def test_spin_subagent_with_and_without_rows(self):
        sess = SimpleNamespace(status="running")
        footer = FooterHarness(is_subagent=True)
        footer._subagent_session = sess
        footer._last_grid_rows = [("a", "")]
        with patch.object(footer, "_render_stream_frame") as rsf, patch.object(
            footer, "update_subagent_footer"
        ) as usf:
            footer._spin()
            rsf.assert_called_once()

            footer._last_grid_rows = None
            footer._spin()
            usf.assert_called_once()

    def test_update_subagent_footer_running(self):
        agent = MagicMock()
        agent.role = "explorer"
        agent.thinking_effort = "high"
        agent.provider_key = "openai"
        agent.model = "gpt-4o"
        agent.get_metrics.return_value = {}
        agent.context_limit = 128000
        session = MagicMock()
        session.status = "running"
        session.branch_name = "feat"
        session.agent = agent
        session.project_dir = "/tmp/x"
        session.last_context_tokens = 0
        session.total_tokens = 0
        session.cost_usd = 0.0

        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {"openai": {"name": "OpenAI"}}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        footer = FooterHarness(app=app)
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value="GPT-4o"), patch.object(
            footer, "_git_diff_stats", return_value=""
        ), patch.object(footer, "set_interval", return_value=MagicMock()):
            footer.update_subagent_footer(session)
        self.assertTrue(footer.is_generating)
        self.assertIsNotNone(footer._last_grid_rows)

        # now switching to completed stops the spinner
        timer = MagicMock()
        session.status = "completed"
        footer.is_generating = True
        footer._spinner_timer = timer
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value="GPT-4o"), patch.object(
            footer, "_git_diff_stats", return_value=""
        ):
            footer.update_subagent_footer(session)
        self.assertFalse(footer.is_generating)
        self.assertIsNone(footer._spinner_timer)

    def test_update_status_subagent_branch(self):
        footer = FooterHarness(is_subagent=True)
        with patch.object(footer, "_git_branch", return_value="main"), patch.object(
            footer, "_git_diff_stats", return_value=""
        ):
            footer.update_status(
                provider_key="openai",
                provider_display="OpenAI",
                clean_model="GPT-4o",
                is_connected=True,
                model_name="gpt-4o",
            )
        self.assertIsNotNone(footer._last_grid_rows)

    def test_update_status_compact_with_diff(self):
        footer = FooterHarness(width=40)
        with patch.object(footer, "_git_diff_stats", return_value="+5 / -2"), patch.object(
            footer, "_git_branch", return_value=""
        ):
            footer.update_status(provider_key="openai", is_connected=True, model_name="gpt-4o")
        rows = footer._last_grid_rows
        joined = " ".join(str(r) for r in rows)
        self.assertIn("+5 / -2", joined)

    def test_update_status_noncompact_with_diff(self):
        footer = FooterHarness()
        with patch.object(footer, "_git_diff_stats", return_value="+5 / -2"), patch.object(
            footer, "_git_branch", return_value=""
        ):
            footer.update_status(provider_key="openai", is_connected=False, model_name="")
        joined = " ".join(str(r) for r in footer._last_grid_rows)
        self.assertIn("+5 / -2", joined)


class TestSubagentStatusFooterCoverage(unittest.TestCase):
    def test_on_unmount_timer_stop_raises(self):
        footer = SubagentStatusFooter()
        timer = MagicMock()
        timer.stop.side_effect = Exception("boom")
        footer._spinner_timer = timer
        footer.on_unmount()
        self.assertIsNone(footer._spinner_timer)

    def test_update_session_none_renders(self):
        footer = SubagentStatusFooter()
        footer._harness_app = MagicMock()
        with patch.object(footer, "update") as upd:
            footer.update_session(None)
        upd.assert_called_once()

    def test_update_session_stops_spinner(self):
        footer = SubagentStatusFooter()
        footer.is_generating = True
        timer = MagicMock()
        footer._spinner_timer = timer
        session = MagicMock()
        session.status = "completed"
        session.agent = None
        session.role = "explorer"
        session.project_dir = "/tmp"
        session.branch_name = ""
        with patch.object(footer, "_render_footer") as rf:
            footer.update_session(session)
        self.assertFalse(footer.is_generating)
        timer.stop.assert_called_once()
        self.assertIsNone(footer._spinner_timer)
        rf.assert_called_once()

    def test_spin_no_rows_renders(self):
        footer = SubagentStatusFooter()
        footer._last_grid_rows = None
        with patch.object(footer, "_render_footer") as rf:
            footer._spin()
        rf.assert_called_once()

    def test_render_footer_provider_active_and_pricing(self):
        footer = SubagentStatusFooter()
        footer._harness_app = MagicMock()
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.project_dir = "/tmp"
        session.branch_name = ""
        session.messages = None
        session.last_context_tokens = 0
        session.total_tokens = 200
        session.cost_usd = 0.0

        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        footer._harness_app = app
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value=""), patch(
            "widgets.status_footer.catalog.get_model_pricing",
            side_effect=lambda p, m: {"prompt": 1.0, "completion": 2.0} if p == "openai" else None,
        ), patch.object(footer, "_git_diff_stats", return_value=""):
            footer._render_footer()
        self.assertIsNotNone(footer._last_grid_rows)

    def test_render_footer_exception(self):
        footer = SubagentStatusFooter()
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.project_dir = "/tmp"
        session.branch_name = ""
        session.messages = None
        footer.session = session
        bad_app = MagicMock()
        bad_app.agent = MagicMock()
        bad_app.pm = MagicMock()
        bad_app.pm.load_providers.side_effect = Exception("boom")
        footer._harness_app = bad_app
        footer._render_footer()  # exception swallowed


# ---------------------------------------------------------------------------
# widgets/command_suggestions.py
# ---------------------------------------------------------------------------
class TestCommandSuggestionsCoverage(unittest.IsolatedAsyncioTestCase):
    async def test_no_running_loop_workspace_files_sync(self):
        sugg = CommandSuggestions()
        with patch("asyncio.to_thread", new=AsyncMock(return_value=["a.py", "b/"])):
            res = await sugg.get_workspace_files()
        self.assertEqual(res, ["a.py", "b/"])
        # cached second call
        res2 = await sugg.get_workspace_files()
        self.assertEqual(res2, ["a.py", "b/"])

    async def test_workspace_walk_capped(self):
        sugg = CommandSuggestions()
        real_walk = os.walk

        def fake_walk(cwd):
            # home/root scenario: two levels
            yield (cwd, ["dir1", "dir2", ".git"], ["a.py"])
            yield os.path.join(cwd, "dir1"), [".inside", "sub"], ["b.py", "c.py"]
            yield os.path.join(cwd, "dir1", "sub"), [], ["d.py"]

        os.walk = fake_walk
        try:
            files = sugg._load_workspace_files()
        finally:
            os.walk = real_walk
        self.assertIsInstance(files, list)

    async def test_workspace_walk_raises_swallowed(self):
        sugg = CommandSuggestions()
        real_walk = os.walk
        os.walk = lambda cwd: (_ for _ in ()).throw(Exception("boom"))
        try:
            files = sugg._load_workspace_files()
        finally:
            os.walk = real_walk
        self.assertEqual(files, [])

    async def test_file_suggestion_max_50(self):
        sugg = CommandSuggestions()
        with patch.object(
            sugg,
            "get_workspace_files",
            new=AsyncMock(return_value=[f"f{i}.py" for i in range(100)]),
        ):
            res = await sugg.update_query("@", "@", 1)
        self.assertEqual(len(res), 50)
        self.assertTrue(sugg.display)

    async def test_long_command_desc_truncated(self):
        sugg = CommandSuggestions()
        cmds = [("/test", "x" * 200)]
        with patch("widgets.command_suggestions.get_all_command_suggestions", new=AsyncMock(return_value=cmds)):
            res = await sugg.update_query("/test", "/test", 5)
        self.assertEqual(res, ["/test"])
        opt_text = str(sugg.options[0].prompt)
        self.assertLessEqual(len(opt_text.split("  ")[1]), 60)

    async def test_option_selected_command_and_file_mount(self):
        from widgets.chat_input import ChatInput

        class SuggApp(App[None]):
            def __init__(self, sugg, input_widget):
                super().__init__()
                self.sugg = sugg
                self.input_widget = input_widget

            def compose(self) -> ComposeResult:
                yield self.input_widget
                yield self.sugg

        chat_input = ChatInput(id="message-input")
        chat_input.apply_suggestion = MagicMock()
        chat_input.apply_file_suggestion = MagicMock()
        chat_input.focus = MagicMock()
        sugg = CommandSuggestions()

        async def _run(setup_state):
            app = SuggApp(sugg, chat_input)
            async with app.run_test():
                setup_state()
                sugg.on_option_list_option_selected(MagicMock())
                return sugg

        await _run(
            lambda: (
                setattr(sugg, "current_matched", ["/help"]),
                setattr(sugg, "mode", "command"),
                setattr(sugg, "at_start_idx", 0),
                sugg.add_option("/help Help about commands"),
                setattr(sugg, "highlighted", 0),
            )
        )
        chat_input.apply_suggestion.assert_called_once_with("/help", 0)

        await _run(
            lambda: (
                setattr(sugg, "current_matched", ["f.py"]),
                setattr(sugg, "mode", "file"),
                setattr(sugg, "at_start_idx", 1),
                sugg.add_option("f.py"),
                setattr(sugg, "highlighted", 0),
            )
        )
        chat_input.apply_file_suggestion.assert_called_once_with("f.py", 1)


if __name__ == "__main__":
    unittest.main()
