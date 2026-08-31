"""Shared helpers for the document converter package."""

import re
import zipfile
from typing import List, Optional

# Decompression limits: a crafted office document (which is a ZIP
# of XML parts) may expand enormously. Converters must never read more than
# this cap from a single member.
MAX_MEMBER_BYTES = 64 * 1024 * 1024  # 64 MiB per archive member

_CHUNK_SIZE = 1024 * 1024


def collapse_blank_lines(text: str) -> str:
    """Collapse runs of multiple blank lines to one, outside fenced code.

    Unlike a plain ``re.sub(r"\\n{3,}", "\\n\\n", ...)`` over the whole
    document, fenced code blocks are left untouched so embedded code content
    is preserved verbatim. Fence handling follows the CommonMark rule: an
    opening fence is a line starting with 3+ backticks; a fence closes on a
    line of backticks at least as long as the opening fence.
    """
    lines = text.split("\n")
    out: List[str] = []
    in_fence = False
    fence_len = 0
    blank_run = 0
    for line in lines:
        stripped = line.lstrip().rstrip()
        ticks = 0
        if stripped.startswith("`"):
            ticks = len(stripped) - len(stripped.lstrip("`"))
        if in_fence:
            if ticks >= fence_len and stripped == "`" * ticks:
                in_fence = False
                fence_len = 0
            out.append(line)
        elif ticks >= 3:
            in_fence = True
            fence_len = ticks
            blank_run = 0
            out.append(line)
        elif not line.strip():
            blank_run += 1
            if blank_run <= 1:
                out.append(line)
        else:
            blank_run = 0
            out.append(line)
    return "\n".join(out)


def fenced_code_block(text: str, lang: str = "") -> str:
    """Wrap ``text`` in a code fence.

    The fence is lengthened when the text itself contains backtick runs, per
    CommonMark (a fence must be longer than any backtick run inside).
    """
    max_run = 0
    for match in re.finditer(r"`+", text):
        max_run = max(max_run, len(match.group(0)))
    fence = "`" * max(3, max_run + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


def safe_read_zip_member(
    zf: zipfile.ZipFile, name: str, max_bytes: Optional[int] = None
) -> bytes:
    """Read a zip member in chunks, aborting if decompressed size exceeds a cap.

    Raises ``ValueError`` when the member is too large; callers treat this
    like any other unreadable member (skip it or propagate the failure).
    """
    limit = MAX_MEMBER_BYTES if max_bytes is None else max_bytes
    total = 0
    chunks: List[bytes] = []
    with zf.open(name) as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError(f"zip member '{name}' exceeds {limit} decompressed bytes")
            chunks.append(chunk)
    return b"".join(chunks)


def clean_url(url: str) -> str:
    """Make a URL safe inside a Markdown inline link: spaces become %20 and
    unbalanced parentheses are escaped (balanced ones are valid as-is)."""
    url = url.replace(" ", "%20")
    if url.count("(") != url.count(")"):
        url = url.replace("(", "\\(").replace(")", "\\)")
    return url

