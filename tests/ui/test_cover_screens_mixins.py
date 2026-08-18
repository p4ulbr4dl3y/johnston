"""Coverage-focused tests for several screens and mixins.

These tests exercise uncovered branches/exception paths in:
  widgets/presentation/screens/ask_user.py
  widgets/presentation/screens/subagent_screen.py
  widgets/presentation/screens/mcp.py
  widgets/presentation/screens/permission_confirm.py
  widgets/mixins/session_persistence.py
  widgets/mixins/actions.py
  widgets/mixins/lifecycle.py

They use the established ``CoverageHostApp + run_test`` pattern for mounted
screens and ``MagicMock`` mocking for pure methods (see tests/ui/test_screens_coverage.py).
"""

import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from textual.app import App

from widgets.mixins.actions import ActionsMixin
from widgets.mixins.lifecycle import LifecycleMixin
from widgets.mixins.session_persistence import SessionPersistenceMixin
from widgets.presentation.screens.mcp import MCPScreen
from widgets.presentation.screens.permission_confirm import PermissionConfirmScreen
from widgets.presentation.screens.subagent_screen import SubagentViewScreen


class _PermHostApp(App[None]):
    """Host app for mounting the permission confirm modal."""

    def __init__(self, screen):
        super().__init__()
        self._scr = screen

    def on_mount(self):
        self.push_screen(self._scr)


class _MCPToggleHost(App[None]):
    """Host app providing refresh_status_footer for _do_toggle tests."""

    def __init__(self):
        super().__init__()
        self.footer_calls = 0

    def on_mount(self):
        pass

    def refresh_status_footer(self):
        self.footer_calls += 1


class _SubHostApp(App[None]):
    """Host app for mounting the subagent view screen."""

    def __init__(self, screen, store=None):
        super().__init__()
        self.screen_to_test = screen
        self.sm = store
        self.current_session_id = "sess-main"

    def on_mount(self):
        self.push_screen(self.screen_to_test)

    def refresh_status_footer(self):
        pass


def _ask_screen(questions=(), q_idx=0, raw_options=None, options=None, answers=None):
    """Build a bare AskUserWizardScreen with minimal, safe state."""
    from widgets.presentation.screens.ask_user import AskUserWizardScreen

    s = AskUserWizardScreen.__new__(AskUserWizardScreen)
    s.questions = list(questions)
    s.q_idx = q_idx
    s.raw_options = raw_options if raw_options is not None else []
    s.options = options if options is not None else []
    s.answers = answers if answers is not None else {}
    s._is_mounted = False
    return s


class TestAskUserExtra(unittest.IsolatedAsyncioTestCase):
    """Additional branches of ask_user.py complementing test_ask_user_screen.py."""

    async def test_force_modal_focus_not_mounted(self):
        screen = _ask_screen(questions=[{"question_text": "Q"}], raw_options=["A"])
        screen._force_modal_focus()  # is_mounted False -> early return

    async def test_force_modal_focus_query_exceptions(self):
        from widgets.presentation.screens.ask_user import WRITE_IN_INPUT

        screen = _ask_screen(questions=[{"question_text": "Q"}])
        screen._is_mounted = True

        def fake_qo(sel, cls):
            if sel == WRITE_IN_INPUT:
                raise Exception("no input")
            raise Exception("no opt")

        screen.query_one = fake_qo
        screen._force_modal_focus()  # raw_options empty -> input branch except
        screen.raw_options = ["A"]
        screen._force_modal_focus()  # raw_options set -> option-list branch except

    async def test_focus_options_and_first(self):
        screen = _ask_screen(raw_options=["A", "B"], options=["A", "B", "Write-in..."])
        screen._is_mounted = True
        opt_list = MagicMock()
        input_field = MagicMock()
        screen.query_one = MagicMock(side_effect=lambda sel, cls: input_field if cls.__name__ == "Input" else opt_list)
        screen.focus_options_list()
        self.assertFalse(input_field.display)
        self.assertEqual(opt_list.highlighted, 1)
        screen.focus_first_option()
        self.assertEqual(opt_list.highlighted, 0)

        # exception paths
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.focus_options_list()
        screen.focus_first_option()

    async def test_focus_helpers_no_raw_options(self):
        screen = _ask_screen(raw_options=[])
        screen.focus_options_list()
        screen.focus_first_option()
        screen.focus_write_in_input = MagicMock()
        screen.on_option_list_option_highlighted(MagicMock())  # not mounted -> return 291

    async def test_update_step_write_in_tag_flows(self):
        screen = _ask_screen(
            [{"question_text": "Q1", "options": ["A", "B"]}],
            raw_options=["A", "B"],
            options=["A", "B", "Write-in..."],
        )
        title = MagicMock()
        opt_list = MagicMock()
        opt_list.highlighted = 0
        input_field = MagicMock()

        def fake_qo(sel, cls):
            if cls.__name__ == "Markdown":
                return title
            if cls.__name__ == "OptionList":
                return opt_list
            return input_field  # Label or Input

        screen.query_one = MagicMock(side_effect=fake_qo)
        # prev answer is a write-in (208-210)
        screen.answers = {0: {"answer": "custom"}}
        screen.update_step()
        # prev answer is a raw option (204-206)
        screen.answers = {0: {"answer": "A"}}
        screen.update_step()
        # target_highlight = last (write-in) option with prev write-in answer (200)
        screen.answers = {0: {"answer": "custom"}}
        screen.update_step(target_highlight=2)
        # target_highlight within raw options (201-202)
        screen.answers = {}
        screen.update_step(target_highlight=1)
        # no prev answer -> first option (211-213)
        screen.answers = {}
        screen.update_step()
        self.assertEqual(opt_list.highlighted, 0)
        self.assertTrue(input_field.display is False)

    async def test_on_option_highlighted_and_selected(self):
        screen = _ask_screen(
            [{"question_text": "Q", "options": ["A", "B"]}],
            raw_options=["A", "B"],
            options=["A", "B", "Write-in..."],
        )
        screen._is_mounted = True
        input_field = MagicMock()
        screen.query_one = MagicMock(side_effect=lambda sel, cls: input_field)
        evt = MagicMock()
        evt.option_index = 0
        screen.on_option_list_option_highlighted(evt)  # normal highlight of first option

        # last option selected -> focus write-in input (311)
        evt.option_index = 2
        screen.on_option_list_option_selected(evt)

        # exception path for highlighted (298-299)
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.on_option_list_option_highlighted(evt)

    async def test_selected_guards(self):
        # guard return: q_idx >= len(questions) (303)
        screen = _ask_screen([{"question_text": "Q"}], q_idx=1, raw_options=["A"], options=["A"])
        screen._is_mounted = True
        screen.query_one = MagicMock()
        screen.on_option_list_option_selected(MagicMock())
        # guard return: no raw_options (303)
        screen = _ask_screen([{"question_text": "Q"}], q_idx=0, raw_options=[], options=[])
        screen._is_mounted = True
        screen.query_one = MagicMock()
        screen.on_option_list_option_selected(MagicMock())

    async def test_selected_mount_time_and_input_submitted_guard(self):
        import time

        screen = _ask_screen([{"question_text": "Q"}], raw_options=["A"], options=["A"])
        screen._is_mounted = True
        screen.query_one = MagicMock(return_value=MagicMock())
        screen._mount_time = time.time()  # too recent -> 307 return
        screen.on_option_list_option_selected(MagicMock())
        screen.on_input_submitted(MagicMock())  # -> 317 return

    async def test_action_toggle_selection_branches(self):
        screen = _ask_screen([{"question_text": "Q", "options": ["A"]}], raw_options=["A"], options=["A"])
        # guard return: q_idx too high (349)
        screen.q_idx = 1
        screen.query_one = MagicMock()
        screen.action_toggle_selection()
        screen.q_idx = 0

        # option list not focused -> return (353)
        opt_list = MagicMock()
        opt_list.has_focus = False
        screen.query_one = MagicMock(return_value=opt_list)
        screen.action_toggle_selection()

        # exception path (363-364)
        screen.query_one = MagicMock(side_effect=Exception("boom"))
        screen.action_toggle_selection()

        # actual toggle with focused option list
        opt_list = MagicMock()
        opt_list.has_focus = True
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        screen.action_toggle_selection()
        self.assertIn(0, screen.answers)

    async def test_action_minimize(self):
        screen = _ask_screen(answers={0: {"answer": "A"}}, q_idx=1)
        result = []
        screen.dismiss = result.append
        screen.action_minimize()
        self.assertEqual(result, [{"action": "minimize", "answers": {0: {"answer": "A"}}, "q_idx": 1}])


# --------------------------------------------------------- session_persistence
class _PersistHost:
    """Minimal object backing SessionPersistenceMixin without an App."""

    def __init__(self, session, chat_view=None):
        self.chat_view = chat_view or _fake_chat_view()
        self.sm = MagicMock()
        self.sm.get.return_value = session
        self.sm.set_active_session_id = MagicMock()
        self.agent = MagicMock()
        self.agent.history = []
        self.current_session_id = "sess"
        self.run_worker_coro = None
        self.notified = None
        self.footer_refreshed = 0

    def query_one(self, cls):
        return self.chat_view

    def run_worker(self, coro):
        self.run_worker_coro = coro
        return coro

    def refresh_status_footer(self):
        self.footer_refreshed += 1

    def notify(self, text, **kwargs):
        self.notified = text


def _fake_chat_view():
    cv = MagicMock()
    cv.loading = False
    cv._is_loading_session = False
    cv.children = []
    cv.call_after_refresh = MagicMock()
    cv.check_welcome = MagicMock()
    cv.scroll_end = None

    def bot():
        b = MagicMock()
        b.set_final_content = AsyncMock()
        b.content = ""
        return b

    cv.add_user_message = AsyncMock()
    cv.add_bot_message = AsyncMock(side_effect=lambda **kw: bot())
    tw = MagicMock()
    tw.finish_thinking = MagicMock()
    cv.add_thinking_widget = AsyncMock(return_value=tw)
    cv.add_tool_call = AsyncMock()
    cv.add_event_divider = AsyncMock()
    return cv


def _session(**overrides):
    sess = MagicMock()
    sess.agent_history = []
    sess.tokens_input = 0
    sess.tokens_output = 0
    sess.total_tokens = 0
    sess.cost_usd = 0.0
    sess.last_context_tokens = 5
    sess.description = ""
    sess.messages = []
    sess.__dict__.update(overrides)
    return sess


class TestSessionPersistence(unittest.IsolatedAsyncioTestCase):
    async def test_load_session_ui_no_session(self):
        host = _PersistHost(None)
        SessionPersistenceMixin.load_session_ui(host, "missing")
        self.assertIsNone(host.run_worker_coro)  # early return

    async def test_load_session_ui_all_message_types(self):
        cv = _fake_chat_view()
        cv.children = [MagicMock() for _ in range(5)]  # % 5 == 0 triggers sleep
        cv.call_after_refresh = MagicMock(side_effect=Exception("boom"))
        msgs = [
            "not-a-dict",
            {"type": "user", "text": "hi", "show_in_ui": False},
            {"type": "user", "text": "hi", "attachments": ["a", "b"]},
            {"type": "user", "text": "u1"},
            {"type": "bot", "text": "   "},
            {"type": "bot", "text": "answer"},
            {"type": "thinking", "duration": 1.0, "text": "t"},
            {"type": "tool", "tool_type": "shell", "target": "ls", "result_text": "ok", "args": {"x": 1}},
            {"type": "event_divider", "text": "compact"},
            {"type": "status_change", "status": "running"},
        ]
        sess = _session(messages=msgs)
        host = _PersistHost(sess, chat_view=cv)
        SessionPersistenceMixin.load_session_ui(host, "s1")
        await host.run_worker_coro
        cv.add_user_message.assert_awaited()
        cv.add_bot_message.assert_awaited()
        cv.add_thinking_widget.assert_awaited()
        cv.add_tool_call.assert_awaited()
        cv.add_event_divider.assert_awaited()
        cv.call_after_refresh.assert_called()  # exception swallowed (98-99)
        self.assertEqual(host.footer_refreshed, 1)

    async def test_load_session_ui_inner_exception(self):
        cv = _fake_chat_view()
        cv.children = [MagicMock() for _ in range(5)]
        cv.add_event_divider = AsyncMock(side_effect=Exception("boom"))
        sess = _session(messages=[{"type": "event_divider", "text": "c"}])
        host = _PersistHost(sess, chat_view=cv)
        SessionPersistenceMixin.load_session_ui(host, "s1")
        await host.run_worker_coro

    async def test_load_session_ui_outer_exception(self):
        class RaisingMsgs(list):
            def __iter__(self):
                raise RuntimeError("iter fail")

        cv = _fake_chat_view()
        cv.children = []
        sess = _session(messages=RaisingMsgs())
        host = _PersistHost(sess, chat_view=cv)
        SessionPersistenceMixin.load_session_ui(host, "s1")
        await host.run_worker_coro
        self.assertIsNotNone(host.notified)

    async def test_load_session_ui_notify_raises(self):
        class RaisingMsgs(list):
            def __iter__(self):
                raise RuntimeError("iter fail")

        cv = _fake_chat_view()
        cv.children = []
        sess = _session(messages=RaisingMsgs())

        def _bad_notify(*args, **kwargs):
            raise Exception("no notify")

        host = _PersistHost(sess, chat_view=cv)
        host.notify = _bad_notify
        SessionPersistenceMixin.load_session_ui(host, "s1")
        await host.run_worker_coro  # notification failure swallowed (89-90)


# ------------------------------------------------------------------ actions
class TestActionsExtra(unittest.IsolatedAsyncioTestCase):
    def test_background_all_toggle_expanded_widget(self):
        class ExpWidget:
            is_expanded = True

            def toggle_expanded(self):
                self.toggled = True

        obj = MagicMock()
        obj.task_manager = [
            MagicMock(task_id="tid", is_running=True, is_background=False, kind="shell", move_to_background=MagicMock())
        ]
        widget = ExpWidget()
        obj._background_shell_widgets = {"tid": widget}
        obj.notify = MagicMock()
        ActionsMixin.action_background_all(obj)
        self.assertTrue(widget.toggled)

    def _ask_host(self, on_push):
        obj = MagicMock()
        obj.notify = MagicMock()
        obj.push_screen = MagicMock(side_effect=lambda screen, callback=None: on_push(callback))
        return obj

    async def test_ask_user_normal_answer(self):
        obj = self._ask_host(lambda cb: cb("GPT-4"))
        res = await ActionsMixin.ask_user(obj, [{"question_text": "Q1", "options": ["A", "B"]}])
        self.assertEqual(res, "GPT-4")

    async def test_ask_user_cancelled_answer(self):
        obj = self._ask_host(lambda cb: cb(""))
        res = await ActionsMixin.ask_user(obj, [{"question_text": "Q1", "options": []}])
        self.assertEqual(res, "cancelled by user")

    async def test_ask_user_minimize(self):
        obj = self._ask_host(lambda cb: cb({"action": "minimize", "answers": {}, "q_idx": 1}))
        task = asyncio.create_task(ActionsMixin.ask_user(obj, [{"question_text": "Q1", "options": ["A"]}]))
        await asyncio.sleep(0.05)
        obj.notify.assert_called_once()
        self.assertTrue(callable(obj._pending_ask_user))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_ask_user_minimize_notify_raises(self):
        obj = MagicMock()
        obj.notify = MagicMock(side_effect=Exception("no notify"))
        obj.push_screen = MagicMock(side_effect=lambda screen, callback=None: callback({"action": "minimize", "answers": {}, "q_idx": 1}))
        task = asyncio.create_task(ActionsMixin.ask_user(obj, [{"question_text": "Q1", "options": ["A"]}]))
        await asyncio.sleep(0.05)
        self.assertTrue(callable(obj._pending_ask_user))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------- lifecycle
def _life_host():
    obj = LifecycleMixin.__new__(LifecycleMixin)
    obj.is_app_active = True
    obj.agent = MagicMock()
    obj.agent.rewind_git_restore_task = MagicMock()
    obj.agent.rewind_git_restore_task.done.return_value = False
    obj.sm = MagicMock()
    obj.task_manager = MagicMock()
    obj.save_current_session = MagicMock()
    obj.query_one = MagicMock()
    obj.refresh_status_footer = MagicMock()
    return obj


class TestLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_check_initial_setup_no_providers(self):
        obj = _life_host()
        obj.pm = MagicMock()
        obj.pm.load_providers.return_value = {}

        class FakeCmd:
            async def execute(self, owner):
                self.owner = owner

        fake = FakeCmd()
        with patch.dict(os.environ, {}):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            with patch("widgets.commands.ProvidersCommand", return_value=fake):
                await obj._check_initial_setup()
        self.assertIs(fake.owner, obj)

    async def test_check_initial_setup_no_model(self):
        obj = _life_host()
        obj.pm = MagicMock()
        obj.pm.load_providers.return_value = {"openai": "key"}
        obj.pm.is_provider_connected.return_value = True
        obj.agent.model = ""

        class FakeCmd:
            async def execute(self, owner):
                self.owner = owner

        fake = FakeCmd()
        with patch.dict(os.environ, {}):
            os.environ.pop("PYTEST_CURRENT_TEST", None)
            with patch("widgets.commands.ModelsCommand", return_value=fake):
                await obj._check_initial_setup()
        self.assertIs(fake.owner, obj)

    async def test_on_unmount_git_cancel(self):
        obj = _life_host()
        obj._kill_all_tasks = AsyncMock()
        with (
            patch("core.application.session.stream.cancel_running_subagents"),
            patch("core.infrastructure.mcp.get_mcp_manager"),
        ):
            obj.on_unmount()
            obj.agent.rewind_git_restore_task.cancel.assert_called_once()
            await asyncio.sleep(0)
        self.assertFalse(obj.is_app_active)

    async def test_on_unmount_loop_exception(self):
        obj = _life_host()
        obj._kill_all_tasks = MagicMock()  # avoid creating an unstaged coroutine
        fake_loop = MagicMock()
        fake_loop.create_task.side_effect = Exception("closed")
        with (
            patch("asyncio.get_running_loop", return_value=fake_loop),
            patch("core.application.session.stream.cancel_running_subagents"),
            patch("core.infrastructure.mcp.get_mcp_manager"),
        ):
            obj.on_unmount()  # must not raise

    async def test_kill_all_tasks_raises(self):
        obj = _life_host()
        obj.task_manager.kill_all = MagicMock(side_effect=Exception("boom"))
        await obj._kill_all_tasks()  # must not raise

    async def test_kill_all_tasks_sync(self):
        coro_called = []
        sync_called = []

        async def coro_kill():
            coro_called.append(1)

        def sync_kill():
            sync_called.append(1)

        def raise_kill():
            raise Exception("x")

        obj = _life_host()
        obj.task_manager = [
            MagicMock(kill=coro_kill),
            MagicMock(kill=sync_kill),
            object(),
            MagicMock(kill=raise_kill),
        ]
        obj._kill_all_tasks_sync()
        await asyncio.sleep(0.01)
        self.assertEqual(len(coro_called), 1)
        self.assertEqual(len(sync_called), 1)


# ------------------------------------------------------------- subagent mixins
def _sub_host():
    obj = SubagentViewScreen.__new__(SubagentViewScreen)
    obj.event_queue = asyncio.Queue()
    obj.thinking_widget = None
    obj.current_tool_widget = None
    obj.bot_msg = None
    obj.queue_task = None
    obj.session = MagicMock()
    cv = MagicMock()
    cv.loading = False
    cv._is_loading_session = False
    cv.children = []
    cv.add_user_message = AsyncMock()
    cv.add_thinking_widget = AsyncMock()
    cv.add_bot_message = AsyncMock()
    cv.add_tool_call = AsyncMock()
    cv.add_event_divider = AsyncMock()
    obj.chat_view = cv
    obj.query_one = MagicMock(return_value=cv)
    return obj


class TestSubagentMixins(unittest.IsolatedAsyncioTestCase):
    async def test_load_history_children_finalize(self):
        obj = _sub_host()
        obj._is_mounted = True
        cv = obj.chat_view
        child = MagicMock()
        cv.children = [child]
        cv.call_after_refresh = MagicMock()
        obj.session.messages = [{"type": "user", "text": "hi"}]
        await obj._load_history_session()
        child.remove.assert_called_once()
        self.assertTrue(obj.queue_task is not None)

    async def test_load_history_refresh_exception(self):
        obj = _sub_host()
        obj._is_mounted = True
        obj.chat_view.children = []
        obj.chat_view.call_after_refresh = MagicMock(side_effect=Exception("boom"))
        obj.session.messages = []
        await obj._load_history_session()  # call_after_refresh exception swallowed (132-133)

    async def test_load_history_not_mounted_returns(self):
        obj = _sub_host()
        obj._is_mounted = False
        obj.session = None
        obj.bot_msg = None
        obj.chat_view.children = []
        await obj._load_history_session()
        self.assertIsNone(obj.queue_task)

    async def test_render_user_hidden_and_attachments(self):
        obj = _sub_host()
        await obj._render_event({"type": "user", "text": "[System Notification] x", "show_in_ui": False}, animate=False)
        obj.chat_view.add_user_message.assert_not_called()
        await obj._render_event({"type": "user", "text": "hello", "attachments": ["a", "b"]}, animate=False)
        call = obj.chat_view.add_user_message.await_args
        self.assertEqual(call.kwargs["attachments_count"], 2)

    async def test_render_tool_result(self):
        obj = _sub_host()
        tw = MagicMock()
        obj.current_tool_widget = tw
        await obj._render_event({"type": "tool", "result_text": "r", "is_error": True, "status": "done", "returncode": 1})
        tw.set_result.assert_called_once_with("r", is_error=True, status="done", returncode=1)

    async def test_render_bot_msg_remove(self):
        obj = _sub_host()
        bm = MagicMock()
        bm.content = "   "
        bm.remove = MagicMock()
        obj.bot_msg = bm
        await obj._render_event({"type": "tool", "tool_type": "shell", "target": "ls", "result_text": "r"})
        bm.remove.assert_called_once()
        self.assertIsNone(obj.bot_msg)

    async def test_render_bot_msg_remove_raises(self):
        obj = _sub_host()
        bm = MagicMock()
        bm.content = "   "
        bm.remove = MagicMock(side_effect=Exception("gone"))
        obj.bot_msg = bm
        await obj._render_event({"type": "tool", "tool_type": "read", "target": "a", "result_text": "r"})
        bm.remove.assert_called_once()

    async def test_render_bot_msg_flush_finalize(self):
        obj = _sub_host()
        bm = MagicMock()
        bm.content = "text"
        bm.flush_pending_stream = MagicMock()
        from unittest.mock import AsyncMock as _AM

        bm.finalize_stream = _AM()
        obj.bot_msg = bm
        await obj._render_event({"type": "tool", "tool_type": "read", "target": "a", "result_text": "r"})
        bm.flush_pending_stream.assert_called_once()
        bm.finalize_stream.assert_awaited_once()

    async def test_render_bot_empty_and_stream(self):
        obj = _sub_host()
        await obj._render_event({"type": "bot", "text": "  "}, animate=False)
        obj.chat_view.add_bot_message.assert_not_called()
        obj.bot_msg = None
        obj.chat_view.add_bot_message = AsyncMock(return_value=MagicMock())
        await obj._render_event({"type": "bot", "text": "chunk"})
        self.assertIsNotNone(obj.bot_msg)

    async def test_render_bot_final(self):
        obj = _sub_host()
        obj.bot_msg = None
        bm = MagicMock()
        bm.set_final_content = AsyncMock()
        obj.chat_view.add_bot_message = AsyncMock(return_value=bm)
        await obj._render_event({"type": "bot", "text": "final", "final": True})
        bm.set_final_content.assert_awaited_once()
        self.assertIsNone(obj.bot_msg)

    async def test_render_bot_reset(self):
        obj = _sub_host()
        bm = MagicMock()
        bm.reset_stream = AsyncMock()
        obj.bot_msg = bm
        await obj._render_event({"type": "bot_reset"})
        bm.reset_stream.assert_awaited_once()
        bm.reset_stream = AsyncMock(side_effect=Exception("reset"))
        obj.bot_msg = bm
        await obj._render_event({"type": "bot_reset"})  # swallowed

    async def test_render_event_divider(self):
        obj = _sub_host()
        await obj._render_event({"type": "event_divider", "text": "sep"})
        obj.chat_view.add_event_divider.assert_awaited_once()

    async def test_process_queue_exception_swallowed(self):
        obj = _sub_host()
        obj.event_queue = asyncio.Queue()
        await obj.event_queue.put("x")
        obj._render_event = AsyncMock(side_effect=Exception("boom"))
        task = asyncio.create_task(obj._process_queue())
        await asyncio.sleep(0.01)
        self.assertTrue(obj.event_queue.empty())
        task.cancel()
        result = await task  # CancelledError caught -> break, returns None
        self.assertIsNone(result)

    async def test_on_unmount_cleanup(self):
        obj = _sub_host()
        fr = MagicMock()
        fr.stop = MagicMock()
        obj._footer_refresh = fr
        hw = MagicMock()
        hw.cancel = MagicMock()
        obj._history_worker = hw
        qt = MagicMock()
        qt.done.return_value = False
        qt.cancel = MagicMock()
        obj.queue_task = qt
        SubagentViewScreen.on_unmount(obj)
        fr.stop.assert_called_once()  # 148
        hw.cancel.assert_called_once()  # 154
        qt.cancel.assert_called_once()  # 159
        obj.session.remove_listener.assert_called_once()  # 161
        self.assertIsNone(obj._footer_refresh)

    async def test_on_unmount_stop_exceptions(self):
        obj = _sub_host()
        fr = MagicMock()
        fr.stop = MagicMock(side_effect=Exception("stop"))
        obj._footer_refresh = fr
        hw = MagicMock()
        hw.cancel = MagicMock(side_effect=Exception("cancel"))
        obj._history_worker = hw
        obj.queue_task = None
        obj.session = None
        SubagentViewScreen.on_unmount(obj)  # 149-150, 155-156 swallowed


class TestSubagentOnMount(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        from core.session_manager import SessionStore

        self.store = SessionStore(project_path=self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    def tearDown(self):
        from core.session_manager import SessionStore

        SessionStore._instance = self._old_instance

    async def test_on_mount_store_fallback(self):
        screen = SubagentViewScreen("nonexistent")
        app = _SubHostApp(screen, store=None)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            await pilot.pause(0.1)

    async def test_on_mount_stops_old_footer(self):
        sess = self.store.create_subagent(
            parent_id="sess-main", subagent_id="task-footer", role="worker", description="d", prompt="p", status="running"
        )
        self.store.save(sess)
        screen = SubagentViewScreen("task-footer")
        old = MagicMock()
        old.stop = MagicMock()
        screen._footer_refresh = old
        app = _SubHostApp(screen, store=self.store)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            await pilot.pause(0.1)
        old.stop.assert_called_once()

    async def test_on_mount_footer_stop_raises(self):
        sess = self.store.create_subagent(
            parent_id="sess-main", subagent_id="task-footer2", role="worker", description="d2", prompt="p", status="running"
        )
        self.store.save(sess)
        screen = SubagentViewScreen("task-footer2")
        old = MagicMock()
        old.stop = MagicMock(side_effect=Exception("stop"))
        screen._footer_refresh = old
        app = _SubHostApp(screen, store=self.store)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            await pilot.pause(0.1)
        old.stop.assert_called_once()


# ---------------------------------------------------------------------- mcp
class TestMCPScreenExtra(unittest.IsolatedAsyncioTestCase):
    def test_init_load_servers_exception(self):
        mgr = MagicMock()
        mgr.load_servers.side_effect = Exception("boom")
        with patch("widgets.presentation.screens.mcp.get_mcp_manager", return_value=mgr):
            screen = MCPScreen()
        self.assertEqual(screen.servers, [])

    def test_on_unmount_cancels(self):
        screen = MCPScreen.__new__(MCPScreen)
        wtask = MagicMock()
        wtask.done.return_value = False
        screen._warmup_task = wtask
        t = MagicMock()
        screen._toggle_tasks = {t}
        screen.on_unmount()
        wtask.cancel.assert_called_once()
        t.cancel.assert_called_once()

    async def test_warmup_tools_waits_refresh_task(self):
        mgr = MagicMock()
        mgr.ensure_tools_ready_async = AsyncMock()
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        mgr._tools_refresh_task = fut
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        task = asyncio.create_task(screen._warmup_tools())
        await asyncio.sleep(0.01)
        self.assertFalse(task.done())
        fut.set_result(None)
        await task
        screen.refresh_list.assert_called()

    async def test_load_servers_bg_sync_no_loop(self):
        mgr = MagicMock()
        mgr.load_servers.side_effect = Exception("boom")
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen.servers = ["cached"]
        with patch("asyncio.get_running_loop", side_effect=RuntimeError("no loop")):
            screen._load_servers_bg(refresh=True)
        self.assertEqual(screen.servers, ["cached"])

    async def test_load_servers_bg_call_soon_threadsafe_raises(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = [{"name": "a", "command": "x"}]
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen.servers = []
        screen._is_mounted = True
        loop = asyncio.get_running_loop()
        with patch.object(loop, "call_soon_threadsafe", side_effect=RuntimeError("closed")):
            screen._load_servers_bg(refresh=True)
            await asyncio.sleep(0.1)
        self.assertEqual(screen.servers, [{"name": "a", "command": "x"}])

    async def test_render_status_exception(self):
        screen = MCPScreen.__new__(MCPScreen)
        mgr = MagicMock()
        mgr.get_server_status.side_effect = Exception("boom")
        screen.mm = mgr
        screen.servers = [{"name": "a", "command": "x", "scope": "global", "disabled": False}]
        screen.search_query = ""
        opt_list = MagicMock()
        opt_list.highlighted = None
        screen.query_one = MagicMock(return_value=opt_list)
        screen._render_from_cache()
        self.assertTrue(screen.filtered_servers)

    async def test_add_server_row_status_exception(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = MagicMock()
        screen.mm.get_server_status.side_effect = Exception("boom")
        opt_list = MagicMock()
        screen._add_server_row(opt_list, {"name": "s", "command": "c", "disabled": False}, {})

    async def test_add_server_row_plain_error(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = MagicMock()
        screen.mm.get_server_status.return_value = {"error": "boom boom"}
        opt_list = MagicMock()
        screen._add_server_row(opt_list, {"name": "s", "command": "c", "disabled": False}, {})

    async def test_do_toggle_enabled_warmup_callback(self):
        mgr = MagicMock()
        mgr.toggle_server = lambda name: True
        mgr.ensure_tools_ready_async = AsyncMock()
        fut = asyncio.Future()
        mgr._tools_refresh_task = fut
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen._pending_toggles = set()
        screen._toggle_tasks = set()
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        host = _MCPToggleHost()
        async with host.run_test():
            await screen._do_toggle("s")
            fut.set_result(None)
            await asyncio.sleep(0.01)
        self.assertGreater(host.footer_calls, 0)

    async def test_do_toggle_failure_notify(self):
        mgr = MagicMock()
        mgr.toggle_server = MagicMock(side_effect=Exception("bad"))
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen._pending_toggles = set()
        screen._toggle_tasks = set()
        screen.notify = MagicMock()
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        host = _MCPToggleHost()
        async with host.run_test():
            await screen._do_toggle("s")
        screen.notify.assert_called_once()

    async def test_do_toggle_cancelled_reraises(self):
        mgr = MagicMock()
        screen = MCPScreen.__new__(MCPScreen)
        screen.mm = mgr
        screen._pending_toggles = set()
        screen._toggle_tasks = set()
        screen.notify = MagicMock()
        screen.refresh_list = MagicMock()
        screen._is_mounted = True
        host = _MCPToggleHost()
        async with host.run_test():
            with patch("widgets.presentation.screens.mcp.asyncio.to_thread", side_effect=asyncio.CancelledError()):
                with self.assertRaises(asyncio.CancelledError):
                    await screen._do_toggle("s")
        self.assertNotIn("s", screen._pending_toggles)

    async def test_on_input_submitted_target_none(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.filtered_servers = [None]
        opt_list = MagicMock()
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)
        event = MagicMock()
        event.input.id = "modal-search-input"
        screen.on_input_submitted(event)  # header row -> return

    async def test_on_option_selected_target_none(self):
        screen = MCPScreen.__new__(MCPScreen)
        screen.filtered_servers = [None]
        event = MagicMock()
        event.option_index = 0
        screen.on_option_list_option_selected(event)  # header row -> return


# -------------------------------------------------------- permission_confirm
class TestPermissionConfirmExtra(unittest.IsolatedAsyncioTestCase):
    def test_build_diff_text_unknown_tool(self):
        screen = PermissionConfirmScreen("read", {"path": "x"})
        self.assertEqual(screen._build_diff_text("x"), "")

    async def test_compose_manage_subagent(self):
        cases = [
            {"action": "kill", "session_id": "s1"},
            {"action": "kill"},
            {"action": "list"},
            {"action": "send_message", "session_id": "s1"},
            {"action": "send_message"},
            {"action": "manage", "session_id": "s1"},
        ]
        for args in cases:
            screen = PermissionConfirmScreen("manage_subagent", args)
            async with _PermHostApp(screen).run_test() as pilot:
                await pilot.pause()

    async def test_compose_update_plan(self):
        screen = PermissionConfirmScreen("update_plan", {})
        async with _PermHostApp(screen).run_test() as pilot:
            await pilot.pause()

    async def test_compose_ask_user(self):
        cases = [
            {"questions": [{"q": "1"}, {"q": "2"}]},
            {"questions": [{"q": "1"}]},
            {"questions": []},
        ]
        for args in cases:
            screen = PermissionConfirmScreen("ask_user", args)
            async with _PermHostApp(screen).run_test() as pilot:
                await pilot.pause()


if __name__ == "__main__":
    unittest.main()
