"""Unified output buffer for task execution.

Deduplicates the buffering/formatting logic previously scattered across
background_task.py and shell.py: ANSI stripping, carriage-return collapsing,
a hard byte cap with a truncation marker, and real-time chunk streaming for
subscribers (UI).
"""

import asyncio
import re
from typing import AsyncGenerator, List, Optional

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
        self._subscribers: List["asyncio.Queue[str]"] = []

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
        # Broadcast to live subscribers (non-blocking; full queues drop).
        for q in list(self._subscribers):
            try:
                q.put_nowait(chunk)
            except asyncio.QueueFull:
                # Subscriber too slow; drop the oldest item to keep it fresh.
                try:
                    q.get_nowait()
                    q.put_nowait(chunk)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

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

    # -- streaming ----------------------------------------------------------

    async def stream(self) -> AsyncGenerator[str, None]:
        """Yield freshly appended chunks in real time.

        Subscription is bounded: once a subscriber drops out of the loop the
        queue is discarded. Buffered output present before subscription is not
        replayed (callers wanting that should use ``history``).
        """
        q: "asyncio.Queue[str]" = asyncio.Queue(maxsize=128)
        self._subscribers.append(q)
        try:
            while True:
                chunk = await q.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def close_stream(self) -> None:
        """Signal all active subscribers to stop (send a sentinel)."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
