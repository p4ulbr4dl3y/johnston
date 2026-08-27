"""Unified output buffer for task execution.

Deduplicates the buffering/formatting logic previously scattered across
background_task.py and shell.py: ANSI stripping, carriage-return collapsing,
and a hard byte cap with a truncation marker.
"""

import asyncio
import collections
import os
import queue
import re
import threading
import uuid
from typing import List, Optional

from core.infrastructure.platform.paths import LOGS_DIR

__all__ = [
    "OutputBuffer",
    "OutputLog",
    "make_log_path",
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
        self._chunks: collections.deque[str] = collections.deque()
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
                self._size -= len(self._chunks.popleft())

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


# ---------------------------------------------------------------------------
# Task output log
# ---------------------------------------------------------------------------


# Max length of the readable prefix in a log filename. Keeps snapshot paths
# short so the model does not waste tokens on long names in truncation hints.
MAX_LOG_PREFIX_CHARS = 40


def make_log_path(prefix: str = "", unique: bool = True, ext: str = ".log") -> Optional[str]:
    """Build a log/snapshot path under LOGS_DIR for a ``prefix``.

    Single naming scheme: ``{prefix}-{hex4}{ext}`` when ``unique`` is True,
    else ``{prefix}{ext}``. Prefix is sanitized (slashes -> underscores) and
    capped at ``MAX_LOG_PREFIX_CHARS``. Returns None if the directory could not
    be created / path is unusable.
    """
    ext = ("." + ext.lstrip(".")) if ext else ".log"
    prefix = re.sub(r"[/\\]+", "_", (prefix or "task").strip())[:MAX_LOG_PREFIX_CHARS] or "task"
    filename = prefix + (f"-{uuid.uuid4().hex[:4]}" if unique else "") + ext
    log_path = os.path.join(LOGS_DIR, filename)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        return log_path
    except Exception:
        return None


class OutputLog:
    """Streams raw task output to a log file under LOGS_DIR.

    Unlike the snapshot helpers (truncate_subagent_result / truncate_output),
    this appends decoded chunks as they arrive, so a long-running background
    process logs its entire output without any in-memory cap. The file handle is
    held open until ``close`` and flushed per chunk so the tail is durably
    observable on disk.

    Chunk extrusion (``append``) is non-blocking: writes are pushed onto a queue
    drained by a background worker thread, so the event loop is never blocked on
    disk I/O even for large logs. ``close`` drains the queue before releasing
    the file handle, preserving write order.
    """

    def __init__(self, path: str = "") -> None:
        self.path = path
        self._file = None
        self._closed = False
        self._queue = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        if path:
            try:
                self._file = open(path, "w", encoding="utf-8")
            except Exception:
                self._file = None
        if self._file is not None:
            self._thread = threading.Thread(target=self._worker, name="output-log", daemon=True)
            self._thread.start()

    @classmethod
    def create(cls, prefix: str = "") -> "OutputLog":
        """Open a fresh log for ``prefix``, or return a closed no-op on failure."""
        try:
            path = make_log_path(prefix, unique=False) or ""
        except Exception:
            path = ""
        return cls(path)

    @property
    def opened(self) -> bool:
        return self._file is not None

    def _worker(self) -> None:
        f = self._file
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    try:
                        f.flush()
                    except Exception:
                        pass
                    try:
                        f.close()
                    except Exception:
                        pass
                    break
                try:
                    f.write(item)
                    if self._queue.empty():
                        f.flush()
                except Exception:
                    pass
            finally:
                self._queue.task_done()

    # -- appending ----------------------------------------------------------

    def append(self, text: str) -> None:
        if self._file is None or self._closed:
            return
        if text is None:
            raise TypeError("OutputLog.append() argument must be str, not None")
        self._queue.put(text)

    def flush_now(self) -> None:
        """Synchronously drain the pending queue to disk.

        Blocks until all chunks submitted so far are flushed to the file. Used by
        synchronous readers (e.g. ``open_log`` backfill) that must observe the
        buffered output immediately without waiting for ``close``.
        """
        if self._file is None or self._thread is None:
            return
        self._queue.join()

    def close(self) -> None:
        if self._file is not None:
            self._file = None
        if self._thread is not None and self._thread.is_alive():
            # Sentinel drains any queued chunks (preserving write order) before
            # the worker flushes and closes the handle.
            self._queue.put(None)
            self._queue.join()
            self._thread = None
        self._closed = True

    async def close_async(self) -> None:
        """Async variant of close off the event loop."""
        await asyncio.to_thread(self.close)

    def __enter__(self) -> "OutputLog":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


MAX_SUBAGENT_RESULT_CHARS = 15000


def truncate_subagent_result(text: str, session_id: str = "") -> str:
    """Clip a subagent's final result so a verbose subagent does not flood the
    parent agent's context with a huge <task_result> block. The full session output
    is saved on truncation and the path is returned in the hint.
    """
    text = (text or "").strip()
    from tools.base import truncate_output

    return truncate_output(
        text,
        max_chars=MAX_SUBAGENT_RESULT_CHARS,
        tool_name=session_id or "subagent",
        ext=".md",
    )


def _write_result_log(content: str, *, session_id: str = "", ext: str = ".md") -> Optional[str]:
    """Writes full output to a unique file under LOGS_DIR and returns its path.

    Returns None if logging is skipped (empty content) or the write fails.
    """
    if not (content or "").strip():
        return None
    log_path = make_log_path(session_id or "subagent", ext=ext)
    if not log_path:
        return None
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        return None
    return log_path
