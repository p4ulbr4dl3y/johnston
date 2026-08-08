import unittest

from textual.app import App, ComposeResult

from widgets.inline_question import DEMO_QUESTIONS, InlineQuestionBar


class InlineQuestionApp(App[None]):
    def __init__(self, callback=None):
        super().__init__()
        self.callback = callback

    def compose(self) -> ComposeResult:
        yield InlineQuestionBar(DEMO_QUESTIONS, callback=self.callback)


class TestInlineQuestionBar(unittest.IsolatedAsyncioTestCase):
    async def test_inline_question_flow(self) -> None:
        results = []
        app = InlineQuestionApp(callback=lambda res: results.append(res))

        async with app.run_test() as pilot:
            bar = app.query_one(InlineQuestionBar)
            # Question 1: single select (q_idx = 0)
            self.assertEqual(bar.q_idx, 0)
            await pilot.press("space")  # Toggle item on q_idx 0
            self.assertEqual(bar.q_idx, 0)  # Must stay on q_idx 0!
            await pilot.press("enter")  # Enter advances
            self.assertEqual(bar.q_idx, 1)


            # Question 2: multiselect (q_idx = 1)
            await pilot.press("space")  # Toggle item on q_idx 1
            self.assertEqual(bar.q_idx, 1)  # Must stay on q_idx 1!
            await pilot.press("enter")  # Enter advances
            self.assertEqual(bar.q_idx, 2)

            # Question 3: text input (q_idx = 2)
            await pilot.press("h", "e", "l", "l", "o", "enter")

            # Summary step (q_idx = 3)
            self.assertEqual(bar.q_idx, 3)
            await pilot.press("enter")
            await pilot.pause()

        self.assertEqual(len(results), 1)
        self.assertIsNotNone(results[0])
