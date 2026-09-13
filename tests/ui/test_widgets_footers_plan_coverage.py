"""Coverage tests for StatusFooter, PlanNotch actions and Subagent footers.

Targets exception guards, MCP event handling, spinner lifecycle branches and
action-mixin fallbacks not covered by the existing footer/plan tests.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from johnston.tui.presentation.widgets.plan_notch import PlanActionsMixin, PlanNotch, restore_plan_from_messages
from johnston.tui.presentation.widgets.status_footer import StatusFooter
from johnston.tui.presentation.widgets.subagent_footer import SubagentHeader, SubagentStatusFooter


class FooterHarness(StatusFooter):
    """Minimal StatusFooter subclass: app override + captured update() output."""

    def __init__(self, width=120, app=None, is_mounted=False):
        super().__init__()
        self._harness_app = app
        self._harness_width = width
        self._harness_mounted = is_mounted
        self.last_update = None

    @property
    def app(self):
        return self._harness_app

    @property
    def size(self):
        return SimpleNamespace(width=self._harness_width, height=2)

    @property
    def is_mounted(self):
        return self._harness_mounted

    def update(self, markup):
        self.last_update = markup


class _AppStub:
    """Duck-typed app stand-in exposing the attributes the footer touches."""

    def __init__(self, **kwargs):
        self.project_dir = "/tmp"
        self.mcp_manager = None
        for k, v in kwargs.items():
            setattr(self, k, v)

    def get_model_info(self, provider_key, model_name):
        return SimpleNamespace(display_name="claude-test")

    def estimate_cost(self, provider_key, model_name, total_tokens):
        return 0.5


class _PmStub:
    def __init__(self, pkey="openai", providers=None, connected=True):
        self._pkey = pkey
        self._providers = providers or {pkey: {"name": "OpenAI"}}
        self._connected = connected

    def get_active_provider_key(self):
        return self._pkey

    def load_providers(self):
        return self._providers

    def is_provider_connected(self, key, info=None):
        return self._connected

    def get_provider_thinking_effort(self, key, model_name):
        return "high"


def _make_footer(**kwargs):
    return FooterHarness(**kwargs)


# ---------------------------------------------------------------------------
# StatusFooter
# ---------------------------------------------------------------------------


def test_set_generating_true_mounted_starts_timer():
    footer = _make_footer(is_mounted=True)
    timer = MagicMock()
    footer.set_interval = MagicMock(return_value=timer)
    footer.set_generating(True)
    footer.set_interval.assert_called_once_with(0.3, footer._spin)
    assert footer._spinner_timer is timer
    assert footer.is_generating


def test_set_generating_true_unmounted_skips_timer():
    footer = _make_footer(is_mounted=False)
    footer.is_generating = False
    footer.set_generating(True)
    assert footer._spinner_timer is None
    assert footer.is_generating


def test_set_generating_true_set_interval_raises():
    footer = _make_footer(is_mounted=True)
    footer.set_interval = MagicMock(side_effect=Exception("boom"))
    footer.set_generating(True)
    assert footer._spinner_timer is None


def test_set_generating_false_stop_raises():
    footer = _make_footer()
    timer = MagicMock()
    timer.stop = MagicMock(side_effect=Exception("boom"))
    footer._spinner_timer = timer
    footer.is_generating = True
    with patch.object(footer, "refresh_footer") as rf:
        footer.set_generating(False)
    assert footer._spinner_timer is None
    assert footer._spinner_idx == 0
    rf.assert_called_once()


def test_spin_with_cached_rows_renders_frame():
    footer = _make_footer()
    footer._last_grid_rows = [("left", "right")]
    with patch.object(footer, "_render_stream_frame") as rsf:
        footer._spin()
    rsf.assert_called_once()


def test_on_mount_generating_starts_timer():
    footer = _make_footer(is_mounted=True)
    footer.is_generating = True
    timer = MagicMock()
    footer.set_interval = MagicMock(return_value=timer)
    with patch.object(footer, "refresh_footer") as rf:
        footer.on_mount()
    footer.set_interval.assert_called_once_with(0.3, footer._spin)
    rf.assert_called_once()


def test_on_mount_mcp_registration_fails_silently():
    footer = _make_footer()
    with patch.object(footer, "refresh_footer") as rf:
        with patch("johnston.core.infrastructure.mcp.get_mcp_manager", side_effect=Exception("boom")):
            footer.on_mount()
    rf.assert_called_once()


def test_on_mount_mcp_manager_adds_listener():
    footer = _make_footer()
    mgr = MagicMock()
    with patch.object(footer, "refresh_footer") as rf:
        with patch("johnston.core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            footer.on_mount()
    mgr.add_listener.assert_called_once_with(footer._on_mcp_event)
    rf.assert_called_once()


def test_on_unmount_mcp_remove_raises():
    footer = _make_footer()
    footer._spinner_timer = None
    footer._mcp_poll_timer = None
    footer._resize_timer = None
    with patch("johnston.core.infrastructure.mcp.get_mcp_manager", side_effect=Exception("boom")):
        footer.on_unmount()


def test_on_mcp_event_no_app_refreshes():
    footer = _make_footer(app=None)
    with patch.object(footer, "refresh_footer") as rf:
        footer._on_mcp_event()
    rf.assert_called_once()


def test_on_mcp_event_no_running_loop_refreshes():
    app = _AppStub(pm=_PmStub())
    footer = _make_footer(app=app, is_mounted=True)
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        with patch("johnston.tui.app.status_state.refresh_footer_cache", return_value=None):
            with patch.object(footer, "refresh_footer") as rf:
                footer._on_mcp_event()
    rf.assert_called_once()


def test_on_mcp_event_schedules_cache_refresh():
    app = _AppStub(pm=_PmStub())
    footer = _make_footer(app=app, is_mounted=True)
    with patch("asyncio.get_running_loop") as loop:
        loop.return_value.create_task = MagicMock()
        footer._on_mcp_event()
        loop.return_value.create_task.assert_called_once()


def test_on_mcp_event_build_status_from_cache():
    """When refresh_footer_cache raises, _on_mcp_event falls back to
    refresh_footer directly."""
    app = _AppStub(pm=_PmStub())
    footer = _make_footer(app=app, is_mounted=True)
    with patch(
        "johnston.tui.app.status_state.refresh_footer_cache", side_effect=Exception("boom")
    ):
        with patch.object(footer, "refresh_footer") as rf:
            footer._on_mcp_event()
    rf.assert_called_once()


def test_on_mount_generating_set_interval_raises():
    footer = _make_footer(is_mounted=True)
    footer.is_generating = True
    footer.set_interval = MagicMock(side_effect=Exception("boom"))
    with patch.object(footer, "refresh_footer") as rf:
        footer.on_mount()
    assert footer._spinner_timer is None
    rf.assert_called_once()


def test_on_mcp_event_runtime_error_falls_through_to_refresh():
    """When the running loop raises RuntimeError during create_task, the
    handler falls through to refresh_footer (line 120) instead of the
    outer except."""
    app = _AppStub(pm=_PmStub())
    footer = _make_footer(app=app, is_mounted=True)
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        with patch("johnston.tui.app.status_state.refresh_footer_cache", return_value=None):
            with patch.object(footer, "refresh_footer") as rf:
                footer._on_mcp_event()
    rf.assert_called_once()


async def test_on_mcp_event_outer_exception_refreshes():
    """A non-RuntimeError failure around create_task hits the outer except
    Exception fallback (refresh_footer)."""
    app = _AppStub(pm=_PmStub())
    footer = _make_footer(app=app, is_mounted=True)
    with patch("asyncio.get_running_loop", side_effect=KeyError("boom")):
        with patch.object(footer, "refresh_footer") as rf:
            footer._on_mcp_event()
    rf.assert_called_once()


def test_on_mcp_event_outer_exception_no_app():
    footer = _make_footer(app=None)
    with patch("johnston.tui.app.status_state.refresh_footer_cache", side_effect=Exception("boom")):
        with patch.object(footer, "refresh_footer") as rf:
            footer._on_mcp_event()
    rf.assert_called_once()


def test_refresh_footer_no_app_returns():
    footer = _make_footer(app=None)
    footer.refresh_footer()  # must not raise


def test_refresh_footer_build_raises_falls_back():
    footer = _make_footer(app=_AppStub(pm=_PmStub()))
    with patch("johnston.tui.app.status_state.build_status_kwargs", side_effect=Exception("boom")):
        with patch.object(footer, "update_status") as us:
            footer.refresh_footer()
    us.assert_called_once_with(provider_key="default")


def test_update_status_clean_model_from_client():
    app = _AppStub(pm=_PmStub())
    footer = _make_footer(app=app)
    footer.is_generating = False
    footer.update_status(provider_key="openai", model_name="claude-test")
    assert footer.last_update is not None
    rows = footer._last_grid_rows
    assert rows


def test_update_status_clean_model_client_raises():
    app = _AppStub(pm=_PmStub())
    app.client = MagicMock()
    app.client.get_model_info = MagicMock(side_effect=Exception("boom"))
    footer = _make_footer(app=app)
    footer.update_status(provider_key="openai", model_name="gpt-x")
    footer.update_status(provider_key="", model_name="")


def test_apply_two_row_grid_caches_rows():
    footer = _make_footer()
    footer._apply_two_row_grid("l1", "r1", "l2", "r2")
    assert footer._last_grid_rows == [("l1", "r1"), ("l2", "r2")]
    assert footer.last_update is not None


def test_render_for_size_refreshes():
    footer = _make_footer()
    with patch.object(footer, "refresh_footer") as rf:
        footer.render_for_size()
    rf.assert_called_once()


def test_on_diff_updated_refreshes():
    footer = _make_footer()
    with patch.object(footer, "refresh_footer") as rf:
        footer._on_diff_updated()
    rf.assert_called_once()


# ---------------------------------------------------------------------------
# PlanActionsMixin / PlanNotch
# ---------------------------------------------------------------------------


class _Host(PlanActionsMixin):
    def __init__(self):
        self.current_plan = None
        self.current_plan_explanation = ""
        self.screen = None


def test_action_toggle_plan_no_notches_returns():
    host = _Host()
    host.query = MagicMock(return_value=[])
    host.screen = SimpleNamespace(query=MagicMock(return_value=[]))
    host.action_toggle_plan()  # must not raise


def test_action_toggle_plan_empty_plan_notifies():
    host = _Host()
    notch = PlanNotch()
    notch.plan_items = []
    host.query = MagicMock(return_value=[notch])
    host.notify = MagicMock()
    host.action_toggle_plan()
    host.notify.assert_called_once_with("No active plan", severity="information")


def test_action_toggle_plan_toggles_expanded():
    host = _Host()
    notch = PlanNotch()
    notch.plan_items = [{"step": "A", "status": "in_progress"}]
    notch.toggle_expanded = MagicMock()
    host.query = MagicMock(return_value=[notch])
    host.action_toggle_plan()
    notch.toggle_expanded.assert_called_once()


def test_action_toggle_plan_exception_suppressed():
    host = _Host()
    host.query = MagicMock(side_effect=Exception("boom"))
    host.action_toggle_plan()  # must not raise


def test_action_toggle_plan_falls_back_to_screen():
    host = _Host()
    notch = PlanNotch()
    notch.plan_items = [{"step": "A", "status": "pending"}]
    host.query = MagicMock(return_value=[])
    host.screen = SimpleNamespace(query=MagicMock(return_value=[notch]))
    host.action_toggle_plan()
    assert notch.is_expanded


def test_action_toggle_plan_hidden_exception_suppressed():
    host = _Host()
    host.query = MagicMock(side_effect=Exception("boom"))
    host.action_toggle_plan_hidden()  # must not raise


def test_action_toggle_plan_hidden_screen_fallback():
    host = _Host()
    notch = PlanNotch()
    notch.plan_items = [{"step": "A", "status": "pending"}]
    host.query = MagicMock(return_value=[])
    host.screen = SimpleNamespace(query=MagicMock(return_value=[notch]))
    host.action_toggle_plan_hidden()
    assert notch.display  # False -> True


def test_on_plan_update_non_list_clears():
    host = _Host()
    notch = PlanNotch()
    host.query = MagicMock(return_value=[notch])
    host.on_plan_update("malformed", explanation="x")
    assert host.current_plan == []
    assert host.current_plan_explanation == "x"
    assert notch.plan_items == []


def test_on_plan_update_filters_non_dicts():
    host = _Host()
    notch = PlanNotch()
    host.query = MagicMock(return_value=[notch])
    host.on_plan_update([{"step": "ok", "status": "pending"}, "bad", 1], explanation="  exp  ")
    assert host.current_plan == [{"step": "ok", "status": "pending"}]
    assert host.current_plan_explanation == "exp"
    assert notch.plan_items == [{"step": "ok", "status": "pending"}]


def test_on_plan_update_screen_fallback_exception_suppressed():
    host = _Host()
    notch = PlanNotch()
    host.query = MagicMock(side_effect=[[], Exception("boom")])
    host.screen = SimpleNamespace(query=MagicMock(return_value=[notch]))
    host.on_plan_update([{"step": "A", "status": "pending"}], "")
    assert notch.plan_items == [{"step": "A", "status": "pending"}]


def test_plan_notch_toggle_hidden_no_plan():
    notch = PlanNotch()
    notch.plan_items = []
    notch.display = True
    notch.toggle_hidden()
    assert not notch.display


def test_plan_notch_toggle_hidden_with_plan():
    notch = PlanNotch()
    notch.plan_items = [{"step": "A", "status": "pending"}]
    notch.display = True
    notch.toggle_hidden()
    assert not notch.display
    notch.toggle_hidden()
    assert notch.display


def test_plan_notch_toggle_expanded_hidden_display():
    notch = PlanNotch()
    notch.plan_items = [{"step": "A", "status": "in_progress"}]
    notch.display = False
    notch.toggle_expanded()
    assert notch.display
    assert notch.is_expanded
    assert "expanded" in notch.classes


def test_plan_notch_collapsed_active_step_without_status():
    notch = PlanNotch()
    notch.plan_items = [{"step": "No status step", "status": "weird"}]
    col = notch._render_collapsed()
    assert "0/1" in col.plain


def test_plan_notch_expanded_elided_items():
    """>6 items renders the sliding window with remaining/earlier markers."""
    notch = PlanNotch()
    items = []
    for i in range(9):
        status = "completed" if i < 4 else ("in_progress" if i == 5 else "pending")
        items.append({"step": f"Task {i}", "status": status})
    notch.plan_items = items
    exp = notch._render_expanded()
    assert "Plan (4/9)" in exp.plain
    assert "earlier steps" in exp.plain
    assert "remaining steps" in exp.plain


def test_on_plan_update_query_raises():
    host = _Host()
    host.query = MagicMock(side_effect=Exception("boom"))
    host.on_plan_update([{"step": "A", "status": "pending"}], "")
    assert host.current_plan == [{"step": "A", "status": "pending"}]


def test_plan_notch_expanded_pending_fallback_in_window():
    """>6 items, no in_progress: the pending fallback picks the first pending."""
    notch = PlanNotch()
    items = [{"step": f"T{i}", "status": "completed"} for i in range(4)]
    items += [{"step": f"T{i}", "status": "pending"} for i in range(4, 9)]
    notch.plan_items = items
    exp = notch._render_expanded()
    assert "Plan (4/9)" in exp.plain
    assert "[ ] T4" in exp.plain


def test_plan_notch_expanded_no_active_or_pending_last_item():
    notch = PlanNotch()
    notch.plan_items = [{"step": f"T{i}", "status": "completed"} for i in range(7)]
    exp = notch._render_expanded()
    assert "Plan (7/7)" in exp.plain


def test_plan_notch_refresh_notch_exception_suppressed():
    notch = PlanNotch()
    notch.update = MagicMock(side_effect=Exception("boom"))
    notch.refresh_notch()  # must not raise


def test_restore_plan_from_messages_importable():
    assert callable(restore_plan_from_messages)


# ---------------------------------------------------------------------------
# SubagentStatusFooter / SubagentHeader
# ---------------------------------------------------------------------------


class _SubHarness(SubagentStatusFooter):
    """Subagent footer with the same harness pattern as StatusFooter."""

    def __init__(self, width=120, app=None, is_mounted=False):
        super().__init__()
        self._harness_app = app
        self._harness_width = width
        self._harness_mounted = is_mounted
        self.last_update = None

    @property
    def size(self):
        return SimpleNamespace(width=self._harness_width, height=2)

    @property
    def is_mounted(self):
        return self._harness_mounted

    def update(self, markup):
        self.last_update = markup


class _SubHeaderHarness(SubagentHeader):
    def __init__(self, width=120, app=None, from_tasks=False):
        super().__init__(from_tasks=from_tasks)
        self._harness_app = app
        self._harness_width = width
        self.last_update = None

    @property
    def size(self):
        return SimpleNamespace(width=self._harness_width, height=1)

    def update(self, markup):
        self.last_update = markup


def _sub_session(**overrides):
    session = MagicMock()
    session.status = "running"
    session.agent = None
    session.role = "worker"
    session.messages = []
    session.last_context_tokens = 0
    session.total_tokens = 0
    session.cost_usd = 0.0
    session.id = "sub-1"
    session.title = "Sub Task"
    session.prompt = ""
    for k, v in overrides.items():
        setattr(session, k, v)
    return session


def test_subagent_footer_on_mount_generating_starts_timer():
    footer = _SubHarness(is_mounted=True)
    footer.is_generating = True
    timer = MagicMock()
    footer.set_interval = MagicMock(return_value=timer)
    with patch.object(footer, "_render_footer") as rf:
        footer.on_mount()
    footer.set_interval.assert_called_once_with(0.3, footer._spin)
    rf.assert_called_once()


def test_subagent_footer_on_mount_set_interval_raises():
    footer = _SubHarness(is_mounted=True)
    footer.is_generating = True
    footer.set_interval = MagicMock(side_effect=Exception("boom"))
    with patch.object(footer, "_render_footer") as rf:
        footer.on_mount()
    assert footer._spinner_timer is None
    rf.assert_called_once()


def test_subagent_footer_update_session_starts_timer_when_mounted():
    footer = _SubHarness(is_mounted=True)
    timer = MagicMock()
    footer.set_interval = MagicMock(return_value=timer)
    footer.update_session(_sub_session(status="running"))
    assert footer.is_generating
    assert footer._spinner_timer is timer


def test_subagent_footer_update_session_set_interval_raises():
    footer = _SubHarness(is_mounted=True)
    footer.set_interval = MagicMock(side_effect=Exception("boom"))
    footer.update_session(_sub_session(status="running"))
    assert footer.is_generating
    assert footer._spinner_timer is None


def test_subagent_footer_update_session_unmounted_skips_timer():
    footer = _SubHarness(is_mounted=False)
    footer.update_session(_sub_session(status="running"))
    assert footer.is_generating
    assert footer._spinner_timer is None


def test_subagent_footer_update_session_stop_timer_raises():
    footer = _SubHarness(is_mounted=True)
    footer.is_generating = True
    timer = MagicMock()
    timer.stop = MagicMock(side_effect=Exception("boom"))
    footer._spinner_timer = timer
    footer.update_session(_sub_session(status="completed"))
    assert not footer.is_generating
    assert footer._spinner_timer is None


def test_subagent_footer_update_session_same_running_no_duplicate_timer():
    footer = _SubHarness(is_mounted=True)
    timer = MagicMock()
    footer._spinner_timer = timer
    footer.is_generating = True
    footer.update_session(_sub_session(status="running"))
    assert footer._spinner_timer is timer


def test_subagent_footer_clean_model_from_client():
    app = _AppStub(pm=_PmStub())
    footer = _SubHarness(app=app)
    session = _sub_session()
    session.messages = None
    footer.update_session(session)
    assert footer._last_grid_rows is not None


def test_subagent_footer_clean_model_client_raises():
    app = _AppStub(pm=_PmStub())
    app.client = MagicMock()
    app.client.get_model_info = MagicMock(side_effect=Exception("boom"))
    app.agent = SimpleNamespace(model="gpt-x", provider_key="openai")
    footer = _SubHarness(app=app)
    session = _sub_session()
    session.messages = None
    footer.update_session(session)
    assert footer._last_grid_rows is not None
    # Placeholder model text is rendered after the failed lookup.
    joined = "\n".join(str(r) for r in footer._last_grid_rows)
    assert "Select model" in joined


def test_subagent_footer_context_limit_unparseable():
    app = _AppStub(pm=_PmStub())
    footer = _SubHarness(app=app)
    session = _sub_session()
    session.messages = None

    class _Agent:
        thinking_effort = "auto"
        provider_key = "openai"
        model = "gpt-x"
        context_limit = "not-a-number"

    session.agent = _Agent()
    footer.update_session(session)
    assert footer._last_grid_rows is not None


def test_subagent_footer_history_tokens_cached():
    app = _AppStub(pm=_PmStub())
    footer = _SubHarness(app=app)
    session = _sub_session()
    session.messages = [{"type": "bot", "text": "hi"}]
    footer.update_session(session)
    cached_count = footer._cached_msg_count
    assert cached_count == 1
    footer.update_session(session)
    assert footer._cached_msg_count == cached_count


def test_subagent_footer_render_exception_suppressed():
    footer = _SubHarness(app=None)
    session = MagicMock()
    session.agent = None
    session.role = "worker"
    session.messages = None
    footer.session = session
    # _harness_app property raises -> the _render_footer try/except swallows it.
    footer._harness_app = None
    footer._render_footer()


def test_subagent_footer_from_tasks_esc_label():
    footer = _SubHarness()
    footer.from_tasks = True
    footer.update_session(None)
    assert footer.last_update is not None
    joined = " ".join(str(r) for r in footer._last_grid_rows)
    assert "Back" in joined
    assert "esc" in joined


def test_subagent_footer_on_diff_updated_renders():
    footer = _SubHarness()
    with patch.object(footer, "_render_footer") as rf:
        footer._on_diff_updated()
    rf.assert_called_once()


def test_subagent_footer_render_for_size_renders():
    footer = _SubHarness()
    with patch.object(footer, "_render_footer") as rf:
        footer.render_for_size()
    rf.assert_called_once()


def test_subagent_header_on_mount_renders():
    header = _SubHeaderHarness()
    with patch.object(header, "_render_header") as rh:
        header.on_mount()
    rh.assert_called_once()


def test_subagent_header_on_unmount_cancels_resize():
    header = _SubHeaderHarness()
    with patch.object(header, "cancel_resize_timer") as crt:
        header.on_unmount()
    crt.assert_called_once()


def test_subagent_header_session_app_access_raises():
    header = _SubHeaderHarness()
    session = _sub_session()
    session.status = "completed"
    header.session = session
    header._harness_app = None
    header._render_header()
    assert header._last_grid_rows is not None


def test_subagent_header_session_app_fallback():
    header = _SubHeaderHarness()
    session = _sub_session()
    session.status = "running"
    header.session = session
    header._harness_app = _AppStub(pm=_PmStub())
    header._render_header()
    assert header._last_grid_rows is not None


def test_subagent_header_compact_hint_and_kill():
    header = _SubHeaderHarness(width=30)
    session = _sub_session()
    session.status = "running"
    header.session = session
    header._harness_app = _AppStub(pm=_PmStub())
    header._render_header()
    assert header._last_grid_rows is not None


def test_subagent_header_render_exception_suppressed():
    header = _SubHeaderHarness()

    class _Bad:
        status = "running"

        @property
        def title(self):
            raise Exception("boom")

    header.session = _Bad()
    header._harness_app = _AppStub(pm=_PmStub())
    header._render_header()  # must not raise


def test_subagent_header_on_diff_updated_renders():
    header = _SubHeaderHarness()
    with patch.object(header, "_render_header") as rh:
        header.render_for_size()
    rh.assert_called_once()
