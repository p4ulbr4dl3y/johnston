"""Coverage-focused tests for widgets/mixins/actions.py.

These tests exercise the uncovered branches of ActionsMixin (pointer handlers,
mode toggling, expand/background actions, provider switching) using a mounted
real JohnstonApp where possible, matching the style in tests/ui/test_app.py.
"""

import unittest
from unittest.mock import MagicMock, patch

from app import JohnstonApp
from widgets.chat_input import ChatInput
from widgets.mixins.actions import ActionsMixin


def _bare_mixin() -> ActionsMixin:
    """Return an ActionsMixin instance with no App backing (for early-return branches)."""
    obj = ActionsMixin.__new__(ActionsMixin)
    return obj


class TestActionsRole(unittest.IsolatedAsyncioTestCase):
    async def test_action_toggle_role_cycles(self):
        app = JohnstonApp()
        app.pm.set_active_provider_key("openai")
        app.agent = app.pm.create_active_agent()
        async with app.run_test():
            self.assertEqual(app.agent.role, "worker")
            app.action_toggle_role()
            self.assertNotEqual(app.agent.role, "worker")

    async def test_action_toggle_role_no_agent(self):
        obj = _bare_mixin()
        # No `agent` attribute -> early return
        obj.action_toggle_role()

    async def test_action_toggle_expand(self):
        app = JohnstonApp()
        async with app.run_test():
            with patch.object(app, "query_one", return_value=MagicMock()) as mock_q:
                app.action_toggle_expand()
                mock_q.assert_called_once()
                mock_q.return_value.toggle_expand.assert_called_once_with("all")

    async def test_action_toggle_expand_exception(self):
        app = JohnstonApp()
        async with app.run_test():
            with patch.object(app, "query_one", side_effect=Exception("boom")):
                app.action_toggle_expand()  # must not raise

    async def test_action_background_all_empty(self):
        app = JohnstonApp()
        async with app.run_test():
            app.notify = MagicMock()
            app.action_background_all()
            app.notify.assert_called_once()
            self.assertIn("No active foreground", app.notify.call_args.args[0])

    async def test_action_background_all_moves_task(self):
        app = JohnstonApp()
        async with app.run_test():
            task = MagicMock()
            task.task_id = "task_bg_1"
            task.session_id = app.current_session_id
            task.is_running = True
            task.is_background = False
            task.kind = "shell"
            task.move_to_background = MagicMock()
            mock_widget = MagicMock()
            mock_widget.toggle_expanded = MagicMock()
            app._background_shell_widgets = {"task_bg_1": mock_widget}
            app.task_manager.register(task)
            app.action_background_all()
            task.move_to_background.assert_called_once()
            # ctrl+b must NOT close an open expansion; live output keeps streaming
            mock_widget.toggle_expanded.assert_not_called()

    async def test_action_background_all_no_move_method(self):
        app = JohnstonApp()
        async with app.run_test():
            task = MagicMock()
            task.session_id = app.current_session_id
            task.is_running = True
            task.is_background = False
            task.kind = "shell"
            del task.move_to_background
            app.task_manager.register(task)
            app.action_background_all()
            self.assertTrue(task.is_background)


class TestActionsPointer(unittest.IsolatedAsyncioTestCase):
    async def test_on_click_focuses_input(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = False
            target.classes = []
            target.id = "other"
            click_evt.widget = target
            app.on_click(click_evt)
            app.screen.clear_selection.assert_called()

    async def test_on_click_selected_text_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="selected")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            click_evt.widget = None
            app.on_click(click_evt)

    async def test_on_click_focusable_target_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = True
            target.classes = []
            target.id = "not-input"
            click_evt.widget = target
            with patch.object(app, "query_one", return_value=MagicMock()) as mock_q:
                app.on_click(click_evt)
                mock_q.return_value.focus.assert_not_called()

    async def test_on_click_button_target_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = True
            target.classes = ["button"]
            target.id = "x"
            click_evt.widget = target
            app.on_click(click_evt)

    async def test_on_click_copy_id_target_returns(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            target = MagicMock()
            target.can_focus = False
            target.classes = []
            target.id = "copy-btn"
            click_evt.widget = target
            app.on_click(click_evt)

    async def test_on_click_chatview_target_clears_selection(self):
        from textual import events

        from widgets.presentation.widgets.chat_container import ChatView

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
            click_evt.widget = ChatView()
            app.on_click(click_evt)
            app.screen.clear_selection.assert_called()

    async def test_on_click_modal_screen_returns(self):
        from textual import events
        from textual.screen import ModalScreen

        obj = MagicMock()
        obj.screen.__class__ = ModalScreen
        click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
        ActionsMixin.on_click(obj, click_evt)
        obj.screen.clear_selection.assert_not_called()

    async def test_on_click_query_exception(self):
        from textual import events

        app = JohnstonApp()
        async with app.run_test():
            app.screen.get_selected_text = MagicMock(return_value="")
            with patch.object(app, "query_one", side_effect=Exception("no chat view")):
                click_evt = events.Click(0, 0, 0, 0, 0, 1, False, False, False)
                click_evt.widget = None
                app.on_click(click_evt)

    def test_on_mouse_down_tracks_position(self):
        app = MagicMock()
        event = MagicMock()
        event.screen_x = 10
        event.screen_y = 20
        ActionsMixin.on_mouse_down(app, event)
        self.assertEqual(app._mouse_down_pos, (10, 20))


class TestActionsMouseUp(unittest.IsolatedAsyncioTestCase):
    async def test_on_mouse_up_no_down_pos(self):

        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            app._mouse_down_pos = None
            event = MagicMock()
            event.screen_x = 5
            event.screen_y = 5
            app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_welcome_clear(self):

        app = JohnstonApp()
        async with app.run_test():
            app.screen.clear_selection = MagicMock()
            app._mouse_down_pos = (0, 0)
            event = MagicMock()
            event.screen_x = 0
            event.screen_y = 0
            with patch.object(app, "query_one", return_value=MagicMock()):
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_query_one_exception(self):
        app = JohnstonApp()
        async with app.run_test():
            app.selection_copy_active = False
            app.screen.get_selected_text = MagicMock(return_value="")
            app.screen.clear_selection = MagicMock()
            app._mouse_down_pos = None
            with patch.object(app, "query_one", side_effect=Exception("boom")):
                event = MagicMock()
                event.screen_x = 5
                event.screen_y = 5
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_drag_copy(self):
        import asyncio

        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="hello world")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_called_once_with("hello world")
            self.assertTrue(app.selection_copy_active)
            deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < deadline:
                if not app.selection_copy_active:
                    break
                await asyncio.sleep(0.1)
            self.assertFalse(app.selection_copy_active)

    async def test_on_mouse_up_chat_input_selection(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            chat_input = MagicMock()
            chat_input.selected_text = "input text selection"

            def mock_query(target, *args, **kwargs):
                if target == "#message-input" or target is ChatInput:
                    return chat_input
                return chat_view

            with patch.object(app, "query_one", side_effect=mock_query):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_called_once_with("input text selection")

    async def test_on_mouse_up_banner_text(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="__ johnston |_|")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_not_called()

    async def test_on_mouse_up_non_drag_clears(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (5, 5)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="accidental block selection")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 5
                event.screen_y = 5
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()
            app.copy_to_clipboard.assert_not_called()

    async def test_on_mouse_up_selected_text_else_clears(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="   ")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_not_called()

    async def test_on_mouse_up_target_is_chatview(self):
        from widgets.presentation.widgets.chat_container import ChatView

        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="selected chat text")
            app.copy_to_clipboard = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = ChatView()
                event.target = None
                app.on_mouse_up(event)
            app.copy_to_clipboard.assert_called_once_with("selected chat text")

    async def test_on_mouse_up_welcome_query_clear(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="")
            chat_view = MagicMock()
            chat_view.query.return_value = [MagicMock()]
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_welcome_widget_parent(self):
        from widgets.presentation.widgets.chat_welcome import WelcomeWidget

        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="")
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = MagicMock()
                event.target = None
                event.widget.parent = WelcomeWidget()
                app.on_mouse_up(event)
            app.screen.clear_selection.assert_called()

    async def test_on_mouse_up_copy_failure(self):
        app = JohnstonApp()
        async with app.run_test():
            app._mouse_down_pos = (0, 0)
            app.screen.clear_selection = MagicMock()
            app.screen.get_selected_text = MagicMock(return_value="hello")
            app.copy_to_clipboard = MagicMock(side_effect=Exception("no clipboard"))
            app.notify = MagicMock()
            chat_view = MagicMock()
            chat_view.query.return_value = []
            with patch.object(app, "query_one", return_value=chat_view):
                event = MagicMock()
                event.screen_x = 10
                event.screen_y = 10
                event.widget = None
                event.target = None
                app.on_mouse_up(event)
            app.notify.assert_called_once()
            self.assertIn("Copy failed", app.notify.call_args.args[0])


class TestActionsConfirmPermission(unittest.IsolatedAsyncioTestCase):
    async def test_confirm_permission_always_allow_sets_overrides(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()

        app = JohnstonApp()
        async with app.run_test():
            def on_push(screen, callback):
                callback("always_allow")

            with (
                patch.object(app, "push_screen", side_effect=on_push),
                patch("core.permission_manager.PermissionManager.get_instance", return_value=pm),
            ):
                result = await app.confirm_permission("shell", {"command": "ls"}, "Destructive", "shell")
            self.assertTrue(result)
            self.assertEqual(pm.session_overrides.get("shell"), "allow")
            self.assertNotIn("shell_guard", pm.session_overrides)
            pm.clear_session_overrides()

    async def test_confirm_permission_denied(self):
        from core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        pm.clear_session_overrides()

        app = JohnstonApp()
        async with app.run_test():
            def on_push(screen, callback):
                callback("deny")

            with patch.object(app, "push_screen", side_effect=on_push):
                result = await app.confirm_permission("read", {"path": "x"}, "Confirm")
            self.assertFalse(result)

    async def test_confirm_permission_allow(self):
        app = JohnstonApp()
        async with app.run_test():
            def on_push(screen, callback):
                callback("allow")

            with patch.object(app, "push_screen", side_effect=on_push):
                result = await app.confirm_permission("read", {"path": "x"}, "Confirm")
            self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
