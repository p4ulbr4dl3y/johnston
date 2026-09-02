import asyncio
import unittest
from unittest.mock import MagicMock, patch

from textual import events
from textual.app import App, ComposeResult
from textual.widgets import Input, Label, OptionList, Static

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.api_key import ApiKeyScreen
from widgets.presentation.screens.constants import (
    MODAL_HINT,
    MODAL_OPTION_LIST,
    MODAL_OPTION_LIST_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
)
from widgets.presentation.screens.providers import ProvidersScreen
from widgets.presentation.screens.rewind import (
    RewindScreen,
    RewindSelection,
    format_rewind_files,
)
from widgets.presentation.screens.rewind_action import RewindActionScreen


class ModalTestApp(App):
    """Simple Test App for mounting modal screens."""

    def compose(self) -> ComposeResult:
        yield Static("root")


class TestRewindActionScreen(unittest.IsolatedAsyncioTestCase):
    """Coverage tests for RewindActionScreen."""

    def test_init_and_compose(self):
        entry = RewindEntry(1, "Fix bug in parser", "+5 / -2", changed_files=["parser.py"])
        screen = RewindActionScreen(
            entry,
            session_id="sess-123",
            project_path="/proj",
            user_messages=[entry],
        )
        self.assertEqual(screen.session_id, "sess-123")
        self.assertEqual(screen.project_path, "/proj")
        self.assertEqual(len(screen.user_messages), 1)
        self.assertEqual(len(screen.items), 3)

    async def test_mount_and_files_display_with_changes(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entry = RewindEntry(0, "commit message", "+10 / -5", changed_files=["a.py", "b.py"])
            screen = RewindActionScreen(entry)
            await app.push_screen(screen)
            await pilot.pause()

            files_widget = screen.query_one("#rewind-files", Static)
            self.assertTrue(files_widget.display)
            self.assertIn("Files to revert", str(files_widget.render()))

            opt_list = screen.query_one(f"#{MODAL_OPTION_LIST_ID}", OptionList)
            self.assertEqual(opt_list.highlighted, 0)

            # Test on_resize
            screen.on_resize(events.Resize(100, 50, 100, 50))
            self.assertTrue(files_widget.display)

    async def test_mount_and_files_display_without_changes(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entry = RewindEntry(0, "clean message", "", changed_files=[])
            screen = RewindActionScreen(entry)
            await app.push_screen(screen)
            await pilot.pause()

            files_widget = screen.query_one("#rewind-files", Static)
            self.assertFalse(files_widget.display)

    def test_row_width_and_apply_dialog_fit_fallbacks(self):
        entry = RewindEntry(0, "msg")
        screen = RewindActionScreen(entry)
        # Not mounted, query_one will fail, fallbacks executed safely
        self.assertGreater(screen._row_width(), 0)
        screen._apply_dialog_fit()

    def test_on_mount_and_update_files_display_fallbacks(self):
        entry = RewindEntry(0, "msg", changed_files=["a.py"])
        screen = RewindActionScreen(entry)
        # Calling without mount should not throw
        screen._update_files_display()
        screen.on_mount()

    async def test_option_selection_actions(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entry = RewindEntry(5, "message text", "+1 / -1")
            screen = RewindActionScreen(entry)
            await app.push_screen(screen)
            await pilot.pause()

            # Invalid option index
            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = 99
            screen.on_option_list_option_selected(mock_event)
            mock_event.stop.assert_called_once()

            # Option 0 -> conversation only (restore_code=False)
            dismissed = []
            screen.dismiss = lambda val: dismissed.append(val)
            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = 0
            screen.on_option_list_option_selected(mock_event)
            self.assertEqual(len(dismissed), 1)
            self.assertEqual(dismissed[-1], RewindSelection(index=5, restore_code=False))

            # Option 1 -> both (restore_code=True)
            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = 1
            screen.on_option_list_option_selected(mock_event)
            self.assertEqual(len(dismissed), 2)
            self.assertEqual(dismissed[-1], RewindSelection(index=5, restore_code=True))

            # Option 2 -> diff
            with patch.object(screen, "_open_diff_viewer") as mock_diff:
                mock_event = MagicMock(spec=OptionList.OptionSelected)
                mock_event.option_index = 2
                screen.on_option_list_option_selected(mock_event)
                mock_diff.assert_called_once()

    async def test_open_diff_viewer(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            msg0 = RewindEntry(0, "init")
            msg1 = RewindEntry(5, "clean\nmultiline\rtext", "+3 / -1", changed_files=["foo.py"])
            user_messages = [msg0, msg1]

            screen = RewindActionScreen(
                msg1,
                session_id="sess-abc",
                project_path="/tmp/project",
                user_messages=user_messages,
            )
            await app.push_screen(screen)
            await pilot.pause()

            mock_cm = MagicMock()
            mock_cm.get_checkpoint_diff.return_value = [("foo.py", "@@ -1 +1 @@", 1, 1)]

            with patch("core.domain.ports.checkpoint.get_checkpoint_manager", return_value=mock_cm), \
                 patch.object(app, "push_screen") as mock_push:
                screen._open_diff_viewer()
                mock_cm.get_checkpoint_diff.assert_called_once_with(
                    "sess-abc",
                    1,
                    project_path="/tmp/project",
                    scoped_files=["foo.py"],
                )
                mock_push.assert_called_once()
                diff_screen = mock_push.call_args[0][0]
                self.assertIn("clean multiline text", diff_screen.title_text)

    async def test_open_diff_viewer_empty_text_and_no_cm(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            msg = RewindEntry(0, "   \n\r  ", changed_files=[])
            screen = RewindActionScreen(msg, session_id="sess-1")
            await app.push_screen(screen)
            await pilot.pause()

            with patch("core.domain.ports.checkpoint.get_checkpoint_manager", side_effect=Exception("no cm")), \
                 patch.object(app, "push_screen") as mock_push:
                screen._open_diff_viewer()
                mock_push.assert_called_once()
                diff_screen = mock_push.call_args[0][0]
                self.assertIn("(empty message)", diff_screen.title_text)

    def test_open_diff_viewer_without_session_id_or_app(self):
        entry = RewindEntry(0, "test")
        screen = RewindActionScreen(entry, session_id=None)
        with patch.object(RewindActionScreen, "app", new=None):
            # Should execute cleanly without error
            screen._open_diff_viewer()

    def test_key_handling_and_action_cancel(self):
        entry = RewindEntry(0, "test")
        screen = RewindActionScreen(entry)

        dismissed = []
        screen.dismiss = lambda val: dismissed.append(val)

        # escape key
        esc_event = events.Key("escape", "escape")
        screen._on_key(esc_event)
        self.assertEqual(dismissed, [None])

        # tab key
        tab_event = events.Key("tab", "tab")
        screen._on_key(tab_event)
        self.assertTrue(tab_event._stop_propagation)

        # action_cancel
        dismissed.clear()
        screen.action_cancel()
        self.assertEqual(dismissed, [None])


class TestRewindScreen(unittest.IsolatedAsyncioTestCase):
    """Additional coverage tests for RewindScreen."""

    def test_format_rewind_files_edge_cases(self):
        # Empty changed files
        t_empty = format_rewind_files([])
        self.assertEqual(t_empty.plain, "")

        # max_width > 0 but small (< 15 limit)
        files = ["very_long_file_name_for_testing_purposes.py"]
        t_small_w = format_rewind_files(files, max_width=10)
        self.assertIn("very_long_", t_small_w.plain)

        # max_width <= 0
        t_no_limit = format_rewind_files(files, max_width=0)
        self.assertIn("very_long_file_name_for_testing_purposes.py", t_no_limit.plain)

        # changed_files > max_show
        files_many = [f"file_{i}.py" for i in range(10)]
        t_many = format_rewind_files(files_many, git_stats="+10/-2", max_show=3)
        self.assertIn("... and 7 more", t_many.plain)
        self.assertIn("(+10/-2)", t_many.plain)

    def test_format_step1_options_empty_text_and_checkpoints(self):
        screen = RewindScreen([], checkpoints_enabled=True)
        entries = [
            RewindEntry(0, "\n\r   \t"),
            RewindEntry(1, "normal text", git_stats=""),
            RewindEntry(2, "another text", git_stats="+2 / -1"),
        ]
        opts = screen._format_step1_options(60, entries)
        self.assertIn("(empty message)", opts[0])
        self.assertIn("normal text", opts[1])
        self.assertIn("+2 / -1", opts[2])

    def test_row_width_fallback(self):
        screen = RewindScreen([])
        w = screen._row_width()
        self.assertGreater(w, 0)

    def test_apply_filter_fallback_without_mount(self):
        screen = RewindScreen([RewindEntry(0, "test")])
        # Calling without mount triggers query_one exception safely
        screen._apply_filter("test")

    async def test_apply_filter_and_refresh_options(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entries = [
                RewindEntry(0, "alpha beta"),
                RewindEntry(1, "gamma delta"),
                RewindEntry(2, "beta theta"),
            ]
            screen = RewindScreen(entries, checkpoints_enabled=True)
            await app.push_screen(screen)
            await pilot.pause()

            # Filter with match
            screen._apply_filter("beta")
            self.assertEqual(len(screen.filtered_entries), 2)
            opt_list = screen.query_one(MODAL_OPTION_LIST, OptionList)
            self.assertEqual(opt_list.highlighted, 2)

            # Filter with no match
            screen._apply_filter("nonexistent token")
            self.assertEqual(len(screen.filtered_entries), 0)
            self.assertEqual(opt_list.highlighted, 0)

            # Filter reset
            screen._apply_filter("")
            self.assertEqual(len(screen.filtered_entries), 3)

            # _refresh_options when opt_list.highlighted is None
            opt_list.highlighted = None
            screen._refresh_options()
            self.assertEqual(opt_list.highlighted, 3)

            # _refresh_options when opt_list.highlighted is out of range
            opt_list.highlighted = 999
            screen._refresh_options()
            self.assertEqual(opt_list.highlighted, 3)

            # Resize triggers refresh
            screen.on_resize(events.Resize(40, 20, 40, 20))
            self.assertIsNotNone(opt_list.highlighted)

    async def test_refresh_options_responsive_width_breakpoint(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            screen = RewindScreen([RewindEntry(0, "test")])
            await app.push_screen(screen)
            await pilot.pause()

            with patch("widgets.utils.responsive.resolve_screen_width", return_value=30):
                screen._refresh_options()
                hint = screen.query_one(MODAL_HINT, Label)
                self.assertIn("enter", str(hint.render()))

    async def test_on_mount_default_value_selection(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entries = [RewindEntry(10, "first"), RewindEntry(20, "second")]
            screen = RewindScreen(entries)
            screen.default_value = 10
            await app.push_screen(screen)
            await pilot.pause()
            opt_list = screen.query_one(MODAL_OPTION_LIST, OptionList)
            self.assertEqual(opt_list.highlighted, 0)

    async def test_on_mount_fallback_focus_option_list(self):
        app = ModalTestApp()
        async with app.run_test():
            screen = RewindScreen([RewindEntry(0, "test")])
            # Mount when search input focus fails
            with patch.object(screen, "query_one") as mock_q:
                opt_mock = MagicMock()
                mock_q.side_effect = lambda selector, *args, **kwargs: (
                    opt_mock if selector in (MODAL_OPTION_LIST, OptionList) or selector == f"#{MODAL_OPTION_LIST_ID}" else (_ for _ in ()).throw(Exception("no input"))
                )
                screen.on_mount()
                opt_mock.focus.assert_called()

    async def test_on_input_changed_and_submitted(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entries = [
                RewindEntry(0, "first message"),
                RewindEntry(1, "second message"),
            ]
            screen = RewindScreen(entries, checkpoints_enabled=False)
            await app.push_screen(screen)
            await pilot.pause()

            # on_input_changed
            inp = screen.query_one(MODAL_SEARCH_INPUT, Input)
            screen.on_input_changed(Input.Changed(inp, "second"))
            self.assertEqual(len(screen.filtered_entries), 1)

            # on_input_submitted with matched entry (highlighted = 0)
            opt_list = screen.query_one(MODAL_OPTION_LIST, OptionList)
            opt_list.highlighted = 0
            dismissed = []
            screen.dismiss = lambda val: dismissed.append(val)
            screen.on_input_submitted(Input.Submitted(inp, "second"))
            self.assertEqual(dismissed[-1], RewindSelection(index=1, restore_code=False))

            # on_input_submitted with Current state (highlighted = 1)
            opt_list.highlighted = 1
            screen.on_input_submitted(Input.Submitted(inp, "second"))
            self.assertIsNone(dismissed[-1])

    async def test_on_option_list_option_selected_invalid_and_out_of_bounds(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entries = [RewindEntry(0, "first msg")]
            screen = RewindScreen(entries)
            await app.push_screen(screen)
            await pilot.pause()

            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = -1
            screen.on_option_list_option_selected(mock_event)
            mock_event.stop.assert_called_once()

            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = 50
            screen.on_option_list_option_selected(mock_event)
            mock_event.stop.assert_called_once()

    async def test_on_option_list_option_selected_no_changes(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entries = [RewindEntry(0, "no git changes", git_stats="no changes")]
            screen = RewindScreen(entries, checkpoints_enabled=True)
            await app.push_screen(screen)
            await pilot.pause()

            dismissed = []
            screen.dismiss = lambda val: dismissed.append(val)

            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = 0
            screen.on_option_list_option_selected(mock_event)
            self.assertEqual(dismissed, [RewindSelection(index=0, restore_code=False)])

    async def test_action_done_callback_in_rewind_screen(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            entries = [RewindEntry(0, "code changes", "+10 / -2", changed_files=["main.py"])]
            screen = RewindScreen(entries, checkpoints_enabled=True)
            await app.push_screen(screen)
            await pilot.pause()

            mock_event = MagicMock(spec=OptionList.OptionSelected)
            mock_event.option_index = 0

            with patch.object(app, "push_screen") as mock_push:
                screen.on_option_list_option_selected(mock_event)
                mock_push.assert_called_once()
                args, kwargs = mock_push.call_args
                cb = kwargs["callback"]

                # Case 1: user selected an action
                dismissed = []
                screen.dismiss = lambda val: dismissed.append(val)
                cb(RewindSelection(index=0, restore_code=True))
                self.assertEqual(dismissed, [RewindSelection(index=0, restore_code=True)])

                # Case 2: user cancelled action modal (sel is None) -> focuses search input
                cb(None)
                search_input = screen.query_one(MODAL_SEARCH_INPUT, Input)
                self.assertTrue(search_input.has_focus)

                # Case 3: user cancelled action modal but search_input focus throws
                with patch.object(screen, "query_one", side_effect=Exception("search input gone")):
                    cb(None)

    async def test_key_handling_and_cancel(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            screen = RewindScreen([RewindEntry(0, "test")])
            await app.push_screen(screen)
            await pilot.pause()

            dismissed = []
            screen.dismiss = lambda val: dismissed.append(val)

            # Tab
            tab_ev = events.Key("tab", "tab")
            await screen._on_key(tab_ev)
            self.assertTrue(tab_ev._stop_propagation)

            # Search nav key (up/down handled by mixin)
            with patch.object(screen, "_handle_search_navigation", return_value=True):
                up_ev = events.Key("up", "up")
                await screen._on_key(up_ev)

            # Non-nav key delegates to super
            with patch.object(screen, "_handle_search_navigation", return_value=False):
                char_ev = events.Key("a", "a")
                res = screen._on_key(char_ev)
                if asyncio.iscoroutine(res):
                    await res

            screen.action_cancel()
            self.assertEqual(dismissed, [None])


class TestApiKeyScreen(unittest.IsolatedAsyncioTestCase):
    """Coverage tests for ApiKeyScreen."""

    async def test_compose_placeholder_variants(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            # Long key masked
            s1 = ApiKeyScreen("OpenAI", current_key="sk-1234567890abcdef")
            await app.push_screen(s1)
            await pilot.pause()
            inp1 = s1.query_one("#providers-key-input", Input)
            self.assertEqual(inp1.placeholder, "sk-1...cdef")
            s1.dismiss(None)

            # Short key masked
            s2 = ApiKeyScreen("Anthropic", current_key="short")
            await app.push_screen(s2)
            await pilot.pause()
            inp2 = s2.query_one("#providers-key-input", Input)
            self.assertEqual(inp2.placeholder, "short")
            s2.dismiss(None)

            # Empty key
            s3 = ApiKeyScreen("Gemini", current_key="")
            await app.push_screen(s3)
            await pilot.pause()
            inp3 = s3.query_one("#providers-key-input", Input)
            self.assertEqual(inp3.placeholder, "API Key...")
            s3.dismiss(None)

    async def test_mount_resize_and_submit_value(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            screen = ApiKeyScreen("ProviderX", current_key="old-key")
            await app.push_screen(screen)
            await pilot.pause()

            inp = screen.query_one("#providers-key-input", Input)
            self.assertTrue(inp.has_focus)

            # Resize
            screen.on_resize(events.Resize(80, 24, 80, 24))

            # Submit new value
            dismissed = []
            screen.dismiss = lambda val: dismissed.append(val)
            screen.on_input_submitted(Input.Submitted(inp, "  new-secret-key  "))
            self.assertEqual(dismissed, ["new-secret-key"])

    async def test_submit_empty_value_retains_current_key(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            screen = ApiKeyScreen("ProviderX", current_key="default-key")
            await app.push_screen(screen)
            await pilot.pause()

            inp = screen.query_one("#providers-key-input", Input)
            dismissed = []
            screen.dismiss = lambda val: dismissed.append(val)
            screen.on_input_submitted(Input.Submitted(inp, "   "))
            self.assertEqual(dismissed, ["default-key"])

    def test_key_handling_and_cancel(self):
        screen = ApiKeyScreen("ProviderX")
        dismissed = []
        screen.dismiss = lambda val: dismissed.append(val)

        # escape
        esc_ev = events.Key("escape", "escape")
        screen._on_key(esc_ev)
        self.assertEqual(dismissed, [None])

        # tab
        tab_ev = events.Key("tab", "tab")
        screen._on_key(tab_ev)
        self.assertTrue(tab_ev._stop_propagation)

        # action_cancel
        dismissed.clear()
        screen.action_cancel()
        self.assertEqual(dismissed, [None])

    def test_apply_dialog_fit_fallback(self):
        screen = ApiKeyScreen("ProviderX")
        # Unmounted call does not raise
        screen._apply_dialog_fit()
        screen.on_mount()


class TestProvidersScreen(unittest.IsolatedAsyncioTestCase):
    """Coverage tests for ProvidersScreen."""

    def test_init_and_build_options_status_tags(self):
        providers = {
            "p_disabled": {"name": "Disabled Provider", "enabled": False},
            "p_active": {"name": "Active Provider", "models": ["m1", "m2"]},
            "p_configured": {"name": "Configured Provider", "models": ["m1"]},
            "p_auth": {"name": "Auth Needed Provider"},
            "invalid_entry": "not_a_dict",
        }
        configured = {"p_active": "key1", "p_configured": "key2"}
        screen = ProvidersScreen(
            providers=providers,
            active_key="p_active",
            configured_keys=configured,
            disabled_providers=["p_disabled"],
        )

        self.assertEqual(len(screen.raw_items), 4)
        self.assertIn("p_active", screen.raw_items)
        self.assertIn("p_configured", screen.raw_items)
        self.assertIn("p_disabled", screen.raw_items)
        self.assertIn("p_auth", screen.raw_items)

    def test_get_provider_model_count_sources(self):
        screen = ProvidersScreen({}, "", {})

        # 1. Directly in provider dict
        self.assertEqual(screen._get_provider_model_count("p1", {"models": ["a", "b"]}), 2)

        # 2. From cache file
        with patch("os.path.exists", return_value=True), \
             patch("widgets.presentation.screens.providers.cached_json_read", return_value={"models": ["m1", "m2", "m3"]}):
            self.assertEqual(screen._get_provider_model_count("cached_p", {}), 3)

        # 3. From models catalog
        with patch("os.path.exists", return_value=False), \
             patch("widgets.presentation.screens.providers.catalog.get_catalog_provider", return_value={"models": ["cat1"]}):
            self.assertEqual(screen._get_provider_model_count("catalog_p", {}), 1)

        # 4. Fallback 0
        with patch("os.path.exists", return_value=False), \
             patch("widgets.presentation.screens.providers.catalog.get_catalog_provider", side_effect=Exception("error")):
            self.assertEqual(screen._get_provider_model_count("none_p", {}), 0)

    async def test_mount_resize_and_filter(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            providers = {
                "openai": {"name": "OpenAI", "models": ["gpt-4o"]},
                "anthropic": {"name": "Anthropic", "models": ["claude-3-5-sonnet"]},
            }
            screen = ProvidersScreen(providers, "openai", {"openai": "key"})
            await app.push_screen(screen)
            await pilot.pause()

            inp = screen.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
            inp.value = "Anthropic"
            screen.on_resize(events.Resize(80, 24, 80, 24))
            self.assertEqual(len(screen.filtered_items), 1)
            self.assertEqual(screen.filtered_items[0], "anthropic")

    async def test_handle_selection_pushes_api_key_modal(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            providers = {
                "openai": {"name": "OpenAI"},
            }
            mock_pm = MagicMock()
            mock_pm.get_api_key.return_value = "pm-key"

            screen = ProvidersScreen(providers, "", {}, pm=mock_pm)
            await app.push_screen(screen)
            await pilot.pause()

            # Selection out of bounds or None item
            screen._handle_selection(99)
            screen._handle_selection(-1)
            screen.filtered_items = [None]
            screen._handle_selection(0)

            # Valid selection -> pushes ApiKeyScreen
            screen.filtered_items = ["openai"]
            with patch.object(app, "push_screen") as mock_push:
                screen._handle_selection(0)
                mock_push.assert_called_once()
                args, kwargs = mock_push.call_args
                api_key_screen = args[0]
                cb = kwargs["callback"]
                self.assertIsInstance(api_key_screen, ApiKeyScreen)
                self.assertEqual(api_key_screen.provider_name, "OpenAI")

                # Test callback when key entered
                dismissed = []
                screen.dismiss = lambda val: dismissed.append(val)
                cb("new-key-123")
                self.assertEqual(dismissed, [("openai", "new-key-123")])

                # Test callback when cancelled (entered_key is None) with show_search=True
                cb(None)
                await pilot.pause()
                inp = screen.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
                self.assertTrue(inp.has_focus)

                # Test callback when cancelled with show_search=False
                screen.show_search = False
                cb(None)
                await pilot.pause()
                opt_list = screen.query_one(f"#{screen.option_list_id}", OptionList)
                self.assertTrue(opt_list.has_focus)

    async def test_toggle_disabled_action_and_reconciliation(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            providers = {
                "p1": {"name": "Provider One"},
                "p2": {"name": "Provider Two"},
            }
            mock_pm = MagicMock()
            mock_pm.get_active_provider_key.return_value = "p1"

            screen = ProvidersScreen(providers, "p1", {"p1": "k1"}, pm=mock_pm)
            await app.push_screen(screen)
            await pilot.pause()

            opt_list = screen.query_one(MODAL_OPTION_LIST, OptionList)
            opt_list.highlighted = 0

            with patch("widgets.app.role_service.reconcile_active_agent") as mock_reconcile:
                # Toggle p1 to disabled
                screen.action_toggle_disabled()
                self.assertIn("p1", screen.disabled_set)
                mock_pm.set_provider_disabled.assert_called_with("p1", True)
                mock_reconcile.assert_called_once()

                # Toggle p1 back to enabled
                screen.action_toggle_disabled()
                self.assertNotIn("p1", screen.disabled_set)
                mock_pm.set_provider_disabled.assert_called_with("p1", False)

            # Test toggle when highlighted is None
            opt_list.highlighted = None
            screen.action_toggle_disabled()
            self.assertIn("p1", screen.disabled_set)

    async def test_key_handling_bindings(self):
        app = ModalTestApp()
        async with app.run_test() as pilot:
            screen = ProvidersScreen({"p1": {"name": "P1"}}, "p1", {})
            await app.push_screen(screen)
            await pilot.pause()

            toggled = []
            screen.action_toggle_disabled = lambda: toggled.append(True)

            # Tab / Ctrl+T
            tab_ev = events.Key("tab", "tab")
            await screen._on_key(tab_ev)
            self.assertEqual(len(toggled), 1)
            self.assertTrue(tab_ev._stop_propagation)

            # Space is a declared binding now (P2-11), so the hint and /help
            # can advertise it; _on_key no longer handles it directly.
            self.assertIn("space", {binding[0] for binding in ProvidersScreen.BINDINGS})
            space_ev = events.Key("space", " ")
            res = screen._on_key(space_ev)
            if asyncio.iscoroutine(res):
                await res
            self.assertEqual(len(toggled), 1)

            # A real space keystroke still toggles once focus is on the list.
            screen.query_one(MODAL_OPTION_LIST, OptionList).focus()
            await pilot.press("space")
            await pilot.pause()
            self.assertEqual(len(toggled), 2)

    def test_action_cancel(self):
        screen = ProvidersScreen({}, "", {})
        dismissed = []
        screen.dismiss = lambda val: dismissed.append(val)
        screen.action_cancel()
        self.assertEqual(dismissed, [None])

    def test_row_width_fallback(self):
        screen = ProvidersScreen({}, "", {})
        w = screen._row_width()
        self.assertGreater(w, 0)
