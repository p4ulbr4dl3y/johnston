import unittest
from unittest.mock import MagicMock

from tools.ask_user import AskUserTool
from tools.context import ToolContext


class TestAskUserTool(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        ToolContext._instance = None

    def tearDown(self):
        ToolContext._instance = None

    async def test_no_app_returns_error(self):
        tool = AskUserTool()
        res = await tool.execute({"questions": [{"question_text": "Test?", "options": ["a"]}]})
        self.assertIn("Error", res)
        self.assertIn("App instance not available", res)

    async def test_no_questions_no_app(self):
        tool = AskUserTool()
        res = await tool.execute({})
        self.assertIn("Error", res)

    async def test_dict_questions_normalized_but_no_app(self):
        tool = AskUserTool()
        res = await tool.execute({"questions": {"question_text": "Single?", "options": ["y"]}})
        self.assertIn("Error", res)

    async def test_single_question_field_normalized_but_no_app(self):
        tool = AskUserTool()
        res = await tool.execute({"question": "What color?"})
        self.assertIn("Error", res)

    async def test_error_on_push_screen_failure(self):
        tool = AskUserTool()
        mock_app = MagicMock()
        mock_app.push_screen.side_effect = RuntimeError("no display available")
        res = await tool.execute(
            {"questions": [{"question_text": "Pick one", "options": ["red", "blue"]}]},
            app=mock_app,
        )
        self.assertIn("Error prompting user", res)

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
                callback("Cancelled by user.")

        mock_app.push_screen = mock_push_screen
        res = await tool.execute(
            {"questions": [{"question_text": "Cancel this?", "options": []}]},
            app=mock_app
        )
        self.assertEqual(res, "Cancelled by user.")


if __name__ == "__main__":
    unittest.main()


