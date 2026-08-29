"""Coverage/exception-path tests for the screen-support mixins.

Covers widgets/mixins/session_persistence.py, widgets/mixins/actions.py and
widgets/mixins/lifecycle.py (the behaviour shared by the app / screen hosts).
"""

import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import _make_agent_mock
from widgets.mixins.actions import ActionsMixin
from widgets.mixins.lifecycle import LifecycleMixin
from widgets.mixins.session_persistence import SessionPersistenceMixin


# --------------------------------------------------------- session_persistence
class _PersistHost:
    """Minimal object backing SessionPersistenceMixin without an App."""

    def __init__(self, session, chat_view=None):
        self.chat_view = chat_view or _fake_chat_view()
        self.sm = MagicMock()
        self.sm.get.return_value = session
        self.sm.set_active_session_id = MagicMock()
        self.agent = _make_agent_mock()
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
    sess.title = ""
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

    async def test_load_session_ui_restores_display_text(self):
        cv = _fake_chat_view()
        msgs = [
            {"type": "user", "text": "full prompt with skill...", "display_text": "/caveman test", "show_in_ui": True},
        ]
        sess = _session(messages=msgs)
        host = _PersistHost(sess, chat_view=cv)
        SessionPersistenceMixin.load_session_ui(host, "s1")
        await host.run_worker_coro
        cv.add_user_message.assert_awaited_once_with("/caveman test", animate=False, attachments_count=0)

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
    def test_background_all_leaves_widget_expanded(self):
        obj = MagicMock()
        obj.task_manager = [
            MagicMock(task_id="tid", is_running=True, is_background=False, kind="shell", move_to_background=MagicMock())
        ]
        widget = MagicMock()
        widget.is_expanded = True
        obj._background_shell_widgets = {"tid": widget}
        obj.notify = MagicMock()
        ActionsMixin.action_background_all(obj)
        widget.toggle_expanded.assert_not_called()

    def _ask_host(self, on_push):
        obj = MagicMock()
        obj.notify = MagicMock()
        obj.push_screen = MagicMock(side_effect=lambda screen, callback=None: on_push(callback))
        return obj

    async def test_ask_user_normal_answer(self):
        obj = self._ask_host(lambda cb: cb("GPT-4"))
        res = await ActionsMixin.ask_user(obj, [{"question": "Q1", "options": ["A", "B"]}])
        self.assertEqual(res, "GPT-4")

    async def test_ask_user_cancelled_answer(self):
        obj = self._ask_host(lambda cb: cb(""))
        res = await ActionsMixin.ask_user(obj, [{"question": "Q1", "options": []}])
        self.assertEqual(res, "cancelled by user")

    async def test_ask_user_minimize(self):
        obj = self._ask_host(lambda cb: cb({"action": "minimize", "answers": {}, "q_idx": 1}))
        task = asyncio.create_task(ActionsMixin.ask_user(obj, [{"question": "Q1", "options": ["A"]}]))
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
        task = asyncio.create_task(ActionsMixin.ask_user(obj, [{"question": "Q1", "options": ["A"]}]))
        await asyncio.sleep(0.05)
        self.assertTrue(callable(obj._pending_ask_user))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------- lifecycle
def _life_host():
    obj = LifecycleMixin.__new__(LifecycleMixin)
    obj.is_app_active = True
    obj.agent = _make_agent_mock()
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
        obj.pm.get_active_provider_key.return_value = ""
        obj.pm.is_provider_connected.return_value = False

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
        obj.pm.get_active_provider_key.return_value = "openai"
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


if __name__ == "__main__":
    unittest.main()
