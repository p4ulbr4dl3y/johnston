import unittest
from unittest.mock import MagicMock

from textual.events import Key

from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.providers import ApiKeyInputScreen


class TestModalSearchShiftTab(unittest.TestCase):
    def test_base_selection_screen_blocks_shift_tab_when_search_enabled(self):
        screen = BaseSelectionScreen(
            title="Test", options=["Opt1", "Opt2"], items=["item1", "item2"], default_value="item1", show_search=True
        )

        for key_name in ("shift+tab", "backtab", "shift_tab"):
            event = Key(key=key_name, character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()

            screen._on_key(event)

            event.prevent_default.assert_called_once()
            event.stop.assert_called_once()

    def test_base_selection_screen_allows_other_keys(self):
        screen = BaseSelectionScreen(
            title="Test", options=["Opt1", "Opt2"], items=["item1", "item2"], default_value="item1", show_search=True
        )

        event = Key(key="a", character="a")
        event.prevent_default = MagicMock()
        event.stop = MagicMock()

        screen._on_key(event)

        event.prevent_default.assert_not_called()
        event.stop.assert_not_called()

    def test_api_key_input_screen_blocks_shift_tab(self):
        screen = ApiKeyInputScreen(provider_name="Test", provider_key="test")

        for key_name in ("shift+tab", "backtab", "shift_tab"):
            event = Key(key=key_name, character=None)
            event.prevent_default = MagicMock()
            event.stop = MagicMock()

            screen._on_key(event)

            event.prevent_default.assert_called_once()
            event.stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
