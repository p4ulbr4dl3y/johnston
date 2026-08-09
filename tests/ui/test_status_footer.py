import unittest
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult

from widgets.status_footer import StatusFooter


class DummyTask:
    def __init__(self, task_id: str, is_running: bool = True, is_background: bool = True, session_id: str = "test-session", kind: str = "shell"):
        self.task_id = task_id
        self.kind = kind
        self.is_running = is_running
        self.is_background = is_background
        self.session_id = session_id


class StubPM:
    """Provider manager stub without get_provider_thinking_effort."""

    def get_active_provider_key(self):
        return "openai"

    def load_providers(self):
        return {"openai": {"name": "OpenAI"}}

    def is_provider_connected(self, key, info=None):
        return True


class FooterTestApp(App):
    def __init__(self):
        super().__init__()
        self.current_session_id = "test-session"
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

        class DummySession:
            def __init__(self, status: str):
                self.status = status

        self.sm = MagicMock()
        self.sm.get_subagents_for_parent.return_value = [
            DummySession("running"),
            DummySession("completed"),
        ]

        self.background_tasks = [
            DummyTask("bash-1", is_running=True),
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

    def test_spin_without_last_status_args(self):
        footer = StatusFooter()
        with patch.object(footer, "refresh_footer") as mock_rf:
            footer._spin()
            mock_rf.assert_called_once()

    async def test_set_generating_noop_when_state_unchanged(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            footer.set_generating(True)
            self.assertTrue(footer.is_generating)
            footer.set_generating(True)  # no-op
            footer.set_generating(False)
            self.assertFalse(footer.is_generating)
            footer.set_generating(False)  # no-op

    async def test_refresh_footer_exception_falls_back_to_default(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            with patch("core.mcp_manager.get_mcp_manager", side_effect=Exception("boom")):
                with patch.object(footer, "update_status") as mock_us:
                    footer.refresh_footer()
                    mock_us.assert_called_once_with(provider_key="default")

    async def test_refresh_footer_clean_model_placeholder(self):
        app = FooterTestApp()
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            with patch("core.models_catalog.catalog.get_model_display_name", return_value=""):
                footer.refresh_footer()
                await pilot.pause()
            self.assertEqual(footer._last_status_args["clean_model"], "[Select model: /models]")

    async def test_refresh_footer_thinking_effort_fallback(self):
        app = FooterTestApp()
        app.pm = StubPM()
        app.agent.thinking_effort = "medium"
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            await pilot.pause()
            self.assertEqual(footer._last_status_args["thinking_effort"], "medium")

    async def test_refresh_footer_mcp_active_counting(self):
        app = FooterTestApp()
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "url-only", "url": "http://x", "command": None, "disabled": False},
                {"name": "err-client", "command": "python", "disabled": False},
                {"name": "good", "command": "python", "disabled": False},
                {"name": "off", "command": "python", "disabled": True},
            ]
            mgr.clients = {
                "err-client": MagicMock(last_error="boom"),
                "good": MagicMock(last_error=None),
            }
            footer._mcp_cache_time = 0  # force reload of cached servers
            with patch("core.mcp_manager.get_mcp_manager", return_value=mgr):
                footer.refresh_footer()
                await pilot.pause()
            self.assertEqual(footer._last_status_args["mcp_active"], 1)
            self.assertEqual(footer._last_status_args["mcp_total"], 4)

    async def test_update_status_fallback_branches(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            with patch("core.models_catalog.catalog.get_model_display_name", return_value=""):
                footer.update_status(provider_key="openai", model_name="gpt-4o", is_connected=True)
            footer.update_status(provider_key="openai", is_connected=True, model_name="")
            footer.update_status(provider_key="openai", is_connected=False, model_name="")

    async def test_update_status_compact_mode(self):
        app = FooterTestApp()
        async with app.run_test(size=(60, 24)):
            footer = app.query_one(StatusFooter)
            with patch.object(app, "query_one", return_value=MagicMock(clipboard_attachments=[1, 2])):
                footer.update_status(
                    provider_key="openai",
                    provider_display="OpenAI",
                    is_connected=True,
                    model_name="gpt-4o",
                    active_bg_tasks=1,
                    subagents_active=1,
                    subagents_total=2,
                    context_used=1000,
                    context_limit=128000,
                    total_tokens=5000,
                    mcp_active=1,
                    mcp_total=2,
                )
            footer.update_status(provider_key="openai", provider_display="OpenAI", is_connected=True, model_name="")
            footer.update_status(provider_key="openai", provider_display="OpenAI", is_connected=False, model_name="")

    async def test_update_status_noncompact_attachments(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            with patch.object(app, "query_one", return_value=MagicMock(clipboard_attachments=[1, 2])):
                footer.update_status(
                    provider_key="openai", provider_display="OpenAI", is_connected=True, model_name="gpt-4o"
                )
            with patch.object(app, "query_one", return_value=MagicMock(clipboard_attachments=[1])):
                footer.update_status(
                    provider_key="openai", provider_display="OpenAI", is_connected=True, model_name="gpt-4o"
                )
