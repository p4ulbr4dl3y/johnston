import unittest
from unittest.mock import MagicMock

from tools.ask_user import AskUserTool


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


if __name__ == "__main__":
    unittest.main()


