import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.widgets import OptionList

from widgets.presentation.commands import DiffCommand
from widgets.presentation.screens.diff import DiffFooter, DiffHeader, DiffScreen, disambiguate_file_paths


class TestDisambiguateFilePaths(unittest.TestCase):
    def test_empty_and_single(self):
        self.assertEqual(disambiguate_file_paths([]), [])
        self.assertEqual(disambiguate_file_paths(["app.py"]), ["app.py"])

    def test_unique_basenames(self):
        paths = ["core/app.py", "widgets/view.py", "tools/run.py"]
        self.assertEqual(disambiguate_file_paths(paths), ["app.py", "view.py", "run.py"])

    def test_duplicate_basenames_disambiguated(self):
        paths = [
            "core/application/actions.py",
            "widgets/mixins/actions.py",
            "core/prompt_builder.py",
        ]
        self.assertEqual(
            disambiguate_file_paths(paths),
            ["application/actions.py", "mixins/actions.py", "prompt_builder.py"],
        )

    def test_nested_duplicate_basenames(self):
        paths = [
            "a/sub/util.py",
            "b/sub/util.py",
        ]
        self.assertEqual(
            disambiguate_file_paths(paths),
            ["a/sub/util.py", "b/sub/util.py"],
        )


class TestDiffScreen(unittest.TestCase):
    def test_diff_screen_empty(self):
        screen = DiffScreen([])
        self.assertEqual(screen.stats_summary, "no changes")
        self.assertEqual(len(screen.diff_items), 0)

    def test_diff_screen_with_items(self):
        items = [
            ("file1.py", "--- a/file1.py\n+++ b/file1.py\n@@ -1 +1 @@\n-old\n+new", 1, 1),
            ("file2.py", "--- a/file2.py\n+++ b/file2.py\n@@ -1 +1,2 @@\n-a\n+b\n+c", 2, 1),
        ]
        screen = DiffScreen(items, title="Test Diff")
        self.assertEqual(screen.stats_summary, "2 files, +3 / -2")
        self.assertEqual(len(screen.diff_items), 2)

    def test_diff_header_and_footer(self):
        header_close = DiffHeader("Title", "2 files, +1/-1", from_rewind=False)
        header_close.render_header()

        header_back = DiffHeader("Title", "2 files, +1/-1", from_rewind=True)
        header_back.render_header()

        footer = DiffFooter()
        footer.update_info("test.py", "+1 / -1")
        self.assertEqual(footer.current_file, "test.py")

    def test_diff_screen_navigation_actions(self):
        items = [
            ("file1.py", "diff1", 1, 0),
            ("file2.py", "diff2", 0, 1),
        ]
        screen = DiffScreen(items)

        # Render diff item 0
        screen._render_current_diff(0)
        self.assertEqual(screen.selected_index, 0)

        # Highlight event
        mock_hl = MagicMock(spec=OptionList.OptionHighlighted)
        mock_hl.option_index = 1
        screen.on_option_list_option_highlighted(mock_hl)
        self.assertEqual(screen.selected_index, 1)

        # Option selected event
        mock_sel = MagicMock(spec=OptionList.OptionSelected)
        mock_sel.option_index = 0
        screen.on_option_list_option_selected(mock_sel)
        self.assertEqual(screen.selected_index, 0)

        # Close
        screen.dismiss = MagicMock()
        screen.action_close()
        screen.dismiss.assert_called_once_with(None)

    def test_diff_screen_search_filtering(self):
        from textual.widgets import Input

        items = [
            ("src/core/app.py", "diff1", 1, 0),
            ("src/widgets/chat.py", "diff2", 0, 1),
            ("tests/test_app.py", "diff3", 2, 2),
        ]
        screen = DiffScreen(items)
        mock_input = MagicMock(spec=Input)
        mock_input.id = "diff-search-input"

        # Mock query_one
        opt_list = MagicMock()
        content_view = MagicMock()
        footer = MagicMock()

        def fake_qo(selector, *args, **kwargs):
            if "diff-file-list" in str(selector):
                return opt_list
            if "diff-content-view" in str(selector):
                return content_view
            if "diff-footer" in str(selector):
                return footer
            if "diff-search-input" in str(selector):
                return mock_input
            return MagicMock()

        screen.query_one = MagicMock(side_effect=fake_qo)

        # Filter by "chat"
        mock_event = MagicMock(spec=Input.Changed)
        mock_event.input = mock_input
        mock_event.value = "chat"
        screen.on_input_changed(mock_event)
        self.assertEqual(screen.filtered_indices, [1])

        # Filter with no match
        mock_event.value = "nonexistent"
        screen.on_input_changed(mock_event)
        self.assertEqual(screen.filtered_indices, [])

        # Clear filter
        mock_event.value = ""
        screen.on_input_changed(mock_event)
        self.assertEqual(screen.filtered_indices, [0, 1, 2])

    def test_diff_screen_toggle_sidebar_wide(self):
        items = [("file1.py", "diff1", 1, 0)]
        screen = DiffScreen(items)
        screen._update_layout = MagicMock()

        with patch("widgets.presentation.screens.diff.resolve_width", return_value=100):
            screen.action_toggle_sidebar()
            self.assertFalse(screen.sidebar_visible)
            screen.action_toggle_sidebar()
            self.assertTrue(screen.sidebar_visible)

    def test_diff_screen_compact_mode_navigation(self):
        items = [("file1.py", "diff1", 1, 0)]
        screen = DiffScreen(items)
        screen.dismiss = MagicMock()
        screen.query_one = MagicMock()

        with patch("widgets.presentation.screens.diff.resolve_width", return_value=50):
            # In compact mode, default is files view
            self.assertEqual(screen.compact_view, "files")

            # Selecting an option switches to diff view
            mock_sel = MagicMock(spec=OptionList.OptionSelected)
            mock_sel.option_index = 0
            screen.on_option_list_option_selected(mock_sel)
            self.assertEqual(screen.compact_view, "diff")

            # Pressing close in diff view switches back to files view
            screen.action_close()
            self.assertEqual(screen.compact_view, "files")
            screen.dismiss.assert_not_called()

            # Pressing close in files view dismisses the screen
            screen.action_close()
            screen.dismiss.assert_called_once_with(None)

    def test_diff_screen_input_submitted_in_compact_mode(self):
        from textual.widgets import Input

        items = [("file1.py", "diff1", 1, 0)]
        screen = DiffScreen(items)
        screen._update_layout = MagicMock()

        with patch("widgets.presentation.screens.diff.resolve_width", return_value=50):
            mock_event = MagicMock(spec=Input.Submitted)
            screen.on_input_submitted(mock_event)
            self.assertEqual(screen.compact_view, "diff")

    def test_sidebar_row_width_compact_stays_full_width(self):
        items = [("test_modal_badge_adaptivity.py", "diff1", 1, 0)]
        screen = DiffScreen(items)

        with patch("widgets.presentation.screens.diff.resolve_width", return_value=60):
            # Row width must use screen width (60 - 2 = 58), not fallback 31
            self.assertEqual(screen._sidebar_row_width(), 58)
            options = screen._format_sidebar_options(screen._sidebar_row_width())
            # Filename fits completely in 58 columns without truncation (was truncated at 31)
            self.assertIn("test_modal_badge_adaptivity.py", options[0])

    def test_keyboard_navigation_after_tab(self):
        items = [("file1.py", "diff1", 1, 0), ("file2.py", "diff2", 2, 0)]
        screen = DiffScreen(items)
        screen._update_layout = MagicMock()

        opt_list = MagicMock()
        opt_list.highlighted = 0
        scroll_box = MagicMock()
        search_input = MagicMock()

        def fake_qo(selector, *args, **kwargs):
            if "diff-file-list" in str(selector):
                return opt_list
            if "diff-scroll-box" in str(selector):
                return scroll_box
            if "diff-search-input" in str(selector):
                return search_input
            return MagicMock()

        screen.query_one = MagicMock(side_effect=fake_qo)
        screen.focus = MagicMock()

        # Tab: sidebar hides, focus shifts to screen
        tab_event = MagicMock(key="tab")
        screen._on_key(tab_event)
        self.assertFalse(screen.sidebar_visible)
        tab_event.prevent_default.assert_called()

        # Up/Down with hidden sidebar: scrolls diff scroll_box
        down_event = MagicMock(key="down")
        screen._on_key(down_event)
        scroll_box.scroll_down.assert_called_with(animate=False)

        up_event = MagicMock(key="up")
        screen._on_key(up_event)
        scroll_box.scroll_up.assert_called_with(animate=False)

        # PgUp / PgDn with hidden sidebar: page scrolls scroll_box
        pgdn_event = MagicMock(key="pagedown")
        screen._on_key(pgdn_event)
        scroll_box.scroll_page_down.assert_called_with(animate=False)

        pgup_event = MagicMock(key="pageup")
        screen._on_key(pgup_event)
        scroll_box.scroll_page_up.assert_called_with(animate=False)

        # Tab again: sidebar restores, focus to search_input
        screen._on_key(tab_event)
        self.assertTrue(screen.sidebar_visible)
        search_input.focus.assert_called()

        # Up/Down with visible sidebar: moves option list
        down_event = MagicMock(key="down")
        screen._on_key(down_event)
        opt_list.action_cursor_down.assert_called()

    def test_toggle_diff_mode_and_hunk_navigation(self):
        items = [
            (
                "file1.py",
                "--- a/file1.py\n+++ b/file1.py\n@@ -1,2 +1,2 @@\n-a\n+b\n@@ -10,2 +10,2 @@\n-c\n+d\n",
                2,
                2,
            )
        ]
        screen = DiffScreen(items)
        scroll_box = MagicMock()
        scroll_box.scroll_offset = MagicMock(y=0)
        footer = MagicMock()
        content_view = MagicMock()

        def fake_qo(selector, *args, **kwargs):
            if "diff-scroll-box" in str(selector):
                return scroll_box
            if "diff-footer" in str(selector):
                return footer
            if "diff-content-view" in str(selector):
                return content_view
            return MagicMock()

        screen.query_one = MagicMock(side_effect=fake_qo)
        screen._render_current_diff(0)

        # Toggle mode
        self.assertEqual(screen.diff_mode, "unified")
        screen.action_toggle_diff_mode()
        self.assertEqual(screen.diff_mode, "split")
        screen.action_toggle_diff_mode()
        self.assertEqual(screen.diff_mode, "unified")

        # Next hunk
        screen.action_next_hunk()
        scroll_box.scroll_to.assert_called()

        # Prev hunk
        scroll_box.scroll_offset.y = 10
        screen.action_prev_hunk()
        scroll_box.scroll_to.assert_called()

    def test_vim_key_navigation_when_sidebar_hidden(self):
        items = [("file1.py", "diff", 1, 0)]
        screen = DiffScreen(items)
        screen.sidebar_visible = False
        scroll_box = MagicMock()
        screen.query_one = MagicMock(return_value=scroll_box)

        # j / k
        j_event = MagicMock(key="j")
        screen._on_key(j_event)
        scroll_box.scroll_down.assert_called_with(animate=False)

        k_event = MagicMock(key="k")
        screen._on_key(k_event)
        scroll_box.scroll_up.assert_called_with(animate=False)

        # g / G
        g_event = MagicMock(key="g")
        screen._on_key(g_event)
        scroll_box.scroll_home.assert_called_with(animate=False)

        cap_g_event = MagicMock(key="G")
        screen._on_key(cap_g_event)
        scroll_box.scroll_end.assert_called_with(animate=False)






class TestDiffCommand(unittest.IsolatedAsyncioTestCase):
    async def test_diff_command_no_session(self):
        app = MagicMock()
        app.current_session_id = None
        cmd = DiffCommand()
        await cmd.execute(app)
        app.notify.assert_called_once_with("No active session found", severity="warning")

    async def test_diff_command_no_changes(self):
        app = MagicMock()
        app.current_session_id = "test-session"
        app.sm = MagicMock()
        app.sm.project_path = "/path"
        app.sm.get.return_value = None
        cmd = DiffCommand()

        with patch("core.application.session.actions.get_session_diff", new_callable=AsyncMock) as mock_get_diff:
            mock_get_diff.return_value = []
            await cmd.execute(app)
            app.notify.assert_called_once_with("No workspace changes found for session files", severity="information")

    async def test_diff_command_with_changes(self):
        app = MagicMock()
        app.current_session_id = "test-session"
        app.sm = MagicMock()
        app.sm.project_path = "/path"
        cmd = DiffCommand()

        with patch("core.application.session.actions.get_session_diff", new_callable=AsyncMock) as mock_get_diff:
            mock_get_diff.return_value = [("file.py", "diff content", 1, 0)]
            await cmd.execute(app)
            app.push_screen.assert_called_once()
