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
        
        # Проверяем работу авто-высоты
        assert chat_input.styles.height.value == 3
        chat_input.load_text("1\n2\n3\n4\n5")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 7
        
        chat_input.load_text("")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 3
        print("✓ Auto-height works")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
