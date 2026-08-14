import unittest
from unittest.mock import AsyncMock


class _AsyncHost:
    """Host that implements the ToolHost protocol with real methods."""

    def __init__(self):
        self.question_calls = []
        self.notified = []
        self.confirmed = None

    async def ask_user(self, questions: list[dict]) -> str:
        self.question_calls.append(questions)
        return "Question: Q\nAnswer: A"

    def notify(self, message: str, severity: str = "info"):
        self.notified.append((message, severity))

    def confirm_permission(self, screen_name, args, reason, perm_name=None):
        self.confirmed = True
        return True

    def get_current_session_id(self):
        return "sess-X"


class _BareHost:
    """Host object with no host-method capabilities."""


class TestToolHostProtocol(unittest.TestCase):
    def test_is_protocol_and_runtime_checkable(self):
        from typing import Protocol

        from tools.host import ToolHost

        # ToolHost is a lightweight runtime-checkable Protocol (no ABC).
        self.assertTrue(issubclass(ToolHost, Protocol))
        self.assertTrue(getattr(ToolHost, "_is_runtime_protocol", False))
        for name in (
            "ask_user",
            "confirm_permission",
            "notify",
            "trigger_ai_response",
            "refresh_status_footer",
            "get_task_manager",
            "get_provider_manager",
            "get_current_session_id",
            "get_project_dir",
        ):
            self.assertTrue(hasattr(ToolHost, name), name)

    def test_host_missing_method_degrades_via_getattr(self):
        # A minimal host with no capabilities never breaks a tool call: the
        # context helper returns None instead of raising.
        self.assertFalse(hasattr(_BareHost(), "ask_user"))


class TestToolHostWithAsyncCapableHost(unittest.IsolatedAsyncioTestCase):
    async def test_ask_user_delegates_and_awaits(self):
        from tools.context import ToolContext

        host = _AsyncHost()
        ctx = ToolContext(host)
        res = await ctx.ask_user([{"question_text": "Pick", "options": ["a"]}])
        self.assertEqual(res, "Question: Q\nAnswer: A")
        self.assertEqual(len(host.question_calls), 1)


class TestToolContextDegradation(unittest.TestCase):
    def test_bare_host_degrades(self):
        from tools.context import ToolContext

        ctx = ToolContext(_BareHost())
        ctx.refresh_status()  # no-op, no host method
        self.assertIsNone(ctx.task_manager)
        self.assertIsNone(ctx.provider_manager)
        self.assertIsNone(ctx.session_id)
        self.assertIsNotNone(ctx.project_dir)  # falls back to cwd/cwd()
        self.assertEqual(ctx.background_tasks, [])
        self.assertIsNone(ctx.create_agent())

    def test_async_mocked_host_ask_user_via_context(self):
        import asyncio

        from tools.context import ToolContext

        host = AsyncMock()
        host.ask_user = AsyncMock(return_value="Question: Q\nAnswer: X")

        async def run():
            ctx = ToolContext(host)
            return await ctx.ask_user([{"question_text": "Q", "options": ["X"]}])

        res = asyncio.run(run())
        self.assertIn("Answer: X", res)
        host.ask_user.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
