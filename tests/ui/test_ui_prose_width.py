"""Prose line length on wide terminals (P1-7).

At 200 columns a paragraph used to render ~180 characters wide — far outside
the comfortable 60-100 range. Prose blocks are now capped while code fences
keep the full width, because wrapping code hurts more than long lines do.
"""

import pytest
from textual.app import App, ComposeResult

from widgets.presentation.widgets.chat_markdown import PROSE_MAX_WIDTH, ProseMarkdown

SAMPLE = (
    ("word " * 60).strip()
    + "\n\n# Heading that is also extremely long "
    + "z" * 160
    + "\n\n```python\n# "
    + "x" * 180
    + "\nvalue = 1\n```\n\n- bullet item "
    + "q" * 140
    + "\n"
)


class ProseApp(App):
    def compose(self) -> ComposeResult:
        yield ProseMarkdown("", id="md")


def _blocks(md: ProseMarkdown) -> dict[str, object]:
    """Top-level markdown blocks keyed by their markdown-it token name."""
    out: dict[str, object] = {}
    for child in md.children:
        name = getattr(child, "name", "") or type(child).__name__
        out.setdefault(name, child)
    return out


@pytest.mark.asyncio
async def test_prose_is_capped_on_wide_terminals():
    async with ProseApp().run_test(size=(200, 40)) as pilot:
        md = pilot.app.query_one("#md", ProseMarkdown)
        await md.update(SAMPLE)
        await pilot.pause(0.4)
        blocks = _blocks(md)
        for name in ("paragraph_open", "heading_open", "bullet_list_open"):
            assert blocks[name].size.width == PROSE_MAX_WIDTH, (name, blocks[name].size.width)
        # Reading width now sits in the accepted band instead of ~180.
        assert blocks["paragraph_open"].size.width <= 120


@pytest.mark.asyncio
async def test_code_fences_keep_the_full_width():
    async with ProseApp().run_test(size=(200, 40)) as pilot:
        md = pilot.app.query_one("#md", ProseMarkdown)
        await md.update(SAMPLE)
        await pilot.pause(0.4)
        blocks = _blocks(md)
        assert blocks["fence"].size.width > PROSE_MAX_WIDTH
        assert blocks["fence"].size.width == md.size.width


@pytest.mark.asyncio
async def test_no_cap_on_narrow_terminals():
    async with ProseApp().run_test(size=(80, 40)) as pilot:
        md = pilot.app.query_one("#md", ProseMarkdown)
        await md.update(SAMPLE)
        await pilot.pause(0.4)
        blocks = _blocks(md)
        assert blocks["paragraph_open"].size.width == md.size.width
        assert blocks["paragraph_open"].styles.max_width is None


@pytest.mark.asyncio
async def test_cap_follows_resize():
    async with ProseApp().run_test(size=(200, 40)) as pilot:
        md = pilot.app.query_one("#md", ProseMarkdown)
        await md.update(SAMPLE)
        await pilot.pause(0.4)
        assert _blocks(md)["paragraph_open"].size.width == PROSE_MAX_WIDTH

        await pilot.resize_terminal(90, 40)
        await pilot.pause(0.4)
        paragraph = _blocks(md)["paragraph_open"]
        assert paragraph.styles.max_width is None
        assert paragraph.size.width == md.size.width

        await pilot.resize_terminal(200, 40)
        await pilot.pause(0.4)
        assert _blocks(md)["paragraph_open"].size.width == PROSE_MAX_WIDTH
