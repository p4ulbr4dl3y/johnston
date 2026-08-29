import unittest

from widgets.presentation.screens.resume import ResumeScreen, _order_sessions_hierarchically


class TestResumeScreen(unittest.TestCase):
    def test_order_sessions_hierarchically(self):
        sessions = [
            {"id": "p1", "title": "Parent 1"},
            {"id": "p2", "title": "Parent 2"},
            {"id": "c1", "parent_id": "p1", "title": "Child 1 of P1"},
            {"id": "c2", "parent_id": "p1", "title": "Child 2 of P1"},
        ]
        ordered = _order_sessions_hierarchically(sessions)
        ordered_ids = [s["id"] for s in ordered]
        self.assertEqual(ordered_ids, ["p1", "c1", "c2", "p2"])

    def test_order_sessions_hierarchically_multilevel_nesting(self):
        sessions = [
            {"id": "p1", "title": "Root"},
            {"id": "p2", "title": "Other Root"},
            {"id": "c1", "parent_id": "p1", "title": "Child of P1"},
            {"id": "gc1", "parent_id": "c1", "title": "Grandchild of P1"},
            {"id": "ggc1", "parent_id": "gc1", "title": "Great-Grandchild of P1"},
        ]
        ordered = _order_sessions_hierarchically(sessions)
        ordered_ids = [s["id"] for s in ordered]
        self.assertEqual(ordered_ids, ["p1", "c1", "gc1", "ggc1", "p2"])

    def test_order_sessions_hierarchically_subtree_updated_at(self):
        sessions = [
            {"id": "p_old", "updated_at": 100, "title": "Old parent"},
            {"id": "p_recent", "updated_at": 200, "title": "Recent parent"},
            {"id": "c_active", "parent_id": "p_old", "updated_at": 300, "title": "Active fork"},
        ]
        ordered = _order_sessions_hierarchically(sessions)
        ordered_ids = [s["id"] for s in ordered]
        # p_old is pulled to top because its child c_active has updated_at 300 > 200
        self.assertEqual(ordered_ids, ["p_old", "c_active", "p_recent"])

    def test_order_sessions_hierarchically_cycle_safety(self):
        sessions = [
            {"id": "s1", "parent_id": "s2", "title": "S1"},
            {"id": "s2", "parent_id": "s1", "title": "S2"},
        ]
        ordered = _order_sessions_hierarchically(sessions)
        ordered_ids = set(s["id"] for s in ordered)
        self.assertEqual(len(ordered), 2)
        self.assertEqual(ordered_ids, {"s1", "s2"})

    def test_resume_screen_fork_branch_prefix(self):
        from rich.cells import cell_len
        from rich.text import Text

        sessions = [
            {"id": "p1", "title": "Parent 1", "message_count": 5},
            {"id": "c1", "parent_id": "p1", "title": "Fork of P1", "message_count": 2},
        ]
        screen = ResumeScreen(sessions)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("└─", screen.raw_options[0])
        self.assertIn("└─", screen.raw_options[1])
        self.assertIn("Fork of P1", screen.raw_options[1])

        # Both parent and fork rows must have identical visible cell width for flush-right alignment
        len_p = cell_len(Text.from_markup(screen.raw_options[0]).plain)
        len_c = cell_len(Text.from_markup(screen.raw_options[1]).plain)
        self.assertEqual(len_p, len_c)

    def test_resume_screen_fork_ellipsis_alignment(self):
        from rich.cells import cell_len
        from rich.text import Text

        long_title = "исследуй реализацию skill manager, насколько сделано чисто и модульно в проекте" * 2
        sessions = [
            {"id": "p1", "title": long_title, "message_count": 55},
            {"id": "c1", "parent_id": "p1", "title": long_title, "message_count": 14},
        ]
        screen = ResumeScreen(sessions)
        len_p = cell_len(Text.from_markup(screen.raw_options[0]).plain)
        len_c = cell_len(Text.from_markup(screen.raw_options[1]).plain)
        self.assertEqual(len_p, len_c)
        self.assertIn("55 steps", screen.raw_options[0])
        self.assertIn("14 steps", screen.raw_options[1])

    def test_resume_screen_initial_selected_id(self):
        sessions = [
            {"id": "s1", "title": "Active Session", "message_count": 5},
            {"id": "s2", "title": "Target Session", "message_count": 2},
        ]
        screen = ResumeScreen(sessions, current_session_id="s1", initial_selected_id="s2")
        self.assertEqual(screen.default_value, "s2")
        self.assertEqual(screen.current_session_id, "s1")
        self.assertTrue(screen.raw_options[0].startswith("● "))
        self.assertTrue(screen.raw_options[1].startswith("  "))

    def test_resume_screen_badge_with_relative_time(self):
        import time

        now = time.time()
        sessions = [
            {"id": "s1", "title": "Recent Session", "message_count": 1, "updated_at": now - 120},
            {"id": "s2", "title": "Older Session", "message_count": 4, "created_at": now - 7200},
        ]
        screen = ResumeScreen(sessions)
        self.assertIn("1 step • 2m ago", screen.raw_options[0])
        self.assertIn("4 steps • 2h ago", screen.raw_options[1])


    def test_resume_screen_locked_pushes_conflict_modal(self):
        from unittest.mock import MagicMock

        from textual.widgets import OptionList

        from widgets.presentation.screens.session_conflict import SessionConflictScreen

        sessions = [
            {"id": "s1", "title": "Free Session", "message_count": 2, "is_locked": False},
            {"id": "s2", "title": "Locked Session", "message_count": 5, "is_locked": True},
        ]
        screen = ResumeScreen(sessions)
        screen.dismiss = MagicMock()
        mock_app = MagicMock()

        with unittest.mock.patch.object(ResumeScreen, "app", new=mock_app):
            # Select unlocked session -> dismiss with sid
            ev1 = MagicMock(spec=OptionList.OptionSelected)
            ev1.option_index = 0
            screen.on_option_list_option_selected(ev1)
            screen.dismiss.assert_called_once_with("s1")

            # Select locked session -> pushes SessionConflictScreen
            screen.dismiss.reset_mock()
            ev2 = MagicMock(spec=OptionList.OptionSelected)
            ev2.option_index = 1
            screen.on_option_list_option_selected(ev2)
            mock_app.push_screen.assert_called_once()

            args, kwargs = mock_app.push_screen.call_args
            conflict_screen = args[0]
            cb = kwargs.get("callback")
            self.assertIsInstance(conflict_screen, SessionConflictScreen)
            self.assertEqual(conflict_screen.session_id, "s2")

            # Resolving conflict with "steal" dismisses with steal:s2
            cb("steal")
            screen.dismiss.assert_called_once_with("steal:s2")

    def test_resume_screen_rename_flow(self):
        from unittest.mock import MagicMock

        sessions = [
            {"id": "s1", "title": "Old Title 1", "message_count": 2},
            {"id": "s2", "title": "Old Title 2", "message_count": 5},
        ]
        screen = ResumeScreen(sessions, current_session_id="s1")

        mock_app = MagicMock()
        mock_sess = MagicMock()
        mock_sess.title = "Old Title 1"
        mock_app.sm.get.return_value = mock_sess
        mock_app.current_session_id = "s1"

        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)

        with unittest.mock.patch.object(ResumeScreen, "app", new=mock_app):
            # Trigger rename hotkey
            key_ev = MagicMock(key="ctrl+r")
            screen._on_key(key_ev)
            mock_app.push_screen.assert_called_once()

            # Check pushed screen callback execution
            args, kwargs = mock_app.push_screen.call_args
            rename_screen = args[0]
            cb = kwargs.get("callback")
            self.assertEqual(rename_screen.current_title, "Old Title 1")

            # Execute callback with new title
            cb("New Brand Title")
            self.assertEqual(mock_sess.title, "New Brand Title")
            mock_app.sm.save.assert_called_once_with(mock_sess)
            mock_app.refresh_status_footer.assert_called_once()
            mock_app.notify.assert_called_once_with("Session renamed", severity="information", timeout=1.5)
            self.assertEqual(screen.sessions[0]["title"], "New Brand Title")
            self.assertIn("New Brand Title", screen.raw_options[0])

    def test_resume_screen_delete_flow(self):
        from unittest.mock import MagicMock

        sessions = [
            {"id": "s1", "title": "Active Session", "message_count": 2},
            {"id": "s2", "title": "Deletable Session", "message_count": 5},
            {"id": "s3", "title": "Locked Session", "message_count": 3, "is_locked": True},
        ]
        screen = ResumeScreen(sessions, current_session_id="s1")

        mock_app = MagicMock()
        mock_app.current_session_id = "s1"

        opt_list = MagicMock()
        screen.query_one = MagicMock(return_value=opt_list)

        with unittest.mock.patch.object(ResumeScreen, "app", new=mock_app):
            # 1. Try deleting active session (s1, idx 0) -> blocked with warning
            opt_list.highlighted = 0
            key_ev = MagicMock(key="ctrl+d")
            screen._on_key(key_ev)
            mock_app.notify.assert_called_once_with("Cannot delete active session", severity="warning")
            mock_app.push_screen.assert_not_called()

            # 2. Try deleting locked session (s3, idx 2) -> blocked with warning
            mock_app.notify.reset_mock()
            opt_list.highlighted = 2
            screen._on_key(key_ev)
            mock_app.notify.assert_called_once_with("Cannot delete locked session", severity="warning")
            mock_app.push_screen.assert_not_called()

            # 3. Delete regular session (s2, idx 1) -> opens ConfirmScreen
            mock_app.notify.reset_mock()
            opt_list.highlighted = 1
            screen._on_key(key_ev)
            mock_app.push_screen.assert_called_once()

            args, kwargs = mock_app.push_screen.call_args
            confirm_screen = args[0]
            cb = kwargs.get("callback")
            self.assertIn("Deletable Session", confirm_screen.message)

            # Confirm delete
            cb(True)
            mock_app.sm.delete.assert_called_once_with("s2")
            mock_app.notify.assert_called_once_with("Session deleted", severity="information", timeout=1.5)
            self.assertEqual([s["id"] for s in screen.sessions], ["s1", "s3"])
            self.assertEqual(len(screen.raw_options), 2)




class TestResumeScreenPilot(unittest.IsolatedAsyncioTestCase):
    async def test_resume_screen_locked_flow_pilot(self):
        from textual.app import App

        from widgets.presentation.screens.session_conflict import SessionConflictScreen

        class PilotApp(App):
            def __init__(self, sessions):
                super().__init__()
                self.sessions = sessions
                self.resume_screen = ResumeScreen(sessions)
                self.result = None

            async def on_mount(self):
                def cb(res):
                    self.result = res

                self.push_screen(self.resume_screen, callback=cb)

        sessions = [
            {"id": "s1", "title": "Free Session", "is_locked": False},
            {"id": "s2", "title": "Locked Session", "is_locked": True},
        ]
        app = PilotApp(sessions)
        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(app.screen, app.resume_screen)

            # Move down to session 2 (locked) and press enter
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()

            # Must push SessionConflictScreen modal
            self.assertIsInstance(app.screen, SessionConflictScreen)
            self.assertEqual(app.screen.session_id, "s2")

            # Esc returns to ResumeScreen
            await pilot.press("escape")
            await pilot.pause()
            self.assertEqual(app.screen, app.resume_screen)

            # Enter again -> select readonly -> dismisses full resume flow with readonly:s2
            await pilot.press("enter")
            await pilot.pause()
            self.assertIsInstance(app.screen, SessionConflictScreen)
            await pilot.press("enter")
            await pilot.pause()
            self.assertEqual(app.result, "readonly:s2")

    async def test_resume_screen_rename_pilot(self):
        from unittest.mock import MagicMock

        from textual.app import App

        class PilotApp(App):
            def __init__(self, sessions):
                super().__init__()
                self.sessions = sessions
                self.resume_screen = ResumeScreen(sessions)
                self.sm = MagicMock()
                self.current_session_id = "s1"

            async def on_mount(self):
                self.push_screen(self.resume_screen)

        sessions = [
            {"id": "s1", "title": "Original Title", "message_count": 1},
        ]
        app = PilotApp(sessions)
        mock_sess = MagicMock()
        mock_sess.title = "Original Title"
        app.sm.get.return_value = mock_sess

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(app.screen, app.resume_screen)

            # Press ctrl+r to trigger rename modal
            await pilot.press("ctrl+r")
            await pilot.pause()
            from widgets.presentation.screens.rename_session import RenameSessionScreen

            self.assertIsInstance(app.screen, RenameSessionScreen)

            # Type new title and press enter
            inp = app.screen.query_one("#session-rename-input")
            inp.value = "Updated Renamed Session"
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.screen, app.resume_screen)
            self.assertEqual(app.resume_screen.sessions[0]["title"], "Updated Renamed Session")
            self.assertIn("Updated Renamed Session", app.resume_screen.raw_options[0])
            self.assertEqual(mock_sess.title, "Updated Renamed Session")

    async def test_resume_screen_delete_pilot(self):
        from unittest.mock import MagicMock

        from textual.app import App

        class PilotApp(App):
            def __init__(self, sessions):
                super().__init__()
                self.sessions = sessions
                self.resume_screen = ResumeScreen(sessions, current_session_id="s1")
                self.sm = MagicMock()
                self.current_session_id = "s1"

            async def on_mount(self):
                self.push_screen(self.resume_screen)

        sessions = [
            {"id": "s1", "title": "Active Session", "message_count": 1},
            {"id": "s2", "title": "Old Garbage Session", "message_count": 3},
        ]
        app = PilotApp(sessions)

        async with app.run_test() as pilot:
            await pilot.pause()
            self.assertEqual(app.screen, app.resume_screen)

            # Move to s2 (index 1)
            await pilot.press("down")
            await pilot.press("ctrl+d")
            await pilot.pause()

            from widgets.presentation.screens.confirm import ConfirmScreen

            self.assertIsInstance(app.screen, ConfirmScreen)

            # Press enter on ConfirmScreen to delete
            await pilot.press("enter")
            await pilot.pause()

            self.assertEqual(app.screen, app.resume_screen)
            self.assertEqual(len(app.resume_screen.sessions), 1)
            self.assertEqual(app.resume_screen.sessions[0]["id"], "s1")
            app.sm.delete.assert_called_once_with("s2")




