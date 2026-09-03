import difflib
import re
import threading
from collections import OrderedDict
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


class SplitDiffLine:
    """Represents a side-by-side diff row with left and right columns."""

    def __init__(
        self,
        left_prefix: Text,
        left_code: Text,
        left_bg: str | None,
        right_prefix: Text,
        right_code: Text,
        right_bg: str | None,
        sep: Text | None = None,
    ):
        self.left_prefix = left_prefix
        self.left_code = left_code
        self.left_bg = left_bg
        self.right_prefix = right_prefix
        self.right_code = right_code
        self.right_bg = right_bg
        self.sep = sep if sep is not None else Text(" │ ", style="dim #71717a")

    @property
    def plain(self) -> str:
        return self.to_text(half_width=40).plain

    def to_text(self, half_width: int = 40) -> Text:
        left = Text.assemble(self.left_prefix, self.left_code)
        if left.cell_len < half_width:
            left.pad_right(half_width - left.cell_len)
        elif left.cell_len > half_width:
            left.truncate(half_width)
        if self.left_bg:
            left.stylize(self.left_bg)

        right = Text.assemble(self.right_prefix, self.right_code)
        if right.cell_len < half_width:
            right.pad_right(half_width - right.cell_len)
        elif right.cell_len > half_width:
            right.truncate(half_width)
        if self.right_bg:
            right.stylize(self.right_bg)

        return Text.assemble(left, self.sep, right)


class DiffRenderable:
    """Custom Rich renderable for diff views with full-width background, word diff, and split mode."""

    def __init__(self, formatted_lines: list[Any], hunk_lines: list[int] | None = None):
        self.formatted_lines = formatted_lines
        self.hunk_lines = hunk_lines or []
        plain_texts = [line.to_text() if hasattr(line, "to_text") else line for line in formatted_lines]
        self._text = Text("\n").join(plain_texts)
        self._text.overflow = "fold"
        self._text.no_wrap = False

    def __rich_console__(self, console, options):
        new_opts = options.update(no_wrap=False, overflow="fold")
        target_width = options.max_width
        for line in self.formatted_lines:
            if isinstance(line, SplitDiffLine):
                sep_len = line.sep.cell_len
                left_w = max(10, (target_width - sep_len) // 2)
                right_w = max(10, target_width - sep_len - left_w)

                left = Text.assemble(line.left_prefix, line.left_code)
                if left.cell_len < left_w:
                    left.pad_right(left_w - left.cell_len)
                elif left.cell_len > left_w:
                    left.truncate(left_w)
                if line.left_bg and left.plain.strip():
                    left.stylize(line.left_bg)

                right = Text.assemble(line.right_prefix, line.right_code)
                if right.cell_len < right_w:
                    right.pad_right(right_w - right.cell_len)
                elif right.cell_len > right_w:
                    right.truncate(right_w)
                if line.right_bg and right.plain.strip():
                    right.stylize(line.right_bg)

                full_line = Text.assemble(left, line.sep, right)
                yield from console.render(full_line, new_opts)
            elif hasattr(line, "prefix") and hasattr(line, "code"):
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

_LEX_CACHE_MAX = 32
_lex_cache: OrderedDict[tuple[str, str], tuple[tuple[Text, ...], tuple[Text, ...]]] = OrderedDict()
_lex_cache_lock = threading.Lock()


def _get_lexed_lines(
    diff_text: str,
    file_path: str,
    old_code_lines: list[str],
    new_code_lines: list[str],
    lexer: Any,
) -> tuple[list[Text], list[Text]]:
    """Lex old/new code lines, reusing the pygments pass for repeated inputs.

    ``format_edit_diff`` is recomputed on every tool-content refresh with the same
    ``(diff_text, file_path)``; lexing the whole diff buffer is the dominant cost, so
    identical inputs reuse the previous result. The lexing inputs are fully
    determined by the two key strings (parsed code lines and the lexer derive from
    them), and theme coloring/word diffs still recompute on every call. Callers
    mutate the returned ``Text`` objects (intra-line word diffs), so cache entries
    are always handed out as copies to keep the stored representation pristine.
    """
    key = (diff_text, file_path)
    with _lex_cache_lock:
        cached = _lex_cache.get(key)
        if cached is not None:
            _lex_cache.move_to_end(key)
            return ([t.copy() for t in cached[0]], [t.copy() for t in cached[1]])
    old_texts = lex_block_to_line_texts(old_code_lines, lexer)
    new_texts = lex_block_to_line_texts(new_code_lines, lexer)
    with _lex_cache_lock:
        _lex_cache[key] = (tuple(t.copy() for t in old_texts), tuple(t.copy() for t in new_texts))
        if len(_lex_cache) > _LEX_CACHE_MAX:
            _lex_cache.popitem(last=False)
    return old_texts, new_texts


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


def get_diff_word_colors(theme: Any = None) -> tuple[str, str]:
    """Return (add_word_bg, remove_word_bg) for intra-line word diffs."""
    if theme is None:
        try:
            from widgets.app.theme_manager import theme_manager

            theme = theme_manager.current_theme
        except Exception:
            theme = None

    is_dark = getattr(theme, "dark", True) if theme else True
    if is_dark:
        return "on #1c5230", "on #5e2129"
    return "on #acf2bd", "on #ffb3ba"


def apply_word_diff(
    old_text: Text,
    new_text: Text,
    old_str: str,
    new_str: str,
    remove_word_bg: str,
    add_word_bg: str,
) -> None:
    """Apply intra-line difference highlighting using difflib sequence matching."""
    if not old_str and not new_str:
        return
    matcher = difflib.SequenceMatcher(None, old_str, new_str, autojunk=False)
    if matcher.ratio() < 0.2:
        return
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            old_text.stylize(f"bold {remove_word_bg}", i1, i2)
        if tag in ("replace", "insert") and j2 > j1:
            new_text.stylize(f"bold {add_word_bg}", j1, j2)


def format_edit_diff(diff_text: str, file_path: str, view_mode: str = "unified") -> Any:
    diff_text = re.sub(
        r"^(?:Success|OK):\s*file\s+'[^']+'\s*(?:updated|created|saved)[^\n]*\n?", "", diff_text, flags=re.MULTILINE
    ).strip()

    lexer_name = guess_lexer_name(file_path)
    try:
        lexer = get_lexer_by_name(lexer_name)
    except Exception:
        lexer = None

    lines = diff_text.splitlines()
    old_code_lines: list[str] = []
    new_code_lines: list[str] = []
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

    old_texts, new_texts = _get_lexed_lines(diff_text, file_path, old_code_lines, new_code_lines, lexer)

    diff_add_fg, diff_add_bg, diff_remove_fg, diff_remove_bg, diff_gutter = get_diff_colors()
    diff_add_word_bg, diff_remove_word_bg = get_diff_word_colors()

    formatted_lines: list[Any] = []
    hunk_lines: list[int] = []

    def make_prefix(num_val: int | None, symbol: str, is_removed: bool | None) -> Text:
        prefix = Text()
        if num_val is None:
            prefix.append(" " * max_num_digits, style=diff_gutter)
            prefix.append("   ")
            return prefix
        num_str = str(num_val).rjust(max_num_digits)
        if is_removed is True:
            prefix.append(f"{num_str} ", style=diff_remove_fg)
            prefix.append(f"{symbol} ", style=f"bold {diff_remove_fg}")
        elif is_removed is False:
            prefix.append(f"{num_str} ", style=diff_add_fg)
            prefix.append(f"{symbol} ", style=f"bold {diff_add_fg}")
        else:
            prefix.append(f"{num_str} ", style=diff_gutter)
            prefix.append("  ")
        return prefix

    # Pre-parse hunks to allow pair word diffing
    old_cursor = 0
    new_cursor = 0
    in_hunk = False
    hunk_count = 0

    pending_old: list[tuple[int, int, str]] = []  # (old_line_num, old_idx, content)
    pending_new: list[tuple[int, int, str]] = []  # (new_line_num, new_idx, content)

    def flush_pending() -> None:
        nonlocal pending_old, pending_new
        if not pending_old and not pending_new:
            return

        # Perform intra-line word diff on paired lines
        pair_count = min(len(pending_old), len(pending_new))
        for i in range(pair_count):
            _, o_idx, o_str = pending_old[i]
            _, n_idx, n_str = pending_new[i]
            if o_idx < len(old_texts) and n_idx < len(new_texts):
                apply_word_diff(
                    old_texts[o_idx],
                    new_texts[n_idx],
                    o_str,
                    n_str,
                    diff_remove_word_bg,
                    diff_add_word_bg,
                )

        if view_mode == "split":
            max_len = max(len(pending_old), len(pending_new))
            for i in range(max_len):
                if i < len(pending_old):
                    o_num, o_idx, _ = pending_old[i]
                    l_pfx = make_prefix(o_num, "-", is_removed=True)
                    l_code = old_texts[o_idx] if o_idx < len(old_texts) else Text("")
                    l_bg = diff_remove_bg
                else:
                    l_pfx = make_prefix(None, " ", None)
                    l_code = Text("")
                    l_bg = None

                if i < len(pending_new):
                    n_num, n_idx, _ = pending_new[i]
                    r_pfx = make_prefix(n_num, "+", is_removed=False)
                    r_code = new_texts[n_idx] if n_idx < len(new_texts) else Text("")
                    r_bg = diff_add_bg
                else:
                    r_pfx = make_prefix(None, " ", None)
                    r_code = Text("")
                    r_bg = None

                formatted_lines.append(SplitDiffLine(l_pfx, l_code, l_bg, r_pfx, r_code, r_bg))
        else:
            for o_num, o_idx, _ in pending_old:
                pfx = make_prefix(o_num, "-", is_removed=True)
                code = old_texts[o_idx] if o_idx < len(old_texts) else Text("")
                formatted_lines.append(DiffLine(pfx, code, style_bg=diff_remove_bg))
            for n_num, n_idx, _ in pending_new:
                pfx = make_prefix(n_num, "+", is_removed=False)
                code = new_texts[n_idx] if n_idx < len(new_texts) else Text("")
                formatted_lines.append(DiffLine(pfx, code, style_bg=diff_add_bg))

        pending_old = []
        pending_new = []

    for line in lines:
        if line.startswith(GIT_HEADER_PREFIXES):
            continue

        hunk_match = HUNK_HEADER_RE.match(line)
        if hunk_match:
            flush_pending()
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(3))
            if hunk_count > 0 and formatted_lines:
                sep_prefix = Text(f"{'···'.rjust(max_num_digits)}   ", style=f"dim {diff_gutter}")
                if view_mode == "split":
                    formatted_lines.append(
                        SplitDiffLine(
                            sep_prefix,
                            Text(""),
                            None,
                            sep_prefix,
                            Text(""),
                            None,
                            sep=Text(" │ ", style=f"dim {diff_gutter}"),
                        )
                    )
                else:
                    formatted_lines.append(DiffLine(sep_prefix, Text(""), style_bg=None))
            hunk_lines.append(len(formatted_lines))
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
            content = line[1:].expandtabs(4)
            pending_old.append((old_line, old_cursor, content))
            old_cursor += 1
            old_line += 1
        elif line.startswith("+"):
            content = line[1:].expandtabs(4)
            pending_new.append((new_line, new_cursor, content))
            new_cursor += 1
            new_line += 1
        elif line.startswith("\\"):
            continue
        else:
            flush_pending()
            content = line[1:].expandtabs(4) if line.startswith(" ") else line.expandtabs(4)
            c_code = new_texts[new_cursor] if new_cursor < len(new_texts) else Text(content)
            if view_mode == "split":
                l_pfx = make_prefix(old_line, " ", None)
                r_pfx = make_prefix(new_line, " ", None)
                formatted_lines.append(SplitDiffLine(l_pfx, c_code.copy(), None, r_pfx, c_code.copy(), None))
            else:
                pfx = make_prefix(new_line, " ", None)
                formatted_lines.append(DiffLine(pfx, c_code, style_bg=None))
            old_cursor += 1
            new_cursor += 1
            old_line += 1
            new_line += 1

    flush_pending()
    return DiffRenderable(formatted_lines, hunk_lines=hunk_lines)

