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
        
        # Начальная высота должно быть 3
        assert chat_input.styles.height.value == 3
        
        # Вводим 4 строки текста
        chat_input.load_text("Строка 1\nСтрока 2\nСтрока 3\nСтрока 4")
        await pilot.pause(0.1)
        
        # Высота должна автоматически вырасти до 6 (4 + 2 рамки)
        assert chat_input.styles.height.value == 6
        print("✓ Dynamic height expansion test passed!")
        
        # Отправляем сообщение
        await pilot.press("enter")
        await pilot.pause(2.0)
        
        # После отправки высота возвращается к 3
        assert chat_input.styles.height.value == 3
        print("✓ Height reset test passed!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
