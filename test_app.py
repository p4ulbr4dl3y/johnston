import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, BotMessage
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        # 1. Отправляем запрос на создание и запуск
        chat_input.load_text("создай новый файл и запусти тест")
        await pilot.press("enter")
        await pilot.pause(2.0)
        
        chat_view = app.query_one(ChatView)
        bot_msgs = [c for c in chat_view.children if isinstance(c, BotMessage)]
        assert len(bot_msgs) == 1
        
        content = bot_msgs[0].content
        print("Bot content output:\n", content)
        
        assert "● Create(" in content
        assert "● Bash(" in content
        print("✓ Agent tool calls (Create, Bash) rendered successfully!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
