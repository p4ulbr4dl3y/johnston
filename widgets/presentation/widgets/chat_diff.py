import re
from typing import Any

from pygments.lexers import get_lexer_by_name
from rich.text import Span, Text

from core.domain.defaults.config import (
    COLOR_DIFF_ADD_BG,
    COLOR_DIFF_ADD_FG,
    COLOR_DIFF_GUTTER,
    COLOR_DIFF_REMOVE_BG,
    COLOR_DIFF_REMOVE_FG,
)
from widgets.utils.lexer import HUNK_HEADER_RE, guess_lexer_name, lex_block_to_line_texts


class DiffLine:
    """Represents a single formatted diff line with gutter prefix and code text."""

    def __init__(self, prefix: Text, code: Text, style_bg: str | None = None):
        self.prefix = prefix
        self.code = code
        self.style_bg = style_bg
        self.prefix_len = prefix.cell_len

    @property
    def plain(self) -> str:
        return self.to_text().plain

    @property
    def cell_len(self) -> int:
        return self.prefix_len + self.code.cell_len

    def to_text(self) -> Text:
        line = Text.assemble(self.prefix, self.code)
        if self.style_bg:
            line.stylize(self.style_bg)
        return line


class DiffRenderable:
    """Custom Rich renderable for diff views with full-width background and line wrapping."""

    def __init__(self, formatted_lines: list[Any]):
        self.formatted_lines = formatted_lines
        plain_texts = [line.to_text() if hasattr(line, "to_text") else line for line in formatted_lines]
        self._text = Text("\n").join(plain_texts)
        self._text.overflow = "fold"
        self._text.no_wrap = False

    def __rich_console__(self, console, options):
        new_opts = options.update(no_wrap=False, overflow="fold")
        target_width = options.max_width
        for line in self.formatted_lines:
            if hasattr(line, "prefix") and hasattr(line, "code"):
                prefix = line.prefix
                code = line.code
                style_bg = line.style_bg
                prefix_len = line.prefix_len
                code_width = max(10, target_width - prefix_len)

                if code.cell_len > code_width and target_width > prefix_len + 10:
                    chunks = code.wrap(console, code_width, overflow="fold")
                else:
                    chunks = [code]

                blank_gutter = Text(" " * prefix_len)
                for idx, chunk in enumerate(chunks):
                    pfx = prefix.copy() if idx == 0 else blank_gutter.copy()
                    full_line = Text.assemble(pfx, chunk)
                    pad_count = max(0, target_width - full_line.cell_len)
                    if pad_count > 0:
                        full_line.pad_right(pad_count)
                    if style_bg:
                        full_line.stylize(style_bg)
                    yield from console.render(full_line, new_opts)
            else:
                line_copy = line.copy()
                pad_count = max(0, target_width - line_copy.cell_len)
                if pad_count > 0:
                    old_len = len(line_copy.plain)
                    line_copy.pad_right(pad_count)
                    new_len = len(line_copy.plain)
                    line_copy._spans = [
                        Span(s.start, new_len, s.style) if s.end == old_len else s for s in line_copy._spans
                    ]
                yield from console.render(line_copy, new_opts)

    def __rich_measure__(self, console, options):
        return self._text.__rich_measure__(console, options)

    def __getattr__(self, name):
        return getattr(self._text, name)


GIT_HEADER_PREFIXES = (
    "diff --git ",
    "index ",
    "--- ",
    "+++ ",
    "new file mode ",
    "deleted file mode ",
    "similarity index ",
    "rename from ",
    "rename to ",
    "old mode ",
    "new mode ",
    "Binary files ",
    "GIT binary patch",
)


def get_diff_colors(theme: Any = None) -> tuple[str, str, str, str, str]:
    """Return (add_fg, add_bg, remove_fg, remove_bg, gutter) harmonized with active theme."""
    if theme is None:
        try:
            from widgets.app.theme_manager import theme_manager

            theme = theme_manager.current_theme
        except Exception:
            theme = None

    is_dark = getattr(theme, "dark", True) if theme else True
    gutter = getattr(theme, "muted", COLOR_DIFF_GUTTER) if theme else COLOR_DIFF_GUTTER

    if theme is not None:
        raw_add = getattr(theme, "accent_success", None)
        add_fg = raw_add if isinstance(raw_add, str) else (COLOR_DIFF_ADD_FG if is_dark else "#1a7f37")
        raw_remove = getattr(theme, "accent_error", None)
        remove_fg = raw_remove if isinstance(raw_remove, str) else (COLOR_DIFF_REMOVE_FG if is_dark else "#cf222e")
    else:
        add_fg = COLOR_DIFF_ADD_FG if is_dark else "#1a7f37"
        remove_fg = COLOR_DIFF_REMOVE_FG if is_dark else "#cf222e"

    if is_dark:
        add_bg = COLOR_DIFF_ADD_BG
        remove_bg = COLOR_DIFF_REMOVE_BG
    else:
        add_bg = "on #dafbe1"
        remove_bg = "on #ffebe9"

    if theme and getattr(theme, "syntax_tokens", None):
        from pygments.token import Token

        if Token.Generic.Inserted in theme.syntax_tokens:
            add_fg = theme.syntax_tokens[Token.Generic.Inserted].split()[0]
        if Token.Generic.Deleted in theme.syntax_tokens:
            remove_fg = theme.syntax_tokens[Token.Generic.Deleted].split()[0]

    return add_fg, add_bg, remove_fg, remove_bg, gutter


def format_edit_diff(diff_text: str, file_path: str) -> Any:
    diff_text = re.sub(
        r"^(?:Success|OK):\s*file\s+'[^']+'\s*(?:updated|created|saved)[^\n]*\n?", "", diff_text, flags=re.MULTILINE
    ).strip()

    lexer_name = guess_lexer_name(file_path)
    try:
        lexer = get_lexer_by_name(lexer_name)
    except Exception:
        lexer = None

    lines = diff_text.splitlines()
    formatted_lines = []

    old_code_lines = []
    new_code_lines = []
    in_hunk = False
    max_num = 1
    current_old = 0
    current_new = 0

    for line in lines:
        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            current_old = int(hunk_match.group(1))
            current_new = int(hunk_match.group(3))
            in_hunk = True
            continue
        if line.startswith(GIT_HEADER_PREFIXES):
            continue
        if not in_hunk:
            continue

        if line.startswith("-"):
            max_num = max(max_num, current_old)
            current_old += 1
            old_code_lines.append(line[1:].expandtabs(4))
        elif line.startswith("+"):
            max_num = max(max_num, current_new)
            current_new += 1
            new_code_lines.append(line[1:].expandtabs(4))
        elif line.startswith("\\"):
            continue
        else:
            content = line[1:] if line.startswith(" ") else line
            max_num = max(max_num, current_old, current_new)
            current_old += 1
            current_new += 1
            old_code_lines.append(content.expandtabs(4))
            new_code_lines.append(content.expandtabs(4))
    max_num_digits = max(len(str(max_num)), 3)

    full_sample = "\n".join(old_code_lines + new_code_lines)
    if lexer_name in ("html", "htm", "xhtml", "php", "vue", "svelte"):
        has_html_tags = bool(
            re.search(
                r"</?(?:div|p|a|span|form|button|input|h[1-6]|section|header|footer|ul|li|ol|img|script|style|label|svg|path|body|html|head|main|nav|aside|table|tr|td|th)\b|<!--",
                full_sample,
                re.IGNORECASE,
            )
        )
        if not has_html_tags:
            has_script_open = bool(re.search(r"<script[\s>]", full_sample, re.IGNORECASE))
            has_style_open = bool(re.search(r"<style[\s>]", full_sample, re.IGNORECASE))

            has_js = any(
                w in full_sample
                for w in (
                    "function",
                    "let",
                    "const",
                    "var",
                    "if",
                    "return",
                    "=>",
                    "document",
                    "window",
                    "console",
                    "addEventListener",
                    "preventDefault",
                    "classList",
                )
            )
            has_css = "{" in full_sample and ":" in full_sample and ";" in full_sample

            if has_js and not has_script_open:
                try:
                    lexer = get_lexer_by_name("javascript")
                except Exception:
                    pass
            elif has_css and not has_style_open and not has_js:
                try:
                    lexer = get_lexer_by_name("css")
                except Exception:
                    pass

    old_texts = lex_block_to_line_texts(old_code_lines, lexer)
    new_texts = lex_block_to_line_texts(new_code_lines, lexer)

    formatted_lines = []
    old_line = 0
    new_line = 0
    old_idx = 0
    new_idx = 0

    diff_add_fg, diff_add_bg, diff_remove_fg, diff_remove_bg, diff_gutter = get_diff_colors()

    def append_diff_line(
        num_str: str,
        symbol: str,
        code_text: Text,
        style_bg: str | None = None,
        style_fg: str | None = None,
    ) -> None:
        prefix = Text()
        if style_fg:
            prefix.append(f"{num_str} ", style=style_fg)
            prefix.append(f"{symbol} ", style=f"bold {style_fg}")
        else:
            prefix.append(f"{num_str} ", style=diff_gutter)
            prefix.append("  ")
        formatted_lines.append(DiffLine(prefix, code_text, style_bg=style_bg))

    in_hunk = False
    hunk_count = 0
    for line in lines:
        if line.startswith(GIT_HEADER_PREFIXES):
            continue

        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(3))
            if hunk_count > 0 and formatted_lines:
                sep_prefix = Text(f"{'···'.rjust(max_num_digits)}   ", style=f"dim {diff_gutter}")
                formatted_lines.append(DiffLine(sep_prefix, Text(""), style_bg=None))
            hunk_count += 1
            in_hunk = True
            continue

        if not in_hunk:
            if line.strip():
                if line.startswith(("Success:", "OK:")) or " updated" in line or " created" in line or " saved" in line:
                    continue
                formatted_lines.append(Text(line, style="dim"))
            continue

        if line.startswith("-"):
            num_str = str(old_line).rjust(max_num_digits)
            code_text = old_texts[old_idx] if old_idx < len(old_texts) else Text(line[1:].expandtabs(4))
            old_idx += 1
            append_diff_line(num_str, "-", code_text, style_bg=diff_remove_bg, style_fg=diff_remove_fg)
            old_line += 1
        elif line.startswith("+"):
            num_str = str(new_line).rjust(max_num_digits)
            code_text = new_texts[new_idx] if new_idx < len(new_texts) else Text(line[1:].expandtabs(4))
            new_idx += 1
            append_diff_line(num_str, "+", code_text, style_bg=diff_add_bg, style_fg=diff_add_fg)
            new_line += 1
        elif line.startswith("\\"):
            continue
        else:
            num_str = str(new_line).rjust(max_num_digits)
            content = line[1:] if line.startswith(" ") else line
            code_text = new_texts[new_idx] if new_idx < len(new_texts) else Text(content.expandtabs(4))
            old_idx += 1
            new_idx += 1
            append_diff_line(num_str, " ", code_text, style_bg=None, style_fg=None)
            old_line += 1
            new_line += 1

    return DiffRenderable(formatted_lines)
