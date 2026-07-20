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
        
        # Начальная высота = 3
        assert chat_input.styles.height.value == 3
        
        # Вводим 5 строк текста
        chat_input.load_text("1\n2\n3\n4\n5")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 7
        print("✓ Expanded to 7 lines")
        
        # Стираем часть строк (уменьшаем до 2 строк)
        chat_input.load_text("1\n2")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 4
        print("✓ Successfully shrunk back to 4 lines on deletion")
        
        # Очищаем (возврат к 3)
        chat_input.load_text("")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 3
        print("✓ Reset to minimum height 3")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
