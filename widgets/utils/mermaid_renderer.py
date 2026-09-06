"""Mermaid diagram detection and ASCII/Unicode terminal rendering."""

from __future__ import annotations

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
            output = res.stdout.rstrip()
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
