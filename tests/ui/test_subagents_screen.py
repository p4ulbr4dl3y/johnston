import asyncio
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from textual.app import App

from core.subagent_tracker import SUBAGENTS_DIR, SubagentSessionData, SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen
from widgets.screens.subagents import SubagentsScreen


class DummyHostApp(App[None]):
    """Host app for testing the modal subagents screen with pilot."""

    def __init__(self, screen_to_test):
        super().__init__()
        self.screen_to_test = screen_to_test
        self.dismiss_result = None
        self.current_session_id = None

    def on_mount(self) -> None:
        def callback(res=None):
            self.dismiss_result = res
        self.push_screen(self.screen_to_test, callback=callback)

    def refresh_status_footer(self):
        pass


class _RaisingAttributeApp:
    """App stand-in whose attribute access raises to hit the except branch."""
    def __getattr__(self, name):
        raise RuntimeError("boom")


@contextmanager
def mock_app_context(current_session_id=None):
    """Provide a fake active app to the Textual contextvar.

    Textual's ``Widget.app`` property reads ``textual._context.active_app``,
    so patching that contextvar lets unit tests exercise UI handlers that call
    ``self.app`` without a mounted App.
    """
    mock_app = MagicMock()
    mock_app.current_session_id = current_session_id
    with patch("textual.message_pump.active_app") as ctx:
        ctx.get.return_value = mock_app
        yield mock_app


def make_sess(
    task_id,
    description="desc",
    prompt="prompt",
    subagent_type="general",
    status="running",
    session_id=None,
    async_task=None,
    role=None,
):
    obj = SubagentSessionData(task_id, description, prompt, subagent_type, False, session_id=session_id)
    obj.status = status
    obj.async_task = async_task
    obj.role = role if role is not None else subagent_type
    return obj


class TestSubagentsScreenUnit(unittest.TestCase):
    def setUp(self):
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    def tearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir

    def test_initialization(self):
        screen = SubagentsScreen()
        self.assertEqual(screen.sessions, [])
        self.assertEqual(screen.filtered_sessions, [])
        self.assertEqual(screen.search_query, "")
        self.assertFalse(screen.ALLOW_SELECT)

    def test_bindings(self):
        keys = [b[0] for b in SubagentsScreen.BINDINGS]
        self.assertIn("escape", keys)
        self.assertIn("tab", keys)
        self.assertIn("ctrl+c", keys)
        self.assertIn("ctrl+q", keys)

    def test_action_quit_app(self):
        with mock_app_context() as mock_app:
            screen = SubagentsScreen()
            screen.action_quit_app()
            mock_app.exit.assert_called_once()

    def test_action_cancel(self):
        screen = SubagentsScreen()
        with patch.object(screen, "dismiss") as mock_dismiss:
            screen.action_cancel()
            mock_dismiss.assert_called_once_with(None)

    def test_refresh_list_sort_and_search(self):
        running = make_sess("run-1", "Running task", "first prompt", status="running")
        done = make_sess("done-1", "Done task", "second prompt", status="completed")
        done2 = make_sess("done-2", "", "third", status="completed")

        with mock_app_context(current_session_id="sess-1"):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 0
            screen.query_one = MagicMock(return_value=opt_list)

            with patch.object(screen.st, "get_sessions_for_session", return_value=[done, running, done2]) as mock_get:
                screen.refresh_list()
                mock_get.assert_called_with("sess-1")
                # running sorts first
                self.assertEqual(screen.sessions[0].task_id, "run-1")
                self.assertEqual(screen.filtered_sessions, screen.sessions)
                opt_list.add_option.assert_called()

    def test_refresh_list_no_sessions_this_session_fallback(self):
        with mock_app_context(current_session_id="sess-1"):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 0
            screen.query_one = MagicMock(return_value=opt_list)
            fallback = [make_sess("fb-1", "Fallback")]

            def fake_get(session_id):
                if session_id == "sess-1":
                    return []
                return fallback

            with patch.object(screen.st, "get_sessions_for_session", side_effect=fake_get):
                screen.refresh_list()
                self.assertEqual(screen.sessions, fallback)

    def test_refresh_list_no_sessions_no_current(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 0
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[]):
                screen.refresh_list()
                self.assertEqual(screen.sessions, [])
                self.assertEqual(screen.filtered_sessions, [])
                opt_list.add_option.assert_called_once()

    def test_refresh_list_no_sessions_with_current_no_fallback(self):
        with mock_app_context(current_session_id="sess-1"):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)

            def fake_get(session_id):
                return [] if session_id == "sess-1" else []

            with patch.object(screen.st, "get_sessions_for_session", side_effect=fake_get):
                screen.refresh_list()
                self.assertEqual(screen.sessions, [])
                self.assertEqual(screen.filtered_sessions, [])

    def test_refresh_list_with_search_no_match(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 0
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "zzz-no-match"
            with patch.object(screen.st, "get_sessions_for_session", return_value=[make_sess("t1", "A description")]):
                screen.refresh_list()
                self.assertEqual(screen.filtered_sessions, [])
                self.assertEqual(len(screen.sessions), 1)
                opt_list.add_option.assert_called_once()
                self.assertIn("No matching subagents found.", str(opt_list.add_option.call_args[0][0]))

    def test_refresh_list_search_matches_description(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "DESCRIPTION"
            sess = make_sess("t2", "My Description here", "prompt text", "role-x")
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                self.assertEqual(screen.filtered_sessions, [sess])
                self.assertEqual(opt_list.highlighted, 0)

    def test_refresh_list_search_matches_prompt(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "PROMPT"
            sess = make_sess("t3", "desc", "My Prompt here")
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                self.assertEqual(screen.filtered_sessions, [sess])

    def test_refresh_list_search_matches_task_id(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "MY-TASK"
            sess = make_sess("my-task-id", "desc", "prompt")
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                self.assertEqual(screen.filtered_sessions, [sess])

    def test_refresh_list_search_matches_role(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            screen.search_query = "ROLE"
            sess = make_sess("t4", "desc", "prompt", subagent_type="role")
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                self.assertEqual(screen.filtered_sessions, [sess])

    def test_refresh_list_truncates_long_description(self):
        long_desc = "t" * 100
        sess = make_sess("long-1", description=long_desc)
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                called = str(opt_list.add_option.call_args[0][0])
                # Truncated to 75 chars, not the full 100-char description
                self.assertNotIn(long_desc, called)
                self.assertLess(len(called), 90)

    def test_refresh_list_option_count_sets_highlight(self):
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 2
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[make_sess("a"), make_sess("b")]):
                screen.refresh_list()
                self.assertEqual(opt_list.highlighted, 0)

    def test_refresh_list_status_label_and_option(self):
        sess = make_sess("st-1", "Status task", "prompt", status="completed")
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                called = opt_list.add_option.call_args[0][0]
                self.assertIn("[COMPLETED]", called)

    def test_refresh_list_none_status_unknown(self):
        sess = make_sess("ns-1", "No status task")
        sess.status = None
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 1
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess]):
                screen.refresh_list()
                called = opt_list.add_option.call_args[0][0]
                self.assertIn("[UNKNOWN]", called)

    def test_refresh_list_desc_empty_falls_back_to_prompt_and_task(self):
        sess1 = make_sess("e1", description="no desc", prompt="")
        sess1.prompt = ""
        sess2 = make_sess("e2", description="", prompt="")
        sess2.prompt = ""
        with mock_app_context(current_session_id=None):
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 2
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[sess1, sess2]):
                screen.refresh_list()
                self.assertEqual(len(opt_list.add_option.call_args_list), 2)

    def test_on_input_changed(self):
        screen = SubagentsScreen()
        with patch.object(screen, "refresh_list") as mock_refresh:
            event = MagicMock()
            event.input.id = "modal-search-input"
            event.value = "hello"
            screen.on_input_changed(event)
            self.assertEqual(screen.search_query, "hello")
            mock_refresh.assert_called_once_with()

    def test_on_input_changed_ignores_other_input(self):
        screen = SubagentsScreen()
        with patch.object(screen, "refresh_list") as mock_refresh:
            event = MagicMock()
            event.input.id = "other-input"
            screen.on_input_changed(event)
            mock_refresh.assert_not_called()

    def test_on_option_list_option_selected(self):
        sess = make_sess("t-opt", "Opt desc")
        with mock_app_context() as mock_app:
            screen = SubagentsScreen()
            screen.filtered_sessions = [sess]
            event = MagicMock()
            event.option_index = 0
            screen.on_option_list_option_selected(event)
            self.assertEqual(mock_app.push_screen.call_count, 1)
            pushed = mock_app.push_screen.call_args[0][0]
            self.assertIsInstance(pushed, SubagentViewScreen)
            self.assertEqual(pushed.task_id_or_desc, "t-opt")

    def test_on_option_list_option_selected_out_of_range(self):
        with mock_app_context() as mock_app:
            screen = SubagentsScreen()
            screen.filtered_sessions = [make_sess("only-1")]
            event = MagicMock()
            event.option_index = 5
            screen.on_option_list_option_selected(event)
            mock_app.push_screen.assert_not_called()

    def test_on_input_submitted(self):
        sess = make_sess("t-sub", "Sub desc")
        with mock_app_context() as mock_app:
            screen = SubagentsScreen()
            screen.filtered_sessions = [sess]
            opt_list = MagicMock()
            opt_list.highlighted = 0
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.input.id = "modal-search-input"
            screen.on_input_submitted(event)
            self.assertEqual(mock_app.push_screen.call_count, 1)
            pushed = mock_app.push_screen.call_args[0][0]
            self.assertEqual(pushed.task_id_or_desc, "t-sub")

    def test_on_input_submitted_other_input(self):
        with mock_app_context() as mock_app:
            screen = SubagentsScreen()
            event = MagicMock()
            event.input.id = "other-input"
            screen.on_input_submitted(event)
            mock_app.push_screen.assert_not_called()

    def test_on_input_submitted_highlight_out_of_range(self):
        with mock_app_context() as mock_app:
            screen = SubagentsScreen()
            screen.filtered_sessions = [make_sess("t-x")]
            opt_list = MagicMock()
            opt_list.highlighted = 9
            screen.query_one = MagicMock(return_value=opt_list)
            event = MagicMock()
            event.input.id = "modal-search-input"
            screen.on_input_submitted(event)
            mock_app.push_screen.assert_not_called()

    def test_on_key_down_with_focus_none_highlight(self):
        screen = SubagentsScreen()
        screen.filtered_sessions = [make_sess("k1")]

        search_input = MagicMock()
        search_input.has_focus = True
        opt_list = MagicMock()
        opt_list.highlighted = None

        def fake_query_one(id_name, _type=None):
            if id_name == "#modal-search-input":
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=fake_query_one)
        event = MagicMock(key="down")
        screen._on_key(event)
        self.assertEqual(opt_list.highlighted, 0)
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    def test_on_key_down_existing_highlight(self):
        screen = SubagentsScreen()
        screen.filtered_sessions = [make_sess("k2")]

        search_input = MagicMock()
        search_input.has_focus = True
        opt_list = MagicMock()
        opt_list.highlighted = 1

        def fake_query_one(id_name, _type=None):
            if id_name == "#modal-search-input":
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=fake_query_one)
        event = MagicMock(key="down")
        screen._on_key(event)
        opt_list.action_cursor_down.assert_called_once()
        event.prevent_default.assert_called_once()
        event.stop.assert_called_once()

    def test_on_key_up_existing_highlight(self):
        screen = SubagentsScreen()
        screen.filtered_sessions = [make_sess("k3")]

        search_input = MagicMock()
        search_input.has_focus = True
        opt_list = MagicMock()
        opt_list.highlighted = 2

        def fake_query_one(id_name, _type=None):
            if id_name == "#modal-search-input":
                return search_input
            return opt_list

        screen.query_one = MagicMock(side_effect=fake_query_one)
        event = MagicMock(key="up")
        screen._on_key(event)
        opt_list.action_cursor_up.assert_called_once()
        event.prevent_default.assert_called_once()

    def test_on_key_search_input_not_focused(self):
        screen = SubagentsScreen()
        search_input = MagicMock()
        search_input.has_focus = False
        screen.query_one = MagicMock(return_value=search_input)
        event = MagicMock(key="down")
        screen._on_key(event)
        event.prevent_default.assert_not_called()

    def test_on_key_output_list_full_or_focus_query_error(self):
        screen = SubagentsScreen()
        screen.filtered_sessions = []
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        event = MagicMock(key="down")
        screen._on_key(event)
        event.prevent_default.assert_not_called()

    def test_on_key_ignores_non_nav_keys(self):
        screen = SubagentsScreen()
        event = MagicMock(key="enter")
        screen._on_key(event)
        event.prevent_default.assert_not_called()

    def test_action_kill_subagent_no_sessions(self):
        screen = SubagentsScreen()
        screen.filtered_sessions = []
        with patch.object(screen, "refresh_list") as mock_refresh:
            asyncio.run(screen.action_kill_subagent())
            mock_refresh.assert_not_called()

    def test_action_kill_subagent_running_with_task(self):
        def _run():
            async def scenario():
                sess = make_sess("kill-1", status="running")
                task = asyncio.create_task(asyncio.sleep(10))
                task.cancel()
                sess.async_task = task
                screen = SubagentsScreen()
                screen.filtered_sessions = [sess]
                opt_list = MagicMock()
                opt_list.highlighted = 0
                screen.query_one = MagicMock(return_value=opt_list)
                with patch.object(screen, "refresh_list") as mock_refresh:
                    await screen.action_kill_subagent()
                    self.assertEqual(sess.status, "cancelled")
                    mock_refresh.assert_called_once_with()
            asyncio.run(scenario())

        _run()

    def test_action_kill_subagent_running_done_task(self):
        def _run():
            async def scenario():
                done_task = asyncio.Future()
                done_task.set_result(None)
                sess = make_sess("kill-done", status="running", async_task=done_task)
                screen = SubagentsScreen()
                screen.filtered_sessions = [sess]
                opt_list = MagicMock()
                opt_list.highlighted = 0
                screen.query_one = MagicMock(return_value=opt_list)
                with patch.object(screen, "refresh_list") as mock_refresh:
                    await screen.action_kill_subagent()
                    self.assertEqual(sess.status, "cancelled")
                    mock_refresh.assert_called_once()
            asyncio.run(scenario())

        _run()

    def test_action_kill_subagent_cancel_raises(self):
        class _BoomTask:
            def done(self):
                return False

            def cancel(self):
                raise RuntimeError("boom")

        sess = make_sess("kill-arr", status="running", async_task=_BoomTask())
        screen = SubagentsScreen()
        screen.filtered_sessions = [sess]
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)

        with patch.object(screen, "refresh_list") as mock_refresh:
            asyncio.run(screen.action_kill_subagent())
            self.assertEqual(sess.status, "cancelled")
            mock_refresh.assert_called_once()

    def test_action_kill_subagent_not_running(self):
        sess = make_sess("kill-x", status="completed")
        screen = SubagentsScreen()
        screen.filtered_sessions = [sess]
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)

        with patch.object(screen, "refresh_list") as mock_refresh:
            asyncio.run(screen.action_kill_subagent())
            self.assertEqual(sess.status, "completed")
            mock_refresh.assert_not_called()

    def test_action_kill_subagent_idx_out_of_range(self):
        screen = SubagentsScreen()
        screen.filtered_sessions = [make_sess("k-range")]
        opt_list = MagicMock()
        opt_list.highlighted = 99
        screen.query_one = MagicMock(return_value=opt_list)
        with patch.object(screen, "refresh_list") as mock_refresh:
            asyncio.run(screen.action_kill_subagent())
            mock_refresh.assert_not_called()

    def test_on_mount_focus_success(self):
        screen = SubagentsScreen()
        screen.st._load_all_sessions = MagicMock()
        search_input = MagicMock()
        screen.query_one = MagicMock(return_value=search_input)
        with patch.object(screen, "refresh_list") as mock_refresh:
            screen.on_mount()
            mock_refresh.assert_called_once()
            search_input.focus.assert_called_once()

    def test_on_mount_focus_failure(self):
        screen = SubagentsScreen()
        screen.st._load_all_sessions = MagicMock()
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        with patch.object(screen, "refresh_list") as mock_refresh:
            screen.on_mount()
            mock_refresh.assert_called_once()

    def test_refresh_list_current_session_getattr_exception(self):
        with patch("textual.message_pump.active_app") as ctx:
            ctx.get.side_effect = lambda: _RaisingAttributeApp()
            screen = SubagentsScreen()
            screen.st._load_all_sessions = MagicMock()
            opt_list = MagicMock()
            opt_list.option_count = 0
            screen.query_one = MagicMock(return_value=opt_list)
            with patch.object(screen.st, "get_sessions_for_session", return_value=[]):
                screen.refresh_list()
                self.assertEqual(screen.sessions, [])


class TestSubagentsScreenPilot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()
        self.sess = self.tracker.create_session(
            "pilot-1", "Pilot task description", "Pilot prompt", "general", False
        )
        self.sess.role = "general"

    def tearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir

    async def test_mount_refresh_and_search_in_ui(self):
        screen = SubagentsScreen()
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            from textual.widgets import OptionList

            opt_list = screen.query_one("#subagents-option-list", OptionList)
            self.assertGreaterEqual(opt_list.option_count, 1)

            screen.search_query = "ZZZ-no-match"
            screen.refresh_list()
            self.assertEqual(screen.filtered_sessions, [])

            screen.search_query = ""
            screen.refresh_list()
            self.assertEqual(screen.filtered_sessions, [self.sess])

            await pilot.press("escape")
            await pilot.pause()

    async def test_compose_and_mount_pilot(self):
        screen = SubagentsScreen()
        app = DummyHostApp(screen)
        async with app.run_test() as pilot:
            await pilot.pause(0.2)
            self.assertTrue(screen.query_one("#subagents-title"))
            self.assertTrue(screen.query_one("#modal-search-input"))
            self.assertTrue(screen.query_one("#subagents-option-list"))
            self.assertTrue(screen.query_one("#modal-hint"))
            await pilot.press("escape")
            await pilot.pause()


if __name__ == "__main__":
    unittest.main()
