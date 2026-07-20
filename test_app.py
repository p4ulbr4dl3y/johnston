import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserMessage, BotMessage
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_view = app.query_one(ChatView)
        assert chat_view is not None
        
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        chat_input.load_text("Первая строка\nВторая строка")
        
        await pilot.press("enter")
        await pilot.pause(2.0)
        
        user_msgs = [c for c in chat_view.children if isinstance(c, UserMessage)]
        bot_msgs = [c for c in chat_view.children if isinstance(c, BotMessage)]
        
        assert len(user_msgs) == 1
        assert len(bot_msgs) == 1
        assert len(bot_msgs[0].content) > 0
        print("✓ Multi-line input test passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
