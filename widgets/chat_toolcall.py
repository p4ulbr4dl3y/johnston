"""Chat tool call widget and presentation components."""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, Static

from core.infrastructure.config.settings import get_settings
from widgets.presentation.screens.constants import TOOL_HEADER, TOOL_HEADER_EXPANDABLE, TOOL_SCROLL_BOX
from widgets.presentation.tool_mixins import FormattingMixin, ParsingMixin
from widgets.presentation.tool_renderers import (
    build_synthetic_create_diff,
    clean_truncation_marker,
    compute_tool_call_content,
    format_ask_user_display,
    format_manage_shell_display,
    format_manage_subagent_display,
    format_plan_display,
    format_truncation_for_ui,
)
from widgets.presentation.widgets.chat_markdown import (
    TransparentSyntax,
    safe_update_markdown,
    to_snake_case,
)

# Re-exports for backwards compatibility and test imports
_clean_truncation_marker = clean_truncation_marker
_format_truncation_for_ui = format_truncation_for_ui

DISPLAY_NAMES: dict[str, str] = {
    "read": "Read",
    "create": "Create",
    "edit": "Edit",
    "shell": "Shell",
    "ask_user": "AskUser",
    "manage_shell": "ManageShell",
    "invoke_subagent": "InvokeSubagent",
    "manage_subagent": "ManageSubagent",
    "web_fetch": "WebFetch",
    "update_plan": "UpdatePlan",
}

SYSTEM_TOOLS: frozenset[str] = frozenset(DISPLAY_NAMES.keys())


class ToolScrollBox(Vertical):
    """Horizontal scroll box for tool code/diff view."""

    pass


class ToolCallWidget(FormattingMixin, ParsingMixin, Vertical):
    """Tool call widget (Create, Read, Edit, Shell) with expansion support."""

    can_focus = False
    ALLOW_SELECT = False

    EXPANDABLE_TOOLS = {
        "create",
        "edit",
        "shell",
        "update_plan",
    }

    DISPLAY_NAMES = DISPLAY_NAMES
    SYSTEM_TOOLS = SYSTEM_TOOLS

    _RAW_BASH_LIMIT = 200 * 1024  # 200 KB retained raw buffer
    _RAW_BASH_TRUNC = "[…[truncated]]\n"

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
        self.args = args if isinstance(args, dict) else {}
        self.returncode = returncode
        self.is_mcp = is_mcp
        self.is_expanded = False
        self.background_task_id = None
        self.log_path: str | None = None
        self.task_id: str | None = None
        self.subagent_session_id: str | None = None
        self._shell_update_scheduled = False
        self._shell_update_handle: asyncio.TimerHandle | None = None
        if status is not None:
            self.status = status
        else:
            self.status = "running" if not result_text else "done"

        is_clickable = self.is_clickable_header()
        header_cls = f"{TOOL_HEADER} {TOOL_HEADER_EXPANDABLE}" if is_clickable else TOOL_HEADER
        self.header_label = Label("", classes=header_cls)
        self.content_widget = Static("", classes="tool-content", markup=False)
        self.md_widget = Markdown("", classes="tool-content-md")
        self.scroll_box = ToolScrollBox(self.content_widget, self.md_widget, classes=TOOL_SCROLL_BOX)

    def is_expandable(self) -> bool:
        from core.infrastructure.runtime.tool_name import normalize_tool_name

        canonical = getattr(self, "canonical_tool", None) or normalize_tool_name(self.tool_type)
        if canonical == "shell":
            return True
        if self.status in ("error", "cancelled"):
            return False
        if canonical == "ask_user":
            return "Answer:" in (self.result_text or "")
        if canonical in (
            "read",
            "web_fetch",
            "invoke_subagent",
            "manage_shell",
            "manage_subagent",
        ):
            return False
        if canonical in self.EXPANDABLE_TOOLS:
            return True
        if hasattr(self, "SYSTEM_TOOLS") and self.tool_type not in self.SYSTEM_TOOLS:
            return True
        return self.tool_type in self.EXPANDABLE_TOOLS

    def is_clickable_header(self) -> bool:
        if self.status in ("error", "cancelled"):
            return (
                self.canonical_tool == "shell" and bool((self.result_text or "").strip())
            )
        if self.canonical_tool == "manage_shell":
            action = self.args.get("action", "list")
            return (action or "list").lower() == "list"
        if self.canonical_tool == "manage_subagent":
            args = self.args
            action = (args.get("action") or "list").lower()
            return bool(getattr(self, "subagent_session_id", None) or args.get("session_id") or action == "list")
        return (
            self.is_expandable()
            or self.canonical_tool in ("invoke_subagent", "ask_user")
        )

    def _clean_hints_for_ui(self, text: str) -> str:
        return format_truncation_for_ui(text)

    def _clean_markup_text(self, text: str) -> str:
        if not text:
            return ""
        clean = self._clean_hints_for_ui(text)
        if "\x1b" in clean:
            clean = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", clean)
        return clean

    def _is_parent_at_bottom(self) -> bool:
        try:
            from textual.containers import VerticalScroll

            parent = getattr(self, "parent", None)
            if isinstance(parent, VerticalScroll):
                return getattr(parent, "is_at_bottom", lambda: True)()
        except Exception:
            pass
        return True

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.scroll_box

    def on_mount(self) -> None:
        if self.is_expanded and self.is_expandable():
            self._should_scroll_on_render = self._is_parent_at_bottom()
            self.render_content()
        else:
            self.content_widget.display = False
            self.md_widget.display = False
        self.render_header()
        self._sync_sequential_with_prev()

    def on_unmount(self) -> None:
        if getattr(self, "_shell_update_handle", None) is not None:
            try:
                self._shell_update_handle.cancel()
            except Exception:
                pass
            self._shell_update_handle = None

    def _update_next_sibling_spacing(self) -> None:
        if not self.parent:
            return
        children = list(self.parent.children)
        try:
            idx = children.index(self)
        except ValueError:
            return
        for child in children[idx + 1 :]:
            from widgets.presentation.widgets.chat_messages import BotMessage

            if isinstance(child, BotMessage):
                c_str = child.raw_text if hasattr(child, "raw_text") else getattr(child, "content", "")
                if not (c_str or "").strip():
                    continue
            if isinstance(child, ToolCallWidget) and getattr(child, "is_sequential", False):
                if self.is_expanded:
                    child.remove_class("tool-sequential")
                else:
                    child.add_class("tool-sequential")
            break

    def _sync_sequential_with_prev(self) -> None:
        if not getattr(self, "is_sequential", False) or not self.parent:
            return
        children = list(self.parent.children)
        try:
            idx = children.index(self)
        except ValueError:
            return
        for child in reversed(children[:idx]):
            from widgets.presentation.widgets.chat_messages import BotMessage

            if isinstance(child, BotMessage):
                c_str = child.raw_text if hasattr(child, "raw_text") else getattr(child, "content", "")
                if not (c_str or "").strip():
                    continue
            if isinstance(child, ToolCallWidget):
                if child.is_expanded:
                    self.remove_class("tool-sequential")
                else:
                    self.add_class("tool-sequential")
            break

    def set_result(
        self,
        result_text: str,
        is_error: bool = False,
        status: str = None,
        returncode: int = None,
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

        if self.tool_type == "shell":
            if getattr(self, "_shell_update_handle", None) is not None:
                try:
                    self._shell_update_handle.cancel()
                except Exception:
                    pass
                self._shell_update_handle = None
            self._shell_update_scheduled = False
            is_bg_banner = "[Background Task ID:" in cleaned or "[background task" in cleaned
            if is_bg_banner:
                bg_m = re.search(r"(?:Background Task ID:|id:)\s*([^\s\]\|]+)", cleaned)
                if bg_m and not self.background_task_id:
                    self.background_task_id = bg_m.group(1)
                log_m = re.search(r"(?:Full Log:|log:)\s*([^\s\(\)\|\]]+)", cleaned)
                if log_m and not self.log_path:
                    self.log_path = log_m.group(1).rstrip(".]")
            if cleaned and not (status == "running" and is_bg_banner):
                self.result_text = cleaned
        else:
            self.result_text = cleaned

        if not self.is_clickable_header():
            was_expanded = self.is_expanded
            self.is_expanded = False
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
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
        self.render_header()
        if self.is_expanded:
            self._should_scroll_on_render = self._is_parent_at_bottom()
            self.render_content()

    def mark_cancelled(self) -> None:
        """Mark an interrupted tool call as cancelled."""
        if self.status != "running":
            return
        self.status = "cancelled"
        clean = (self.result_text or "").strip()
        if not clean:
            self.result_text = "[Tool call interrupted or cancelled]"
        elif "[Command interrupted" not in clean and "[Tool call" not in clean:
            self.result_text = f"{clean}\n[Command interrupted by user]"
        if not self.is_clickable_header():
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
            self.content_widget.display = False
            self.md_widget.display = False
        else:
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)
        self.render_header()

    def mark_running(self, text: str = "") -> None:
        """Mark the tool card as running (yellow) with optional status text."""
        self.status = "running"
        if text:
            self.result_text = text.strip()
        if not self.is_clickable_header():
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
        else:
            self.header_label.add_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.remove_class(TOOL_HEADER)
        self.render_header()

    def render_header(self) -> None:
        c = self._get_status_color()
        if self.canonical_tool in self.SYSTEM_TOOLS or self.canonical_tool in (
            "invoke_subagent",
            "manage_subagent",
            "manage_shell",
            "ask_user",
        ):
            display_name = self.DISPLAY_NAMES.get(self.canonical_tool, self.tool_type or "Tool")
            from widgets.presentation.tool_display import extract_tool_display

            target_str = (
                extract_tool_display(self.canonical_tool, self.args)
                if (self.args or self.canonical_tool == "update_plan")
                else self.target
            )
            self.header_label.update(f"[{c}]● [bold]{display_name}[/bold][/{c}]({escape(str(target_str))})")
        else:
            from widgets.presentation.tool_display import format_compact_dict

            compact = format_compact_dict(self.args)
            is_mcp = (self.tool_type or "").startswith("mcp_") or self.is_mcp
            tool_name_display = to_snake_case(self.tool_type) if is_mcp else (self.tool_type or "Tool")
            escaped_compact = escape(compact)
            self.header_label.update(f"[{c}]● [bold]{tool_name_display}[/bold][/{c}]({escaped_compact})")

    def on_click(self, event) -> None:
        if not self.is_clickable_header():
            return

        app = None
        try:
            app = self.app
        except Exception:
            pass

        if self.canonical_tool == "invoke_subagent":
            args = self.args
            session_id = getattr(self, "subagent_session_id", None)
            identifier = session_id or args.get("title") or args.get("prompt") or self.target
            store = getattr(app, "sm", None) if app else None
            if store is None:
                from core.infrastructure.storage.session_store import SessionStore

                store = SessionStore.get_instance()
            curr_session_id = getattr(app, "current_session_id", None) if app else None
            session = store.find_session_by_description_or_id(identifier, parent_id=curr_session_id) if store else None
            if not session and store:
                session = store.find_session_by_description_or_id(identifier)
            if not session:
                if app and hasattr(app, "notify"):
                    app.notify("Subagent session not found", severity="warning")
                event.stop()
                return
            event.stop()
            try:
                from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                if app:
                    app.push_screen(SubagentViewScreen(identifier))
            except Exception:
                pass
            return
        if self.canonical_tool == "manage_subagent":
            args = self.args
            session_id = getattr(self, "subagent_session_id", None) or args.get("session_id")
            if session_id:
                store = getattr(app, "sm", None) if app else None
                if store is None:
                    from core.infrastructure.storage.session_store import SessionStore

                    store = SessionStore.get_instance()
                curr_session_id = getattr(app, "current_session_id", None) if app else None
                session = (
                    store.find_session_by_description_or_id(session_id, parent_id=curr_session_id)
                    if store
                    else None
                )
                if not session:
                    if app and hasattr(app, "notify"):
                        app.notify("Subagent session not found", severity="warning")
                    event.stop()
                    return
                event.stop()
                try:
                    from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                    if app:
                        app.push_screen(SubagentViewScreen(session_id))
                except Exception:
                    pass
                return
            else:
                action = (args.get("action") or "list").lower()
                if action == "list":
                    store = getattr(app, "sm", None) if app else None
                    if store is None:
                        from core.infrastructure.storage.session_store import SessionStore

                        store = SessionStore.get_instance()
                    curr_session_id = getattr(app, "current_session_id", None) if app else None
                    subagents = (
                        store.children(curr_session_id)
                        if curr_session_id and store
                        else (store.list(kind="subagent") if store else [])
                    )
                    has_active = any(getattr(s, "status", "") == "running" for s in (subagents or []))
                    event.stop()
                    if has_active:
                        try:
                            from widgets.presentation.screens.tasks import SubagentsScreen

                            if app:
                                app.push_screen(SubagentsScreen())
                        except Exception:
                            pass
                    else:
                        if app and hasattr(app, "notify"):
                            app.notify("No active subagents", severity="information")
                    return
        if self.canonical_tool == "manage_shell":
            args = self.args
            action = (args.get("action") or "list").lower()
            if action == "list":
                tasks = getattr(app, "task_manager", []) if app else []
                curr_sid = getattr(app, "current_session_id", None) if app else None
                has_active = any(
                    getattr(t, "kind", "") == "shell"
                    and getattr(t, "is_background", False)
                    and getattr(t, "is_running", False)
                    and (getattr(t, "session_id", None) == curr_sid if curr_sid else True)
                    for t in (tasks or [])
                )
                event.stop()
                if has_active:
                    try:
                        from widgets.presentation.screens.tasks import ShellTasksScreen

                        if app:
                            app.push_screen(ShellTasksScreen())
                    except Exception:
                        pass
                else:
                    if app and hasattr(app, "notify"):
                        app.notify("No active background tasks", severity="information")
                return
        if self.canonical_tool == "shell":
            tasks = getattr(app, "task_manager", []) if app else []
            curr_sid = getattr(app, "current_session_id", None) if app else None
            task_id = getattr(self, "task_id", None)
            is_bg_running = any(
                getattr(t, "kind", "") == "shell"
                and getattr(t, "is_background", False)
                and getattr(t, "is_running", False)
                and (t.task_id == task_id if task_id else True)
                and (getattr(t, "session_id", None) == curr_sid if curr_sid else True)
                for t in (tasks or [])
            ) if (self.status == "running" or getattr(self, "is_background", False)) else False
            if is_bg_running:
                try:
                    from widgets.presentation.screens.tasks import ShellTasksScreen

                    if app:
                        app.push_screen(ShellTasksScreen())
                    event.stop()
                    return
                except Exception:
                    pass
        if self.canonical_tool == "ask_user":
            if getattr(app, "_pending_ask_user", None) is not None:
                self._resume_ask_user_wizard()
                event.stop()
                return

        if self.is_expandable():
            self.toggle_expanded()
            event.stop()

    def _resume_ask_user_wizard(self) -> None:
        """Resume a minimized ask_user wizard if present."""
        pending = getattr(self.app, "_pending_ask_user", None)
        if callable(pending):
            pending()

    def _parse_ask_user_questions(self) -> list[dict]:
        args = self.args
        qs = args.get("questions")
        out = []
        if isinstance(qs, list):
            for q in qs:
                if not isinstance(q, dict):
                    continue
                q_text = q.get("question") or ""
                opts = q.get("options")
                if q_text and isinstance(opts, list):
                    out.append({"question": str(q_text), "options": [str(o) for o in opts]})
        return out

    def _parse_ask_user_answers(self, questions: list[dict]) -> dict:
        answers = {}
        text = self.result_text or ""
        if "Answer:" not in text:
            return answers
        q_pairs = re.findall(r"^Question:\s*(.*?)\nAnswer:\s*(.*)$", text, re.MULTILINE)
        if not q_pairs:
            return answers
        used = set()
        for q_text, ans in q_pairs:
            for i, q in enumerate(questions):
                if i in used:
                    continue
                if (q.get("question") or "").strip() == q_text.strip():
                    answers[i] = {"answer": ans.strip()}
                    used.add(i)
                    break
        for i in range(len(questions)):
            if i not in answers:
                answers[i] = {"answer": "(No response)"}
        return answers

    def _scroll_if_needed(self, force: bool = False) -> None:
        from widgets.presentation.widgets.chat_messages import scroll_parent_if_needed

        scroll_parent_if_needed(self, force=force)

    def _scroll_to_widget(self, top: bool = False) -> None:
        from widgets.presentation.widgets.chat_messages import scroll_parent_to_widget

        scroll_parent_to_widget(self, top=top)

    def toggle_expanded(self, scroll: bool = True) -> None:
        if not self.is_expandable():
            return
        self.is_expanded = not self.is_expanded
        self.render_header()
        if self.is_expanded:
            if getattr(self, "_shell_update_scheduled", False):
                self._flush_shell_update()
            self._should_scroll_to_widget = scroll
            self.render_content()
        else:
            self._should_scroll_to_widget = False
            self.content_widget.display = False
            self.md_widget.display = False
        self._update_next_sibling_spacing()

    def append_shell_output(self, text: str) -> None:
        if not hasattr(self, "_raw_bash_buffer"):
            self._raw_bash_buffer = ""
        self._raw_bash_buffer += text
        if len(self._raw_bash_buffer) > self._RAW_BASH_LIMIT:
            self._raw_bash_buffer = self._RAW_BASH_TRUNC + self._raw_bash_buffer[-self._RAW_BASH_LIMIT :]
        self._schedule_shell_update()

    def _schedule_shell_update(self) -> None:
        if getattr(self, "_shell_update_scheduled", False):
            return
        self._shell_update_scheduled = True
        try:
            loop = asyncio.get_running_loop()
            self._shell_update_handle = loop.call_later(get_settings().ui.stream_flush_interval, self._flush_shell_update)
        except RuntimeError:
            self._flush_shell_update()

    def _flush_shell_update(self) -> None:
        self._shell_update_scheduled = False
        self._shell_update_handle = None
        from core.infrastructure.tasks.output import process_carriage_returns

        buf = getattr(self, "_raw_bash_buffer", "")
        cleaned = self._clean_bash_output(buf)
        self.result_text = process_carriage_returns(cleaned)
        if self.is_expanded:
            self.render_content()
            self._scroll_if_needed()

    def _compute_content(self) -> tuple[str, Any]:
        """Pure content computation (safe to run in a thread); returns (kind, value)."""
        return compute_tool_call_content(
            tool_type=self.tool_type,
            canonical_tool=self.canonical_tool,
            args=self.args,
            target=self.target,
            result_text=self.result_text,
            is_error=self._is_error(),
            guess_lexer=self._guess_lexer,
            clean_markup=self._clean_markup_text,
            clean_hints=self._clean_hints_for_ui,
            clean_bash_output=self._clean_bash_output,
            format_ask_user_display_fn=self._format_ask_user_display,
            format_json_result_fn=self._format_json_result,
        )

    def _apply_content(self, kind: str, value: Any) -> None:
        """Apply a computed content payload to the widgets (event-loop only)."""
        try:
            if kind == "raw":
                self.content_widget.update(value)
                self.content_widget.display = True
                self.md_widget.display = False
            elif kind == "md":
                safe_update_markdown(self.md_widget, value)
                self.md_widget.display = True
                self.content_widget.display = False
            else:  # "markup"
                self.content_widget.update(value)
                self.content_widget.display = True
                self.md_widget.display = False
        except Exception:
            pass

    def render_content(self) -> None:
        """Render the tool's terminal content into the widgets."""
        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop is not None and getattr(self, "is_mounted", True):
                self.content_widget.display = True
                self.md_widget.display = False
                gate: asyncio.Task | None = self._render_gate if hasattr(self, "_render_gate") else None
                if gate is not None and not gate.done():
                    gate.cancel()
                self._render_version = getattr(self, "_render_version", 0) + 1
                version = self._render_version
                self._render_gate = loop.create_task(self._async_render_content(version))
            else:
                kind, value = self._compute_content()
                self._apply_content(kind, value)
                if self.is_expanded:
                    if getattr(self, "_should_scroll_to_widget", False):
                        self._should_scroll_to_widget = False
                        self._scroll_to_widget(top=False)
                    else:
                        force = getattr(self, "_should_scroll_on_render", False)
                        self._should_scroll_on_render = False
                        self._scroll_if_needed(force=force)
        except Exception:
            pass

    async def _async_render_content(self, version: int) -> None:
        try:
            kind, value = await asyncio.to_thread(self._compute_content)
        except Exception:
            kind, value = "markup", self._clean_markup_text(self.result_text or "")
        if version != getattr(self, "_render_version", 0):
            return
        if not getattr(self, "is_mounted", True):
            return
        self._apply_content(kind, value)
        if self.is_expanded:
            if getattr(self, "_should_scroll_to_widget", False):
                self._should_scroll_to_widget = False
                self._scroll_to_widget(top=False)
            else:
                force = getattr(self, "_should_scroll_on_render", False)
                self._should_scroll_on_render = False
                self._scroll_if_needed(force=force)


ChatToolCall = ToolCallWidget

__all__ = [
    "ChatToolCall",
    "DISPLAY_NAMES",
    "FormattingMixin",
    "ParsingMixin",
    "SYSTEM_TOOLS",
    "ToolCallWidget",
    "ToolScrollBox",
    "TransparentSyntax",
    "_clean_truncation_marker",
    "_format_truncation_for_ui",
    "build_synthetic_create_diff",
    "format_ask_user_display",
    "format_manage_shell_display",
    "format_manage_subagent_display",
    "format_plan_display",
    "format_truncation_for_ui",
]
