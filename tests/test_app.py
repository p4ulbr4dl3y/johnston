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

        # 1. Test /help
        chat_input.load_text("/help")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, HelpScreen)

        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, HelpScreen)
        print("✓ HelpScreen tests passed")

        # 2. User messages
        for msg in ["First message", "Second message", "Third message"]:
            chat_input.load_text(msg)
            await pilot.press("enter")
            await pilot.pause(0.5)

        # 3. Test /rewind
        chat_input.load_text("/rewind")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, RewindScreen)

        # Select first element with Enter
        await pilot.press("enter")
        await pilot.pause(0.5)

        chat_view = app.query_one(ChatView)
        user_msgs = [c for c in chat_view.children if isinstance(c, UserMessage)]
        assert len(user_msgs) == 2
        assert chat_input.text == "Third message"
        print("✓ RewindScreen tests passed cleanly!")

        # 4. Test /resume
        chat_input.load_text("/resume")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ResumeScreen)

        await pilot.press("escape")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, ResumeScreen)
        print("✓ ResumeScreen tests passed cleanly!")

        # 5. Test /provider
        chat_input.load_text("/provider")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert isinstance(app.screen, ProviderScreen)
        await pilot.press("escape")
        await pilot.pause(0.2)
        print("✓ ProviderScreen tests passed cleanly!")

        # 6. Test /models and model search
        chat_input.load_text("/models")
        await pilot.press("enter")
        await pilot.pause(0.5)
        assert isinstance(app.screen, ModelScreen)
        await pilot.press("d", "e", "e", "p", "space", "f", "l", "a", "s", "h")
        await pilot.pause(0.2)
        assert len(app.screen.filtered_items) > 0
        await pilot.press("escape")
        await pilot.pause(0.2)
        print("✓ ModelScreen tests passed cleanly!")

        # 7. Test /new
        chat_input.load_text("/new")
        await pilot.press("enter")
        await pilot.pause(0.5)
        chat_view = app.query_one(ChatView)
        assert len(chat_view.get_user_messages()) == 0
        print("✓ /new command tests passed cleanly!")

        # 8. Test /tasks
        chat_input.load_text("/tasks")
        await pilot.press("enter")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, TasksListScreen)
        print("✓ /tasks command tests passed cleanly!")

        # 9. Test mode toggle via Shift+Tab
        assert getattr(app.agent, "mode", "action") == "action"
        await pilot.press("shift+tab")
        await pilot.pause(0.2)
        assert getattr(app.agent, "mode", "action") == "explore"
        await pilot.press("shift+tab")
        await pilot.pause(0.2)
        assert getattr(app.agent, "mode", "action") == "action"
        # 10. Test input height auto-expansion on multiline text insert
        chat_input.load_text("")
        chat_input.insert("line1\nline2\nline3\nline4")
        await pilot.pause(0.1)
        assert chat_input.styles.height.value == 5

        # 11. Test long text folding on paste (> 10 lines)
        chat_input.load_text("")
        from textual import events
        chat_input.on_paste(events.Paste("hello\n" * 15))
        await pilot.pause(0.1)
        assert "[Pasted text #1 +15 lines]" in chat_input.text
        assert chat_input.get_full_text() == "hello\n" * 15
        # 12. Test atomic deletion of paste block via Backspace
        chat_input.move_cursor((0, len(chat_input.text)))
        await pilot.press("backspace")
        await pilot.pause(0.1)
        assert chat_input.text == ""
        assert chat_input.pasted_texts == {}
        print("✓ Atomic tag deletion tests passed cleanly!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
