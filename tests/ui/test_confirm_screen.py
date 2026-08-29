import unittest
from unittest.mock import MagicMock

from widgets.presentation.screens.confirm import ConfirmScreen


class TestConfirmScreen(unittest.TestCase):
    def test_confirm_screen_enter_and_y_dismiss_true(self):
        screen = ConfirmScreen(title="Test Title", message="Test Msg")
        screen.dismiss = MagicMock()

        key_enter = MagicMock(key="enter")
        screen._on_key(key_enter)
        screen.dismiss.assert_called_once_with(True)

        screen.dismiss.reset_mock()
        key_y = MagicMock(key="y")
        screen._on_key(key_y)
        screen.dismiss.assert_called_once_with(True)

    def test_confirm_screen_esc_and_n_dismiss_false(self):
        screen = ConfirmScreen(title="Test Title", message="Test Msg")
        screen.dismiss = MagicMock()

        key_esc = MagicMock(key="escape")
        screen._on_key(key_esc)
        screen.dismiss.assert_called_once_with(False)

        screen.dismiss.reset_mock()
        key_n = MagicMock(key="n")
        screen._on_key(key_n)
        screen.dismiss.assert_called_once_with(False)

        screen.dismiss.reset_mock()
        screen.action_cancel()
        screen.dismiss.assert_called_once_with(False)


class TestConfirmScreenPilot(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_screen_pilot_enter_and_esc(self):
        from textual.app import App

        class PilotApp(App):
            def __init__(self):
                super().__init__()
                self.result = None

            async def on_mount(self):
                def cb(res):
                    self.result = res

                self.push_screen(ConfirmScreen(title="Delete?", message="Sure?"), callback=cb)

        app = PilotApp()
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmScreen)
            # Verify dialog width uses compact max width 56
            dialog = app.screen.query_one("#modal-dialog")
            self.assertIsNotNone(dialog.styles.width)
            self.assertEqual(dialog.styles.width.value, 56)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.result, True)


if __name__ == "__main__":
    unittest.main()

