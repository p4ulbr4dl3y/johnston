import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserMessage, BotMessage
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        # Отправляем первое сообщение
        chat_input.load_text("Первый запрос")
        await pilot.press("enter")
        await pilot.pause(0.5)
        
        # Отправляем второе сообщение
        chat_input.load_text("Второй запрос")
        await pilot.press("enter")
        await pilot.pause(0.5)
        
        # Нажимаем Вверх -> должен загрузиться "Второй запрос"
        await pilot.press("up")
        assert chat_input.text == "Второй запрос"
        print("✓ Up arrow recalled latest prompt: 'Второй запрос'")
        
        # Еще раз Вверх -> должен загрузиться "Первый запрос"
        await pilot.press("up")
        assert chat_input.text == "Первый запрос"
        print("✓ Up arrow recalled earlier prompt: 'Первый запрос'")
        
        # Нажимаем Вниз -> возврат к "Второй запрос"
        await pilot.press("down")
        assert chat_input.text == "Второй запрос"
        print("✓ Down arrow navigated forward to 'Второй запрос'")
        
        # Нажимаем Вниз -> возврат к черновику (пустой строке)
        await pilot.press("down")
        assert chat_input.text == ""
        print("✓ Down arrow returned to empty draft")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
