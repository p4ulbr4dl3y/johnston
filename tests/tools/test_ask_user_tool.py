import unittest
from unittest.mock import AsyncMock, MagicMock

from tools.ask_user import AskUserTool, _is_recommended_option, _sort_recommended_first


class TestRecommendedSorting(unittest.TestCase):
    def test_is_recommended_prefix_variants(self):
        for opt in [
            "(Recommended) Fix now",
            "[Recommended] Fix now",
            "Recommended: Fix now",
            "recommended fix now",
        ]:
            self.assertTrue(_is_recommended_option(opt), opt)

    def test_is_recommended_suffix_variants(self):
        for opt in [
            "Fix now (Recommended)",
            "Fix now [Recommended]",
            "Fix now (recommended)",
            "Fix now recommended",
        ]:
            self.assertTrue(_is_recommended_option(opt), opt)

    def test_is_not_recommended(self):
        for opt in ["Fix now", "Recommendation: do this", "Unrelated", ""]:
            self.assertFalse(_is_recommended_option(opt), opt)

    def test_sort_recommended_first(self):
        options = ["plain", "(Recommended) Fix now", "other", "later (Recommended)"]
        self.assertEqual(
            _sort_recommended_first(options),
            ["(Recommended) Fix now", "later (Recommended)", "plain", "other"],
        )

    def test_sort_preserves_relative_order(self):
        options = ["a", "b", "c"]
        self.assertEqual(_sort_recommended_first(options), ["a", "b", "c"])
        self.assertEqual(_sort_recommended_first([]), [])


class TestAskUserTool(unittest.IsolatedAsyncioTestCase):
    async def test_no_app_returns_error(self):
        tool = AskUserTool()
        res = str(await tool.execute({"questions": [{"question": "Test?", "options": ["a"]}]}))
        self.assertIn("ERR", res)
        self.assertIn("ERR: context 'app': unavailable", res)

    async def test_no_questions_returns_error(self):
        tool = AskUserTool()
        res = str(await tool.execute({}))
        self.assertEqual(res, "ERR: params 'questions': missing or invalid")

    async def test_invalid_questions_type_returns_error(self):
        tool = AskUserTool()
        res = str(await tool.execute({"questions": "invalid"}))
        self.assertEqual(res, "ERR: params 'questions': missing or invalid")

    async def test_error_on_push_screen_failure(self):
        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app.ask_user = AsyncMock(side_effect=RuntimeError("no display available"))
        res = str(await tool.execute(
            {"questions": [{"question": "Pick one", "options": ["red", "blue"]}]},
            ctx=mock_app,
        ))
        self.assertIn("ERR: prompt:", res)

    async def test_successful_interactive_flow(self):
        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app.ask_user = AsyncMock(return_value="Question: Choose item\nAnswer: Option A")
        res = str(await tool.execute(
            {"questions": [{"question": "Choose item", "options": ["Option A", "Option B"]}]},
            ctx=mock_app,
        ))
        self.assertIn("Question: Choose item", res)
        self.assertIn("Answer: Option A", res)

    async def test_cancelled_flow(self):
        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app.ask_user = AsyncMock(return_value="cancelled by user")
        res = str(await tool.execute(
            {"questions": [{"question": "Cancel this?", "options": []}]},
            ctx=mock_app,
        ))
        self.assertEqual(res, "cancelled by user")

    async def test_unknown_status_cancels(self):
        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app.ask_user = AsyncMock(return_value="cancelled by user")
        res = str(await tool.execute({"questions": [{"question": "Q?", "options": ["a"]}]}, ctx=mock_app))
        self.assertIn("cancelled by user", res)

    async def test_execute_sorts_options_before_display(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        async def fake_ask_user(questions):
            self.assertEqual(questions[0]["options"], ["Yes (Recommended)", "Maybe", "No"])
            return "Question: Q\nAnswer: Yes"

        mock_app.ask_user = fake_ask_user
        res = str(await tool.execute(
            {"questions": [{"question": "Q", "options": ["Maybe", "No", "Yes (Recommended)"]}]},
            ctx=mock_app,
        ))
        self.assertIn("Yes", res)

    async def test_minimized_flow_resumed_by_callback(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        async def fake_ask_user(questions):
            if not hasattr(mock_app, "_first_call_done"):
                mock_app._first_call_done = True
                if hasattr(mock_app, "_pending_ask_user") and mock_app._pending_ask_user:
                    mock_app._pending_ask_user()
            return "Question: Choice?\nAnswer: Opt1"

        mock_app.ask_user = fake_ask_user
        res = str(await tool.execute(
            {"questions": [{"question": "Choice?", "options": ["Opt1"]}]},
            ctx=mock_app,
        ))
        self.assertIn("Question: Choice?", res)
        self.assertIn("Answer: Opt1", res)

    async def test_minimized_then_esc_clears_pending_and_re_raises(self):
        # User minimizes the wizard (pending saved), then the agent run is cancelled.
        # The CancelledError must clear the pending flag and re-raise (cooperative
        # cancellation), not swallow the cancellation as a normal result.
        import asyncio

        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app._pending_ask_user = lambda: None

        async def cancelled_ask_user(questions):
            raise asyncio.CancelledError()

        mock_app.ask_user = cancelled_ask_user
        with self.assertRaises(asyncio.CancelledError):
            await tool.execute(
                {"questions": [{"question": "Choice?", "options": ["Opt1"]}]},
                ctx=mock_app,
            )
        self.assertIsNone(mock_app._pending_ask_user)


if __name__ == "__main__":
    unittest.main()
