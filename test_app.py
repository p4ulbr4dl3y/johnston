import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, UserMessage
from widgets.chat_input import ChatInput
from widgets.modal_screens import HelpScreen, RewindScreen, ResumeScreen, ProviderScreen, ModelScreen

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        # 1. Проверяем /help
        chat_input.load_text("/help")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, HelpScreen)
        
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, HelpScreen)
        print("✓ HelpScreen tests passed")

        # 2. Сообщения пользователя
        for msg in ["First message", "Second message", "Third message"]:
            chat_input.load_text(msg)
            await pilot.press("enter")
            await pilot.pause(0.5)
            
        # 3. Проверяем /rewind
        chat_input.load_text("/rewind")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, RewindScreen)
        
        # Выбираем первый элемент по Enter
        await pilot.press("enter")
        await pilot.pause(0.5)
        
        chat_view = app.query_one(ChatView)
        user_msgs = [c for c in chat_view.children if isinstance(c, UserMessage)]
        assert len(user_msgs) == 1
        assert user_msgs[0].raw_text == "First message"
        print("✓ RewindScreen tests passed cleanly!")

        # 4. Проверяем /resume
        chat_input.load_text("/resume")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ResumeScreen)
        
        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ResumeScreen)
        print("✓ ResumeScreen tests passed cleanly!")

        # 5. Проверяем /provider
        chat_input.load_text("/provider")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ProviderScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        print("✓ ProviderScreen tests passed cleanly!")

        # 6. Проверяем /models
        chat_input.load_text("/models")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert isinstance(app.screen, ModelScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        print("✓ ModelScreen tests passed cleanly!")

        # 7. Проверяем /new
        chat_input.load_text("/new")
        await pilot.press("enter")
        await pilot.pause(0.5)
        chat_view = app.query_one(ChatView)
        assert len(list(chat_view.children)) == 0
        print("✓ /new command tests passed cleanly!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
