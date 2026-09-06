"""Mermaid diagram detection and ASCII/Unicode terminal rendering."""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Optional

from rich.text import Text
from textual.content import Content

_BOX_CHARS = frozenset("┌┐└┘├┤┬┴┼─│━┃╭╮╰╯═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬◄►▲▼◀▶◆◇○●┄┈┆┊")
_RENDER_CACHE: dict[str, Optional[str]] = {}
_CACHE_MAX_SIZE = 256


def is_mermaid(language: str | None) -> bool:
    """Return True if the fence language indicates a Mermaid diagram."""
    clean = (language or "").strip().lower()
    return clean in ("mermaid", "mmd")


def _get_mermaid_binary() -> Optional[str]:
    """Locate mermaid-ascii binary from python package or system PATH."""
    try:
        import mermaid_ascii

        if hasattr(mermaid_ascii, "_resolve_binary"):
            return mermaid_ascii._resolve_binary()
    except Exception:
        pass
    return shutil.which("mermaid-ascii") or shutil.which("mermaid-ascii.exe")


def clean_mermaid_code(code: str) -> str:
    """Strip code fence markers or trailing whitespace if present."""
    if not code:
        return ""
    lines = code.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


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
            diff = len(chunk) - len(decoded)
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


def render_mermaid_to_ascii(code: str, timeout: float = 2.0) -> Optional[str]:
    """Render mermaid code to ASCII/Unicode diagram string using mermaid-ascii.

    Returns rendered diagram string or None on syntax error / missing binary.
    Caches results in-memory.
    """
    cleaned = clean_mermaid_code(code)
    if not cleaned:
        return None

    if cleaned in _RENDER_CACHE:
        return _RENDER_CACHE[cleaned]

    binary = _get_mermaid_binary()
    if not binary:
        _store_cache(cleaned, None)
        return None

    try:
        res = subprocess.run(
            [binary],
            input=cleaned,
            text=True,
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
    if len(_RENDER_CACHE) >= _CACHE_MAX_SIZE:
        try:
            _RENDER_CACHE.pop(next(iter(_RENDER_CACHE)))
        except Exception:
            _RENDER_CACHE.clear()
    _RENDER_CACHE[key] = value


def clear_mermaid_cache() -> None:
    """Clear in-memory render cache (useful for tests)."""
    _RENDER_CACHE.clear()


def format_mermaid_content(diagram_str: str, dark: bool = True) -> Content:
    """Format ASCII diagram with colored box drawing lines into Textual Content."""
    text = Text()
    box_style = "bold #38bdf8" if dark else "bold #0284c7"
    for char in diagram_str:
        if char in _BOX_CHARS:
            text.append(char, style=box_style)
        else:
            text.append(char)
    return Content.from_rich_text(text)
