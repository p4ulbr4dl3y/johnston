"""Regression tests for shared responsive-design primitives (widgets/utils/responsive.py,
widgets/mixins/resize_debounce.py) and the widgets refactored onto them."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from textual.timer import Timer

from widgets.command_suggestions import CommandSuggestions
from widgets.mixins.resize_debounce import ResizeDebounceMixin
from widgets.presentation.screens.diff import DiffFooter, DiffHeader
from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen
from widgets.status_footer import SubagentStatusFooter
from widgets.utils.responsive import (
    BREAKPOINT_BANNER,
    BREAKPOINT_COMPACT,
    BREAKPOINT_HINT,
    DEFAULT_TERMINAL_WIDTH,
    is_compact_width,
    resolve_width,
)


class _WidthStub:
    """Minimal stand-in exposing controllable ``size``/``app`` resolution."""

    def __init__(self, size_width=0, app=None, harness_app=None):
        self.size = SimpleNamespace(width=size_width, height=1)
        if app is not None:
            self.app = app
        if harness_app is not None:
            self._harness_app = harness_app


class _UnmountedWidthStub(_WidthStub):
    """Stub whose ``app`` access raises like an unmounted Textual widget."""

    def __init__(self, harness_app):
        super().__init__(size_width=0, harness_app=harness_app)

    @property
    def app(self):
        raise RuntimeError("not mounted")


class _BadSizesStub(_WidthStub):
    """Stub with non-int widths everywhere plus a raising ``app``."""

    def __init__(self, harness_app=None):
        if harness_app is not None:
            self._harness_app = harness_app

    @property
    def size(self):
        return SimpleNamespace(width="bad")

    @property
    def app(self):
        raise RuntimeError("not mounted")


# ---------------------------------------------------------------------------
# breakpoints + helpers
# ---------------------------------------------------------------------------


class TestBreakpoints:
    def test_ordering_and_defaults(self):
        assert BREAKPOINT_BANNER < BREAKPOINT_HINT < BREAKPOINT_COMPACT < DEFAULT_TERMINAL_WIDTH

    def test_is_compact_width_boundaries(self):
        assert is_compact_width(BREAKPOINT_COMPACT - 1)
        assert not is_compact_width(BREAKPOINT_COMPACT)
        assert not is_compact_width(0)
        assert not is_compact_width(-5)
        assert not is_compact_width(None)
        assert not is_compact_width("60")

    def test_is_compact_width_custom_breakpoint(self):
        assert is_compact_width(BREAKPOINT_BANNER - 1, breakpoint=BREAKPOINT_BANNER)
        assert not is_compact_width(BREAKPOINT_BANNER, breakpoint=BREAKPOINT_BANNER)


class TestResolveWidth:
    def test_prefers_own_size(self):
        app = MagicMock()
        app.size.width = 120
        assert resolve_width(_WidthStub(size_width=55, app=app)) == 55

    def test_falls_back_to_app_size(self):
        app = MagicMock()
        app.size.width = 120
        assert resolve_width(_WidthStub(size_width=0, app=app)) == 120

    def test_falls_back_to_harness_app_size(self):
        harness = MagicMock()
        harness.size.width = 60
        assert resolve_width(_UnmountedWidthStub(harness)) == 60

    def test_default_when_nothing_usable(self):
        assert resolve_width(_WidthStub()) == DEFAULT_TERMINAL_WIDTH

    def test_ignores_non_positive_and_non_int_sizes(self):
        app = MagicMock()
        app.size.width = "bogus"
        assert resolve_width(_BadSizesStub(app)) == DEFAULT_TERMINAL_WIDTH


# ---------------------------------------------------------------------------
# ResizeDebounceMixin
# ---------------------------------------------------------------------------


class _DebouncedWidget(ResizeDebounceMixin):
    def __init__(self):
        self.render_calls = 0
        self.timers = []

    def set_timer(self, delay, callback):
        timer = MagicMock(spec=Timer)
        self.timers.append((delay, callback, timer))
        return timer

    def render_for_size(self) -> None:
        self.render_calls += 1


class TestResizeDebounceMixin:
    def test_first_resize_schedules_single_timer(self):
        w = _DebouncedWidget()
        w.on_resize(SimpleNamespace(size=SimpleNamespace(width=100)))
        assert len(w.timers) == 1
        delay, callback, timer = w.timers[0]
        assert delay == ResizeDebounceMixin.RESIZE_DEBOUNCE_SECONDS == 0.15
        assert w._resize_timer is timer

    def test_same_size_event_is_deduped(self):
        w = _DebouncedWidget()
        event = SimpleNamespace(size=SimpleNamespace(width=100))
        w.on_resize(event)
        w.on_resize(event)
        assert len(w.timers) == 1

    def test_new_size_cancels_pending_timer(self):
        w = _DebouncedWidget()
        first = MagicMock(spec=Timer)
        w._resize_timer = first
        w._last_resize_size = SimpleNamespace(width=1)
        w.on_resize(SimpleNamespace(size=SimpleNamespace(width=2)))
        first.stop.assert_called_once()
        assert w._resize_timer is w.timers[-1][2]

    def test_debounced_callback_renders_and_clears_handle(self):
        w = _DebouncedWidget()
        w.on_resize(SimpleNamespace(size=SimpleNamespace(width=100)))
        _, callback, _timer = w.timers[0]
        callback()
        assert w.render_calls == 1
        assert w._resize_timer is None

    def test_cancel_swallows_stop_errors(self):
        w = _DebouncedWidget()
        broken = MagicMock(spec=Timer)
        broken.stop.side_effect = Exception("boom")
        w._resize_timer = broken
        w.cancel_resize_timer()
        assert w._resize_timer is None

    def test_bare_mixin_render_for_size_raises(self):
        class _Bare(ResizeDebounceMixin):
            pass

        try:
            _Bare().render_for_size()
        except NotImplementedError:
            pass
        else:
            raise AssertionError("expected NotImplementedError")


# ---------------------------------------------------------------------------
# refactored widgets
# ---------------------------------------------------------------------------


def _table_text(table) -> str:
    """Render a rich Table grid to plain text (no ANSI, wide fixed console)."""
    from io import StringIO

    from rich.console import Console

    buf = StringIO()
    Console(file=buf, width=220, legacy_windows=False, no_color=True).print(table)
    return buf.getvalue()


class TestRefactoredWidgets:
    def test_footers_and_diff_widgets_use_debounce_mixin(self):
        assert any(issubclass(b, ResizeDebounceMixin) for b in SubagentStatusFooter.__bases__)
        assert any(issubclass(b, ResizeDebounceMixin) for b in DiffHeader.__bases__)
        assert any(issubclass(b, ResizeDebounceMixin) for b in DiffFooter.__bases__)

    def test_diff_header_compact_below_breakpoint(self):
        class _Sized(DiffHeader):
            def __init__(self, width):
                super().__init__(title="some/long/path.py", stats_summary="+1/-1")
                self._width = width
                self.rendered = None

            @property
            def size(self):
                return SimpleNamespace(width=self._width)

            @property
            def app(self):
                raise RuntimeError("unmounted")

            def update(self, content):
                self.rendered = content

        narrow = _Sized(BREAKPOINT_COMPACT - 1)
        wide = _Sized(120)
        narrow.render_header()
        wide.render_header()

        assert "Diff Viewer" not in _table_text(narrow.rendered)
        assert _table_text(narrow.rendered).rstrip().endswith("esc")
        assert "Diff Viewer" in _table_text(wide.rendered)
        assert "esc: close" in _table_text(wide.rendered)

    def test_diff_footer_hint_collapses_below_hint_breakpoint(self):
        class _Sized(DiffFooter):
            def __init__(self, width):
                super().__init__()
                self._width = width
                self.rendered = None

            @property
            def size(self):
                return SimpleNamespace(width=self._width)

            @property
            def app(self):
                raise RuntimeError("unmounted")

            def update(self, content):
                self.rendered = content

        def _render(width):
            widget = _Sized(width)
            widget.current_file = "a.py"
            widget.current_stats = "+1"
            widget.render_footer()
            return widget.rendered

        assert "pgup/pgdn" not in _table_text(_render(BREAKPOINT_HINT - 1))
        assert "pgup/pgdn" in _table_text(_render(BREAKPOINT_HINT + 20))

    def test_permission_hint_adapts_to_width(self):
        screen = PermissionConfirmScreen.__new__(PermissionConfirmScreen)
        compact = screen._build_hint_text(BREAKPOINT_HINT - 1)
        full = screen._build_hint_text()
        assert compact != full
        assert screen._build_hint_text(BREAKPOINT_HINT) == full
        assert screen._build_hint_text(None) == full

    def test_permission_on_mount_updates_hint_for_narrow(self):
        class _NarrowScreen(PermissionConfirmScreen):
            @property
            def size(self):
                return SimpleNamespace(width=BREAKPOINT_HINT - 1)

        screen = _NarrowScreen.__new__(_NarrowScreen)
        expected = screen._build_hint_text(BREAKPOINT_HINT - 1)
        hint = MagicMock()
        focus_target = MagicMock()
        queries = {"#permission-options-list": focus_target, "#modal-hint": hint}
        with patch.object(screen, "query_one", side_effect=lambda sel, *a: queries[sel]):
            screen.on_mount()
        hint.update.assert_called_once_with(expected)


class TestCommandSuggestionsViewportAwareness:
    class _Sized(CommandSuggestions):
        def __init__(self, width):
            super().__init__()
            self._width = width
            self.added = []

        @property
        def size(self):
            return SimpleNamespace(width=self._width)

        def clear_options(self):
            self.added.clear()

        def add_option(self, row):
            self.added.append(row)

        def _set_display(self, show):
            pass

    def test_long_path_truncated_but_kind_tag_visible_when_narrow(self):
        cs = self._Sized(width=40)
        long_path = "deeply/nested/directory/structure/with/a/very/long/file_name.py"
        cs._render_file_suggestions([long_path], "")
        assert cs.added, "expected one suggestion row"
        row = cs.added[0]
        assert row.endswith("File[/dim #71717a]")
        assert "..." in row

    def test_short_paths_align_at_legacy_column_when_wide(self):
        cs = self._Sized(width=200)
        cs._render_file_suggestions(["a.txt"], "")
        row = cs.added[0]
        plain_prefix = row.split(" [dim")[0]
        assert plain_prefix.startswith("a.txt")
        assert len(plain_prefix) >= 46 - len(" Dir") - 1

    def test_command_description_budget_shrinks_with_viewport(self):
        async def run():
            cs = self._Sized(width=50)
            desc = "x" * 120

            async def fake_provider():
                return [("/cmd", desc)]

            with patch("widgets.command_suggestions.get_all_command_suggestions", fake_provider):
                await cs.update_query("/cm", "/cm", 3)
            return cs.added

        rows = asyncio.run(run())
        assert rows, "expected at least one suggestion row"
