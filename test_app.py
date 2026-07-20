import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, ToolCallWidget
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        chat_input.load_text("создай новый модуль")
        await pilot.press("enter")
        await pilot.pause(2.0)
        
        chat_view = app.query_one(ChatView)
        tool_widgets = [c for c in chat_view.children if isinstance(c, ToolCallWidget)]
        assert len(tool_widgets) > 0
        
        first_tool = tool_widgets[0]
        assert first_tool.tool_type == "Create"
        print(f"✓ Distinct ToolCallWidget rendered cleanly: {first_tool.tool_type} -> {first_tool.target}")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
