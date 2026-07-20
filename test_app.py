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
        
        # 1. Печатаем "/" -> подсказки активируются
        chat_input.load_text("/")
        await pilot.pause(0.1)
        assert suggestions.display
        print("✓ Suggestions displayed when typing '/'")
        
        # 2. Печатаем "/h" -> фильтрация до /help
        chat_input.load_text("/h")
        await pilot.pause(0.1)
        assert suggestions.display
        
        # 3. Нажимаем Tab -> автодополнение до "/help"
        await pilot.press("tab")
        await pilot.pause(0.1)
        assert chat_input.text == "/help"
        assert not suggestions.display
        print("✓ Tab key autocompleted '/h' to '/help'")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
