"""Shell streaming helpers and mixin for ToolCallWidget."""
from __future__ import annotations

import asyncio
import re

from johnston.core.infrastructure.config.settings import get_settings
from johnston.core.infrastructure.tasks.output import (
    is_spinner_line,
    process_carriage_returns,
    process_carriage_returns_lines,
)
from johnston.tui.presentation.tool_renderers import format_truncation_for_ui

_TRUNC_BANNER_START = re.compile(r"(?:\.\.\.\s*)?\[(?:Output\s+truncated|Truncated)", re.IGNORECASE)


def _format_trunc(text: str, *, strip_edges: bool = True) -> str:
    import sys

    mod = sys.modules.get("johnston.tui.presentation.widgets.chat_toolcall")
    fn = getattr(mod, "format_truncation_for_ui", format_truncation_for_ui)
    return fn(text, strip_edges=strip_edges)


def bash_safe_boundary(examine: str) -> int:
    """Byte offset in ``examine`` up to which the flush can commit safely."""
    boundary = examine.rfind("\n") + 1
    committed = examine[:boundary]
    last_close = committed.rfind("]")
    for m in _TRUNC_BANNER_START.finditer(committed):
        if m.start() > last_close:
            boundary = examine.rfind("\n", 0, m.start()) + 1
            break
    return boundary


def bash_ends_with_spinner(text: str) -> bool:
    """True when the last line of ``text`` is a single spinner character."""
    if not text:
        return False
    return is_spinner_line(text.rsplit("\n", 1)[-1])


def compose_bash_result(
    tail: str,
    carry_raw: str,
    tail_line_is_spinner: bool,
    leading_stripped: bool,
) -> str:
    """Reconstruct ``result_text`` from the committed tail + carried remainder."""
    if carry_raw:
        part = process_carriage_returns(_format_trunc(carry_raw, strip_edges=False).rstrip())
        if tail and tail_line_is_spinner and "\n" not in part and is_spinner_line(part):
            nl = tail.rfind("\n")
            tail = (tail[: nl + 1] if nl != -1 else "") + part
        else:
            tail = f"{tail}\n{part}" if tail else part
    if leading_stripped:
        return tail.rstrip()
    return tail.strip()


class ToolCallShellMixin:
    """Incremental shell stream buffer management and delta flushing."""

    _RAW_BASH_TRUNC = "[…[truncated]]\n"

    @property
    def _RAW_BASH_LIMIT(self) -> int:
        import sys

        mod = sys.modules.get("johnston.tui.presentation.widgets.chat_toolcall")
        fn = getattr(mod, "get_settings", None) if mod else None
        if fn is not None:
            return fn().tools.shell_stream_buffer_bytes
        return get_settings().tools.shell_stream_buffer_bytes

    def append_shell_output(self, text: str) -> None:
        if not hasattr(self, "_raw_bash_buffer"):
            self._raw_bash_buffer = ""
        self._raw_bash_buffer += text
        if len(self._raw_bash_buffer) > self._RAW_BASH_LIMIT:
            self._raw_bash_buffer = self._RAW_BASH_TRUNC + self._raw_bash_buffer[-self._RAW_BASH_LIMIT :]
            # The front of the buffer was cut: the processed offset and the
            # rendered tail are stale, so the next flush must re-sync.
            self._bash_needs_resync = True
        self._schedule_shell_update()

    def _schedule_shell_update(self) -> None:
        if getattr(self, "_shell_update_scheduled", False):
            return
        self._shell_update_scheduled = True
        import sys

        mod = sys.modules.get("johnston.tui.presentation.widgets.chat_toolcall")
        fn = getattr(mod, "get_settings", None) if mod else None
        interval = (fn() if fn else get_settings()).ui.stream_flush_interval
        try:
            loop = asyncio.get_running_loop()
            self._shell_update_handle = loop.call_later(interval, self._flush_shell_update)
        except RuntimeError:
            self._flush_shell_update()

    def _cancel_shell_update(self) -> None:
        if getattr(self, "_shell_update_handle", None) is not None:
            try:
                self._shell_update_handle.cancel()
            except Exception:
                pass
            self._shell_update_handle = None
        self._shell_update_scheduled = False

    def _flush_shell_update(self) -> None:
        """Incrementally fold the shell stream delta into the rendered tail.

        Only the bytes appended since the previous flush are re-processed
        (truncation-banner cleanup + carriage-return collapsing), so a growing
        ``_RAW_BASH_LIMIT`` buffer is no longer fully re-processed on every
        flush.
        """
        self._shell_update_scheduled = False
        self._shell_update_handle = None

        buf = getattr(self, "_raw_bash_buffer", "")
        if getattr(self, "_bash_needs_resync", False):
            # The raw buffer front was cut to respect _RAW_BASH_LIMIT: the
            # offset and rendered tail are stale, so fall back to reprocessing
            # the buffer from scratch (rare, amortized O(limit) per eviction).
            self._bash_needs_resync = False
            self._bash_processed_len = 0
            self._rendered_bash_tail = ""
            self._bash_tail_line_is_spinner = False
            self._bash_leading_stripped = False

        processed = getattr(self, "_bash_processed_len", 0)
        carry_raw = ""
        if len(buf) > processed:
            examine = buf[processed:]
            boundary = bash_safe_boundary(examine)
            commit_raw = examine[:boundary]
            carry_raw = examine[boundary:]
            if commit_raw:
                cleaned = _format_trunc(commit_raw, strip_edges=False)
                if cleaned and not cleaned.endswith("\n"):
                    # A truncation banner swallowed the trailing newline: reprocess
                    # the whole buffer like the legacy path to stay byte-identical.
                    self.result_text = process_carriage_returns(self._clean_bash_output(buf))
                    self._bash_processed_len = len(buf)
                    self._rendered_bash_tail = self.result_text
                    self._bash_tail_line_is_spinner = bash_ends_with_spinner(self.result_text)
                    self._bash_leading_stripped = True
                    if getattr(self, "is_expanded", False):
                        self.render_content()
                        self._scroll_if_needed()
                    return
                lines = cleaned.split("\n")[:-1]
                leading_stripped = getattr(self, "_bash_leading_stripped", False)
                if not leading_stripped:
                    for i, ln in enumerate(lines):
                        lstripped = ln.lstrip()
                        if lstripped:
                            lines = [lstripped] + lines[i + 1 :]
                            leading_stripped = True
                            break
                    else:
                        lines = []
                tail, is_spinner = process_carriage_returns_lines(
                    lines,
                    tail=getattr(self, "_rendered_bash_tail", ""),
                    tail_is_spinner=getattr(self, "_bash_tail_line_is_spinner", False),
                )
                self._bash_processed_len = processed + boundary
                self._rendered_bash_tail = tail
                self._bash_tail_line_is_spinner = is_spinner
                self._bash_leading_stripped = leading_stripped

        result_text = self._bash_compose_result(carry_raw)
        if result_text != getattr(self, "result_text", ""):
            self.result_text = result_text
            if getattr(self, "is_expanded", False):
                self.render_content()
                self._scroll_if_needed()

    def _bash_compose_result(self, carry_raw: str) -> str:
        return compose_bash_result(
            tail=getattr(self, "_rendered_bash_tail", ""),
            carry_raw=carry_raw,
            tail_line_is_spinner=getattr(self, "_bash_tail_line_is_spinner", False),
            leading_stripped=getattr(self, "_bash_leading_stripped", False),
        )
