"""Unified output buffer for task execution.

Deduplicates the buffering/formatting logic previously scattered across
background_task.py and shell.py: ANSI stripping, carriage-return collapsing,
and a hard byte cap with a truncation marker.
"""

import os
import re
import uuid
from typing import List, Optional

from core.config import LOGS_DIR

__all__ = [
    "OutputBuffer",
    "strip_ansi",
    "process_carriage_returns",
    "tail_output",
    "truncate_subagent_result",
]

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Cap on retained raw output bytes for a task. Old chunks are dropped from the
# front (tail preserved) past this limit so `"".join` stays bounded.
_OUTPUT_BYTE_LIMIT = 300 * 1024  # 300 KB
_OUTPUT_TRUNCATED_MARKER = "[Output truncated: showing recent output]\n"


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


def process_carriage_returns(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    processed = []
    for line in lines:
        if "\r" in line:
            parts = [p for p in line.split("\r") if p]
            line = parts[-1] if parts else ""
        processed.append(line)

    filtered = []
    spinner_chars = {"-", "\\", "|", "/", "—"}
    for line in processed:
        stripped = line.strip()
        if stripped in spinner_chars and filtered and filtered[-1].strip() in spinner_chars:
            filtered[-1] = line
        else:
            filtered.append(line)
    return "\n".join(filtered)


class OutputBuffer:
    """Thread/async-safe ring buffer of raw output chunks with formatting."""

    def __init__(self, byte_limit: int = _OUTPUT_BYTE_LIMIT) -> None:
        self._chunks: List[str] = []
        self._size = 0
        self._truncated = False
        self._byte_limit = byte_limit

    # -- appending ----------------------------------------------------------

    def append(self, chunk: str) -> None:
        if not chunk:
            return
        self._chunks.append(chunk)
        self._size += len(chunk)
        if self._size > self._byte_limit:
            self._truncated = True
            # Drop old chunks from the front (tail preserved) until the size
            # no longer exceeds the full cap.
            while self._chunks and self._size > self._byte_limit:
                self._size -= len(self._chunks.pop(0))

    # -- reading ------------------------------------------------------------

    @property
    def history(self) -> List[str]:
        return list(self._chunks)

    @property
    def size_bytes(self) -> int:
        return self._size

    def __len__(self) -> int:
        return self._size

    def formatted(self, max_chars: Optional[int] = None) -> str:
        prefix = _OUTPUT_TRUNCATED_MARKER if self._truncated else ""
        raw = prefix + "".join(self._chunks)
        text = process_carriage_returns(strip_ansi(raw))
        if max_chars is None or len(text) <= max_chars:
            return text
        return text[-max_chars:]

    def tail(self, max_chars: int = 4000) -> str:
        return self.formatted(max_chars=max_chars)


def tail_output(text: str, max_chars: int = 2000) -> str:
    """Returns tail of text with a truncation notice if max_chars is exceeded."""
    if not text or len(text) <= max_chars:
        return text
    return f"... [Output truncated, showing last {max_chars} chars]\n{text[-max_chars:]}"


MAX_SUBAGENT_RESULT_CHARS = 15000


def truncate_subagent_result(text: str, session_id: str = "") -> str:
    """Clip a subagent's final result so a verbose subagent does not flood the
    parent agent's context with a huge <task_result> block. The full session log
    is saved on truncation and the path is returned in the hint.
    """
    text = (text or "").strip()
    if len(text) <= MAX_SUBAGENT_RESULT_CHARS:
        return text

    log_path = _write_result_log(text, session_id=session_id or "subagent") or "log file"
    truncated = text[:MAX_SUBAGENT_RESULT_CHARS]
    shown_lines = truncated.count("\n") + (1 if truncated else 0)
    next_line = shown_lines + 1
    return (
        truncated
        + f"\n... [Subagent result truncated at {MAX_SUBAGENT_RESULT_CHARS} chars (lines 1-{shown_lines} shown). Full log saved to {log_path}. Use `read` tool (path='{log_path}', start_line={next_line}) to inspect remaining output.]"
    )


def _write_result_log(content: str, *, session_id: str = "") -> Optional[str]:
    """Writes full output to a unique log file under LOGS_DIR and returns its path.

    Returns None if logging is skipped (empty content) or the write fails.
    """
    if not (content or "").strip():
        return None
    filename = f"{session_id}-{uuid.uuid4().hex[:4]}.log"
    log_path = os.path.join(LOGS_DIR, filename)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        return None
    return log_path
