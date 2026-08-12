import unittest

from app import JohnstonApp


class TestChatViewEdge(unittest.IsolatedAsyncioTestCase):
    async def test_empty_state_shows_welcome(self):
        app = JohnstonApp()
        async with app.run_test():
            from widgets.chat_view import ChatView, WelcomeWidget

            chat_view = app.query_one(ChatView)
            welcome = list(chat_view.query(WelcomeWidget))
            self.assertGreaterEqual(len(welcome), 1)

    async def test_add_user_message_none_text(self):
        """None text input must not crash the message mount."""
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one("ChatView")
            await chat_view.add_user_message(None)
            await pilot.pause()
            self.assertEqual(len(chat_view.get_user_messages()), 1)

    async def test_add_user_message_empty_attachments_list(self):
        """An empty attachments list must behave like no attachments."""
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one("ChatView")
            await chat_view.add_user_message("hi", attachments=[])
            await pilot.pause()
            self.assertEqual(len(chat_view.get_user_messages()), 1)

    async def test_add_tool_call_none_result(self):
        """Tool calls with no result text must mount cleanly."""
        app = JohnstonApp()
        async with app.run_test() as pilot:
            chat_view = app.query_one("ChatView")
            from widgets.chat_view import ToolCallWidget

            tool = await chat_view.add_tool_call("read", "f.py", None)
            await pilot.pause()
            self.assertIsInstance(tool, ToolCallWidget)


if __name__ == "__main__":
    unittest.main()
