"""Chat tool call widget and presentation components."""
from __future__ import annotations

import json
import re

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, Static

from core.infrastructure.config.settings import get_settings
from core.infrastructure.tasks.output import strip_ansi
from widgets.presentation.screens.constants import TOOL_HEADER, TOOL_HEADER_EXPANDABLE, TOOL_SCROLL_BOX
from widgets.presentation.tool_mixins import FormattingMixin, ParsingMixin
from widgets.presentation.tool_renderers import format_truncation_for_ui
from widgets.presentation.toolcall_actions import ToolCallActionsMixin
from widgets.presentation.toolcall_content import ToolCallContentMixin
from widgets.presentation.toolcall_hints import ToolCallHintsMixin
from widgets.presentation.toolcall_shell import (
    ToolCallShellMixin,
    bash_ends_with_spinner,
    bash_safe_boundary,
)
from widgets.presentation.widgets.chat_markdown import TransparentSyntax

DISPLAY_NAMES: dict[str, str] = {
    "read": "Read",
    "create": "Create",
    "edit": "Edit",
    "shell": "Shell",
    "search": "Search",
    "ask_user": "AskUser",
    "kill": "Kill",
    "invoke_subagent": "InvokeSubagent",
    "message_subagent": "MessageSubagent",
    "web_fetch": "WebFetch",
    "update_plan": "UpdatePlan",
}

SYSTEM_TOOLS: frozenset[str] = frozenset(DISPLAY_NAMES.keys())

_bash_safe_boundary = bash_safe_boundary
_bash_ends_with_spinner = bash_ends_with_spinner


class ToolScrollBox(Vertical):
    """Horizontal scroll box for tool code/diff view."""

    pass


class ToolCallWidget(
    ToolCallContentMixin,
    ToolCallActionsMixin,
    ToolCallHintsMixin,
    ToolCallShellMixin,
    FormattingMixin,
    ParsingMixin,
    Vertical,
):
    """Tool call widget (Create, Read, Edit, Shell) with expansion support."""

    can_focus = False
    ALLOW_SELECT = False

    EXPANDABLE_TOOLS = {
        "create",
        "edit",
        "shell",
        "search",
        "update_plan",
    }

    DISPLAY_NAMES = DISPLAY_NAMES
    SYSTEM_TOOLS = SYSTEM_TOOLS

    @property
    def _RAW_BASH_LIMIT(self) -> int:
        return get_settings().tools.shell_stream_buffer_bytes

    def __init__(
        self,
        tool_type: str,
        target: str,
        result_text: str = "",
        is_sequential: bool = False,
        args: dict = None,
        status: str = None,
        returncode: int = None,
        is_mcp: bool = False,
        subagent_session_id: str = None,
        background_task_id: str = None,
        log_path: str = None,
    ):
        classes = f"tool-call tool-{(tool_type or '').lower()}"
        if is_sequential:
            classes += " tool-sequential"
        super().__init__(classes=classes)
        from core.infrastructure.runtime.tool_name import normalize_tool_name

        self.is_sequential = is_sequential
        self.tool_type = tool_type
        self.canonical_tool = normalize_tool_name(tool_type)
        if isinstance(target, str):
            target = re.sub(r"\s+", " ", target.replace("\n", " ").replace("\r", " ")).strip()
        self.target = target
        self.result_text = result_text
        self.args = dict(args) if isinstance(args, dict) else {}
        self.returncode = returncode
        self.is_mcp = is_mcp
        self.is_expanded = False
        self.background_task_id = background_task_id
        self.log_path: str | None = log_path
        self.task_id: str | None = None
        self.subagent_session_id: str | None = str(subagent_session_id) if subagent_session_id is not None else None
        if not self.subagent_session_id and hasattr(self, "bind_subagent_session"):
            self.bind_subagent_session()
        self.tool_call_id: str | None = None
        self.tool_call_index: int | None = None
        self._shell_update_scheduled = False
        self._shell_update_handle = None
        self._show_hints = False
        self._hint_handle = None
        # Incremental shell-stream flush state (see _flush_shell_update).
        self._bash_processed_len = 0
        self._bash_needs_resync = False
        self._rendered_bash_tail = ""
        self._bash_tail_line_is_spinner = False
        self._bash_leading_stripped = False
        if status is not None:
            self.status = status
        else:
            self.status = "running" if not result_text else "done"
        if self.status == "running":
            self._schedule_hint_timer()

        is_clickable = self.is_clickable_header()
        header_cls = f"{TOOL_HEADER} {TOOL_HEADER_EXPANDABLE}" if is_clickable else TOOL_HEADER
        self.header_label = Label("", classes=header_cls)
        self.content_widget = Static("", classes="tool-content", markup=False)
        self.md_widget = Markdown("", classes="tool-content-md")
        self.scroll_box = ToolScrollBox(self.content_widget, self.md_widget, classes=TOOL_SCROLL_BOX)
        self.scroll_box.display = False

    def is_expandable(self) -> bool:
        if self.status == "generating":
            return False
        from core.infrastructure.runtime.tool_name import normalize_tool_name

        canonical = getattr(self, "canonical_tool", None) or normalize_tool_name(self.tool_type)
        if canonical == "shell":
            return True
        if self.status in ("error", "cancelled"):
            return False
        if canonical == "ask_user":
            return bool((self.result_text or "").strip())
        if canonical == "read":
            res = (self.result_text or "").lstrip()
            return res.startswith(("[dir", "[archive"))
        if canonical in (
            "web_fetch",
            "invoke_subagent",
            "kill",
            "message_subagent",
        ):
            return False
        if canonical in self.EXPANDABLE_TOOLS:
            return True
        if hasattr(self, "SYSTEM_TOOLS") and self.tool_type not in self.SYSTEM_TOOLS:
            return True
        return self.tool_type in self.EXPANDABLE_TOOLS

    def _clean_hints_for_ui(self, text: str) -> str:
        return format_truncation_for_ui(text)

    def _clean_markup_text(self, text: str) -> str:
        if not text:
            return ""
        clean = self._clean_hints_for_ui(text)
        if "\x1b" in clean:
            clean = strip_ansi(clean)
        return clean

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.scroll_box

    def on_mount(self) -> None:
        if self.is_expanded and self.is_expandable():
            self.scroll_box.display = True
            self._should_scroll_on_render = self._is_parent_at_bottom()
            self.render_content()
        else:
            self.scroll_box.display = False
            self.content_widget.display = False
            self.md_widget.display = False
        if self.is_clickable_header():
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)
        else:
            self.header_label.add_class(TOOL_HEADER)
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
        self.render_header()
        self._sync_sequential_with_prev()
        if self.status == "running" and self.is_expandable():
            parent = getattr(self, "parent", None)
            if parent is not None and getattr(parent, "_has_active_hints", False):
                if hasattr(parent, "activate_hint"):
                    self._cancel_hint_timer()
                    parent.activate_hint(self)

    def on_unmount(self) -> None:
        self._cancel_hint_timer()
        parent = getattr(self, "parent", None)
        if parent is not None and getattr(parent, "_active_hint_widget", None) is self:
            if hasattr(parent, "clear_active_hints"):
                parent.clear_active_hints(immediate=True)
        self._cancel_shell_update()
        if getattr(self, "_render_gate", None) is not None:
            try:
                self._render_gate.cancel()
            except Exception:
                pass
            self._render_gate = None
        try:
            try:
                app = getattr(self, "app", None)
            except Exception:
                app = None
            if app is None:
                app = getattr(self, "_app", None)
            if app is not None and hasattr(app, "_background_shell_widgets") and isinstance(app._background_shell_widgets, dict):
                tid = getattr(self, "background_task_id", None)
                if tid:
                    app._background_shell_widgets.pop(tid, None)
                for k, v in list(app._background_shell_widgets.items()):
                    if v is self:
                        app._background_shell_widgets.pop(k, None)
        except Exception:
            pass

    def mark_background(self, task_id: str, log_path: str | None = None) -> None:
        """Mark the tool card as moved to background task."""
        self.background_task_id = task_id
        if log_path:
            self.log_path = log_path
        self.render_header()

    def set_result(
        self,
        result_text: str,
        is_error: bool = False,
        status: str = None,
        returncode: int = None,
        background_task_id: str | None = None,
        log_path: str | None = None,
    ) -> None:
        """Apply a tool's terminal/streamed result to the card."""
        if not isinstance(result_text, str):
            result_text = json.dumps(result_text, ensure_ascii=False) if result_text is not None else ""
        cleaned = (result_text or "").strip()
        if status is not None:
            self.status = status
            if returncode is not None:
                self.returncode = returncode
        elif is_error:
            self.status = "error"
        else:
            self.status = "done"

        if background_task_id:
            self.background_task_id = background_task_id
        if log_path:
            self.log_path = log_path

        if getattr(self, "canonical_tool", None) in ("invoke_subagent", "message_subagent") and not self.subagent_session_id:
            if hasattr(self, "bind_subagent_session"):
                self.bind_subagent_session()

        if self.canonical_tool == "shell":
            if status != "running":
                self._cancel_shell_update()
                self.result_text = cleaned
        else:
            self.result_text = cleaned

        if self.status != "running":
            self._cancel_hint_timer()
            parent = getattr(self, "parent", None)
            if parent is not None and hasattr(parent, "on_widget_finished"):
                parent.on_widget_finished(self)
            else:
                self._show_hints = False
        else:
            self._schedule_hint_timer()

        if not self.is_clickable_header():
            was_expanded = self.is_expanded
            self.is_expanded = False
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
            self.scroll_box.display = False
            self.content_widget.display = False
            self.md_widget.display = False
            if was_expanded:
                self._update_next_sibling_spacing()
        else:
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)
            parent = getattr(self, "parent", None)
            if getattr(parent, "auto_expand_all", False) and self.is_expandable():
                self.is_expanded = True
                self.scroll_box.display = True
        self.render_header()
        if self.is_expanded:
            self.scroll_box.display = True
            self._should_scroll_on_render = self._is_parent_at_bottom()
            self.render_content()
            self._update_next_sibling_spacing()

    def mark_cancelled(self) -> None:
        """Mark an interrupted tool call as cancelled."""
        if self.status not in ("running", "generating"):
            return
        self.status = "cancelled"
        self._cancel_hint_timer()
        parent = getattr(self, "parent", None)
        if parent is not None and hasattr(parent, "clear_active_hints"):
            parent.clear_active_hints(immediate=True)
        self._show_hints = False
        clean = (self.result_text or "").strip()
        if not clean:
            self.result_text = "[interrupted | tool cancelled]"
        elif "[interrupted" not in clean:
            self.result_text = f"{clean}\n[interrupted | command cancelled]"
        self._cancel_shell_update()
        if not self.is_clickable_header():
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
            self.scroll_box.display = False
            self.content_widget.display = False
            self.md_widget.display = False
        else:
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)
        self.render_header()

    def mark_generating(self, text: str = "") -> None:
        """Mark the tool card as generating (yellow hollow circle) with optional status text."""
        self.status = "generating"
        self._cancel_hint_timer()
        self._show_hints = False
        if text:
            self.result_text = text.strip()
        self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
        self.header_label.add_class(TOOL_HEADER)
        self.scroll_box.display = False
        self.content_widget.display = False
        self.md_widget.display = False
        self.render_header()

    def mark_running(self, text: str = "") -> None:
        """Mark the tool card as running (yellow) with optional status text."""
        self.status = "running"
        self._schedule_hint_timer()
        if text:
            self.result_text = text.strip()
        if not self.is_clickable_header():
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
        else:
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)

        parent = getattr(self, "parent", None)
        if getattr(parent, "auto_expand_all", False) and self.is_expandable() and not self.is_expanded:
            self.set_expanded(True, scroll=False)
        else:
            self.render_header()

    def update_tool_call(self, target: str = None, args: dict = None) -> None:
        """Update target and/or args during streaming and re-render header."""
        if target is not None:
            if isinstance(target, str):
                target = re.sub(r"\s+", " ", target.replace("\n", " ").replace("\r", " ")).strip()
            self.target = target
        if args is not None and isinstance(args, dict):
            self.args.update(args)
        if not self.is_clickable_header():
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
        else:
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)
        self.render_header()

    def set_expanded(self, expanded: bool, scroll: bool = False) -> None:
        if not self.is_expandable():
            return
        if self.is_expanded == expanded:
            return
        self.is_expanded = expanded
        self.render_header()
        if self.is_expanded:
            self.scroll_box.display = True
            if getattr(self, "_shell_update_scheduled", False):
                self._flush_shell_update()
            self._should_scroll_to_widget = scroll
            self.render_content()
        else:
            self._should_scroll_to_widget = False
            self.scroll_box.display = False
            self.content_widget.display = False
            self.md_widget.display = False
        self._update_next_sibling_spacing()

    def toggle_expanded(self, scroll: bool = True) -> None:
        self.set_expanded(not self.is_expanded, scroll=scroll)


__all__ = [
    "DISPLAY_NAMES",
    "FormattingMixin",
    "ParsingMixin",
    "SYSTEM_TOOLS",
    "ToolCallActionsMixin",
    "ToolCallContentMixin",
    "ToolCallHintsMixin",
    "ToolCallShellMixin",
    "ToolCallWidget",
    "ToolScrollBox",
    "TransparentSyntax",
    "_bash_ends_with_spinner",
    "_bash_safe_boundary",
    "format_truncation_for_ui",
]
