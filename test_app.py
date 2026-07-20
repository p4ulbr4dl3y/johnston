import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserMessage, BotMessage
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        # Отправляем 2 сообщения
        chat_input.load_text("Сообщение 1")
        await pilot.press("enter")
        await pilot.pause(0.2)
        
        chat_input.load_text("Сообщение 2")
        await pilot.press("enter")
        await pilot.pause(0.2)
        
        # Проверяем зацикливание Вверх (Up)
        # 1. Up -> "Сообщение 2"
        await pilot.press("up")
        assert chat_input.text == "Сообщение 2"
        
        # 2. Up -> "Сообщение 1"
        await pilot.press("up")
        assert chat_input.text == "Сообщение 1"
        
        # 3. Up на самом первом элементе -> Зацикливание к черновику (пустая строка)
        await pilot.press("up")
        assert chat_input.text == ""
        print("✓ Up arrow looped back to draft cleanly!")
        
        # 4. Up снова -> "Сообщение 2"
        await pilot.press("up")
        assert chat_input.text == "Сообщение 2"
        
        # Проверяем зацикливание Вниз (Down)
        # Находясь на "Сообщение 2", прессы Вниз:
        # Down -> Черновик ""
        await pilot.press("down")
        assert chat_input.text == ""
        
        # Down на черновике -> Зацикливание к "Сообщение 1"
        await pilot.press("down")
        assert chat_input.text == "Сообщение 1"
        print("✓ Down arrow looped from draft to oldest prompt cleanly!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
