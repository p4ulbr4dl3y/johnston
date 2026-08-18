import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from rich.console import Console
from rich.segment import Segment
from rich.style import Style as RichStyle
from textual.geometry import Offset
from textual.screen import Screen
from textual.selection import Selection
from textual.strip import Strip
from textual.visual import RichVisual
from textual.widget import Widget
from textual.widgets import Static

from widgets.patch import apply_textual_patches


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
