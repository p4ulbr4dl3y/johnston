import unittest
from unittest.mock import MagicMock

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
        res = await tool.execute({"questions": [{"question_text": "Test?", "options": ["a"]}]})
        self.assertIn("ERR", res)
        self.assertIn("app instance not available", res)

    async def test_no_questions_returns_error(self):
        tool = AskUserTool()
        res = await tool.execute({})
        self.assertEqual(res, "ERR: invalid or missing 'questions' list")

    async def test_invalid_questions_type_returns_error(self):
        tool = AskUserTool()
        res = await tool.execute({"questions": "invalid"})
        self.assertEqual(res, "ERR: invalid or missing 'questions' list")


    async def test_error_on_push_screen_failure(self):
        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app.push_screen.side_effect = RuntimeError("no display available")
        res = await tool.execute(
            {"questions": [{"question_text": "Pick one", "options": ["red", "blue"]}]},
            app=mock_app,
        )
        self.assertIn("ERR: prompt failed", res)

    async def test_successful_interactive_flow(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        def mock_push_screen(screen, callback=None):
            if callback:
                callback("Question: Choose item\nAnswer: Option A")

        mock_app.push_screen = mock_push_screen
        res = await tool.execute(
            {"questions": [{"question_text": "Choose item", "options": ["Option A", "Option B"]}]},
            app=mock_app
        )
        self.assertIn("Question: Choose item", res)
        self.assertIn("Answer: Option A", res)

    async def test_cancelled_flow(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        def mock_push_screen(screen, callback=None):
            if callback:
                callback("cancelled")

        mock_app.push_screen = mock_push_screen
        res = await tool.execute(
            {"questions": [{"question_text": "Cancel this?", "options": []}]},
            app=mock_app
        )
        self.assertEqual(res, "OK: cancelled by user")

    async def test_unknown_status_cancels(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        def fake_push(screen, callback=None):
            if callback:
                callback({"status": "unknown_garbage"})

        mock_app.push_screen.side_effect = fake_push
        res = await tool.execute({"questions": [{"question_text": "Q?", "options": ["a"]}]}, app=mock_app)
        self.assertIn("OK: cancelled by user", res)

    async def test_execute_sorts_options_before_display(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        def mock_push_screen(screen, callback=None):
            opts = screen.questions[0]["options"]
            self.assertEqual(opts, ["Yes (Recommended)", "Maybe", "No"])
            if callback:
                callback("Question: Q\nAnswer: Yes")

        mock_app.push_screen = mock_push_screen
        res = await tool.execute(
            {"questions": [{"question_text": "Q", "options": ["Maybe", "No", "Yes (Recommended)"]}]},
            app=mock_app,
        )
        self.assertIn("Yes", res)
    async def test_minimized_flow_resumed_by_callback(self):
        tool = AskUserTool()
        mock_app = MagicMock()

        def mock_push_screen(screen, callback=None):
            if not hasattr(mock_app, "_first_call_done"):
                mock_app._first_call_done = True
                if callback:
                    callback({"action": "minimize", "answers": {}, "q_idx": 0})
                if hasattr(mock_app, "_pending_ask_user") and mock_app._pending_ask_user:
                    mock_app._pending_ask_user()
            else:
                if callback:
                    callback("Question: Choice?\nAnswer: Opt1")

        mock_app.push_screen = mock_push_screen
        res = await tool.execute(
            {"questions": [{"question_text": "Choice?", "options": ["Opt1"]}]},
            app=mock_app,
        )
        self.assertIn("Question: Choice?", res)
        self.assertIn("Answer: Opt1", res)


if __name__ == "__main__":
    unittest.main()


