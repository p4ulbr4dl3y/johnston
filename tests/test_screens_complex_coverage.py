import asyncio
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

from textual.app import App
from textual.events import Click, Key, Resize
from textual.widgets import Input, OptionList, RichLog, Static

from widgets.presentation.screens.diff import (
    DiffFooter,
    DiffHeader,
    DiffScreen,
    format_relative_path,
)
from widgets.presentation.screens.help import (
    COMMANDS_DATA,
    KEYBINDINGS_DATA,
    HelpScreen,
    _build_help_table,
    _format_help_key,
)
from widgets.presentation.screens.permission_confirm import (
    PermissionConfirmScreen,
    RejectReasonInput,
)
from widgets.presentation.screens.tasks import (
    BaseTasksListScreen,
    ShellTasksScreen,
    SubagentsScreen,
    TaskConsoleScreen,
    _filter_and_sort_tasks,
    extract_shell_task_progress,
    format_shell_task_row,
    format_subagent_task_row,
)


class HostModalApp(App[None]):
    def __init__(self, screen_to_mount):
        super().__init__()
        self.scr = screen_to_mount

    def on_mount(self):
        self.push_screen(self.scr)


class TestDiffScreenCoverage(unittest.IsolatedAsyncioTestCase):
    def test_format_relative_path(self):
        self.assertEqual(format_relative_path(""), "")
        self.assertEqual(format_relative_path("short/path.py", max_length=40), "short/path.py")

        # 4+ parts where shortened fits in max_length (len(path) > max_length, but parts[0]/parts[1]/.../parts[-1] <= max_length)
        fit_4 = "src/core/middle_directory_that_is_very_long_indeed/file.py"
        shortened_fit = format_relative_path(fit_4, max_length=30)
        self.assertEqual(shortened_fit, "src/core/.../file.py")

        # 4 parts where shortened does NOT fit in max_length
        long_4_parts = "very_long_dir_1/very_long_dir_2/very_long_dir_3/very_long_dir_4/file.py"
        shortened = format_relative_path(long_4_parts, max_length=25)
        self.assertIn("...", shortened)
        self.assertIn("file.py", shortened)

        long_2_parts = "very_long_directory_name_one/file.py"
        shortened_2 = format_relative_path(long_2_parts, max_length=20)
        self.assertIn("...", shortened_2)

        long_1_part = "very_long_single_file_name_with_no_slash_at_all.py"
        shortened_1 = format_relative_path(long_1_part, max_length=15)
        self.assertTrue(shortened_1.endswith("..."))

    def test_diff_header_variants(self):
        header = DiffHeader("A" * 80, "+10 / -5", from_rewind=False)
        header.render_for_size()
        self.assertIsNotNone(header._render())

        # Test compact width < 52
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=40):
            header.render_header()

        # Test compact width between 52 and 80
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=60):
            header.render_header()

        # Test non-compact width with from_rewind=True
        header_rewind = DiffHeader("Title", "+1 / -1", from_rewind=True)
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=100):
            header_rewind.render_header()

        # Test on_mount
        header.on_mount()

    def test_diff_footer_variants(self):
        footer = DiffFooter()
        footer.on_mount()
        footer.render_for_size()

        # No file selected
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=100):
            footer.render_footer()

        # File selected, non-compact, width >= BREAKPOINT_HINT (80)
        footer.update_info("core/app.py", "+5 / -2")
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=90):
            footer.render_footer()

        # File selected, non-compact, width < BREAKPOINT_HINT (e.g. 70)
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=70):
            footer.render_footer()

        # Compact width < 52, diff view
        footer.set_view_context(is_compact=True, compact_view="diff")
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=45):
            footer.render_footer()

        # Compact width < 52, files view
        footer.set_view_context(is_compact=True, compact_view="files")
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=45):
            footer.render_footer()

        # Compact width >= 52, diff view
        footer.set_view_context(is_compact=True, compact_view="diff")
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=60):
            footer.render_footer()

        # Compact width >= 52, files view
        footer.set_view_context(is_compact=True, compact_view="files")
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=60):
            footer.render_footer()

    def test_diff_screen_format_sidebar_options_truncation(self):
        items = [
            ("short.py", "diff", 1, 1),
            ("very_long_file_name_with_extension.python_module", "diff", 100, 50),
            ("long_file_without_standard_extension", "diff", 0, 0),
            ("a/b/c/long_name_with_short_ext.ts", "diff", 2, 2),
        ]
        screen = DiffScreen(items, title="My Diff")
        self.assertEqual(screen.stats_summary, "4 files, +103 / -53")

        # Format options with small target width to trigger truncation paths
        options = screen._format_sidebar_options(target_width=20)
        self.assertEqual(len(options), 4)
        self.assertIn("…", options[1])
        self.assertIn("…", options[2])
        self.assertIn("…", options[3])

        # Singular file count
        screen_single = DiffScreen([("a.py", "diff", 1, 0)])
        self.assertEqual(screen_single.stats_summary, "1 file, +1 / -0")

    def test_diff_screen_sidebar_row_width(self):
        items = [("a.py", "diff", 1, 1)]
        screen = DiffScreen(items)

        # Compact mode
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=50):
            self.assertEqual(screen._sidebar_row_width(), 48)

        # Non-compact mode with mock sidebar width
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=100):
            mock_sidebar = MagicMock()
            mock_sidebar.size.width = 40
            screen.query_one = MagicMock(return_value=mock_sidebar)
            self.assertEqual(screen._sidebar_row_width(), 39)

            # Query one fails -> fallback to default DIFF_SIDEBAR_ROW_WIDTH
            screen.query_one = MagicMock(side_effect=Exception("not found"))
            self.assertGreater(screen._sidebar_row_width(), 0)

    async def test_diff_screen_pilot_full_flow(self):
        items = [
            ("src/app.py", "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new", 1, 1),
            ("tests/test_foo.py", "--- a/tests/test_foo.py\n+++ b/tests/test_foo.py\n@@ -1 +1 @@\n-1\n+2", 1, 1),
        ]
        screen = DiffScreen(items, title="Full Diff", from_rewind=False)

        async with HostModalApp(screen).run_test(size=(100, 30)) as pilot:
            await pilot.pause()

            # Test search filtering
            search_inp = screen.query_one("#diff-search-input", Input)
            search_inp.value = "foo"
            await pilot.pause()
            self.assertEqual(screen.filtered_indices, [1])

            # Test search with no match
            search_inp.value = "non_existent"
            await pilot.pause()
            self.assertEqual(screen.filtered_indices, [])

            # Reset search
            search_inp.value = ""
            await pilot.pause()
            self.assertEqual(screen.filtered_indices, [0, 1])

            # Test navigation keys (up and down with highlighted reset)
            opt_list = screen.query_one("#diff-file-list", OptionList)
            opt_list.highlighted = None
            await pilot.press("down")
            await pilot.press("up")
            await pilot.press("pagedown")
            await pilot.press("pageup")
            await pilot.press("tab")  # Toggles sidebar hidden
            self.assertFalse(screen.sidebar_visible)

            # Up/Down and Home/End when sidebar is hidden
            await pilot.press("down")
            await pilot.press("up")
            await pilot.press("home")
            await pilot.press("end")
            await pilot.press("tab")  # Toggles sidebar visible
            self.assertTrue(screen.sidebar_visible)

            # Test compact mode input submitted & option selected
            with patch("widgets.presentation.screens.diff.resolve_width", return_value=45):
                screen.on_input_submitted(Input.Submitted(search_inp, "foo"))
                self.assertEqual(screen.compact_view, "diff")

                # Close in compact diff view returns to files view
                screen.action_close()
                self.assertEqual(screen.compact_view, "files")

                # Option selected switches to diff view
                mock_sel = MagicMock(spec=OptionList.OptionSelected, option_index=0)
                screen.on_option_list_option_selected(mock_sel)
                self.assertEqual(screen.compact_view, "diff")

                # Action toggle sidebar in compact mode toggles view
                screen.action_toggle_sidebar()
                self.assertEqual(screen.compact_view, "files")

            # Test resize event
            screen.on_resize(MagicMock())
            await pilot.pause()

            # Test quit app action
            with patch.object(screen.app, "exit") as mock_exit:
                screen.action_quit_app()
                mock_exit.assert_called_once()

            # Test close action
            screen.action_close()
            await pilot.pause()

    async def test_diff_screen_empty_pilot(self):
        screen = DiffScreen([], title="Empty Diff")
        async with HostModalApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            self.assertEqual(screen.stats_summary, "no changes")
            screen.action_close()
            await pilot.pause()

    def test_diff_screen_render_current_diff_error_fallback(self):
        items = [("bad_diff.py", "invalid diff text", 0, 0)]
        screen = DiffScreen(items)
        content_view = MagicMock(spec=Static)
        scroll_box = MagicMock()
        footer = MagicMock(spec=DiffFooter)

        def fake_query(selector, *args, **kwargs):
            if "diff-content-view" in str(selector):
                return content_view
            if "diff-scroll-box" in str(selector):
                return scroll_box
            if "diff-footer" in str(selector):
                return footer
            return MagicMock()

        screen.query_one = MagicMock(side_effect=fake_query)

        with patch("widgets.presentation.screens.diff.format_edit_diff", side_effect=Exception("lexer fail")):
            screen._render_current_diff(0)
            content_view.update.assert_called()

        # Out of range index does nothing
        screen._render_current_diff(999)


class TestPermissionConfirmScreenCoverage(unittest.IsolatedAsyncioTestCase):
    def test_build_diff_text_variants(self):
        # Pre-set diff
        s1 = PermissionConfirmScreen("edit", {"path": "a.py"}, diff="custom_diff")
        self.assertEqual(s1._build_diff_text("a.py"), "custom_diff")

        # Create tool with content
        s2 = PermissionConfirmScreen("create", {"path": "b.py", "content": "line1\nline2"})
        self.assertIn("+line1", s2._build_diff_text("b.py"))

        # Edit tool
        s3 = PermissionConfirmScreen("edit", {"path": "c.py", "old_str": "old", "new_str": "new"})
        self.assertIn("-old", s3._build_diff_text("c.py"))

        # Other tool
        s4 = PermissionConfirmScreen("read", {"path": "d.py"})
        self.assertEqual(s4._build_diff_text("d.py"), "")

    async def test_permission_confirm_all_tool_compose_variants(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"existing content")
            temp_file = f.name

        try:
            tools = [
                ("create", {"path": temp_file, "content": "print('updated')"}),
                ("create", {"path": "new_non_existent.py", "content": "print('new')"}),
                ("edit", {"path": "main.py", "old_str": "a", "new_str": "b"}),
                ("read", {"path": "readme.md"}),
                ("web_fetch", {"url": "https://api.github.com"}),
                ("invoke_subagent", {"role": "Tester", "title": "Run Unit Tests", "prompt": "pytest"}),
                ("invoke_subagent", {"type": "Explorer"}),
                ("manage_shell", {"action": "kill", "task_id": "task-42"}),
                ("manage_shell", {"action": "kill"}),
                ("manage_shell", {"action": "list"}),
                ("manage_shell", {"action": "send_input", "task_id": "task-42", "input": "y\n"}),
                ("manage_shell", {"action": "status", "task_id": "task-42"}),
                ("manage_shell", {"action": "status"}),
                ("manage_subagent", {"action": "kill", "session_id": "sess-99"}),
                ("manage_subagent", {"action": "kill"}),
                ("manage_subagent", {"action": "list"}),
                ("manage_subagent", {"action": "send_message", "session_id": "sess-99", "message": "hello"}),
                ("manage_subagent", {"action": "info", "session_id": "sess-99"}),
                ("manage_subagent", {"action": "info"}),
                ("update_plan", {"explanation": "Add security checks"}),
                ("update_plan", {}),
                ("ask_user", {"questions": [{"question": "Proceed with deployment?"}]}),
                ("ask_user", {"questions": ["Simple question?"]}),
                ("ask_user", {}),
                ("shell", {"command": "git push origin main"}),
                ("custom_api", {"param1": 123, "param2": "value"}),
                ("custom_empty", {}),
            ]

            for t_name, t_args in tools:
                screen = PermissionConfirmScreen(t_name, t_args)
                async with HostModalApp(screen).run_test(size=(85, 24)) as pilot:
                    await pilot.pause()
        finally:
            os.unlink(temp_file)

    async def test_permission_confirm_screen_height_branches(self):
        # Test short terminal height < 18
        screen_short = PermissionConfirmScreen("shell", {"command": "ls -la"})
        async with HostModalApp(screen_short).run_test(size=(80, 15)) as pilot:
            await pilot.pause()
            dialog = screen_short.query_one("#modal-dialog")
            self.assertIsNotNone(dialog)

    async def test_permission_confirm_screen_option_selection_and_highlight(self):
        screen = PermissionConfirmScreen("shell", {"command": "pytest"})
        dismiss_val = None

        def fake_dismiss(res):
            nonlocal dismiss_val
            dismiss_val = res

        screen.dismiss = fake_dismiss

        async with HostModalApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            opt_list = screen.query_one("#permission-options-list", OptionList)

            # Test option selection for each key
            # 0: allow
            mock_sel0 = MagicMock(spec=OptionList.OptionSelected, option_index=0)
            screen.on_option_list_option_selected(mock_sel0)
            self.assertEqual(dismiss_val, "allow")

            # 1: pattern
            mock_sel1 = MagicMock(spec=OptionList.OptionSelected, option_index=1)
            screen.on_option_list_option_selected(mock_sel1)
            self.assertTrue(str(dismiss_val).startswith("pattern:"))

            # 2: always_allow
            mock_sel2 = MagicMock(spec=OptionList.OptionSelected, option_index=2)
            screen.on_option_list_option_selected(mock_sel2)
            self.assertEqual(dismiss_val, "always_allow")

            # 3: deny
            mock_sel3 = MagicMock(spec=OptionList.OptionSelected, option_index=3)
            screen.on_option_list_option_selected(mock_sel3)
            self.assertEqual(dismiss_val, "deny")

            # 4: reject_reason
            mock_sel4 = MagicMock(spec=OptionList.OptionSelected, option_index=4)
            screen.on_option_list_option_selected(mock_sel4)
            inp = screen.query_one("#reject-reason-input", RejectReasonInput)
            self.assertTrue(inp.display)

            # Test reject reason input keys while mounted
            await inp._on_key(Key("up", "up"))
            self.assertFalse(inp.display)

            # Reactivate reject reason input and test down key
            screen.focus_reject_input()
            await inp._on_key(Key("down", "down"))
            self.assertFalse(inp.display)

            # Focus again and test clear selection
            inp._clear_selection()

            # Test actions while input has focus
            screen.focus_reject_input()
            with patch.object(Input, "has_focus", new_callable=PropertyMock, return_value=True):
                screen.action_approve()  # Should submit input value
                self.assertEqual(dismiss_val, "deny")  # Empty value denies

                # Action allow_pattern and action_always_allow while input has focus return early
                screen.action_allow_pattern()
                screen.action_always_allow()

            # Submitting non-empty input
            inp.value = "change tests"
            screen.on_input_submitted(Input.Submitted(inp, "change tests"))
            self.assertEqual(dismiss_val, "deny:change tests")

            # Test focus_options_list and focus_first_option
            screen.focus_options_list()
            self.assertFalse(inp.display)
            screen.focus_first_option()
            self.assertEqual(opt_list.highlighted, 0)

            # Highlighting last option activates reject reason input
            mock_hl_last = MagicMock(spec=OptionList.OptionHighlighted, option_index=len(screen._option_keys) - 1)
            screen.on_option_list_option_highlighted(mock_hl_last)
            self.assertTrue(inp.display)

            # Highlighting earlier option deactivates reject reason input
            mock_hl_0 = MagicMock(spec=OptionList.OptionHighlighted, option_index=0)
            screen.on_option_list_option_highlighted(mock_hl_0)
            self.assertFalse(inp.display)

            # Test action_deny and action_cancel
            screen.action_deny()
            self.assertEqual(dismiss_val, "deny")
            screen.action_cancel()
            self.assertEqual(dismiss_val, "deny")

            # Test scroll page up and page down actions
            screen.action_page_up()
            screen.action_page_down()
            opt_list.action_page_up()
            opt_list.action_page_down()

            # Test reject with reason action
            screen.action_reject_with_reason()
            self.assertTrue(inp.display)

            # allow_pattern without suggested_pattern must NOT escalate
            # to always-allow; the action is a no-op and dismisses nothing.
            dismiss_val = "sentinel"
            screen_no_pat = PermissionConfirmScreen("read", {"path": "a.txt"})
            screen_no_pat.dismiss = fake_dismiss
            screen_no_pat.suggested_pattern = ""
            screen_no_pat.action_allow_pattern()
            self.assertEqual(dismiss_val, "sentinel")

            # Test hint text compact width
            self.assertIn("enter", screen._build_hint_text(width=50))
            self.assertIn("enter: select", screen._build_hint_text(width=80))

            # Test resize
            screen.on_resize(MagicMock())

    def test_permission_confirm_content_width_branches(self):
        # create tool with file existing
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as f:
            f.write(b"existing code\nline2")
            temp_path = f.name
        try:
            screen_create = PermissionConfirmScreen("create", {"path": temp_path, "content": "new code"})
            w1 = screen_create._calculate_content_width()
            self.assertGreaterEqual(w1, 40)
        finally:
            os.unlink(temp_path)

        # manage_shell send_input
        screen_ms = PermissionConfirmScreen("manage_shell", {"action": "send_input", "input": "yes\nall\n"})
        w2 = screen_ms._calculate_content_width()
        self.assertGreaterEqual(w2, 38)

        # manage_subagent send_message
        screen_sub = PermissionConfirmScreen("manage_subagent", {"action": "send_message", "message": "hello\nworld\n"})
        w3 = screen_sub._calculate_content_width()
        self.assertGreaterEqual(w3, 38)

        # invoke_subagent prompt
        screen_sub_prompt = PermissionConfirmScreen("invoke_subagent", {"prompt": "line1\nline2\n"})
        w4 = screen_sub_prompt._calculate_content_width()
        self.assertGreaterEqual(w4, 38)

        # generic args dict
        screen_gen = PermissionConfirmScreen("custom", {"k": "v"})
        w5 = screen_gen._calculate_content_width()
        self.assertGreaterEqual(w5, 38)


class TestHelpScreenCoverage(unittest.IsolatedAsyncioTestCase):
    def test_format_help_key(self):
        self.assertEqual(_format_help_key("Shift+Tab", is_compact=False), "Shift+Tab")
        self.assertEqual(_format_help_key("Shift+Tab", is_compact=True), "S-Tab")
        self.assertEqual(_format_help_key("Ctrl+C / Ctrl+Q", is_compact=True), "C-C/C-Q")
        self.assertEqual(_format_help_key("NonExistentKey", is_compact=True), "NonExistentKey")

    def test_build_help_table(self):
        table_wide = _build_help_table(COMMANDS_DATA, is_compact=False)
        table_compact = _build_help_table(KEYBINDINGS_DATA, is_compact=True)
        self.assertIsNotNone(table_wide)
        self.assertIsNotNone(table_compact)

    async def test_help_screen_pilot_interactions(self):
        screen = HelpScreen()
        async with HostModalApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            # Default is Commands tab (0)
            self.assertEqual(screen.active_tab, 0)

            # Switch to Keybindings via tab key
            await pilot.press("tab")
            self.assertEqual(screen.active_tab, 1)

            # Switch back via left / right / backtab keys
            await pilot.press("left")
            self.assertEqual(screen.active_tab, 0)
            await pilot.press("right")
            self.assertEqual(screen.active_tab, 1)
            await pilot.press("backtab")
            self.assertEqual(screen.active_tab, 0)

            # Test scrolling keys
            await pilot.press("down")
            await pilot.press("up")
            await pilot.press("pagedown")
            await pilot.press("pageup")

            # Test clicking on tabs
            tab_keys = screen.query_one("#help-tab-keybindings", Static)
            tab_cmds = screen.query_one("#help-tab-commands", Static)

            click_keys = Click(tab_keys, x=1, y=1, delta_x=0, delta_y=0, button=1, shift=False, meta=False, ctrl=False)
            screen.on_click(click_keys)
            self.assertEqual(screen.active_tab, 1)

            click_cmds = Click(tab_cmds, x=1, y=1, delta_x=0, delta_y=0, button=1, shift=False, meta=False, ctrl=False)
            screen.on_click(click_cmds)
            self.assertEqual(screen.active_tab, 0)

            # Click on non-tab element does nothing
            screen.on_click(Click(screen, x=0, y=0, delta_x=0, delta_y=0, button=1, shift=False, meta=False, ctrl=False))
            self.assertEqual(screen.active_tab, 0)

            # Test compact width refresh
            with patch("widgets.utils.responsive.resolve_screen_width", return_value=40):
                screen._refresh_view()

            # Test resize event
            screen.on_resize(Resize(screen.size, screen.size))
            await pilot.pause()

            # Test close action
            screen.action_close()
            await pilot.pause()


class TestTasksScreensCoverage(unittest.IsolatedAsyncioTestCase):
    def test_extract_shell_task_progress(self):
        self.assertEqual(extract_shell_task_progress(None), "")

        # Running task with created_at
        task_running = MagicMock()
        task_running.is_running = True
        task_running.created_at = time.time() - 5.0
        res = extract_shell_task_progress(task_running)
        self.assertIn("5", res)

        # Running task without created_at
        task_running_no_time = MagicMock()
        task_running_no_time.is_running = True
        task_running_no_time.created_at = None
        self.assertEqual(extract_shell_task_progress(task_running_no_time), "running...")

        # Terminal state: was_killed
        task_killed = MagicMock()
        task_killed.is_running = False
        task_killed.was_killed = True
        self.assertEqual(extract_shell_task_progress(task_killed), "killed")

        # Terminal state: status timeout
        task_timeout = MagicMock()
        task_timeout.is_running = False
        task_timeout.was_killed = False
        task_timeout.status = "timeout"
        self.assertEqual(extract_shell_task_progress(task_timeout), "timeout")

        # Terminal state: exit_code with duration
        task_exit = MagicMock()
        task_exit.is_running = False
        task_exit.was_killed = False
        task_exit.status = "completed"
        task_exit.created_at = 100.0
        task_exit.completed_at = 105.0
        task_exit.exit_code = 0
        self.assertEqual(extract_shell_task_progress(task_exit), "exit 0 • 5.0s")

        # Terminal state: returncode from process
        task_proc = MagicMock()
        task_proc.is_running = False
        task_proc.was_killed = False
        task_proc.status = ""
        task_proc.exit_code = None
        task_proc.process = MagicMock(returncode=2)
        task_proc.created_at = None
        self.assertEqual(extract_shell_task_progress(task_proc), "exit 2")

        # Terminal state: status error
        task_err = MagicMock()
        task_err.is_running = False
        task_err.was_killed = False
        task_err.exit_code = None
        task_err.process = None
        task_err.status = "error"
        task_err.created_at = None
        self.assertEqual(extract_shell_task_progress(task_err), "exit 1")

        # Terminal state: status finished
        task_fin = MagicMock()
        task_fin.is_running = False
        task_fin.was_killed = False
        task_fin.exit_code = None
        task_fin.process = None
        task_fin.status = "finished"
        task_fin.created_at = None
        self.assertEqual(extract_shell_task_progress(task_fin), "exit 0")

        # Terminal state: other status
        task_other = MagicMock()
        task_other.is_running = False
        task_other.was_killed = False
        task_other.exit_code = None
        task_other.process = None
        task_other.status = "paused"
        task_other.created_at = None
        self.assertEqual(extract_shell_task_progress(task_other), "paused")

    def test_format_shell_task_row(self):
        row_running = format_shell_task_row("uv run pytest", task=None, is_running=True, target_width=40)
        self.assertIn("running...", row_running)
        row_done = format_shell_task_row("git diff", task=None, is_running=False, target_width=40)
        self.assertIn("done", row_done)

    def test_format_subagent_task_row(self):
        session = MagicMock()
        session.agent.role = "researcher"
        session.status = "idle"
        row = format_subagent_task_row("find test cases", session=session, is_running=True, target_width=50)
        self.assertIn("Researcher: find test cases", row)

        # Pre-formatted command role
        row2 = format_subagent_task_row("Researcher: find test cases", session=session, is_running=False, target_width=50)
        self.assertIn("Researcher: find test cases", row2)

    def test_filter_and_sort_tasks(self):
        items = [
            {"id": "t1", "command": "pytest tests/", "is_running": False},
            {"id": "t2", "command": "python server.py", "is_running": True},
            {"id": "t3", "command": "coverage report", "is_running": False},
        ]
        res = _filter_and_sort_tasks(items, "py")
        self.assertEqual(len(res), 2)
        # Running should be first
        self.assertEqual(res[0]["id"], "t2")
        self.assertEqual(res[1]["id"], "t1")

    def test_base_tasks_list_screen_not_implemented_methods(self):
        base = BaseTasksListScreen()
        with self.assertRaises(NotImplementedError):
            base._get_header_md()
        with self.assertRaises(NotImplementedError):
            base._get_filtered_tasks()
        with self.assertRaises(NotImplementedError):
            base._format_task_row({}, 50)
        with self.assertRaises(NotImplementedError):
            base._on_task_selected({})

    async def test_task_console_screen_pilot(self):
        bg_task = MagicMock()
        bg_task.command = "python long_running.py"
        bg_task.is_running = True
        bg_task.output.history = []  # Empty history to cover (Waiting for command output...)
        bg_task.send_input = AsyncMock()
        bg_task.kill = AsyncMock()  # Awaitable kill
        listeners = []
        bg_task.add_listener = lambda cb: listeners.append(cb)
        bg_task.remove_listener = lambda cb: listeners.remove(cb) if cb in listeners else None

        screen = TaskConsoleScreen(bg_task)
        async with HostModalApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            # Test live chunk arrival
            for listener in list(listeners):
                listener("live chunk 1\nlive chunk 2")
            await pilot.pause()

            # Test final EOF chunk (empty string)
            for listener in list(listeners):
                listener("")
            await pilot.pause()

            # Submit stdin input
            stdin_inp = screen.query_one("#shell-stdin-input", Input)
            stdin_inp.value = "my input"
            screen.on_input_submitted(Input.Submitted(stdin_inp, "my input"))
            await pilot.pause()
            bg_task.send_input.assert_called_with("my input")

            # Kill task action
            await screen.action_kill_task()
            bg_task.kill.assert_called_once()

            # Test resize
            screen.on_resize(Resize(screen.size, screen.size))

            # Test back action
            screen.action_back()
            await pilot.pause()

    async def test_task_console_screen_not_running(self):
        bg_task = MagicMock()
        bg_task.command = "echo done"
        bg_task.is_running = False
        bg_task.output.history = []
        screen = TaskConsoleScreen(bg_task)
        async with HostModalApp(screen).run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            log_widget = screen.query_one("#console-log", RichLog)
            self.assertIsNotNone(log_widget)

    async def test_shell_tasks_screen_pilot(self):
        t1 = MagicMock()
        t1.kind = "shell"
        t1.task_id = "t1"
        t1.command = "npm run build"
        t1.is_background = True
        t1.is_running = True
        t1.session_id = "sess_1"
        t1.add_listener = MagicMock()
        t1.remove_listener = MagicMock()
        t1.kill = AsyncMock()

        t2 = MagicMock()
        t2.kind = "shell"
        t2.task_id = "t2"
        t2.command = "pytest"
        t2.is_background = True
        t2.is_running = False
        t2.session_id = "sess_1"
        t2.add_listener = MagicMock()
        t2.remove_listener = MagicMock()

        # Task that is not background
        t_foreground = MagicMock()
        t_foreground.kind = "shell"
        t_foreground.is_background = False

        screen = ShellTasksScreen()

        class MockApp(App[None]):
            def __init__(self):
                super().__init__()
                self.task_manager = [t1, t2, t_foreground]
                self.current_session_id = "sess_1"
                self.scr = screen

            def on_mount(self):
                self.push_screen(self.scr)

        app = MockApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()

            # Check header
            self.assertEqual(screen._get_header_md(), "### **Shell Tasks**")

            # Test filter search
            search_inp = screen.query_one("#modal-search-input", Input)
            search_inp.value = "npm"
            await pilot.pause()
            self.assertEqual(len([t for t in screen.filtered_tasks if t]), 1)

            # Test selection -> opens TaskConsoleScreen
            with patch.object(app, "push_screen") as mock_push:
                screen.on_input_submitted(Input.Submitted(search_inp, "npm"))
                mock_push.assert_called()

            # Test input submitted when highlighted is None
            opt_list = screen._get_option_list()
            opt_list.highlighted = None
            with patch.object(app, "push_screen") as mock_push:
                screen.on_input_submitted(Input.Submitted(search_inp, "npm"))
                mock_push.assert_called()

            # Test option list item selected
            with patch.object(app, "push_screen") as mock_push:
                mock_sel = MagicMock(spec=OptionList.OptionSelected, option_index=1)
                screen.on_option_list_option_selected(mock_sel)
                mock_push.assert_called()

            # Test kill task action on highlighted item
            opt_list.highlighted = 1  # Index of running item
            await screen.action_kill_task()
            t1.kill.assert_called_once()

            # Test kill task when highlighted is a None header item
            opt_list.highlighted = 0
            await screen.action_kill_task()

            # Test hint update in compact mode
            with patch("widgets.utils.responsive.resolve_screen_width", return_value=40):
                screen._update_hint()

            # Test event listener notification
            screen._on_task_event("new text")
            await pilot.pause()

            # Test empty tasks dismissal when search query cleared and no tasks
            app.task_manager = []
            search_inp.value = ""
            screen.update_tasks_list()

            # Test key handlers
            await pilot.press("tab")  # Tab prevented
            await pilot.press("escape")

    async def test_subagents_screen_pilot(self):
        s1 = MagicMock()
        s1.id = "sub_1"
        s1.title = "Explore architecture"
        s1.status = "running"
        s1.agent.role = "explorer"
        s1.async_task = MagicMock(done=lambda: False)
        s1.finish = MagicMock()
        s1.add_listener = MagicMock()
        s1.remove_listener = MagicMock()

        # Role prefix check when title already starts with role
        s2 = MagicMock()
        s2.id = "sub_2"
        s2.title = "Coder: refactor database"
        s2.status = "completed"
        s2.agent.role = "coder"
        s2.async_task = MagicMock(done=lambda: True)
        s2.add_listener = MagicMock()
        s2.remove_listener = MagicMock()

        # Session with async task cancel raising exception
        s3 = MagicMock()
        s3.id = "sub_3"
        s3.title = "Worker task"
        s3.status = "running"
        s3.agent = None
        s3.role = "worker"
        s3.async_task = MagicMock(done=lambda: False, cancel=MagicMock(side_effect=RuntimeError("cancel failed")))
        s3.finish = MagicMock()
        s3.add_listener = MagicMock()
        s3.remove_listener = MagicMock()

        screen = SubagentsScreen()

        class MockApp(App[None]):
            def __init__(self):
                super().__init__()
                self.current_session_id = "main_session"
                self.scr = screen

            def on_mount(self):
                self.push_screen(self.scr)

        app = MockApp()
        mock_store = MagicMock()
        mock_store.children.return_value = [s1, s2, s3]

        with patch("core.infrastructure.storage.session_store.get_session_store", return_value=mock_store), \
             patch("widgets.presentation.tool_display.is_subagent_running", side_effect=lambda s: s.id in ("sub_1", "sub_3")):

            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()

                self.assertEqual(screen._get_header_md(), "### **Subagents**")

                # Test search
                search_inp = screen.query_one("#modal-search-input", Input)
                search_inp.value = "explore"
                await pilot.pause()

                # Test selection opens SubagentViewScreen
                with patch.object(app, "push_screen") as mock_push:
                    screen.on_input_submitted(Input.Submitted(search_inp, "explore"))
                    mock_push.assert_called()

                # Test kill item with cancel exception
                await screen._kill_item({"raw_obj": s3})
                s3.finish.assert_called_with("cancelled", "Terminated from subagents menu")

                # Test session event
                screen._on_session_event()
                await pilot.pause()

                # Close
                screen.action_close()
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()


class TestAdditionalCoverageEdgeCases(unittest.IsolatedAsyncioTestCase):
    def test_diff_footer_breakpoint_hint_boundary(self):
        footer = DiffFooter()
        footer.current_file = "test.py"
        footer.set_view_context(is_compact=False, compact_view="files")
        with patch("widgets.presentation.screens.diff.resolve_width", return_value=75):
            footer.render_footer()

    def test_diff_screen_key_and_quit_exceptions(self):
        screen = DiffScreen([("a.py", "diff", 1, 1)])
        # action_quit_app with app raising exception
        mock_app = MagicMock()
        mock_app.exit.side_effect = RuntimeError("exit failed")
        screen._app = mock_app
        screen.action_quit_app()

        # home and end keys when sidebar inactive
        screen.sidebar_visible = False
        mock_box = MagicMock()
        screen.query_one = MagicMock(return_value=mock_box)
        screen._on_key(MagicMock(key="home"))
        mock_box.scroll_home.assert_called_with(animate=False)
        screen._on_key(MagicMock(key="end"))
        mock_box.scroll_end.assert_called_with(animate=False)

    def test_help_screen_click_and_key_exceptions(self):
        screen = HelpScreen()
        # on_click with event.widget None
        screen.on_click(MagicMock(widget=None))

        # _on_key with query_one exception
        screen.query_one = MagicMock(side_effect=RuntimeError("no scroll box"))
        # Should not raise
        asyncio.run(screen._on_key(MagicMock(key="up")))

    def test_tasks_consume_without_log_widget(self):
        screen = TaskConsoleScreen(MagicMock(command="ls", is_running=False))
        screen.log_widget = None
        self.assertTrue(screen._is_at_bottom())
        screen._consume("text")
        screen._flush_pending()
        screen._apply_dynamic_log_height()

    def test_tasks_listeners_sync_and_unmount_exceptions(self):
        screen = ShellTasksScreen()
        bad_task = MagicMock()
        bad_task.add_listener.side_effect = RuntimeError("failed add")
        bad_task.remove_listener.side_effect = RuntimeError("failed remove")
        screen._observed_tasks.add(bad_task)
        screen._sync_task_listeners([bad_task])
        screen.on_unmount()

        sub_screen = SubagentsScreen()
        bad_sess = MagicMock()
        bad_sess.add_listener.side_effect = RuntimeError("failed add")
        bad_sess.remove_listener.side_effect = RuntimeError("failed remove")
        sub_screen._observed_sessions.add(bad_sess)
        sub_screen._sync_session_listeners([bad_sess])
        sub_screen.on_unmount()
