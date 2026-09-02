import asyncio
import inspect
import re
import threading
from collections import OrderedDict
from typing import Any

from markdown_it import MarkdownIt
from pygments.lexers import get_lexer_by_name
from pygments.style import Style as PygmentsStyle
from pygments.styles import get_style_by_name
from pygments.token import Token
from rich.segment import Segment
from rich.syntax import PygmentsSyntaxTheme, Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
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

from core.domain.defaults.themes import ZINC_DARK


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
_CURRENT_SYNTAX_THEME: PygmentsSyntaxTheme | str | None = None


def get_current_syntax_theme(dark: bool = True) -> PygmentsSyntaxTheme | str:
    """Return the active dynamic PygmentsSyntaxTheme or fallback to dark/light base theme."""
    global _CURRENT_SYNTAX_THEME
    if _CURRENT_SYNTAX_THEME is not None:
        return _CURRENT_SYNTAX_THEME
    return CODE_THEME if dark else "github-light"

# Highlight result cache. Fences get re-mounted whenever a Markdown document is
# rebuilt (final render after streaming, session load, theme switch), and
# pygments highlighting is the dominant cost of that pass (~10ms per large
# block, synchronously on the UI thread inside compose()). The pre-warmed
# Content lets compose() mount instantly; the cache also survives stream →
# final re-renders of the same code. Keyed by the code string, lexer name,
# syntax-theme object (identity) and dark flag, so entries can never outlive
# the theme they were rendered for. LRU-bounded + lock-guarded (pre-warm runs
# in worker threads while compose() may read from the UI thread).
_HIGHLIGHT_CACHE_MAX = 256
_highlight_cache: "OrderedDict[tuple, Content]" = OrderedDict()
_highlight_cache_lock = threading.Lock()

# Shared truecolor console for syntax rendering: creating a fresh Console per
# highlight call is measurable overhead when a message mounts many fences.
_HIGHLIGHT_CONSOLE: Any = None


def _get_highlight_console() -> Any:
    global _HIGHLIGHT_CONSOLE
    if _HIGHLIGHT_CONSOLE is None:
        from rich.console import Console

        _HIGHLIGHT_CONSOLE = Console(force_terminal=True, color_system="truecolor")
    return _HIGHLIGHT_CONSOLE


def resolve_highlight_lexer(language: str | None) -> str:
    """Map a fence info string to a pygments lexer name ("text" when unknown)."""
    clean_lang = (language or "").strip().lower()
    if clean_lang in ("text", "txt", "plaintext", "none", "raw", "output", "code", "log", ""):
        return "text"
    try:
        get_lexer_by_name(clean_lang)
        return clean_lang
    except Exception:
        return "text"


def prewarm_fences_from_markdown(markdown: str, dark: bool = True) -> int:
    """Highlight code fences from a markdown document off the UI thread.

    Scans for fenced blocks and fills the highlight cache so the subsequent
    Markdown mount composes instantly. Called via asyncio.to_thread from
    BotMessage._render_markdown; returns the number of blocks highlighted.
    Block detection mirrors clean_markdown_for_rendering (fence lines may be
    indented); over-matching indented-code blocks only wastes a cache entry.
    """
    count = 0
    lines = markdown.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        if not lines[i].strip().startswith("```"):
            i += 1
            continue
        lang = lines[i].strip()[3:].strip()
        i += 1
        code_lines: list[str] = []
        closed = False
        while i < n:
            if lines[i].strip().startswith("```"):
                closed = True
                i += 1
                break
            code_lines.append(lines[i])
            i += 1
        # Unclosed trailing fence: the parser autocloses it at EOF, but
        # clean_markdown_for_rendering appends the closer first — either way
        # only pre-warm blocks with actual content.
        if closed and code_lines:
            try:
                CustomMarkdownFence.highlight("\n".join(code_lines), lang, dark=dark)
                count += 1
            except Exception:
                pass
    return count


def prepare_markdown_text(text: str, dark: bool = True) -> str:
    """clean_markdown_for_rendering + fence pre-highlight in one worker hop.

    Runs inside asyncio.to_thread from BotMessage._render_markdown so the
    subsequent Markdown mount never blocks the UI loop on pygments.
    """
    cleaned = clean_markdown_for_rendering(text)
    if "```" in cleaned:
        prewarm_fences_from_markdown(cleaned, dark=dark)
    return cleaned


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
    CustomMarkdownFence .fence-header {
        height: 1;
        width: 100%;
        max-width: 100%;
    }
    CustomMarkdownFence .fence-scroll-box {
        height: auto;
        width: 100%;
    }
    CustomMarkdownFence #code-content {
        height: auto;
        width: 100%;
    }
    """

    @property
    def allow_horizontal_scroll(self) -> bool:
        return False

    @classmethod
    def highlight(
        cls, code: str, language: str | None = None, ansi: bool = False, dark: bool = True
    ) -> Content:
        code_str = code if isinstance(code, str) else str(code)
        clean_code = code_str.rstrip("\r\n")
        target_lexer = resolve_highlight_lexer(language)

        if target_lexer == "text":
            return Content.from_rich_text(Text(clean_code))

        syntax_theme = _CURRENT_SYNTAX_THEME or (CODE_THEME if dark else "github-light")
        key = (clean_code, target_lexer, syntax_theme, dark)
        with _highlight_cache_lock:
            cached = _highlight_cache.get(key)
            if cached is not None:
                _highlight_cache.move_to_end(key)
                return cached

        try:
            syntax = Syntax(clean_code, target_lexer, theme=syntax_theme, word_wrap=True)
            console = _get_highlight_console()
            rich_text = Text()
            for segment in syntax._get_syntax(console, console.options):
                style = segment.style.copy() if segment.style else None
                if style and style.bgcolor:
                    style._bgcolor = None
                rich_text.append(segment.text, style=style)
            rich_text.rstrip()
            content = Content.from_rich_text(rich_text)
        except Exception:
            content = MarkdownFence.highlight(clean_code, language=target_lexer, ansi=ansi, dark=dark)

        with _highlight_cache_lock:
            _highlight_cache[key] = content
            while len(_highlight_cache) > _HIGHLIGHT_CACHE_MAX:
                _highlight_cache.popitem(last=False)
        return content

    def compose(self) -> ComposeResult:
        lang_str = self.lexer.strip() if self.lexer else "text"
        lang_label = Label(lang_str, classes="fence-lang")
        lang_label.ALLOW_SELECT = False
        copy_btn = Button("copy", classes="fence-copy-btn")
        copy_btn.can_focus = False
        copy_btn.ALLOW_SELECT = False
        header = Horizontal(classes="fence-header")
        header.ALLOW_SELECT = False
        with header:
            yield lang_label
            yield copy_btn

        from widgets.app.theme_manager import theme_manager

        app = getattr(self, "app", None)
        is_ansi = getattr(app, "native_ansi_color", False) if app else True
        curr = getattr(app, "current_theme", None) or theme_manager.current_theme
        is_dark = getattr(curr, "dark", True)
        code_content = self.highlight(self.code, self.lexer, ansi=is_ansi, dark=is_dark)
        with Vertical(classes="fence-scroll-box"):
            yield Label(code_content, id="code-content", expand=True)

    def notify_style_update(self) -> None:
        """Update highlight theme when App theme changes."""
        from widgets.app.theme_manager import theme_manager

        app = getattr(self, "app", None)
        is_ansi = getattr(app, "native_ansi_color", False) if app else True
        curr = getattr(app, "current_theme", None) or theme_manager.current_theme
        is_dark = getattr(curr, "dark", True)
        self._highlighted_code = self.highlight(
            self.code,
            self.lexer,
            ansi=is_ansi,
            dark=is_dark,
        )
        self.set_content(self._highlighted_code)
        return super().notify_style_update()

    def set_content(self, content: Any) -> None:
        self._content = content
        if hasattr(content, "code") and isinstance(getattr(content, "code", None), str):
            content.code = content.code.rstrip("\r\n")
        if hasattr(content, "word_wrap"):
            content.word_wrap = True
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
        code_style = JOHNSTON_RICH_MARKDOWN_STYLES.get("markdown.code")
        if code_style:
            try:
                return Style.parse(code_style)
            except Exception:
                pass
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
    self.BLOCKS["table_open"] = CustomMarkdownTable
    _old_markdown_init(self, *args, **kwargs)


_old_markdown_block_get_style = MarkdownBlock._get_style


def _update_syntax_theme(theme_obj: Any) -> None:
    """Build PygmentsSyntaxTheme from active Theme syntax_tokens."""
    global _CURRENT_SYNTAX_THEME
    is_dark = getattr(theme_obj, "dark", True)
    base_name = "one-dark" if is_dark else "github-light"
    try:
        base_cls = get_style_by_name(base_name)
        styles = dict(base_cls.styles)
    except Exception:
        styles = {}
    syntax_tokens = getattr(theme_obj, "syntax_tokens", {})
    if isinstance(syntax_tokens, dict):
        for tok, color in syntax_tokens.items():
            styles[tok] = color
    theme_name = getattr(theme_obj, "name", "custom").replace("-", "_")
    dyn_cls = type(f"{theme_name.title()}SyntaxStyle", (PygmentsStyle,), {"styles": styles, "background_color": None})
    _CURRENT_SYNTAX_THEME = PygmentsSyntaxTheme(dyn_cls)


def sync_theme_styles(theme_obj: Any = None) -> None:
    """Sync rich markdown and token styles with active Theme."""
    from widgets.app.theme_manager import theme_manager

    t = theme_obj or theme_manager.current_theme
    if getattr(t, "markdown_styles", None):
        JOHNSTON_RICH_MARKDOWN_STYLES.update(t.markdown_styles)
        try:
            from rich.default_styles import DEFAULT_STYLES
            from rich.style import Style as RichStyle

            for k, v in t.markdown_styles.items():
                DEFAULT_STYLES[k] = RichStyle.parse(v)
        except Exception:
            pass
    if getattr(t, "syntax_tokens", None):
        TOKEN_COLORS.clear()
        TOKEN_COLORS.update(t.syntax_tokens)
    _update_syntax_theme(t)

    heading_fn_color = TOKEN_COLORS.get(Token.Name.Function, "$text-warning")
    HighlightTheme.STYLES[Token.Generic.Heading] = f"bold {heading_fn_color}"
    HighlightTheme.STYLES[Token.Generic.Subheading] = f"bold {heading_fn_color}"


JOHNSTON_RICH_MARKDOWN_STYLES = dict(ZINC_DARK.markdown_styles)


def _apply_chat_markdown_patches() -> None:
    """Applies Textual Markdown monkey-patches (custom theme, blocks, renderers).

    Kept behind an idempotent flag so importing this module has no side-effects;
    the first widget that needs chat markdown rendering triggers it exactly once.
    """
    global _patched
    if _patched:
        return
    _patched = True
    from widgets.app.theme_manager import theme_manager

    theme_manager.add_listener(sync_theme_styles)
    sync_theme_styles(theme_manager.current_theme)

    HighlightTheme.STYLES[Token.Name.Function] = "$text-warning"
    HighlightTheme.STYLES[Token.Name.Function.Magic] = "$text-warning"
    heading_fn_color = TOKEN_COLORS.get(Token.Name.Function, "$text-warning")
    HighlightTheme.STYLES[Token.Generic.Heading] = f"bold {heading_fn_color}"
    HighlightTheme.STYLES[Token.Generic.Subheading] = f"bold {heading_fn_color}"

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

    Markdown.BLOCKS["fence"] = CustomMarkdownFence
    Markdown.BLOCKS["code_block"] = CustomMarkdownFence
    Markdown.BLOCKS["table_open"] = CustomMarkdownTable

    Markdown.__init__ = _new_markdown_init
    MarkdownBlock._get_style = _new_markdown_block_get_style
    MarkdownTableCellContents._get_style = _new_markdown_block_get_style


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

    text = text.replace("\r\n", "\n")
    if "\t" in text:
        text = text.expandtabs(4)
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

        has_star = "*" in line
        has_colon = ":" in line
        has_quote = ">" in line
        has_dash = "-" in line
        has_digit = any(c.isdigit() for c in line[:10])

        if has_star and has_colon:
            line = _RE_ITALIC_COLON.sub(r"**\1:**", line)
        if has_star or has_dash or has_digit:
            line = _RE_DOUBLE_BULLET.sub(r"\1* ", line)
        if has_quote:
            line = _RE_BLOCKQUOTE_BULLET.sub(r"\1", line)

        if has_star or has_dash or has_digit:
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


TOKEN_COLORS = dict(ZINC_DARK.syntax_tokens)
