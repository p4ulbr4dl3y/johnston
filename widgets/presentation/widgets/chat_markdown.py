import asyncio
import inspect
import re
import warnings
from typing import Any

from markdown_it import MarkdownIt
from pygments.lexers import get_lexer_by_name
from pygments.token import Token
from rich.segment import Segment
from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.color import Color
from textual.containers import Horizontal, Vertical
from textual.highlight import HighlightTheme
from textual.style import Style
from textual.widgets import Button, Label, Markdown, Static
from textual.widgets._markdown import (
    MarkdownBlock,
    MarkdownFence,
    MarkdownTable,
    MarkdownTableCellContents,
    MarkdownTableContent,
)

warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*await_update.*")


class TransparentSyntax(Syntax):
    """Rich Syntax renderable with transparent token background to allow TCSS styling."""

    def _get_syntax(self, console: Any, options: Any):
        for segment in super()._get_syntax(console, options):
            if segment.style and segment.style.bgcolor:
                style = segment.style.copy()
                style._bgcolor = None
                yield Segment(segment.text, style, segment.control)
            else:
                yield segment


CODE_THEME = "one-dark"

_RE_ITALIC_COLON = re.compile(r"(?<!\*)\*([^*:]+):\*(?!\*)")
_RE_DOUBLE_BULLET = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+[-*]\s+")
_RE_BLOCKQUOTE_BULLET = re.compile(r"^(\s*>\s*)[-*]\s+")
_RE_LIST_PREFIX = re.compile(r"^(\s*(?:[-*]|\d+\.))\s+(.*)")
_RE_EXCESS_INDENT = re.compile(r"^(\s+)([-*]|\d+\.)\s+(.*)")


def to_snake_case(name: str) -> str:
    if not name:
        return ""
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(name))
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    s = re.sub(r"[-\s]+", "_", s)
    return s.lower()


class CustomMarkdownTableContent(MarkdownTableContent):
    """Custom Markdown table content without cell hover tooltips."""

    def compose(self) -> ComposeResult:
        for header in self.headers:
            yield MarkdownTableCellContents(header, classes="header")
        for row_index, row in enumerate(self.rows, 1):
            for cell_index, cell in enumerate(row, 1):
                yield MarkdownTableCellContents(
                    cell,
                    classes=f"row{row_index} cell",
                    name=f"cell{row_index}.{cell_index}",
                )
            self.last_row = row_index

    async def _update_rows(self, updated_rows: list[Any]) -> None:
        self.styles.grid_size_columns = len(self.headers)
        await self.query_children(f".cell.row{self.last_row}").remove()
        new_cells: list[Static] = []
        for row_index, row in enumerate(updated_rows, self.last_row):
            for cell in row:
                new_cells.append(
                    Static(
                        cell,
                        markup=False,
                        classes=f"row{row_index} cell",
                    )
                )
            self.last_row = row_index
        await self.mount_all(new_cells)

    def on_mount(self) -> None:
        self.styles.grid_size_columns = len(self.headers)
        for child in self.query("*"):
            child.tooltip = None


class CustomMarkdownTable(MarkdownTable):
    """Custom Markdown table block using CustomMarkdownTableContent."""

    def compose(self) -> ComposeResult:
        headers, rows = self._get_headers_and_rows()
        self._headers = headers
        self._rows = rows
        yield CustomMarkdownTableContent(headers, rows)


class CustomMarkdownFence(MarkdownFence):
    """Markdown code block with a header line and Copy button."""

    DEFAULT_CSS = """
    CustomMarkdownFence {
        width: 100%;
        max-width: 100%;
        height: auto;
        overflow: hidden hidden;
    }
    """

    @property
    def allow_horizontal_scroll(self) -> bool:
        return False

    def compose(self) -> ComposeResult:
        lang_str = self.lexer.strip() if self.lexer else "code"
        copy_btn = Button("copy", classes="fence-copy-btn")
        copy_btn.can_focus = False
        with Horizontal(classes="fence-header"):
            yield Label(lang_str, classes="fence-lang")
            yield copy_btn

        clean_lang = (self.lexer or "").strip().lower()
        if clean_lang in ("text", "txt", "plaintext", "none", "raw", "output", "code", "log", ""):
            target_lexer = "text"
        else:
            try:
                get_lexer_by_name(clean_lang)
                target_lexer = clean_lang
            except Exception:
                target_lexer = "text"

        theme = getattr(self, "theme", None) or getattr(getattr(self, "markdown", None), "theme", None) or CODE_THEME
        code_content = TransparentSyntax(
            self.code, lexer=target_lexer, theme=theme, word_wrap=False, background_color="default"
        )
        if hasattr(code_content, "code") and isinstance(getattr(code_content, "code", None), str):
            code_content.code = code_content.code.rstrip("\r\n")
        with Vertical(classes="fence-scroll-box"):
            yield Label(code_content, id="code-content", expand=True)

    def set_content(self, content: Any) -> None:
        self._content = content
        if hasattr(content, "code") and isinstance(getattr(content, "code", None), str):
            content.code = content.code.rstrip("\r\n")
        if hasattr(content, "word_wrap"):
            content.word_wrap = False
        try:
            self.query_one("#code-content", Label).update(content)
        except Exception:
            pass

    def render(self):
        return ""

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if "fence-copy-btn" in event.button.classes:
            try:
                app = self.app
                if hasattr(app, "copy_to_clipboard"):
                    app.copy_to_clipboard(self.code)
            except Exception:
                pass
            event.stop()


_patched = False


def _new_markdown_block_get_style(self, style):
    if style == ".code_inline":
        return Style(
            background=Color(39, 39, 42),
            foreground=Color(255, 255, 255),
        )
    return _old_markdown_block_get_style(self, style)


def _custom_markdown_parser_factory() -> MarkdownIt:
    md = MarkdownIt("gfm-like", {"linkify": False})
    md.validateLink = lambda url: True
    return md


_old_markdown_init = Markdown.__init__


def _new_markdown_init(self, *args, **kwargs):
    if "parser_factory" not in kwargs or kwargs["parser_factory"] is None:
        kwargs["parser_factory"] = _custom_markdown_parser_factory
    # Reference the live BLOCKS mapping so any Markdown widget created before the
    # global patch still picks up the patched table/fence block classes.
    self.BLOCKS = Markdown.BLOCKS
    _old_markdown_init(self, *args, **kwargs)


_old_markdown_block_get_style = MarkdownBlock._get_style


JOHNSTON_RICH_MARKDOWN_STYLES = {
    "markdown.paragraph": "#f4f4f5",
    "markdown.text": "#f4f4f5",
    "markdown.h1": "bold #ffffff",
    "markdown.h1.border": "none",
    "markdown.h2": "bold #ffffff",
    "markdown.h2.border": "none",
    "markdown.h3": "bold #ffffff",
    "markdown.h4": "bold #ffffff",
    "markdown.h5": "bold #ffffff",
    "markdown.h6": "bold #ffffff",
    "markdown.code": "#ffffff on #27272a",
    "markdown.code_block": "#f4f4f5 on #27272a",
    "markdown.block_quote": "#e4e4e7 on #18181b",
    "markdown.list": "#a1a1aa",
    "markdown.item": "#f4f4f5",
    "markdown.item.bullet": "bold #a1a1aa",
    "markdown.item.number": "bold #a1a1aa",
    "markdown.table.border": "#27272a",
    "markdown.table.header": "bold #ffffff",
    "markdown.hr": "#27272a",
    "markdown.link": "underline #60a5fa",
    "markdown.link_url": "underline #60a5fa",
    "markdown.em": "italic #f4f4f5",
    "markdown.strong": "bold #ffffff",
    "markdown.s": "strike #71717a",
}


def _apply_chat_markdown_patches() -> None:
    """Applies Textual Markdown monkey-patches (custom theme, blocks, renderers).

    Kept behind an idempotent flag so importing this module has no side-effects;
    the first widget that needs chat markdown rendering triggers it exactly once.
    """
    global _patched
    if _patched:
        return
    _patched = True

    HighlightTheme.STYLES[Token.Name.Function] = "$text-warning"
    HighlightTheme.STYLES[Token.Name.Function.Magic] = "$text-warning"
    HighlightTheme.STYLES[Token.Generic.Heading] = "bold #61afef"
    HighlightTheme.STYLES[Token.Generic.Subheading] = "bold #61afef"

    from rich.default_styles import DEFAULT_STYLES
    from rich.markdown import Heading
    from rich.style import Style as RichStyle
    from rich.theme import Theme
    from textual._context import active_app
    from textual.app import App

    Heading.LEVEL_ALIGN = {"h1": "left", "h2": "left", "h3": "left", "h4": "left", "h5": "left", "h6": "left"}
    for k, v in JOHNSTON_RICH_MARKDOWN_STYLES.items():
        DEFAULT_STYLES[k] = RichStyle.parse(v)

    theme = Theme(JOHNSTON_RICH_MARKDOWN_STYLES)
    _old_app_init = App.__init__

    def _new_app_init(self, *args, **kwargs):
        _old_app_init(self, *args, **kwargs)
        if getattr(self, "console", None):
            self.console.push_theme(theme)

    App.__init__ = _new_app_init

    try:
        current = active_app.get()
        if current and getattr(current, "console", None):
            current.console.push_theme(theme)
    except Exception:
        pass

    from rich.markdown import Markdown as RichMarkdown
    from rich.markdown import TextElement

    class CustomRichCodeBlock(TextElement):
        """Rich Markdown CodeBlock matching Johnston theme and #18181b background."""

        style_name = "markdown.code_block"

        @classmethod
        def create(cls, markdown: Any, token: Any) -> "CustomRichCodeBlock":
            node_info = token.info or ""
            lexer_name = node_info.partition(" ")[0]
            return cls(lexer_name or "text", markdown.code_theme)

        def __init__(self, lexer_name: str, theme: str) -> None:
            self.lexer_name = lexer_name
            self.theme = theme

        def __rich_console__(self, console: Any, options: Any) -> Any:
            code = str(self.text).rstrip()
            syntax = Syntax(
                code,
                self.lexer_name,
                theme=self.theme,
                word_wrap=True,
                background_color="#18181b",
                padding=(0, 1),
            )
            yield syntax

    from rich import box
    from rich.markdown import TableElement
    from rich.table import Table

    class CustomRichTableElement(TableElement):
        """Full-width Markdown table with preserved column justification and border styling."""

        def __rich_console__(self, console: Any, options: Any) -> Any:
            table = Table(
                box=box.SIMPLE,
                pad_edge=False,
                style="markdown.table.border",
                show_edge=True,
                collapse_padding=True,
                expand=True,
            )

            if self.header is not None and self.header.row is not None:
                for column in self.header.row.cells:
                    heading = column.content.copy()
                    heading.stylize("markdown.table.header")
                    table.add_column(heading, justify=getattr(column, "justify", "default"))

            if self.body is not None:
                for row in self.body.rows:
                    row_content = [element.content for element in row.cells]
                    table.add_row(*row_content)

            yield table

    from rich.markdown import BlockQuote

    class CustomRichBlockQuote(BlockQuote):
        """Rich Markdown BlockQuote matching Johnston card theme #18181b and padding (0, 1)."""

        def __rich_console__(self, console: Any, options: Any) -> Any:
            render_options = options.update(width=options.max_width)
            style = RichStyle.parse("on #18181b #e4e4e7")
            lines = console.render_lines(self.elements, render_options, style=style)
            for line in lines:
                yield from line
                yield Segment.line()

    RichMarkdown.elements["fence"] = CustomRichCodeBlock
    RichMarkdown.elements["code_block"] = CustomRichCodeBlock
    RichMarkdown.elements["table_open"] = CustomRichTableElement
    RichMarkdown.elements["blockquote_open"] = CustomRichBlockQuote

    Markdown.BLOCKS["fence"] = CustomMarkdownFence
    Markdown.BLOCKS["code_block"] = CustomMarkdownFence
    Markdown.BLOCKS["table"] = CustomMarkdownTable

    Markdown.__init__ = _new_markdown_init

    MarkdownBlock._get_style = _new_markdown_block_get_style


def _handle_markdown_task_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.exception()
    except (asyncio.CancelledError, Exception):
        pass


def clean_markdown_for_rendering(text: str) -> str:
    """Preprocesses LLM markdown text to fix common rendering glitches in Textual:
    - Double bullet markers (e.g. '   * * item' or ' - * item')
    - Blockquote + bullet markers (e.g. ' > * item')
    - Word-ending italic colon syntax ('*Text:*' -> '**Text:**')
    - Unpaired single leading asterisks before words ('*Wait, ...' -> 'Wait, ...')
    - Excessive list indentation capped to 8 spaces
    - Unclosed code blocks during streaming
    """
    if not text:
        return ""

    text = text.replace("\r\n", "\n").expandtabs(4)
    lines = text.splitlines()

    in_code = False
    blank_run = 0
    cleaned = []
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            cleaned.append(line)
            continue

        if in_code:
            cleaned.append(line)
            continue

        line = _RE_ITALIC_COLON.sub(r"**\1:**", line)
        line = _RE_DOUBLE_BULLET.sub(r"\1* ", line)
        line = _RE_BLOCKQUOTE_BULLET.sub(r"\1", line)

        m_list = _RE_LIST_PREFIX.match(line)
        if m_list:
            prefix, body = m_list.groups()
            line = f"{prefix} {body}"

        m = _RE_EXCESS_INDENT.match(line)
        if m:
            indent, marker, content = m.groups()
            new_indent_len = min(len(indent), 8)
            line = (" " * new_indent_len) + marker + " " + content

        if not line.strip():
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0

        cleaned.append(line)

    if in_code:
        cleaned.append("```")

    result = "\n".join(cleaned)
    return result.rstrip("\n")


def safe_update_markdown(widget: Markdown, content: str, on_done: Any = None) -> None:
    """Updates Markdown widget safely without creating unawaited coroutines when unattached."""
    if not getattr(widget, "is_attached", True):
        return
    cleaned = clean_markdown_for_rendering(content)
    try:
        res = widget.update(cleaned)
        if inspect.isawaitable(res):
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    task = loop.create_task(res)

                    def _done_cb(t: asyncio.Task) -> None:
                        _handle_markdown_task_done(t)
                        if on_done:
                            on_done()

                    task.add_done_callback(_done_cb)
                    return
            except RuntimeError:
                # No running loop: close the created coroutine so it isn't left
                # un-awaited (avoids a "coroutine never awaited" RuntimeWarning).
                try:
                    res.close()
                except Exception:
                    pass
        if on_done:
            on_done()
    except Exception:
        if on_done:
            on_done()


TOKEN_COLORS = {
    Token.Keyword: "#c678dd",
    Token.Keyword.Namespace: "#c678dd",
    Token.Keyword.Type: "#e5c07b",
    Token.Keyword.Declaration: "#c678dd",
    Token.Name.Function: "#61afef",
    Token.Name.Class: "#e5c07b",
    Token.Name.Tag: "#e06c75",
    Token.Name.Attribute: "#d19a66",
    Token.Name.Property: "#e06c75",
    Token.Name.Variable: "#e06c75",
    Token.Name.Constant: "#d19a66",
    Token.Name.Builtin: "#e5c07b",
    Token.Name.Label: "#61afef",
    Token.Name.Entity: "#56b6c2",
    Token.Name.Decorator: "#61afef",
    Token.Name.Other: "#e06c75",
    Token.Name: "#e06c75",
    Token.String: "#98c379",
    Token.String.Doc: "#98c379",
    Token.Number: "#d19a66",
    Token.Number.Hex: "#d19a66",
    Token.Literal: "#d19a66",
    Token.Operator: "#56b6c2",
    Token.Punctuation: "#abb2bf",
    Token.Comment: "#7f848e italic",
}
