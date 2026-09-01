"""Markdown render nits: task lists, block quotes, model ids (P2-12)."""

import re

import pytest
from textual.screen import Screen
from textual.app import ComposeResult
from app import JohnstonApp

from widgets.presentation.screens.model import ModelScreen
from widgets.presentation.widgets.chat_markdown import ProseMarkdown
from widgets.utils.row_format import display_width, format_badge_row


# --- model ids -----------------------------------------------------------
def test_model_id_is_shown_when_the_name_hides_it():
    assert ModelScreen._model_id_hint("Claude Sonnet 4 5", "claude-sonnet-4-5-20250929") == "claude-sonnet-4-5-20250929"


def test_model_id_is_hidden_when_the_name_already_says_it():
    assert ModelScreen._model_id_hint("GPT 4o", "gpt-4o") == ""
    assert ModelScreen._model_id_hint("Claude Sonnet 4 5", "claude-sonnet-4-5") == ""
    assert ModelScreen._model_id_hint("Gemini 2.5 Pro", "gemini-2.5-pro") == ""
    assert ModelScreen._model_id_hint("", "gpt-4o") == ""
    assert ModelScreen._model_id_hint("Claude", "") == ""


def test_model_id_is_shown_when_the_name_is_ambiguous_about_the_id():
    # `4.5` vs `4-5` — two different ids, one humanized name.
    assert ModelScreen._model_id_hint("Claude Sonnet 4.5", "claude-sonnet-4-5") == "claude-sonnet-4-5"


def test_badge_row_with_hint_keeps_the_target_width():
    row = format_badge_row("Claude Sonnet 4 5", "vision", target_width=60, hint="claude-sonnet-4-5-20250929")
    assert display_width(row) == 60
    assert "claude-sonnet-4-5-20250929" in row


def test_badge_row_truncates_an_over_long_hint():
    row = format_badge_row("Model", "vision", target_width=40, hint="x" * 80)
    assert display_width(row) <= 40
    assert "…" in row or "..." in row


def test_badge_row_without_hint_is_unchanged():
    assert format_badge_row("plain [title]", "") == "plain \\[title]"
    assert "hint" not in format_badge_row("title", "badge", target_width=60)


# --- task lists ----------------------------------------------------------
class MarkdownScreen(Screen):
    def __init__(self, markdown: str):
        super().__init__()
        self._markdown = markdown

    def compose(self) -> ComposeResult:
        yield ProseMarkdown("", id="md")

    def on_mount(self) -> None:
        self.call_after_refresh(self._load)

    async def _load(self) -> None:
        md = self.query_one("#md", ProseMarkdown)
        await md.update(self._markdown)
        md.post_update()


@pytest.mark.asyncio
async def test_task_items_drop_the_duplicate_marker():
    md_text = "- [x] done item\n- [ ] open item\n- plain bullet\n"
    async with JohnstonApp().run_test(size=(90, 30)) as pilot:
        await pilot.pause(0.4)
        app = pilot.app
        app.push_screen(MarkdownScreen(md_text))
        await pilot.pause(0.9)
        md = app.screen.query_one("#md", ProseMarkdown)
        bullets = list(md.query("MarkdownBullet"))
        symbols = [str(bullet.symbol) for bullet in bullets]
        assert symbols == ["☑ ", "☐ ", "• "], symbols

        texts = [str(p.content).strip() for p in md.query("MarkdownParagraph")]
        assert "done item" in texts
        assert not any(text.startswith("[x]") or text.startswith("[ ]") for text in texts)


@pytest.mark.asyncio
async def test_task_item_keeps_inline_styles():
    md_text = "- [ ] task with **bold** text\n"
    async with JohnstonApp().run_test(size=(90, 30)) as pilot:
        await pilot.pause(0.4)
        app = pilot.app
        app.push_screen(MarkdownScreen(md_text))
        await pilot.pause(0.9)
        md = app.screen.query_one("#md", ProseMarkdown)
        paragraph = list(md.query("MarkdownParagraph"))[0]
        content = paragraph.content
        # The marker is gone, the styled word survived (style spans kept).
        assert content.plain.strip() == "task with bold text"
        assert content.spans, content.spans


@pytest.mark.asyncio
async def test_plain_lists_are_untouched():
    md_text = "- one\n- two\n"
    async with JohnstonApp().run_test(size=(90, 30)) as pilot:
        await pilot.pause(0.4)
        app = pilot.app
        app.push_screen(MarkdownScreen(md_text))
        await pilot.pause(0.9)
        md = app.screen.query_one("#md", ProseMarkdown)
        assert [str(b.symbol) for b in md.query("MarkdownBullet")] == ["• ", "• "]


def test_block_quote_has_a_bar():
    """`> quote` used to be indentation-only (P2-12)."""
    css = (JohnstonApp.CSS_PATH and open(JohnstonApp.CSS_PATH).read()) or ""
    block = re.search(r"MarkdownBlockQuote \{[^}]*\}", css)
    assert block is not None
    assert re.search(r"border-left:\s*(?!none)", block.group(0)), block.group(0)


def test_block_quote_bar_uses_a_token_not_a_literal_colour():
    css = open(JohnstonApp.CSS_PATH).read()
    block = re.search(r"MarkdownBlockQuote \{[^}]*\}", css)
    border = re.search(r"border-left:[^;]*;", block.group(0))
    assert "$" in border.group(0), border.group(0)
