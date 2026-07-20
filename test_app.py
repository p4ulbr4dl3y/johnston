import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserBubble, BotBubble

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_view = app.query_one(ChatView)
        assert chat_view is not None
        
        # Проверяем приветственный бот-баббл
        bot_bubbles = [c for c in chat_view.children if isinstance(c, BotBubble)]
        assert len(bot_bubbles) == 1
        print("✓ Welcome message bot bubble present")
        
        # Находим поле ввода и фокусируемся на нем
        input_widget = app.query_one("#message-input")
        input_widget.focus()
        input_widget.value = "Привет ИИ!"
        
        # Нажимаем Enter
        await pilot.press("enter")
        
        # Ждем выполнения асинхронного воркера
        await pilot.pause(2.0)
        
        # Проверяем бабблы
        user_bubbles = [c for c in chat_view.children if isinstance(c, UserBubble)]
        bot_bubbles = [c for c in chat_view.children if isinstance(c, BotBubble)]
        
        print(f"✓ User bubbles: {len(user_bubbles)}")
        print(f"✓ Bot bubbles: {len(bot_bubbles)}")
        
        assert len(user_bubbles) == 1
        assert len(bot_bubbles) == 2
        
        # Проверяем, что текст бота не пустой
        assert len(bot_bubbles[1].content) > 0
        print(f"✓ Bot response preview: '{bot_bubbles[1].content[:40]}...'")

        print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
