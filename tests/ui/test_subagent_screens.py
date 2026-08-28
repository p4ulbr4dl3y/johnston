"""Coverage/exception-path tests for widgets/presentation/screens/subagent_screen.py."""

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock

from textual.app import App

from widgets.presentation.screens.subagent_screen import SubagentViewScreen


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
        bm.finalize_stream = AsyncMock()
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
        from core.infrastructure.storage.session_store import SessionStore

        self.store = SessionStore(project_path=self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    def tearDown(self):
        from core.infrastructure.storage.session_store import SessionStore

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


if __name__ == "__main__":
    unittest.main()
