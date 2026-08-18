"""Coverage-focused tests for widgets/presentation/screens/base_selection.py.

Exercises the exception paths, alternate display states, key handlers and
selection handlers of the BaseSelectionScreen (search filtering included).
"""

import unittest
from unittest.mock import MagicMock, patch

from textual.events import Key

from widgets.presentation.screens.base_selection import BaseSelectionScreen


class RaisingList(list):
    """List whose .index() always raises, but membership still works."""

    def index(self, *args, **kwargs):
        raise ValueError("boom")


class TestBaseSelectionCoverage(unittest.TestCase):
    def test_on_mount_index_exception(self):
        items = RaisingList(["a", "b"])
        screen = BaseSelectionScreen("t", ["A"], items, "b", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        screen.on_mount()
        self.assertIsNone(opt_list.highlighted)
        opt_list.focus.assert_called_once()

    def test_on_mount_scroll_exception(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "b", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = 1
        opt_list.scroll_to_highlight = MagicMock(side_effect=Exception("boom"))
        screen.query_one = MagicMock(return_value=opt_list)
        screen.on_mount()
        opt_list.focus.assert_called_once()

    def _on_input(self, screen, value):
        opt_list = MagicMock()
        screen.query_one = MagicMock(return_value=opt_list)
        event = MagicMock()
        event.value = value
        screen.on_input_changed(event)
        return opt_list

    def test_on_input_changed_section_filter_and_empty_header(self):
        options = ["Hdr1", "MatchOp", "Hdr2", "x", ""]
        items = [None, "match1", None, "z", None]
        screen = BaseSelectionScreen("t", options, items, "zzz", show_search=True)
        self._on_input(screen, "match")
        self.assertEqual(screen.filtered_items, [None, "match1"])

    def test_on_input_changed_empty_query(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        self._on_input(screen, "  ")
        self.assertEqual(screen.filtered_items, ["a", "b"])
        self.assertEqual(screen.filtered_options, ["A", "B"])

    def test_on_input_submitted_highlighted_item(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("a")

    def test_on_input_submitted_highlighted_none_item_loop(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        screen.filtered_items = [None, "a"]
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("a")

    def test_on_input_submitted_all_none_default(self):
        screen = BaseSelectionScreen("t", ["A"], [None], "def", show_search=False)
        screen.filtered_items = [None]
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("def")

    def test_on_input_submitted_no_highlight_fallback(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_input_submitted(MagicMock())
            mock_dismiss.assert_called_once_with("a")

    def _base_key_harness(self, screen, highlighted=None, non_none_first=True, search_focus=True):
        items = ["a", "b"] if non_none_first else [None, "b"]
        screen.filtered_items = items
        opt_list = MagicMock()
        opt_list.highlighted = highlighted
        search_input = MagicMock()
        search_input.has_focus = search_focus

        def qo(id_, *args):
            if "search-input" in id_:
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=qo)
        return opt_list

    def test_on_key_down_no_highlight_picks_first(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        self._base_key_harness(screen, highlighted=None)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        self.assertEqual(screen.query_one("o").highlighted, 0)
        event.prevent_default.assert_called()
        event.stop.assert_called()

    def test_on_key_down_skips_none(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        opt_list = self._base_key_harness(screen, highlighted=None, non_none_first=False)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        self.assertEqual(opt_list.highlighted, 1)
        event.prevent_default.assert_called()

    def test_on_key_down_moves(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        opt_list = self._base_key_harness(screen, highlighted=0)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        opt_list.action_cursor_down.assert_called_once()
        event.prevent_default.assert_called()

    def test_on_key_up_moves(self):
        screen = BaseSelectionScreen("t", ["A", "B"], ["a", "b"], "a", show_search=True)
        opt_list = self._base_key_harness(screen, highlighted=1)
        event = Key(key="up", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        opt_list.action_cursor_up.assert_called_once()

    def test_on_key_search_not_focused(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=True)
        self._base_key_harness(screen, highlighted=0, search_focus=False)
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)
        event.prevent_default.assert_not_called()

    def test_on_key_exception(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=True)
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        event = Key(key="down", character=None)
        event.prevent_default = MagicMock()
        event.stop = MagicMock()
        screen._on_key(event)  # must not raise

    def test_on_option_selected_none_item_stops(self):
        screen = BaseSelectionScreen("t", ["A"], [None], "a", show_search=False)
        screen.filtered_items = [None]
        event = MagicMock()
        event.option_index = 0
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_option_list_option_selected(event)
            mock_dismiss.assert_not_called()
        event.stop.assert_called_once()

    def test_on_option_selected_item(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        screen.filtered_items = ["a"]
        event = MagicMock()
        event.option_index = 0
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_option_list_option_selected(event)
            mock_dismiss.assert_called_once_with("a")

    def test_on_option_selected_invalid_index(self):
        screen = BaseSelectionScreen("t", ["A"], ["a"], "a", show_search=False)
        screen.filtered_items = ["a"]
        event = MagicMock()
        event.option_index = 99
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.on_option_list_option_selected(event)
            mock_dismiss.assert_not_called()
        event.stop.assert_not_called()


if __name__ == "__main__":
    unittest.main()
