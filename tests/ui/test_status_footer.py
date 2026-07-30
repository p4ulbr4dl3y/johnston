import unittest
from unittest.mock import MagicMock

from textual.app import App, ComposeResult

from widgets.status_footer import StatusFooter


class DummyTask:
    def __init__(self, task_id: str, is_running: bool = True):
        self.task_id = task_id
        self.is_running = is_running


class FooterTestApp(App):
    def __init__(self):
        super().__init__()
        self.pm = MagicMock()
        self.pm.get_active_provider_key.return_value = "openai"
        self.pm.get_provider_thinking_effort.return_value = "high"

        self.agent = MagicMock()
        self.agent.model = "gpt-4o"
        self.agent.mode = "action"
        self.agent.get_metrics.return_value = {
            "context_used": 15000,
            "total_tokens": 50000,
            "context": "128k",
            "context_limit": 128000,
            "cost_usd": 0.05,
        }

        self.background_tasks = [
            DummyTask("bash-1", is_running=True),
            DummyTask("subagent-1", is_running=True),
            DummyTask("subagent-2", is_running=False),
        ]

    def compose(self) -> ComposeResult:
        yield StatusFooter(id="status-footer")


class TestStatusFooter(unittest.IsolatedAsyncioTestCase):
    async def test_status_footer_rendering_and_subagents(self):
        app = FooterTestApp()
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            self.assertIsNotNone(footer)

            # Mount triggers refresh_footer
            footer.refresh_footer()
            await pilot.pause(0.1)

            # Verify last status args
            args = footer._last_status_args
            self.assertEqual(args["provider_key"], "openai")
            self.assertEqual(args["model_name"], "gpt-4o")
            self.assertEqual(args["active_bg_tasks"], 1)
            self.assertEqual(args["subagents_active"], 1)
            self.assertEqual(args["subagents_total"], 2)
            self.assertEqual(args["thinking_effort"], "high")
            self.assertIn("skills_visible", args)
            self.assertIn("skills_total", args)

            # Test generating spinner toggle
            footer.set_generating(True)
            self.assertTrue(footer.is_generating)
            self.assertIsNotNone(footer._spinner_timer)

            footer.set_generating(False)
            self.assertFalse(footer.is_generating)
            self.assertIsNone(footer._spinner_timer)

            # Test compact mode rendering
            footer.update_status(
                provider_key="openai",
                model_name="gpt-4o",
                active_bg_tasks=2,
                subagents_active=1,
                subagents_total=2,
            )
