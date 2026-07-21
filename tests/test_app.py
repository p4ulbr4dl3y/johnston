import asyncio

from app import JohnstonChatApp
from widgets.chat_input import ChatInput
from widgets.chat_view import ChatView, UserMessage
from widgets.modal_screens import HelpScreen, ModelScreen, ProviderScreen, ResumeScreen, RewindScreen, TasksListScreen


async def test_chat_app_flow():
    app = JohnstonChatApp()
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
        assert len(user_msgs) == 2
        assert chat_input.text == "Third message"
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
        assert len(chat_view.get_user_messages()) == 0
        print("✓ /new command tests passed cleanly!")

        # 8. Проверяем /tasks
        chat_input.load_text("/tasks")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, TasksListScreen)
        print("✓ /tasks command tests passed cleanly!")

        # 9. Проверяем переключение режима по Shift+Tab
        assert getattr(app.agent, "mode", "build") == "build"
        await pilot.press("shift+tab")
        await pilot.pause(0.2)
        assert getattr(app.agent, "mode", "build") == "plan"
        await pilot.press("shift+tab")
        await pilot.pause(0.2)
        assert getattr(app.agent, "mode", "build") == "build"
        # 10. Проверяем авто-расширение высоты инпута при вставке многострочного текста
        chat_input.load_text("")
        chat_input.insert("line1\nline2\nline3\nline4")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 5

        # 11. Проверяем сворачивание длинного текста при paste (> 10 строк)
        chat_input.load_text("")
        from textual import events
        chat_input.on_paste(events.Paste("hello\n" * 15))
        await pilot.pause(0.1)
        assert "[Pasted text #1 +15 lines]" in chat_input.text
        assert chat_input.get_full_text() == "hello\n" * 15
        print("✓ Long paste collapse tests passed cleanly!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
