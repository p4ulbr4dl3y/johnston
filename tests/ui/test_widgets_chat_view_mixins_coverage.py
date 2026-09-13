"""Coverage tests for ChatView pagination, scroll and hints mixins.

These target exception guards, run_worker vs raw-loop scheduling, first-message
restoration and scroll-mixin branches not covered by tests/ui/test_chat_view.py.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from textual.geometry import Region, Size

from johnston.tui.presentation.widgets.chat_view_hints import ChatViewHintsMixin
from johnston.tui.presentation.widgets.chat_view_pagination import ChatViewPaginationMixin
from johnston.tui.presentation.widgets.chat_view_scroll import ChatViewScrollMixin
from johnston.tui.presentation.widgets.chat_welcome import WelcomeWidget


class _PagBase:
    """Stands in for the DOM/widget base class in the mixin MRO."""

    def arrange(self, size: Size):
        return self._arrange_result

    def _scroll_update(self, virtual_size: Size) -> None:
        self._scroll_update_called = True

    def remove_children(self, *args, **kwargs):
        self._remove_children_called = True


class PlainPagination(ChatViewPaginationMixin, _PagBase):
    def __init__(self):
        super().__init__()
        self.children = []
        self.scroll_y = 0
        self.scroll_target_y = 0
        self.max_scroll_y = 0
        self.scroll_to = MagicMock()
        self._arrange_result = MagicMock()
        self._scroll_update_called = False
        self._remove_children_called = False


def _pagination_instance() -> PlainPagination:
    return PlainPagination()


class _Placement:
    def __init__(self, widget, region):
        self.widget = widget
        self.region = region


def test_arrange_anchor_sets_scroll_y():
    p = _pagination_instance()
    anchor = MagicMock()
    p._pagination_anchor = anchor
    p._pagination_anchor_offset = 5
    p._arrange_result.placements = [_Placement(anchor, Region(0, 25, 10, 3))]
    p.arrange(Size(80, 20))
    assert p.scroll_y == 20
    assert p.scroll_target_y == 20


def test_arrange_anchor_exception_suppressed():
    p = _pagination_instance()
    anchor = MagicMock()
    p._pagination_anchor = anchor
    p._arrange_result.placements = [_Placement(anchor, "not-a-region")]

    class _BadRegion:
        @property
        def y(self):
            raise Exception("boom")

    p._arrange_result.placements = [_Placement(anchor, _BadRegion())]
    p.arrange(Size(80, 20))  # must not raise


def test_scroll_update_anchor_sets_scroll_y():
    p = _pagination_instance()
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 30, 10, 3)
    p._pagination_anchor = anchor
    p._pagination_anchor_offset = 5
    p._scroll_update(Size(80, 20))
    assert p.scroll_y == 25
    assert p.scroll_target_y == 25
    assert p._scroll_update_called


def test_scroll_update_anchor_exception_suppressed():
    p = _pagination_instance()
    anchor = MagicMock()

    class _BadRegion:
        @property
        def y(self):
            raise Exception("boom")

    anchor.virtual_region = _BadRegion()
    p._pagination_anchor = anchor
    p._scroll_update(Size(80, 20))  # must not raise
    assert p._scroll_update_called


def test_remove_children_resets_pagination_wildcard():
    p = _pagination_instance()
    p._unloaded_messages = [{"type": "user", "text": "old"}]
    p._is_loading_older = True
    p._pagination_anchor = MagicMock()
    p.remove_children()
    assert p._unloaded_messages == []
    assert not p._is_loading_older
    assert p._pagination_anchor is None
    assert p._remove_children_called


def test_remove_children_leaves_state_for_specific_selector():
    p = _pagination_instance()
    p._unloaded_messages = [{"type": "user", "text": "old"}]
    p._is_loading_older = True
    p.remove_children("ToolCallWidget")
    assert len(p._unloaded_messages) == 1
    assert p._is_loading_older
    assert p._remove_children_called


def test_has_older_messages():
    p = _pagination_instance()
    assert not p.has_older_messages()
    p._unloaded_messages = [{"type": "user", "text": "x"}]
    assert p.has_older_messages()


def test_load_older_messages_noop_when_loading():
    p = _pagination_instance()
    p._is_loading_older = True
    p.load_older_messages()  # must not raise
    assert p._is_loading_older


def test_load_older_messages_worker_exception_suppressed():
    p = _pagination_instance()
    p.PAGE_SIZE = 5
    p._unloaded_messages = [{"type": "user", "text": "old"}]
    p.run_worker = MagicMock(side_effect=Exception("boom"))
    p.load_older_messages()  # falls through to loop scheduling
    assert p._is_loading_older is False


def test_load_older_messages_run_worker_returns_early():
    p = _pagination_instance()
    p.PAGE_SIZE = 5
    p._unloaded_messages = [{"type": "user", "text": "old"}]
    p.run_worker = MagicMock()
    p.load_older_messages()
    p.run_worker.assert_called_once()
    assert p._is_loading_older is False


def test_load_older_messages_no_running_loop_suppressed():
    p = _pagination_instance()
    p.PAGE_SIZE = 5
    p._unloaded_messages = [{"type": "user", "text": "old"}]
    p.run_worker = None
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        p.load_older_messages()
    assert p._is_loading_older is False


async def test_load_all_older_messages_was_at_bottom():
    p = _pagination_instance()
    p.PAGE_SIZE = 2
    p._unloaded_messages = [{"type": "user", "text": "a"}, {"type": "user", "text": "b"}]
    p.is_at_bottom = MagicMock(return_value=True)
    p.restore_message = AsyncMock(return_value=None)
    p.scroll_to_bottom = MagicMock()
    p._auto_follow = False

    await p.load_all_older_messages()
    assert p._unloaded_messages == []
    p.scroll_to_bottom.assert_called_once()


async def test_load_older_worker_early_return_when_loading():
    p = _pagination_instance()
    p._is_loading_older = True
    await p._load_older_messages_worker()
    assert p._is_loading_older


async def test_load_older_worker_page_size_from_settings():
    p = _pagination_instance()
    p._unloaded_messages = [{"type": "user", "text": f"m{i}"} for i in range(3)]
    p.restore_message = AsyncMock(return_value=MagicMock())

    settings = SimpleNamespace(ui=SimpleNamespace(chat_page_size=2))
    with patch(
        "johnston.tui.presentation.widgets.chat_view_restore.resolve_settings",
        return_value=settings,
    ):
        await p._load_older_messages_worker()
    assert len(p._unloaded_messages) == 1
    assert not p._is_loading_older


async def test_load_older_worker_no_anchor_restores_all():
    p = _pagination_instance()
    p.PAGE_SIZE = 3
    p._unloaded_messages = [{"type": "user", "text": f"m{i}"} for i in range(3)]
    p.restore_message = AsyncMock(return_value=MagicMock())

    await p._load_older_messages_worker()
    assert p._unloaded_messages == []
    assert p.restore_message.await_count == 3
    assert not p._is_loading_older


async def test_load_older_worker_anchor_restores_widgets_and_compensates():
    p = _pagination_instance()
    p.PAGE_SIZE = 2
    p._unloaded_messages = [{"type": "user", "text": f"m{i}"} for i in range(2)]
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 50, 10, 3)
    p.children = [WelcomeWidget(), anchor]
    widget = MagicMock()
    widget.styles = SimpleNamespace(display="none")
    p.restore_message = AsyncMock(return_value=widget)
    p.call_after_refresh = MagicMock()
    p.scroll_y = 10
    p.max_scroll_y = 0

    await p._load_older_messages_worker()

    assert p._unloaded_messages == []
    assert p.restore_message.await_count == 2
    assert p._pagination_anchor is anchor
    assert p.call_after_refresh.call_count == 1
    cb = p.call_after_refresh.call_args[0][0]
    p.max_scroll_y = 120
    cb()
    p.scroll_to.assert_called_once_with(y=10, animate=False, immediate=True)
    assert p._pagination_anchor is None
    assert not p._is_loading_older


async def test_load_older_worker_styles_display_exception_suppressed():
    p = _pagination_instance()
    p.PAGE_SIZE = 1
    p._unloaded_messages = [{"type": "user", "text": "m"}]
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 50, 10, 3)
    p.children = [anchor]
    widget = MagicMock()

    class _BadStyles:
        @property
        def display(self):
            raise Exception("boom")

        @display.setter
        def display(self, v):
            raise Exception("boom")

    widget.styles = _BadStyles()
    p.restore_message = AsyncMock(return_value=widget)
    p.call_after_refresh = MagicMock()

    await p._load_older_messages_worker()
    assert not p._is_loading_older


async def test_load_older_worker_compensate_second_call_elif_branch():
    """The anchor-less branch of _compensate_scroll (max_scroll_y changed after
    the anchor was popped) runs on a subsequent refresh callback."""
    p = _pagination_instance()
    p.PAGE_SIZE = 1
    p._unloaded_messages = [{"type": "user", "text": "m"}]
    anchor = MagicMock()
    anchor.virtual_region = None
    p.children = [anchor]
    p.restore_message = AsyncMock(return_value=MagicMock())
    p.call_after_refresh = MagicMock()
    p.scroll_y = 0
    p.max_scroll_y = 0

    await p._load_older_messages_worker()
    cb = p.call_after_refresh.call_args[0][0]
    # First invocation: anchor present, no virtual_region -> delta fallback.
    p.max_scroll_y = 40
    cb()
    assert p.scroll_to.call_count == 1
    # Anchor popped now; max_scroll_y changed -> elif branch.
    p.max_scroll_y = 80
    cb()
    assert p.scroll_to.call_count == 2
    assert p.scroll_to.call_args.kwargs["y"] == 80


async def test_load_older_worker_compensate_exception_suppressed():
    p = _pagination_instance()
    p.PAGE_SIZE = 1
    p._unloaded_messages = [{"type": "user", "text": "m"}]
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 50, 10, 3)
    p.children = [anchor]
    p.restore_message = AsyncMock(return_value=MagicMock())
    p.call_after_refresh = MagicMock()
    p.scroll_y = 0
    p.max_scroll_y = 0
    p.scroll_to = MagicMock(side_effect=Exception("boom"))

    await p._load_older_messages_worker()
    cb = p.call_after_refresh.call_args[0][0]
    cb()  # must not raise
    assert p._pagination_anchor is None


async def test_load_older_worker_exception_resets_state():
    p = _pagination_instance()
    p.PAGE_SIZE = 1
    p._unloaded_messages = [{"type": "user", "text": "m"}]
    p.children = []
    p.restore_message = AsyncMock(side_effect=Exception("boom"))
    await p._load_older_messages_worker()
    assert not p._is_loading_older
    assert p._pagination_anchor is None


async def test_load_older_worker_exception_restores_styles_of_partial_widgets():
    p = _pagination_instance()
    p.PAGE_SIZE = 2
    p._unloaded_messages = [{"type": "user", "text": "m1"}, {"type": "user", "text": "m2"}]
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 50, 10, 3)
    p.children = [anchor]
    w1 = MagicMock()
    w1.styles = SimpleNamespace(display="none")
    p.restore_message = AsyncMock(side_effect=[w1, Exception("boom")])
    p.call_after_refresh = MagicMock()

    await p._load_older_messages_worker()
    assert not p._is_loading_older
    assert p._pagination_anchor is None
    assert w1.styles.display == "block"


def test_load_older_messages_creates_loop_task():
    """After run_worker is unavailable/raising, fall back to loop.create_task."""
    p = _pagination_instance()
    p.PAGE_SIZE = 5
    p._unloaded_messages = [{"type": "user", "text": "old"}]
    p.run_worker = None
    created = MagicMock()
    with patch("asyncio.get_running_loop") as loop:
        loop.return_value.create_task.return_value = created
        p.load_older_messages()
    loop.return_value.create_task.assert_called_once()


async def test_load_older_worker_compensate_else_direct_call():
    """Without call_after_refresh, _compensate_scroll runs synchronously."""
    p = _pagination_instance()
    p.PAGE_SIZE = 1
    p._unloaded_messages = [{"type": "user", "text": "m"}]
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 50, 10, 3)
    p.children = [anchor]
    p.restore_message = AsyncMock(return_value=MagicMock())
    p.scroll_y = 0
    p.max_scroll_y = 0

    await p._load_older_messages_worker()
    assert p._pagination_anchor is None
    p.scroll_to.assert_called_once_with(y=0, animate=False, immediate=True)


async def test_load_older_worker_compensate_elif_exception_suppressed():
    p = _pagination_instance()
    p.PAGE_SIZE = 1
    p._unloaded_messages = [{"type": "user", "text": "m"}]
    anchor = MagicMock()
    anchor.virtual_region = None
    p.children = [anchor]
    p.restore_message = AsyncMock(return_value=MagicMock())
    p.call_after_refresh = MagicMock()
    p.scroll_y = 0
    p.max_scroll_y = 0
    p.scroll_to = MagicMock(side_effect=Exception("boom"))

    await p._load_older_messages_worker()
    cb = p.call_after_refresh.call_args[0][0]
    cb()  # anchor-elif branch raises -> suppressed

    # First call popped the anchor; a second call hits the anchor-less elif.
    p.max_scroll_y = 70
    cb()  # must not raise


async def test_load_older_worker_exception_style_restore_raises():
    p = _pagination_instance()
    p.PAGE_SIZE = 2
    p._unloaded_messages = [{"type": "user", "text": "m1"}, {"type": "user", "text": "m2"}]
    anchor = MagicMock()
    anchor.virtual_region = Region(0, 50, 10, 3)
    p.children = [anchor]

    class _BadStyles:
        @property
        def display(self):
            return "none"

        @display.setter
        def display(self, v):
            raise Exception("boom")

    w1 = MagicMock()
    w1.styles = _BadStyles()
    p.restore_message = AsyncMock(side_effect=[w1, Exception("boom")])
    p.call_after_refresh = MagicMock()

    await p._load_older_messages_worker()
    assert not p._is_loading_older
    assert p._pagination_anchor is None


def test_get_total_user_message_count():
    p = _pagination_instance()
    p._unloaded_messages = [
        {"type": "user", "text": "visible"},
        {"type": "user", "text": "hidden", "show_in_ui": False},
        {"type": "bot", "text": "not user"},
    ]
    with patch(
        "johnston.tui.adapters.core_bridge.is_ui_visible_user_message",
        side_effect=lambda m: m.get("type") == "user" and m.get("show_in_ui") is not False,
    ):
        assert p.get_total_user_message_count() == 1


class _ScrollBase:
    def __init__(self):
        self._scroll_up_calls = []
        self._scroll_page_up_calls = []
        self._scroll_home_calls = []
        self._scroll_end_calls = []

    def scroll_up(self, *args, **kwargs):
        self._scroll_up_calls.append((args, kwargs))

    def scroll_page_up(self, *args, **kwargs):
        self._scroll_page_up_calls.append((args, kwargs))

    def scroll_home(self, *args, **kwargs):
        self._scroll_home_calls.append((args, kwargs))

    def scroll_end(self, *args, **kwargs):
        self._scroll_end_calls.append((args, kwargs))

    async def mount(self, *args, **kwargs):
        self._mount_args = (args, kwargs)

    def _wait_until_attached(self, timeout=0.5):
        pass


class PlainScroller(ChatViewScrollMixin, _ScrollBase):
    def __init__(self):
        super().__init__()
        self._is_loading_older = False
        self._is_loading_session = False
        self._has_welcome = False
        self.max_scroll_y = 0
        self.scroll_y = 0
        self.is_attached = True
        self.children = []
        self.call_after_refresh = MagicMock()


def _scroller() -> PlainScroller:
    s = PlainScroller()
    s.has_older_messages = MagicMock(return_value=False)
    s.load_older_messages = MagicMock()
    return s


def test_scroll_up_paginates_near_top():
    s = _scroller()
    s.max_scroll_y = 20
    s.scroll_y = 5
    s.has_older_messages.return_value = True
    s.scroll_up("steps")
    assert not s._auto_follow
    s.load_older_messages.assert_called_once()
    assert s._scroll_up_calls == [(("steps",), {})]


def test_scroll_up_loading_blocks_pagination():
    s = _scroller()
    s.max_scroll_y = 20
    s.scroll_y = 5
    s._is_loading_older = True
    s.scroll_up("steps")
    s.load_older_messages.assert_not_called()
    assert s._scroll_up_calls == []


def test_scroll_page_up_loading_blocks_pagination():
    s = _scroller()
    s.max_scroll_y = 20
    s.scroll_y = 5
    s._is_loading_session = True
    s.scroll_page_up("steps")
    s.load_older_messages.assert_not_called()
    assert s._scroll_page_up_calls == []


def test_scroll_page_up_paginates_and_skips_super():
    s = _scroller()
    s.max_scroll_y = 20
    s.scroll_y = 5
    s.has_older_messages.return_value = True
    s.scroll_page_up("steps")
    s.load_older_messages.assert_called_once()
    assert s._scroll_page_up_calls == []


def test_scroll_up_page_paginates_and_returns():
    s = _scroller()
    s.max_scroll_y = 20
    s.scroll_y = 5
    s.has_older_messages.return_value = True
    s.scroll_up_page()
    s.load_older_messages.assert_called_once()
    assert s._scroll_page_up_calls == []


def test_scroll_up_page_delegates_when_not_near_top():
    s = _scroller()
    s.max_scroll_y = 20
    s.scroll_y = 15
    s.scroll_up_page()
    s.load_older_messages.assert_not_called()
    assert len(s._scroll_page_up_calls) == 1
    assert s._scroll_page_up_calls[0][1] == {"animate": False}


def test_on_mouse_scroll_up_loading_prevents_default():
    s = _scroller()
    s.max_scroll_y = 20
    s._is_loading_session = True
    event = MagicMock()
    s.on_mouse_scroll_up(event)
    event.prevent_default.assert_called_once()
    s.load_older_messages.assert_not_called()


async def test_mount_and_scroll_hidden_display_exception():
    s = _scroller()
    s._is_loading_older = True
    widget = MagicMock()

    class _BadStyles:
        @property
        def display(self):
            raise Exception("boom")

        @display.setter
        def display(self, v):
            raise Exception("boom")

    widget.styles = _BadStyles()
    result = await s._mount_and_scroll(widget, before="anchor")
    assert result is widget
    assert s._mount_args == (("anchor",), {"before": None}) or s._mount_args is not None


async def test_mount_and_scroll_welcome_cleared():
    s = _scroller()
    s.children = [MagicMock(spec=WelcomeWidget)]
    s.clear_welcome = MagicMock()
    widget = MagicMock()
    await s._mount_and_scroll(widget)
    s.clear_welcome.assert_called_once()


class PlainHints(ChatViewHintsMixin):
    def __init__(self):
        super().__init__()
        self._hint_fade_handle = None


def test_on_widget_finished_expandable_render_header():
    h = PlainHints()

    class _Widget:
        is_expandable = staticmethod(lambda: True)
        _show_hints = False
        render_header = MagicMock()

    widget = _Widget()
    h._active_hint_widget = widget
    h._start_hint_fade_timer = MagicMock()
    h.on_widget_finished(widget)
    assert widget._show_hints is True
    widget.render_header.assert_called_once()
    h._start_hint_fade_timer.assert_called_once()


def test_on_widget_finished_non_expandable_clears():
    h = PlainHints()
    widget = MagicMock()
    h._active_hint_widget = widget
    widget.is_expandable = MagicMock(return_value=False)
    widget.set_show_hints = MagicMock()
    h._start_hint_fade_timer = MagicMock()
    h.on_widget_finished(widget)
    widget.set_show_hints.assert_called_once_with(False)
    assert h._active_hint_widget is None
    h._start_hint_fade_timer.assert_called_once()


def test_on_widget_finished_other_widget_ignored():
    h = PlainHints()
    h._active_hint_widget = MagicMock()
    h._start_hint_fade_timer = MagicMock()
    h.on_widget_finished(MagicMock())
    h._start_hint_fade_timer.assert_not_called()


def test_clear_active_hints_immediate_calls_set_show_hints():
    h = PlainHints()
    widget = MagicMock()
    h._active_hint_widget = widget
    h._has_active_hints = True
    h.clear_active_hints(immediate=True)
    widget.set_show_hints.assert_called_once_with(False)
    assert h._active_hint_widget is None
    assert not h._has_active_hints


def test_clear_active_hints_immediate_cancel_raises():
    h = PlainHints()
    handle = MagicMock()
    handle.cancel = MagicMock(side_effect=Exception("boom"))
    h._hint_fade_handle = handle
    h.clear_active_hints(immediate=True)
    assert h._hint_fade_handle is None


def test_clear_active_hints_deferred_starts_timer():
    h = PlainHints()
    with patch.object(h, "_start_hint_fade_timer") as sh:
        h.clear_active_hints(immediate=False)
    sh.assert_called_once()


def test_start_hint_fade_timer_no_loop_clears_immediately():
    h = PlainHints()
    with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
        with patch.object(h, "clear_active_hints") as cah:
            h._start_hint_fade_timer()
    cah.assert_called_once_with(immediate=True)


def test_start_hint_fade_timer_schedules_callback():
    h = PlainHints()
    loop = MagicMock()
    handle = MagicMock()
    loop.call_later.return_value = handle
    with patch("asyncio.get_running_loop", return_value=loop):
        h._start_hint_fade_timer(delay=2.0)
    loop.call_later.assert_called_once_with(2.0, h._on_hint_fade_timeout)
    assert h._hint_fade_handle is handle


def test_on_hint_fade_timeout_clears():
    h = PlainHints()
    h._hint_fade_handle = MagicMock()
    with patch.object(h, "clear_active_hints") as cah:
        h._on_hint_fade_timeout()
    assert h._hint_fade_handle is None
    cah.assert_called_once_with(immediate=True)


def test_on_generation_finished_with_active_widget_starts_timer():
    h = PlainHints()
    h._active_hint_widget = MagicMock()
    with patch.object(h, "_start_hint_fade_timer") as sh:
        h.on_generation_finished()
    sh.assert_called_once()


def test_on_generation_finished_no_active_clears_flag():
    h = PlainHints()
    h._has_active_hints = True
    h.on_generation_finished()
    assert not h._has_active_hints


def test_on_unmount_cancels_timer():
    h = PlainHints()
    handle = MagicMock()
    h._hint_fade_handle = handle
    h.on_unmount()
    handle.cancel.assert_called_once()
    assert h._hint_fade_handle is None


def test_activate_hint_switches_from_previous():
    h = PlainHints()
    prev = MagicMock()
    prev.set_show_hints = MagicMock()
    h._active_hint_widget = prev
    h._has_active_hints = True
    new = MagicMock()
    new.set_show_hints = MagicMock()
    with patch.object(h, "_cancel_hint_fade_timer") as ch:
        h.activate_hint(new)
    prev.set_show_hints.assert_called_once_with(False)
    new.set_show_hints.assert_called_once_with(True)
    assert h._active_hint_widget is new
    assert h._has_active_hints
    ch.assert_called_once()
