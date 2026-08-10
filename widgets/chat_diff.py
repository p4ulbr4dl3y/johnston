import re
from typing import Any

from pygments.lexers import get_lexer_by_name
from rich.text import Span, Text

from widgets.lexer_utils import guess_lexer_name, lex_block_to_line_texts


class DiffRenderable:
    """Custom Rich renderable for diff views to prevent console line wrapping"""

    def __init__(self, formatted_lines: list[Text]):
        self.formatted_lines = formatted_lines
        self._text = Text("\n").join(formatted_lines)
        self._text.overflow = "crop"
        self._text.no_wrap = True

    def __rich_console__(self, console, options):
        new_opts = options.update(no_wrap=True, overflow="crop")
        max_line_len = max((line.cell_len for line in self.formatted_lines), default=0)
        target_width = max(options.max_width, max_line_len)
        for line in self.formatted_lines:
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


def format_edit_diff(diff_text: str, file_path: str) -> Any:
    if "[Linter Feedback]:" in diff_text:
        diff_text = diff_text.split("[Linter Feedback]:")[0].strip()

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
    hunk_regex = re.compile(r"^@@\s+-\s*(\d+)(?:,\d+)?\s+\+\s*(\d+)(?:,\d+)?\s+@@")

    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        if hunk_regex.match(line):
            in_hunk = True
            continue
        if not in_hunk:
            continue

        if line.startswith("-"):
            old_code_lines.append(line[1:].expandtabs(4))
        elif line.startswith("+"):
            new_code_lines.append(line[1:].expandtabs(4))
        elif line.startswith("\\"):
            continue
        else:
            content = line[1:] if line.startswith(" ") else line
            old_code_lines.append(content.expandtabs(4))
            new_code_lines.append(content.expandtabs(4))

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
            elif has_css and not has_style_open and not has_script_open:
                try:
                    lexer = get_lexer_by_name("css")
                except Exception:
                    pass

    old_texts = lex_block_to_line_texts(old_code_lines, lexer)
    new_texts = lex_block_to_line_texts(new_code_lines, lexer)

    old_line = 0
    new_line = 0
    old_idx = 0
    new_idx = 0

    max_num = 1
    temp_old = 0
    temp_new = 0
    in_hunk = False
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            continue
        hunk_match = hunk_regex.match(line)
        if hunk_match:
            temp_old = int(hunk_match.group(1))
            temp_new = int(hunk_match.group(2))
            in_hunk = True
        elif not in_hunk:
            continue
        elif line.startswith("-"):
            max_num = max(max_num, temp_old)
            temp_old += 1
        elif line.startswith("+"):
            max_num = max(max_num, temp_new)
            temp_new += 1
        elif line.startswith("\\"):
            continue
        else:
            max_num = max(max_num, temp_old, temp_new)
            temp_old += 1
            temp_new += 1
    max_num_digits = len(str(max_num))

    def append_diff_line(num_str: str, symbol: str, code_text: Text, style_bg: str = None, style_fg: str = None):
        full_line = Text()
        if style_fg:
            full_line.append(f"{num_str} ", style=style_fg)
            full_line.append(f"{symbol} ", style=f"bold {style_fg}")
        else:
            full_line.append(f"{num_str} ", style="#6e7681")
            full_line.append("  ")
        full_line.append(code_text)

        if style_bg:
            full_line.stylize(style_bg)
        formatted_lines.append(full_line)

    in_hunk = False
    for line in lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            continue

        hunk_match = hunk_regex.match(line)
        if hunk_match:
            old_line = int(hunk_match.group(1))
            new_line = int(hunk_match.group(2))
            in_hunk = True
            continue

        if not in_hunk:
            if line.strip():
                if line.startswith(("Success:", "OK:")) or " updated" in line or " created" in line or " saved" in line:
                    continue
                formatted_lines.append(Text(line, style="dim"))
            continue

        if line.startswith("-"):
            num_str = str(new_line).rjust(max_num_digits)
            code_text = old_texts[old_idx] if old_idx < len(old_texts) else Text(line[1:].expandtabs(4))
            old_idx += 1
            append_diff_line(num_str, "-", code_text, style_bg="on #2a1215", style_fg="#f85149")
            old_line += 1
        elif line.startswith("+"):
            num_str = str(new_line).rjust(max_num_digits)
            code_text = new_texts[new_idx] if new_idx < len(new_texts) else Text(line[1:].expandtabs(4))
            new_idx += 1
            append_diff_line(num_str, "+", code_text, style_bg="on #12261e", style_fg="#3fb950")
            new_line += 1
        elif line.startswith("\\"):
            formatted_lines.append(Text(line, style="dim", overflow="crop"))
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
