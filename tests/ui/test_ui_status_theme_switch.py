"""Status dots must follow a live theme switch (P1-5 follow-up).

The dot colour is baked into the header markup, so `/theme` used to leave every
already rendered tool card on the previous theme's accent until something
forced a repaint.
"""

import re
from unittest.mock import patch

import pytest
from rich.text import Text

from app import JohnstonApp
from widgets.chat_toolcall import ToolCallWidget
from widgets.utils.theme_colors import status_color

HEX = re.compile(r"#(?:[0-9a-fA-F]{6})\b")


def _dot_color(widget: ToolCallWidget) -> str:
    """Colour the status dot is rendered with (the header's markup carries it)."""
    markup = str(widget.header_label.content)
    return HEX.search(markup).group(0)


@pytest.mark.asyncio
async def test_status_dot_follows_a_theme_switch():
    async with JohnstonApp().run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.5)
        app = pilot.app
        app.set_app_theme("zinc", persist=False)
        await pilot.pause(0.3)
        card = ToolCallWidget("read", "widgets/app/app.py", result_text="ok")
        app.screen.mount(card)
        await pilot.pause(0.4)

        dark = _dot_color(card)
        assert dark.lower() == status_color("success").lower()

        app.set_app_theme("github-light", persist=False)
        await pilot.pause(0.5)

        light = _dot_color(card)
        assert light.lower() != dark.lower(), "dot kept the previous theme's colour"
        assert light.lower() == status_color("success").lower()


@pytest.mark.asyncio
async def test_running_card_follows_a_theme_switch():
    async with JohnstonApp().run_test(size=(100, 30)) as pilot:
        await pilot.pause(0.5)
        app = pilot.app
        app.set_app_theme("zinc", persist=False)
        await pilot.pause(0.3)
        card = ToolCallWidget("shell", "ls -la")
        app.screen.mount(card)
        await pilot.pause(0.4)
        assert card.status == "running"
        before = _dot_color(card)

        app.set_app_theme("tokyo-night", persist=False)
        await pilot.pause(0.5)
        assert _dot_color(card).lower() == status_color("running").lower()
        assert _dot_color(card) != before


def test_render_header_is_called_on_theme_change():
    """`watch(app, "theme")` must be wired — the wiring is what repaints."""
    with patch.object(ToolCallWidget, "render_header") as render:
        async def scenario():
            async with JohnstonApp().run_test(size=(100, 30)) as pilot:
                await pilot.pause(0.4)
                pilot.app.set_app_theme("zinc", persist=False)
                await pilot.pause(0.3)
                card = ToolCallWidget("read", "a.py", result_text="ok")
                pilot.app.screen.mount(card)
                await pilot.pause(0.3)
                render.reset_mock()
                pilot.app.set_app_theme("github-light", persist=False)
                await pilot.pause(0.4)

        import asyncio

        asyncio.run(scenario())
        assert render.called, "theme change did not re-render the tool header"


def test_header_markup_is_parseable():
    card = ToolCallWidget("read", "a.py", result_text="ok")
    markup = str(card.header_label.content) if card.header_label.content else ""
    # Sanity: the dot markup used by the tests above is what render_header builds.
    assert markup == "" or isinstance(Text.from_markup(markup), Text)
