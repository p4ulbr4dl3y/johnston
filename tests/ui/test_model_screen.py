import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App
from textual.widgets.option_list import Option

from widgets.presentation.screens.model import ModelScreen


class TestModelScreenBuildData(unittest.TestCase):
    """Unit tests for ModelScreen option building and active-model detection."""

    def test_is_active_model_no_target_model(self):
        self.assertFalse(ModelScreen._is_active_model("p", "m", "prov", ""))

    def test_is_active_model_wrong_provider(self):
        self.assertFalse(ModelScreen._is_active_model("p1", "m", "p2", "target"))

    def test_is_active_model_exact_match(self):
        self.assertTrue(ModelScreen._is_active_model("p1", "model-a", "p1", "model-a"))

    def test_is_active_model_display_name_match(self):
        with patch("core.models_catalog.catalog.get_model_display_name", return_value="display name"):
            self.assertTrue(ModelScreen._is_active_model("p1", "model-a", "p1", "Model A"))

    def test_is_active_model_display_name_no_match(self):
        with patch("core.models_catalog.catalog.get_model_display_name", side_effect=["foo", "bar"]):
            self.assertFalse(ModelScreen._is_active_model("p1", "model-a", "", "Model A"))

    def test_build_data_dict_single_provider_active(self):
        data = {"prov1": {"name": "Provider 1", "models": ["model-a", "model-b"]}}
        screen = ModelScreen(models_data=data, current_model="model-a", current_provider="prov1")
        self.assertEqual(
            screen.raw_items,
            [None, ("prov1", "model-a", "Provider 1"), ("prov1", "model-b", "Provider 1")],
        )
        self.assertEqual(screen.default_value, ("prov1", "model-a", "Provider 1"))
        self.assertIn("●", screen.raw_options[1])
        self.assertNotIn("●", screen.raw_options[2])

    def test_build_data_dict_empty_models_and_separator(self):
        data = {
            "prov1": {"name": "Provider 1", "models": ["model-a"]},
            "prov2": {"name": "Provider 2", "models": []},
            "prov3": {"name": "Provider 3", "models": ["model-c"]},
        }
        screen = ModelScreen(models_data=data, current_model="model-c", current_provider="prov3")
        opts, items = screen.raw_options, screen.raw_items
        self.assertIsInstance(opts[2], Option)
        self.assertEqual(opts[2].prompt, "")
        self.assertTrue(opts[2].disabled)
        self.assertIsNone(items[2])
        self.assertEqual(screen.default_value, ("prov3", "model-c", "Provider 3"))
        self.assertEqual(len(items), 5)

    def test_build_data_list_active(self):
        screen = ModelScreen(models_data=["model-a", "model-b"], current_model="model-a", current_provider="prov1")
        self.assertEqual(screen.raw_items, ["model-a", "model-b"])
        self.assertEqual(screen.default_value, "model-a")
        self.assertIn("●", screen.raw_options[0])
        self.assertNotIn("●", screen.raw_options[1])

    def test_build_data_list_no_target_falls_back_to_first(self):
        screen = ModelScreen(models_data=["model-a"], current_model="", current_provider="")
        self.assertEqual(screen.default_value, "model-a")
        self.assertNotIn("●", screen.raw_options[0])


class ModelHostApp(App[None]):
    def __init__(self, screen):
        super().__init__()
        self.screen_to_test = screen
        self.dismiss_result = None

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res

        self.push_screen(self.screen_to_test, callback=callback)


class TestModelScreenPilot(unittest.IsolatedAsyncioTestCase):
    async def test_select_model_via_keyboard(self):
        data = {
            "prov1": {"name": "Provider 1", "models": ["model-a", "model-b"]},
            "prov2": {"name": "Provider 2", "models": ["model-c"]},
        }
        screen = ModelScreen(models_data=data, current_model="", current_provider="")
        app = ModelHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # First model is auto-highlighted; confirm selection
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.dismiss_result, ("prov1", "model-a", "Provider 1"))

    async def test_select_model_with_navigation(self):
        data = {"prov1": {"name": "Provider 1", "models": ["model-a", "model-b"]}}
        screen = ModelScreen(models_data=data, current_model="", current_provider="")
        app = ModelHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            # Move down to the second model and confirm
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.dismiss_result, ("prov1", "model-b", "Provider 1"))

    async def test_search_filters_models(self):
        data = {"prov1": {"name": "Provider 1", "models": ["model-a", "model-b"]}}
        screen = ModelScreen(models_data=data, current_model="", current_provider="")
        app = ModelHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            self.assertEqual(screen.filtered_items, [None, ("prov1", "model-b", "Provider 1")])
            await pilot.press("escape")
            await pilot.pause()

    async def test_refresh_models_via_keybinding(self):
        initial_data = {"prov1": {"name": "Provider 1", "models": ["model-a"]}}
        refreshed_data = {
            "prov1": {"name": "Provider 1", "models": ["model-a", "model-b", "model-c"]}
        }
        mock_pm = MagicMock()
        mock_pm.fetch_models_grouped = AsyncMock(return_value=refreshed_data)

        screen = ModelScreen(models_data=initial_data, current_model="", current_provider="", pm=mock_pm)
        app = ModelHostApp(screen)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(len(screen.filtered_items), 2)  # [None, model-a]
            await pilot.press("ctrl+r")
            await pilot.pause()
            mock_pm.fetch_models_grouped.assert_called_once_with(force_refresh=True)
            self.assertEqual(len(screen.filtered_items), 4)  # [None, model-a, model-b, model-c]
            await pilot.press("escape")
            await pilot.pause()


class TestModelScreenRefreshAction(unittest.IsolatedAsyncioTestCase):
    async def test_action_refresh_no_pm(self):
        screen = ModelScreen(models_data=["model-a"])
        screen.notify = MagicMock()
        await screen.action_refresh_models()
        screen.notify.assert_called_once_with("Provider manager not available", severity="warning")

    async def test_action_refresh_success(self):
        mock_pm = MagicMock()
        mock_pm.fetch_models_grouped = AsyncMock(return_value={
            "prov1": {"name": "P1", "models": ["model-new"]}
        })
        screen = ModelScreen(models_data=["old-model"], pm=mock_pm)
        screen.notify = MagicMock()
        await screen.action_refresh_models()
        mock_pm.fetch_models_grouped.assert_called_once_with(force_refresh=True)
        self.assertIn(("prov1", "model-new", "P1"), screen.raw_items)
        screen.notify.assert_any_call("Models refreshed")

    async def test_action_refresh_empty_data(self):
        mock_pm = MagicMock()
        mock_pm.fetch_models_grouped = AsyncMock(return_value={})
        screen = ModelScreen(models_data=["old-model"], pm=mock_pm)
        screen.notify = MagicMock()
        await screen.action_refresh_models()
        screen.notify.assert_any_call("No models found", severity="warning")

    async def test_action_refresh_exception(self):
        mock_pm = MagicMock()
        mock_pm.fetch_models_grouped = AsyncMock(side_effect=RuntimeError("Network error"))
        screen = ModelScreen(models_data=["old-model"], pm=mock_pm)
        screen.notify = MagicMock()
        await screen.action_refresh_models()
        screen.notify.assert_any_call("Failed to refresh models: Network error", severity="error")


if __name__ == "__main__":
    unittest.main()
