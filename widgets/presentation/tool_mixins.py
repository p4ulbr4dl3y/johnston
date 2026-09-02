"""Mixins for tool call parsing and formatting."""
from __future__ import annotations

import json
from typing import Any

from rich.text import Text

from widgets.presentation.tool_renderers import (
    format_code_with_line_numbers,
    format_manage_shell_display,
    format_manage_subagent_display,
    format_plan_display,
    format_truncation_for_ui,
)
from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.utils.lexer import guess_lexer_name

_MISSING = object()


class FormattingMixin:
    """Read/Edit/Plan formatting helpers for tool widgets."""

    _lexer_cache: dict[str, str] = {}

    def _guess_lexer(self, path_str: str) -> str:
        cache = self._lexer_cache
        cached = cache.get(path_str)
        if cached is not None:
            return cached
        name = guess_lexer_name(path_str)
        if len(cache) >= 256:
            cache.clear()
        cache[path_str] = name
        return name

    def _format_plan_display(self, plan_items: list, explanation: str) -> Text:
        return format_plan_display(plan_items, explanation)

    def _format_manage_shell_display(self) -> Any:
        return format_manage_shell_display(self.result_text or "")

    def _format_manage_subagent_display(self) -> Any:
        return format_manage_subagent_display(self.result_text or "")

    def _format_edit_diff(self, diff_text: str, file_path: str) -> Any:
        diff_text = self._clean_hints_for_ui(diff_text)
        return format_edit_diff(diff_text, file_path)

    def _clean_bash_output(self, text: str) -> str:
        return format_truncation_for_ui(text)

    def _format_code_with_line_numbers(self, code: str) -> str:
        return format_code_with_line_numbers(code)


class ParsingMixin:
    """Status / JSON / MCP-args parsing helpers for tool widgets."""

    _JSON_PARSE_CACHE_LIMIT = 64

    def _try_parse_json(self, text: str) -> Any:
        cache = getattr(self, "_json_parse_cache", None)
        if cache is None:
            cache = {}
            self._json_parse_cache = cache
        cached = cache.get(text, _MISSING)
        if cached is not _MISSING:
            return cached
        parsed = self._parse_json(text)
        if len(cache) >= self._JSON_PARSE_CACHE_LIMIT:
            cache.clear()
        cache[text] = parsed
        return parsed

    def _parse_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            pass
        if not text or not (text.startswith("{") or text.startswith("[")):
            return None
        stack = []
        in_string = False
        escaped = False
        for char in text:
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char in "[{":
                stack.append(char)
            elif char == "]" and stack and stack[-1] == "[":
                stack.pop()
            elif char == "}" and stack and stack[-1] == "{":
                stack.pop()

        repair = ""
        if in_string:
            repair += '"'
        for opener in reversed(stack):
            if opener == "[":
                repair += "]"
            elif opener == "{":
                repair += "}"

        try:
            return json.loads(text + repair)
        except Exception:
            return None

    def _format_json_result(self, raw_text: str) -> str | None:
        if not raw_text or not raw_text.strip():
            return None
        text = raw_text.strip()
        footer = ""
        if "\n... [Output truncated" in text:
            parts = text.split("\n... [Output truncated", 1)
            text_to_parse = parts[0].strip()
            footer = "... [Output truncated" + parts[1]
        else:
            text_to_parse = text

        parsed = self._try_parse_json(text_to_parse)
        if parsed is not None:
            pretty_json = json.dumps(parsed, indent=2, ensure_ascii=False)
            if footer:
                return f"{pretty_json}\n{footer.strip()}"
            return pretty_json
        return None

    def _is_error(self, text: str = "") -> bool:
        """True when the tool card is in error/cancelled state or returned non-zero exit code."""
        return self.status in ("error", "cancelled") or (self.returncode is not None and self.returncode != 0)

    def _get_status_color(self) -> str:
        """Status dot colour, taken from the active theme (P1-5).

        The old module-level constants were tuned for one dark theme and went
        through no contrast check, so on light themes the dot and the tool name
        beside it dropped to ~2.3:1.
        """
        from widgets.utils.theme_colors import status_color

        if self.status == "running":
            return status_color("running")
        elif self.status in ("error", "cancelled") or (self.returncode is not None and self.returncode != 0):
            return status_color("error")
        else:
            return status_color("success")
