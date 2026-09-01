"""Empty-chat welcome block: version, connection state and first-run tips (P2-10)."""

import pytest
from textual.screen import Screen
from textual.app import ComposeResult
from textual.widgets import Static

from app import JohnstonApp

from widgets.presentation.widgets.chat_welcome import WelcomeWidget


class WelcomeScreen(Screen):
    def compose(self) -> ComposeResult:
        yield WelcomeWidget()


def test_compose_yields_logo_tagline_and_tips():
    composed = list(WelcomeWidget().compose())
    ids = [widget.id for widget in composed]
    assert ids == ["welcome-logo", "welcome-tagline", "welcome-tips"]


def test_tagline_shows_version_and_connection_state():
    widget = WelcomeWidget()
    widget._connection_line = lambda: "Claude Sonnet 4.5 via Anthropic"  # type: ignore[method-assign]
    text = widget._tagline_text()
    assert "v0.28.0" in text or text.startswith("Claude")
    assert "Claude Sonnet 4.5 via Anthropic" in text


def test_tagline_is_truncated_on_narrow_terminals():
    widget = WelcomeWidget()
    widget._connection_line = lambda: "Claude Sonnet 4.5 via Anthropic"  # type: ignore[method-assign]
    text = widget._tagline_text(width=20)
    assert len(text) == 20
    assert text.endswith("…")


def test_tips_are_padded_to_a_common_width():
    widget = WelcomeWidget()
    lines = widget._tips_text(width=100).splitlines()
    assert len(lines) == len(widget.TIPS)
    assert len({len(line) for line in lines}) == 1
    # Keys start at the same column.
    assert {line.index(line.split()[0]) for line in lines} == {0}


@pytest.mark.asyncio
async def test_tips_are_hidden_when_the_logo_collapses():
    async with JohnstonApp().run_test(size=(100, 26)) as pilot:
        await pilot.pause(0.4)
        app = pilot.app
        app.push_screen(WelcomeScreen())
        await pilot.pause(0.5)
        welcome = app.query_one(WelcomeWidget)
        assert welcome.query_one("#welcome-tips", Static).display is True
        assert "johnston" not in str(welcome.query_one("#welcome-logo", Static).content)

        await pilot.resize_terminal(46, 26)
        await pilot.pause(0.5)
        assert welcome.query_one("#welcome-tips", Static).display is False
        assert "johnston" in str(welcome.query_one("#welcome-logo", Static).content)


@pytest.mark.asyncio
async def test_tagline_never_exceeds_the_available_width():
    async with JohnstonApp().run_test(size=(60, 26)) as pilot:
        await pilot.pause(0.4)
        app = pilot.app
        app.push_screen(WelcomeScreen())
        await pilot.pause(0.5)
        tagline = app.query_one("#welcome-tagline", Static)
        width = app.query_one(WelcomeWidget).size.width
        for line in str(tagline.content).splitlines():
            assert len(line) <= width, (line, width)
