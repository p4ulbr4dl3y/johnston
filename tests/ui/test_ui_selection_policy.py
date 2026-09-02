"""Mouse selection policy (P1-8).

`ALLOW_SELECT = False` was set on 22 classes, so the only way to get text out
of the app was the copy button on a code fence or `/copy`. Message prose was
already selectable; tool output and diff content were not.
"""

import pytest

from widgets.chat_toolcall import ToolCallWidget
from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter
from widgets.status_footer import StatusFooter


def test_tool_output_is_selectable():
    assert ToolCallWidget.ALLOW_SELECT is True


@pytest.mark.asyncio
async def test_tool_card_children_are_selectable():
    """`widgets/patch.py` walks the ancestor chain, so flipping the widget is
    enough — verified here through the runtime property, not the class flag."""
    from app import JohnstonApp
    from widgets.presentation.widgets.chat_container import ChatView

    app = JohnstonApp()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one(ChatView)
        card = ToolCallWidget("shell", "echo hi")
        await chat.mount(card)
        await pilot.pause(0.2)
        assert card.allow_select
        for child in card.query("*"):
            assert child.allow_select, f"{child} inherits ALLOW_SELECT=False from an ancestor"


@pytest.mark.asyncio
async def test_message_prose_stays_selectable():
    from app import JohnstonApp
    from widgets.presentation.widgets.chat_container import ChatView

    app = JohnstonApp()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause(0.3)
        chat = app.query_one(ChatView)
        message = await chat.add_bot_message()
        await message.set_final_content("some **prose** to select")
        await pilot.pause(0.2)
        assert message.allow_select
        assert all(child.allow_select for child in message.query("*"))


def test_status_chrome_is_not_selectable():
    """Dragging over a status bar must not select it."""
    assert StatusFooter.ALLOW_SELECT is False
    assert SubagentStatusFooter.ALLOW_SELECT is False


@pytest.mark.asyncio
async def test_diff_content_is_selectable_but_its_chrome_is_not():
    from app import JohnstonApp
    from widgets.presentation.screens.diff import DiffScreen

    app = JohnstonApp()
    async with app.run_test(size=(110, 30)) as pilot:
        await pilot.pause(0.3)
        screen = DiffScreen([("widgets/status_footer.py", "diff --git a/x b/x", 12, 4)])
        app.push_screen(screen)
        await pilot.pause(0.5)

        assert screen.query_one("#diff-content-view").allow_select
        assert screen.query_one("#diff-scroll-box").allow_select
        # Clicking a file still selects the file, not the text under the cursor.
        assert not screen.query_one("#diff-file-list").allow_select
        assert not screen.query_one("#diff-search-input").allow_select
        assert not screen.query_one("#diff-header").allow_select
