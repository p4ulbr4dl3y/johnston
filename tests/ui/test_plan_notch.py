import unittest

import pytest

from widgets.app.app import JohnstonApp
from widgets.presentation.widgets.plan_notch import PlanNotch, PlanNotchContainer


class TestPlanNotch(unittest.TestCase):
    def test_init_and_toggle(self):
        notch = PlanNotch()
        self.assertFalse(notch.is_expanded)
        # Empty notch should not expand
        notch.toggle_expanded()
        self.assertFalse(notch.is_expanded)

        notch.set_plan([{"step": "Step 1", "status": "pending"}])
        notch.toggle_expanded()
        self.assertTrue(notch.is_expanded)
        notch.on_click()
        self.assertFalse(notch.is_expanded)

    def test_set_and_clear_plan(self):
        notch = PlanNotch()
        self.assertEqual(len(notch.plan_items), 0)
        self.assertFalse(notch.display)

        plan = [
            {"step": "Step 1", "status": "completed"},
            {"step": "Step 2", "status": "in_progress"},
            {"step": "Step 3", "status": "pending"},
        ]
        notch.set_plan(plan, "Refactoring parser")
        self.assertTrue(notch.display)
        self.assertEqual(len(notch.plan_items), 3)
        self.assertEqual(notch.plan_explanation, "Refactoring parser")

        col = notch._render_collapsed()
        self.assertIn("1/3", col.plain)
        self.assertIn("Step 2", col.plain)

        exp = notch._render_expanded()
        self.assertIn("Plan (1/3)", exp.plain)
        self.assertIn("Refactoring parser", exp.plain)
        self.assertIn("[▶] Step 2", exp.plain)

        notch.clear_plan()
        self.assertEqual(len(notch.plan_items), 0)
        self.assertFalse(notch.display)
        self.assertFalse(notch.is_expanded)

    def test_malformed_plan_items_resilience(self):
        notch = PlanNotch()
        # 1. String instead of list
        notch.set_plan("malformed string plan", explanation=123)
        self.assertEqual(notch.plan_items, [])
        self.assertFalse(notch.display)
        col = notch._render_collapsed()
        self.assertIn("No active plan", col.plain)
        exp = notch._render_expanded()
        self.assertIn("No tasks in plan", exp.plain)

        # 2. List of strings/invalid types instead of dicts
        notch.set_plan(["step 1", 123, None, {"step": "Valid step", "status": "pending"}])
        self.assertEqual(len(notch.plan_items), 1)
        self.assertEqual(notch.plan_items[0]["step"], "Valid step")
        self.assertTrue(notch.display)

    def test_empty_plan_items(self):
        notch = PlanNotch()
        notch.plan_items = []
        notch.plan_explanation = ""
        col = notch._render_collapsed()
        self.assertIn("No active plan", col.plain)
        exp = notch._render_expanded()
        self.assertIn("No tasks in plan", exp.plain)

    def test_single_item_plan(self):
        notch = PlanNotch()
        notch.plan_items = [{"step": "Single item", "status": "in_progress"}]
        col = notch._render_collapsed()
        self.assertIn("0/1 Single item", col.plain)
        exp = notch._render_expanded()
        self.assertIn("[▶] Single item", exp.plain)

    def test_rich_markup_escaping(self):
        notch = PlanNotch()
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
        notch = PlanNotch()
        notch.plan_items = [{"step": f"Task {i}", "status": "completed"} for i in range(10)]
        col = notch._render_collapsed()
        self.assertIn("10/10 All tasks completed", col.plain)
        exp = notch._render_expanded()
        self.assertIn("Plan (10/10)", exp.plain)
        self.assertIn("Task 9", exp.plain)
        self.assertIn("... (4 earlier steps)", exp.plain)

    def test_no_in_progress_picks_pending(self):
        notch = PlanNotch()
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
        notch = PlanNotch()
        notch.plan_items = [
            {"step": f"Task {i}", "status": "in_progress" if i == 0 else "pending"}
            for i in range(10)
        ]
        exp = notch._render_expanded()
        self.assertIn("[▶] Task 0", exp.plain)
        self.assertIn("... (4 remaining steps)", exp.plain)
        self.assertNotIn("earlier steps", exp.plain)

    def test_refresh_notch_safe(self):
        notch = PlanNotch()
        notch.refresh_notch()
        notch.is_expanded = True
        notch.refresh_notch()

    def test_container_compose(self):
        container = PlanNotchContainer()
        children = list(container.compose())
        self.assertEqual(len(children), 1)
        self.assertIsInstance(children[0], PlanNotch)
        self.assertEqual(children[0].id, "plan-notch")


@pytest.mark.asyncio
async def test_action_toggle_plan_empty_notifies_pilot():
    app = JohnstonApp()
    async with app.run_test() as pilot:
        notch = app.query_one(PlanNotch)
        assert not notch.plan_items
        app.action_toggle_plan()
        assert not notch.is_expanded
        assert not notch.display
        await pilot.press("ctrl+p")
        assert not notch.is_expanded
        assert not notch.display


@pytest.mark.asyncio
async def test_action_toggle_plan_pilot():
    app = JohnstonApp()
    async with app.run_test() as pilot:
        notch = app.query_one(PlanNotch)
        plan = [{"step": "Step 1", "status": "in_progress"}]
        app.on_plan_update(plan, "Running")
        self_expanded_initial = notch.is_expanded
        app.action_toggle_plan()
        self_expanded_after = notch.is_expanded
        assert self_expanded_after != self_expanded_initial
        await pilot.press("ctrl+p")
        assert notch.is_expanded == self_expanded_initial


@pytest.mark.asyncio
async def test_action_toggle_plan_hidden_pilot():
    app = JohnstonApp()
    async with app.run_test() as pilot:
        notch = app.query_one(PlanNotch)
        plan = [{"step": "Step 1", "status": "in_progress"}]
        app.on_plan_update(plan, "Running")
        assert notch.display

        # Press ctrl+h to hide
        await pilot.press("ctrl+h")
        assert not notch.display

        # Press ctrl+h again to restore
        await pilot.press("ctrl+h")
        assert notch.display

        # When hidden, ctrl+p should make it visible and expanded
        await pilot.press("ctrl+h")
        assert not notch.display
        await pilot.press("ctrl+p")
        assert notch.display
        assert notch.is_expanded



@pytest.mark.asyncio
async def test_app_on_plan_update_and_auto_clear_pilot():
    from widgets.chat_input import ChatInput

    app = JohnstonApp()
    async with app.run_test():
        notch = app.query_one(PlanNotch)
        assert not notch.display
        assert notch.plan_items == []

        # 1. Update plan via host method
        plan = [
            {"step": "Step 1", "status": "completed"},
            {"step": "Step 2", "status": "completed"},
        ]
        app.on_plan_update(plan, "Done all tasks")
        assert notch.display
        assert len(notch.plan_items) == 2
        assert app.current_plan == plan
        assert app.current_plan_explanation == "Done all tasks"

        # 2. Submitting new message when plan is completed auto-clears the notch
        event = ChatInput.Submitted(value="Start next feature")
        await app.on_chat_input_submitted(event)
        assert app.current_plan is None
        assert app.current_plan_explanation == ""
        assert not notch.display
        assert notch.plan_items == []


@pytest.mark.asyncio
async def test_session_persistence_restores_plan():
    from core.domain.entities.session import AgentSession

    app = JohnstonApp()
    sess = AgentSession("test-plan-sess")
    sess.messages = [
        {"type": "user", "text": "do task"},
        {
            "type": "tool",
            "tool_type": "update_plan",
            "args": {
                "plan": [{"step": "Analyze codebase", "status": "in_progress"}],
                "explanation": "Research phase",
            },
        },
    ]
    app.sm.save(sess)

    async with app.run_test() as pilot:
        app.load_session_ui("test-plan-sess")
        notch = app.query_one(PlanNotch)
        # 1. While loading, notch is hidden
        assert not notch.display
        assert app.current_plan == [{"step": "Analyze codebase", "status": "in_progress"}]
        assert app.current_plan_explanation == "Research phase"

        # 2. After load finishes, notch becomes visible
        await pilot.pause(0.3)
        assert notch.display
        assert len(notch.plan_items) == 1


@pytest.mark.asyncio
async def test_session_persistence_does_not_restore_completed_plan_if_subsequent_user_message():
    from core.domain.entities.session import AgentSession

    app = JohnstonApp()
    sess = AgentSession("test-completed-plan-sess")
    sess.messages = [
        {"type": "user", "text": "do task"},
        {
            "type": "tool",
            "tool_type": "update_plan",
            "args": {
                "plan": [{"step": "Analyze codebase", "status": "completed"}],
                "explanation": "Research done",
            },
        },
        {"type": "bot", "text": "All tasks completed!"},
        {"type": "user", "text": "Great, now commit"},
        {"type": "bot", "text": "Committed changes."},
    ]
    app.sm.save(sess)

    async with app.run_test() as pilot:
        app.load_session_ui("test-completed-plan-sess")
        notch = app.query_one(PlanNotch)
        assert app.current_plan is None
        assert app.current_plan_explanation == ""
        await pilot.pause(0.3)
        assert not notch.display
        assert notch.plan_items == []


@pytest.mark.asyncio
async def test_session_persistence_restores_completed_plan_if_no_subsequent_user_message():
    from core.domain.entities.session import AgentSession

    app = JohnstonApp()
    sess = AgentSession("test-completed-plan-latest-sess")
    sess.messages = [
        {"type": "user", "text": "do task"},
        {
            "type": "tool",
            "tool_type": "update_plan",
            "args": {
                "plan": [{"step": "Analyze codebase", "status": "completed"}],
                "explanation": "Research done",
            },
        },
        {"type": "bot", "text": "All tasks completed!"},
    ]
    app.sm.save(sess)

    async with app.run_test() as pilot:
        app.load_session_ui("test-completed-plan-latest-sess")
        notch = app.query_one(PlanNotch)
        assert app.current_plan == [{"step": "Analyze codebase", "status": "completed"}]
        assert app.current_plan_explanation == "Research done"
        await pilot.pause(0.3)
        assert notch.display
        assert len(notch.plan_items) == 1


@pytest.mark.asyncio
async def test_app_on_chat_input_submitted_malformed_plan_does_not_crash():
    from widgets.chat_input import ChatInput

    app = JohnstonApp()
    async with app.run_test():
        # Set malformed plan
        app.current_plan = "malformed string"
        app.current_plan_explanation = "test"

        event = ChatInput.Submitted(value="Hello")
        await app.on_chat_input_submitted(event)
        # Should not crash and handle smoothly



