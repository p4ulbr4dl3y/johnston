"""Mermaid diagram detection and ASCII/Unicode terminal rendering."""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
import threading
from collections import OrderedDict
from typing import Any, Optional

from rich.cells import cell_len
from rich.text import Text
from textual.content import Content

_BOX_CHARS = frozenset("┌┐└┘├┤┬┴┼─│━┃╭╮╰╯═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬◆◇○●┄┈┆┊")
_ARROW_CHARS = frozenset("◄►▲▼◀▶")

_CACHE_LOCK = threading.Lock()
_RENDER_CACHE: OrderedDict[str, Optional[str]] = OrderedDict()
_CACHE_MAX_SIZE = 256


def is_mermaid(language: str | None) -> bool:
    """Return True if the fence language indicates a Mermaid diagram."""
    clean = (language or "").strip().lower()
    return clean in ("mermaid", "mmd")


@functools.lru_cache(maxsize=1)
def _get_mermaid_binary() -> Optional[str]:
    """Locate mermaid-ascii binary from python package or system PATH."""
    try:
        import mermaid_ascii

        if hasattr(mermaid_ascii, "_resolve_binary"):
            return mermaid_ascii._resolve_binary()
    except Exception:
        pass
    return shutil.which("mermaid-ascii") or shutil.which("mermaid-ascii.exe")


def _normalize_flowchart_shapes(code: str) -> str:
    """Normalize non-standard node shapes (rhombus, rounded, cylinder, stadium) to standard boxes.

    mermaid-ascii's Go AST parser only maps node identifiers correctly when enclosed
    in square brackets [...]. Shapes like (rounded), {rhombus}, [(db)] otherwise get
    treated as new detached node IDs, splitting the graph topology.

    Protects quoted strings, edge labels with pipes |...|, subgraphs, and styles.
    Supports Unicode/Cyrillic node identifiers.
    """
    lines = code.splitlines()
    in_frontmatter = False
    is_flowchart = False
    for line in lines:
        s = line.strip()
        if not s or s.startswith("%%"):
            continue
        if s == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        first_word = s.lower().split()[0] if s.split() else ""
        if first_word in ("graph", "flowchart"):
            is_flowchart = True
        break

    if not is_flowchart:
        return code

    # Protect string literals and pipe edge labels from shape replacements
    placeholders: list[str] = []

    def _save_placeholder(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"__MERMAID_PH_{len(placeholders) - 1}__"

    protected = re.sub(r'"[^"\n]*"', _save_placeholder, code)
    protected = re.sub(r"\|[^|\n]*\|", _save_placeholder, protected)

    norm_lines: list[str] = []
    skip_prefixes = ("subgraph", "style", "classDef", "class ", "click", "linkStyle", "%%", "---")
    for line in protected.splitlines():
        s = line.strip()
        if s.startswith(skip_prefixes):
            norm_lines.append(line)
            continue

        # Two-character opening/closing shapes (node ID: Unicode word chars + hyphens)
        line = re.sub(r"(\b[\w-]+)\s*\[\((.*?)\)\]", r"\1[\2]", line)  # [(...)]
        line = re.sub(r"(\b[\w-]+)\s*\(\[(.*?)\]\)", r"\1[\2]", line)  # ([...])
        line = re.sub(r"(\b[\w-]+)\s*\(\((.*?)\)\)", r"\1[\2]", line)  # ((...))
        line = re.sub(r"(\b[\w-]+)\s*\[\[(.*?)\]\]", r"\1[\2]", line)  # [[...]]
        line = re.sub(r"(\b[\w-]+)\s*\{\{(.*?)\}\}", r"\1[\2]", line)  # {{...}}
        line = re.sub(r"(\b[\w-]+)\s*\[/(.*?)/\]", r"\1[\2]", line)  # [/ /]
        line = re.sub(r"(\b[\w-]+)\s*\[\x5c(.*?)\x5c\]", r"\1[\2]", line)  # [\ \]
        line = re.sub(r"(\b[\w-]+)\s*\[/(.*?)\x5c\]", r"\1[\2]", line)  # [/ \]
        line = re.sub(r"(\b[\w-]+)\s*\[\x5c(.*?)/\]", r"\1[\2]", line)  # [\ /]

        # Single-character shapes
        line = re.sub(r"(\b[\w-]+)\s*\{(.*?)\}", r"\1[\2]", line)  # {...}
        line = re.sub(r"(\b[\w-]+)\s*>\s*(.*?)]", r"\1[\2]", line)  # >...]
        line = re.sub(r"(\b[\w-]+)\s*\(([^()\n]+)\)", r"\1[\2]", line)  # (...)
        norm_lines.append(line)

    result = "\n".join(norm_lines)
    for i, ph in enumerate(placeholders):
        result = result.replace(f"__MERMAID_PH_{i}__", ph)
    return result


def clean_mermaid_code(code: str) -> str:
    """Strip code fence markers and normalize shapes to preserve graph topology."""
    if not code:
        return ""
    lines = code.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    cleaned = "\n".join(lines).strip()
    return _normalize_flowchart_shapes(cleaned)



_MOJIBAKE_RE = re.compile(
    r"(?:[\u00c0-\u00df][\u0080-\u00bf]|[\u00e0-\u00ef][\u0080-\u00bf]{2}|[\u00f0-\u00f7][\u0080-\u00bf]{3})+"
)


def _fix_mojibake(text: str) -> str:
    """Repair double-encoded UTF-8 artifacts produced by some Go lexers on non-ASCII edge labels.

    Pads the replacement so the character column layout calculated by the Go engine
    remains strictly aligned (preserves vertical borders, arrows, corners).
    """
    lines: list[str] = []
    for line in text.splitlines():

        def _repair(match: re.Match) -> str:
            chunk = match.group(0)
            try:
                decoded = chunk.encode("latin1").decode("utf-8")
            except Exception:
                return chunk
            diff = len(chunk) - cell_len(decoded)
            if diff <= 0:
                return decoded
            start = match.start()
            end = match.end()
            before_char = line[start - 1] if start > 0 else " "
            after_char = line[end] if end < len(line) else " "
            pad_char = "─" if (before_char in "─═━" or after_char in "─═━") else " "
            left_pad = diff // 2
            right_pad = diff - left_pad
            return (pad_char * left_pad) + decoded + (pad_char * right_pad)

        lines.append(_MOJIBAKE_RE.sub(_repair, line))
    return "\n".join(lines)


def get_cached_mermaid(code: str) -> tuple[bool, Optional[str]]:
    """Check if code is already rendered in cache without triggering execution.

    Returns (is_cached, cached_diagram_string_or_None).
    """
    cleaned = clean_mermaid_code(code)
    if not cleaned:
        return True, None
    with _CACHE_LOCK:
        if cleaned in _RENDER_CACHE:
            _RENDER_CACHE.move_to_end(cleaned)
            return True, _RENDER_CACHE[cleaned]
    return False, None


def render_mermaid_to_ascii(code: str, timeout: float = 2.0) -> Optional[str]:
    """Render mermaid code to ASCII/Unicode diagram string using mermaid-ascii.

    Returns rendered diagram string or None on syntax error / missing binary.
    Thread-safe and caches results in-memory.
    """
    cleaned = clean_mermaid_code(code)
    if not cleaned:
        return None

    is_cached, cached_val = get_cached_mermaid(code)
    if is_cached:
        return cached_val

    binary = _get_mermaid_binary()
    if not binary:
        _store_cache(cleaned, None)
        return None

    try:
        res = subprocess.run(
            [binary],
            input=cleaned,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=timeout,
        )
        if res.returncode == 0 and res.stdout.strip():
            output = _fix_mojibake(res.stdout.rstrip())
            _store_cache(cleaned, output)
            return output
    except Exception:
        pass

    _store_cache(cleaned, None)
    return None


def prewarm_mermaid(code: str) -> None:
    """Background prewarm entry point for markdown scanner."""
    render_mermaid_to_ascii(code)


def _store_cache(key: str, value: Optional[str]) -> None:
    with _CACHE_LOCK:
        if key in _RENDER_CACHE:
            _RENDER_CACHE.move_to_end(key)
            _RENDER_CACHE[key] = value
            return
        if len(_RENDER_CACHE) >= _CACHE_MAX_SIZE:
            _RENDER_CACHE.popitem(last=False)
        _RENDER_CACHE[key] = value


def clear_mermaid_cache() -> None:
    """Clear in-memory render cache (useful for tests)."""
    with _CACHE_LOCK:
        _RENDER_CACHE.clear()
    _get_mermaid_binary.cache_clear()


def format_mermaid_content(diagram_str: str, dark: bool = True, theme_obj: Any = None) -> Content:
    """Format ASCII diagram with colored box drawing lines and arrows into Textual Content.

    Uses theme accent tokens when available, matching Johnston's palette aesthetic.
    Batches adjacent characters of identical style into single text spans for performance.
    """
    text = Text()

    box_color = getattr(theme_obj, "accent_info", None) if theme_obj is not None else None
    if not isinstance(box_color, str) or not box_color.strip():
        box_color = "#38bdf8" if dark else "#0284c7"

    arrow_color = getattr(theme_obj, "accent_warning", None) if theme_obj is not None else None
    if not isinstance(arrow_color, str) or not arrow_color.strip():
        arrow_color = "#f59e0b" if dark else "#d97706"

    box_style = f"bold {box_color}"
    arrow_style = f"bold {arrow_color}"

    current_style: str | None = None
    buf: list[str] = []

    for char in diagram_str:
        if char in _ARROW_CHARS:
            style = arrow_style
        elif char in _BOX_CHARS:
            style = box_style
        else:
            style = None

        if style == current_style:
            buf.append(char)
        else:
            if buf:
                text.append("".join(buf), style=current_style)
            buf = [char]
            current_style = style

    if buf:
        text.append("".join(buf), style=current_style)

    return Content.from_rich_text(text)
