import unittest

import pytest

from widgets.app.app import JohnstonApp
from widgets.presentation.widgets.chat_notch import ChatNotch, ChatNotchContainer


class TestChatNotch(unittest.TestCase):
    def test_init_and_toggle(self):
        notch = ChatNotch()
        self.assertFalse(notch.is_expanded)
        notch.toggle_expanded()
        self.assertTrue(notch.is_expanded)
        notch.on_click()
        self.assertFalse(notch.is_expanded)

    def test_render_collapsed_and_expanded_default(self):
        notch = ChatNotch()
        col = notch._render_collapsed()
        self.assertIsNotNone(col)
        self.assertIn("5/12", col.plain)
        exp = notch._render_expanded()
        self.assertIsNotNone(exp)
        self.assertIn("Plan (5/12)", exp.plain)
        self.assertIn("Implement docx/xlsx/pptx/epub safe parser", exp.plain)

    def test_empty_plan_items(self):
        notch = ChatNotch()
        notch.plan_items = []
        notch.plan_explanation = ""
        col = notch._render_collapsed()
        self.assertIn("No active plan", col.plain)
        exp = notch._render_expanded()
        self.assertIn("No tasks in plan", exp.plain)

    def test_single_item_plan(self):
        notch = ChatNotch()
        notch.plan_items = [{"step": "Single item", "status": "in_progress"}]
        col = notch._render_collapsed()
        self.assertIn("0/1 Single item", col.plain)
        exp = notch._render_expanded()
        self.assertIn("[▶] Single item", exp.plain)

    def test_rich_markup_escaping(self):
        notch = ChatNotch()
        notch.plan_explanation = "Using regex [\\[0-9]+] and <tag>"
        notch.plan_items = [
            {"step": "Handle [WIP] pattern with <bold>", "status": "in_progress"},
            {"step": "Done with [/test]", "status": "completed"},
        ]
        col = notch._render_collapsed()
        self.assertIn("[WIP]", col.plain)
        exp = notch._render_expanded()
        self.assertIn("[WIP]", exp.plain)
        self.assertIn("[/test]", exp.plain)

    def test_all_completed_sliding_window(self):
        notch = ChatNotch()
        notch.plan_items = [{"step": f"Task {i}", "status": "completed"} for i in range(10)]
        col = notch._render_collapsed()
        self.assertIn("10/10 All tasks completed", col.plain)
        exp = notch._render_expanded()
        self.assertIn("Plan (10/10)", exp.plain)
        self.assertIn("Task 9", exp.plain)
        self.assertIn("... (4 earlier steps)", exp.plain)

    def test_no_in_progress_picks_pending(self):
        notch = ChatNotch()
        notch.plan_items = [
            {"step": "Task 0", "status": "completed"},
            {"step": "Task 1", "status": "pending"},
            {"step": "Task 2", "status": "pending"},
        ]
        col = notch._render_collapsed()
        self.assertIn("1/3 Task 1", col.plain)
        exp = notch._render_expanded()
        self.assertIn("[ ] Task 1", exp.plain)

    def test_sliding_window_at_beginning(self):
        notch = ChatNotch()
        notch.plan_items = [
            {"step": f"Task {i}", "status": "in_progress" if i == 0 else "pending"}
            for i in range(10)
        ]
        exp = notch._render_expanded()
        self.assertIn("[▶] Task 0", exp.plain)
        self.assertIn("... (4 remaining steps)", exp.plain)
        self.assertNotIn("earlier steps", exp.plain)

    def test_refresh_notch_safe(self):
        notch = ChatNotch()
        notch.refresh_notch()
        notch.is_expanded = True
        notch.refresh_notch()

    def test_container_compose(self):
        container = ChatNotchContainer()
        children = list(container.compose())
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], ChatNotch)
        self.assertEqual(children[0].id, "chat-notch")


@pytest.mark.asyncio
async def test_action_toggle_plan_pilot():
    app = JohnstonApp()
    async with app.run_test() as pilot:
        notch = app.query_one(ChatNotch)
        self_expanded_initial = notch.is_expanded
        app.action_toggle_plan()
        self_expanded_after = notch.is_expanded
        assert self_expanded_after != self_expanded_initial
        await pilot.press("ctrl+p")
        assert notch.is_expanded == self_expanded_initial
