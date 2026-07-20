import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserMessage, BotMessage
from widgets.chat_input import ChatInput
from widgets.modal_screens import HelpScreen, ResumeScreen

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        # 1. Проверяем слэш-команду /help
        chat_input.load_text("/help")
        await pilot.press("enter")
        await pilot.pause(0.2)
        
        # Убеждаемся, что откроется HelpScreen
        assert isinstance(app.screen, HelpScreen)
        print("✓ /help opened HelpScreen modal cleanly!")
        
        # Закрываем модальное окно через Esc
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, HelpScreen)
        print("✓ HelpScreen modal closed on Escape")

        # 2. Отправляем 3 сообщения пользователя
        for msg in ["Первое сообщение", "Второе сообщение", "Третье сообщение"]:
            chat_input.load_text(msg)
            await pilot.press("enter")
            await pilot.pause(0.5)
            
        chat_view = app.query_one(ChatView)
        user_msgs = [c for c in chat_view.children if isinstance(c, UserMessage)]
        assert len(user_msgs) == 3
        
        # 3. Проверяем слэш-команду /resume
        chat_input.load_text("/resume")
        await pilot.press("enter")
        await pilot.pause(0.2)
        
        # Убеждаемся, что откроется ResumeScreen
        assert isinstance(app.screen, ResumeScreen)
        print("✓ /resume opened ResumeScreen modal cleanly!")
        
        # Выбираем первое сообщение для отката (индекс 0) и нажимаем Enter
        await pilot.press("enter")
        await pilot.pause(0.5)
        
        # После отката к первому сообщению должно остаться ровно 1 сообщение пользователя
        user_msgs_after = [c for c in chat_view.children if isinstance(c, UserMessage)]
        assert len(user_msgs_after) == 1
        assert user_msgs_after[0].raw_text == "Первое сообщение"
        print("✓ History rollback (/resume) to first message succeeded!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
