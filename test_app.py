import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserMessage, BotMessage

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_view = app.query_one(ChatView)
        assert chat_view is not None
        
        # Начинаем с пустого чата
        bot_msgs = [c for c in chat_view.children if isinstance(c, BotMessage)]
        assert len(bot_msgs) == 0
        
        input_widget = app.query_one("#message-input")
        input_widget.focus()
        input_widget.value = "Привет без первички"
        
        await pilot.press("enter")
        await pilot.pause(2.0)
        
        user_msgs = [c for c in chat_view.children if isinstance(c, UserMessage)]
        bot_msgs = [c for c in chat_view.children if isinstance(c, BotMessage)]
        
        assert len(user_msgs) == 1
        assert len(bot_msgs) == 1
        assert len(bot_msgs[0].content) > 0
        print("✓ Test without welcome message passed!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
