import asyncio
from app import TUIChatApp
from widgets.chat_view import ChatView, ThinkingWidget, ToolCallWidget
from widgets.chat_input import ChatInput

async def test_chat_app_flow():
    app = TUIChatApp()
    async with app.run_test() as pilot:
        chat_input = app.query_one("#message-input", ChatInput)
        chat_input.focus()
        
        chat_input.load_text("подумай над архитектурой")
        await pilot.press("enter")
        await pilot.pause(0.5)
        
        chat_view = app.query_one(ChatView)
        thinking_widgets = [c for c in chat_view.children if isinstance(c, ThinkingWidget)]
        assert len(thinking_widgets) == 1
        
        widget = thinking_widgets[0]
        # В процессе думания статус active
        assert widget.is_thinking
        print("✓ Thinking... spinner active during processing")
        
        # Даем время завершиться
        await pilot.pause(2.5)
        assert not widget.is_thinking
        assert widget.duration_seconds > 0
        print(f"✓ Thinking finished cleanly: Thought for {widget.duration_seconds:.1f} sec")
        
        # Переключаем разворачивание
        widget.render_expanded()
        assert widget.is_expanded
        print("✓ Expanded thought details cleanly!")

if __name__ == "__main__":
    asyncio.run(test_chat_app_flow())
