import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserBubble, BotBubble

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_view = app.query_one(ChatView)
        assert chat_view is not None
        
        # Приветственный бот-баббл
        bot_bubbles = [c for c in chat_view.children if isinstance(c, BotBubble)]
        assert len(bot_bubbles) == 1
        
        # Ввод сообщения
        input_widget = app.query_one("#message-input")
        input_widget.focus()
        input_widget.value = "Минимализм работает?"
        
        # Нажимаем Enter
        await pilot.press("enter")
        await pilot.pause(2.0)
        
        user_bubbles = [c for c in chat_view.children if isinstance(c, UserBubble)]
        bot_bubbles = [c for c in chat_view.children if isinstance(c, BotBubble)]
        
        assert len(user_bubbles) == 1
        assert len(bot_bubbles) == 2
        assert len(bot_bubbles[1].content) > 0
        print("✓ Minimal interface automated test passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
