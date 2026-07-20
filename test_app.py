import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        suggestions = app.query_one("#command-suggestions", CommandSuggestions)
        assert not suggestions.display
        
        # Симулируем посимвольное нажатие клавиш: '/', 'r', 'e'
        await pilot.press("slash")
        await pilot.pause(0.1)
        assert suggestions.display
        print("✓ Suggestions displayed when typing '/' key")
        
        await pilot.press("r")
        await pilot.press("e")
        await pilot.pause(0.1)
        assert suggestions.display
        print("✓ Suggestions updated when typing '/re'")
        
        # Нажимаем Tab -> автодополнение до "/resume"
        await pilot.press("tab")
        await pilot.pause(0.1)
        assert chat_input.text == "/resume"
        assert not suggestions.display
        print("✓ Tab key autocompleted '/re' to '/resume'")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
