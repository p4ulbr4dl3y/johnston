import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, ThinkingWidget, ToolCallWidget, BotMessage
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        chat_input.load_text("выполни комплексную задачу")
        await pilot.press("enter")
        await pilot.pause(4.0)
        
        chat_view = app.query_one(ChatView)
        children = list(chat_view.children)
        
        thinking_count = len([c for c in children if isinstance(c, ThinkingWidget)])
        tool_count = len([c for c in children if isinstance(c, ToolCallWidget)])
        bot_text_count = len([c for c in children if isinstance(c, BotMessage)])
        
        print(f"✓ Interleaved flow counts: {thinking_count} Thinkings, {tool_count} Tools, {bot_text_count} BotTexts")
        assert thinking_count == 2
        assert tool_count == 3
        assert bot_text_count == 2
        print("✓ Complex interleaved execution pipeline succeeded!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
