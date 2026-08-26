import asyncio
import json
import os
import re
from typing import Any

from rich.console import Group
from rich.markup import escape
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, Static

from widgets.presentation.screens.constants import TOOL_HEADER, TOOL_HEADER_EXPANDABLE, TOOL_SCROLL_BOX
from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.presentation.widgets.chat_markdown import (
    CODE_THEME,
    TransparentSyntax,
    safe_update_markdown,
    to_snake_case,
)
from widgets.utils.lexer import guess_lexer_name

_MISSING = object()


def _clean_truncation_marker(match: re.Match) -> str:
    prefix = match.group(1) or ""
    inner = match.group(2)
    showing_match = re.search(
        r"showing\s+(?:first|last|recent)\s+[^\s.(),|]+(?:\s+chars|\s+output)?",
        inner,
        re.IGNORECASE,
    )
    log_match = re.search(r"(?:Full\s+)?log:\s*([^\s\]|]+)", inner, re.IGNORECASE)

    if showing_match or log_match:
        showing = showing_match.group(0).strip() if showing_match else "showing truncated output"
        if log_match:
            log_path = log_match.group(1).rstrip(".]")
            return f"{prefix}[Output truncated: {showing} | Log: {log_path}]"
        return f"{prefix}[Output truncated: {showing}]"

    return match.group(0)


def _format_truncation_for_ui(text: str) -> str:
    """Format [Output truncated...] banners and strip [Hint:...] for UI display."""
    if not text or "[" not in text:
        return (text or "").strip()
    cleaned = re.sub(r"\s*\[Hint:[\s\S]*$", "", text)
    cleaned = re.sub(r"\s*\[Hint:[^\]]+\]", "", cleaned)
    return re.sub(
        r"(\.\.\.\s*)?\[Output truncated([^\]]*)\]",
        _clean_truncation_marker,
        cleaned,
        flags=re.IGNORECASE,
    ).strip()


def build_synthetic_create_diff(file_path: str, content: str) -> str:
    """Build a synthetic ``--- a/… / +++ b/… / @@ -1,N +1,N @@`` diff for create/write tools."""
    new_lines = content.splitlines() if content else []
    cnt = len(new_lines) or 1
    d_lines = [
        f"--- a/{file_path or 'file'}",
        f"+++ b/{file_path or 'file'}",
        f"@@ -1,{cnt} +1,{cnt} @@",
    ] + [f"+{line_str}" for line_str in new_lines]
    return "\n".join(d_lines)


def format_plan_display(plan_items: Any, explanation: str = "") -> Text:
    """Format an update_plan checklist into a unified rich Text renderable."""
    t = Text()
    if explanation:
        t.append(f"{explanation}\n\n", style="italic #a1a1aa")

    if isinstance(plan_items, list):
        plan_lines = []
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step") or "").strip()
            status = str(item.get("status") or "pending").lower()

            if status == "completed":
                line = Text("[x] ", style="dim #71717a") + Text(step, style="strike dim #71717a")
            elif status == "in_progress":
                line = Text("[>] ", style="#ffffff") + Text(step, style="#ffffff")
            else:
                line = Text("[ ] ", style="dim #a1a1aa") + Text(step, style="dim #a1a1aa")
            plan_lines.append(line)

        for i, pl in enumerate(plan_lines):
            t.append(pl)
            if i < len(plan_lines) - 1:
                t.append("\n")
    elif isinstance(plan_items, str) and plan_items.strip():
        t.append(plan_items.strip(), style="#e4e4e7")

    return t


def format_ask_user_display(questions: list[dict], answers: dict[int, dict] | dict[int, str] | None = None) -> Text:
    """Format ask_user questions and answers into a unified rich Text renderable."""
    answers = answers or {}
    t = Text()
    num_questions = len(questions)
    for i, q in enumerate(questions):
        if i > 0:
            t.append("\n\n")
        q_text = str(q.get("question") or "").strip()
        prefix = f"{i + 1}. " if num_questions > 1 else ""
        t.append(f"{prefix}{q_text}\n", style="#ffffff")
        ans_info = answers.get(i, {})
        ans = ans_info.get("answer", "") if isinstance(ans_info, dict) else str(ans_info or "")
        if ans:
            t.append(ans, style="#a1a1aa")
        else:
            t.append("(No response)", style="italic #71717a")
    return t


def format_manage_shell_display(result_text: str) -> Text:
    """Format manage_shell list output into a monochrome rich Text renderable."""
    raw = (result_text or "").strip()
    if not raw or raw.lower() in ("no tasks active", "no active tasks", "(no active tasks)"):
        return Text("(No active tasks)", style="#e4e4e7")

    t = Text()
    lines = raw.splitlines()
    task_lines = []
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.lower().startswith("active background tasks:"):
            continue
        # Pattern: "- ID: {id} | Status: {status} | Command: {cmd}"
        m = re.match(
            r"^[-\*]?\s*ID:\s*([^\s|]+)\s*\|\s*Status:\s*([^\s|]+)\s*\|\s*Command:\s*(.*)$",
            line_clean,
            re.IGNORECASE,
        )
        if m:
            t_id, status, cmd = m.group(1), m.group(2).upper(), m.group(3).strip()
            if status == "RUNNING":
                task_t = Text("[>] ", style="#ffffff") + Text(f"{t_id}  ", style="bold #ffffff") + Text(cmd, style="#a1a1aa")
            else:
                task_t = Text("[x] ", style="dim #71717a") + Text(f"{t_id}  ", style="dim #71717a") + Text(cmd, style="dim #71717a")
            task_lines.append(task_t)
        else:
            task_lines.append(Text(line_clean, style="#e4e4e7"))

    if not task_lines:
        return Text("(No active tasks)", style="#e4e4e7")

    for i, tl in enumerate(task_lines):
        t.append(tl)
        if i < len(task_lines) - 1:
            t.append("\n")
    return t


def format_manage_subagent_display(result_text: str) -> Text:
    """Format manage_subagent list output into a monochrome rich Text renderable."""
    raw = (result_text or "").strip()
    if not raw or "no subagent sessions found" in raw.lower() or raw.lower() in ("no tasks active", "(no active subagents)"):
        return Text("(No active subagents)", style="#e4e4e7")

    t = Text()
    lines = raw.splitlines()
    subagent_lines = []
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.lower().startswith("active/past subagent sessions:"):
            continue
        # Pattern: "• ID: {id} | Status: {status} | Type: {role} | Title: {title}"
        m = re.match(
            r"^[•\-\*]?\s*ID:\s*([^\s|]+)\s*\|\s*Status:\s*([^\s|]+)\s*\|\s*Type:\s*([^|]*?)\s*\|\s*Title:\s*(.*)$",
            line_clean,
            re.IGNORECASE,
        )
        if m:
            s_id, status, role, title = (
                m.group(1).strip(),
                m.group(2).strip().upper(),
                m.group(3).strip(),
                m.group(4).strip(),
            )
            has_role = bool(role and role.lower() not in ("worker", "subagent", "default", "none", ""))
            desc = f"{role}: {title}" if has_role and title else (title or role or "(no description)")
            if status == "RUNNING":
                item_t = (
                    Text("[>] ", style="#ffffff")
                    + Text(f"{s_id}  ", style="bold #ffffff")
                    + Text(desc, style="#a1a1aa")
                )
            else:
                item_t = (
                    Text("[x] ", style="dim #71717a")
                    + Text(f"{s_id}  ", style="dim #71717a")
                    + Text(desc, style="dim #71717a")
                )
            subagent_lines.append(item_t)
        else:
            subagent_lines.append(Text(line_clean, style="#e4e4e7"))

    if not subagent_lines:
        return Text("(No active subagents)", style="#e4e4e7")

    for i, sl in enumerate(subagent_lines):
        t.append(sl)
        if i < len(subagent_lines) - 1:
            t.append("\n")
    return t


class FormattingMixin:
    """Read/Edit/Plan formatting helpers"""

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

    def _format_ask_user_display(self) -> Any:
        questions = self._parse_ask_user_questions()
        answers = self._parse_ask_user_answers(questions)
        display = format_ask_user_display(questions, answers)
        if not display:
            display.append(self._clean_hints_for_ui(self.result_text or "(No answers)"))
        return display

    def _format_manage_shell_display(self) -> Any:
        return format_manage_shell_display(self.result_text or "")

    def _format_manage_subagent_display(self) -> Any:
        return format_manage_subagent_display(self.result_text or "")

    def _format_edit_diff(self, diff_text: str, file_path: str) -> Any:
        diff_text = self._clean_hints_for_ui(diff_text)
        return format_edit_diff(diff_text, file_path)

    def _clean_bash_output(self, text: str) -> str:
        return _format_truncation_for_ui(text)

    def _format_code_with_line_numbers(self, code: str) -> str:
        lines = code.splitlines()
        if not lines:
            return "[dim]1 │ [/dim]"
        max_digits = max(len(str(len(lines))), 2)
        formatted = []
        for i, line in enumerate(lines, 1):
            num_str = str(i).rjust(max_digits)
            escaped_line = line.replace("[", "\\[")
            formatted.append(f"[dim]{num_str} │ [/dim]{escaped_line}")
        return "\n".join(formatted)


class ParsingMixin:
    """Status / JSON / MCP-args parsing helpers"""

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

    def _format_json_result(self, raw_text: str) -> Syntax | Group | None:
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
            syntax = TransparentSyntax(
                pretty_json, "json", theme=CODE_THEME, word_wrap=True, background_color="default"
            )
            if footer:
                return Group(syntax, Text("\n" + footer.strip()))
            return syntax
        return None

    def _is_error(self, text: str) -> bool:
        """True when the tool card is in error/cancelled state or returned non-zero exit code."""
        return self.status in ("error", "cancelled") or (self.returncode is not None and self.returncode != 0)

    def _get_status_color(self) -> str:
        if self.status == "running":
            return "#e5c07b"
        elif self.status in ("error", "cancelled") or (self.returncode is not None and self.returncode != 0):
            return "#e06c75"
        else:
            return "#98c379"


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
    """Horizontal scroll box for tool code/diff view"""

    pass


class ToolCallWidget(FormattingMixin, ParsingMixin, Vertical):
    """Tool call widget (Create, Read, Edit, Shell) with expansion support"""

    can_focus = False
    ALLOW_SELECT = False

    EXPANDABLE_TOOLS = {
        "create",
        "edit",
        "shell",
        "update_plan",
    }

    def is_expandable(self) -> bool:
        from core.infrastructure.runtime.tool_name import normalize_tool_name

        canonical = getattr(self, "canonical_tool", None) or normalize_tool_name(self.tool_type)
        # Shell output is always useful to the user (return code / stdout),
        # regardless of the tool status, so shell stays expandable.
        if canonical == "shell":
            return True
        # Error/cancelled results are feedback for the agent (they flow to the
        # model), not content for the user to inspect — don't expand those.
        if self.status in ("error", "cancelled"):
            return False
        if canonical == "ask_user":
            # Expandable inline when completed (has answers); minimized wizard is resumed via modal.
            return "Answer:" in (self.result_text or "")
        if canonical == "manage_shell":
            action = (self.args if isinstance(self.args, dict) else {}).get("action", "list")
            return (action or "list").lower() == "list"
        if canonical == "manage_subagent":
            action = (self.args if isinstance(self.args, dict) else {}).get("action", "list")
            return (action or "list").lower() == "list"
        if canonical in (
            "read",
            "web_fetch",
            "invoke_subagent",
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
        return (
            self.is_expandable()
            or self.canonical_tool in ("invoke_subagent", "manage_subagent", "ask_user")
        )

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
        self.args = args or {}
        self.returncode = returncode
        self.is_mcp = is_mcp
        self.is_expanded = False
        self.background_task_id = None
        self._shell_update_scheduled = False
        self._shell_update_handle: asyncio.TimerHandle | None = None
        if status is not None:
            self.status = status
        else:
            # Status is a structured input (from the stream event or session
            # reload), never derived from result text. Default to "running" when
            # the tool has no result yet, "done" when it already has output.
            self.status = "running" if not result_text else "done"

        is_clickable = self.is_clickable_header()
        header_cls = f"{TOOL_HEADER} {TOOL_HEADER_EXPANDABLE}" if is_clickable else TOOL_HEADER
        self.header_label = Label("", classes=header_cls)
        self.content_widget = Static("", classes="tool-content", markup=False)
        self.md_widget = Markdown("", classes="tool-content-md")
        self.scroll_box = ToolScrollBox(self.content_widget, self.md_widget, classes=TOOL_SCROLL_BOX)

    def _clean_hints_for_ui(self, text: str) -> str:
        return _format_truncation_for_ui(text)

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
        """Apply a tool's terminal/streamed result to the card.

        Status comes in structurally (``status``/``is_error`` from the stream
        event); the widget never classifies result text to derive it. The text is
        kept as-is for display. When neither flag is provided we fall back to
        ``is_error`` (callers pass it directly) and finally to the existing card
        state so a completion that omits status keeps its prior color.
        """
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
            is_bg_banner = "[Background Task ID:" in cleaned
            # A ctrl+b transition emits a transient RUNNING banner ("moved to
            # background..."). When live output already streams on the card,
            # keep it instead of overwriting with the banner — chunks keep
            # arriving and the completion repaint sets the final text anyway.
            has_live_output = bool((self.result_text or "").strip())
            if cleaned and not (status == "running" and is_bg_banner and has_live_output):
                self.result_text = cleaned
            if is_bg_banner:
                bg_m = re.search(r"Background Task ID:\s*([^\s\]]+)", cleaned)
                if bg_m:
                    self.background_task_id = bg_m.group(1)
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
        self.render_header()
        if self.is_expanded:
            # Scroll the finished result into view only when the user is
            # already at the bottom; never yank them away from history.
            self._should_scroll_on_render = self._is_parent_at_bottom()
            self.render_content()

    def mark_cancelled(self) -> None:
        """Mark an interrupted tool call as cancelled (not error, not running).

        Called from the message-flow cancel path when a tool was killed before
        emitting a ``tool_result``. The tool stays in a distinct visual state so
        the user can tell it was interrupted rather than still running or failed.
        """
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
        """Mark the tool card as running (yellow) with optional status text.

        Set by the tools layer when a subagent follow-up is dispatched so the
        invoke_subagent card returns to a yellow "working" state instead of
        staying green after a send_message. ``text`` is only applied for
        invoke_subagent cards; other tool types just flip to running.
        """
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

    DISPLAY_NAMES = DISPLAY_NAMES
    SYSTEM_TOOLS = SYSTEM_TOOLS

    def render_header(self) -> None:
        c = self._get_status_color()
        if self.canonical_tool == "update_plan":
            target_str = ""
            if self.args and isinstance(self.args, dict):
                plan_data = self.args.get("plan")
                if isinstance(plan_data, list):
                    total = len(plan_data)
                    completed = sum(
                        1
                        for item in plan_data
                        if isinstance(item, dict) and item.get("status") == "completed"
                    )
                    target_str = f"[{completed}/{total} completed]"
            self.header_label.update(f"[{c}]● [bold]UpdatePlan[/bold][/{c}]({escape(target_str)})")
        elif self.canonical_tool in self.SYSTEM_TOOLS or self.canonical_tool in (
            "invoke_subagent",
            "manage_subagent",
            "manage_shell",
            "ask_user",
        ):
            display_name = self.DISPLAY_NAMES.get(self.canonical_tool, self.tool_type or "Tool")
            from core.infrastructure.presentation.tool_display import extract_tool_display

            target_str = extract_tool_display(self.canonical_tool, self.args) if self.args else self.target
            self.header_label.update(f"[{c}]● [bold]{display_name}[/bold][/{c}]({escape(str(target_str))})")
        else:
            # MCP/custom tool: single format — ToolName({k: v, ...}).
            from core.infrastructure.presentation.tool_display import format_compact_dict

            compact = format_compact_dict(self.args if isinstance(self.args, dict) else {})
            is_mcp = (self.tool_type or "").startswith("mcp_") or self.is_mcp
            tool_name_display = to_snake_case(self.tool_type) if is_mcp else (self.tool_type or "Tool")
            escaped_compact = escape(compact)
            self.header_label.update(f"[{c}]● [bold]{tool_name_display}[/bold][/{c}]({escaped_compact})")

    def on_click(self, event) -> None:
        if not self.is_clickable_header():
            return
        if self.canonical_tool == "invoke_subagent":
            args = self.args if isinstance(self.args, dict) else {}
            session_id = getattr(self, "subagent_session_id", None)
            identifier = session_id or args.get("title") or args.get("prompt") or self.target
            store = getattr(self.app, "sm", None) if self.app else None
            if store is None:
                from core.session_manager import SessionStore

                store = SessionStore.get_instance()
            curr_session_id = getattr(self.app, "current_session_id", None) if self.app else None
            session = store.find_session_by_description_or_id(identifier, parent_id=curr_session_id) if store else None
            if not session and store:
                session = store.find_session_by_description_or_id(identifier)
            if not session:
                if hasattr(self.app, "notify"):
                    self.app.notify("Subagent session not found", severity="warning")
                event.stop()
                return
            try:
                from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                self.app.push_screen(SubagentViewScreen(identifier))
            except Exception:
                pass
            event.stop()
            return
        if self.canonical_tool == "manage_subagent":
            args = self.args if isinstance(self.args, dict) else {}
            session_id = getattr(self, "subagent_session_id", None) or args.get("session_id")
            if session_id:
                store = getattr(self.app, "sm", None) if self.app else None
                if store is None:
                    from core.session_manager import SessionStore

                    store = SessionStore.get_instance()
                curr_session_id = getattr(self.app, "current_session_id", None) if self.app else None
                session = (
                    store.find_session_by_description_or_id(session_id, parent_id=curr_session_id)
                    if store
                    else None
                )
                if not session and store:
                    session = store.find_session_by_description_or_id(session_id)
                if not session:
                    if hasattr(self.app, "notify"):
                        self.app.notify("Subagent session not found", severity="warning")
                    event.stop()
                    return
                try:
                    from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                    self.app.push_screen(SubagentViewScreen(session_id))
                except Exception:
                    pass
                event.stop()
                return
            else:
                action = (args.get("action") or "list").lower()
                if action == "list":
                    store = getattr(self.app, "sm", None) if self.app else None
                    if store is None:
                        from core.session_manager import SessionStore

                        store = SessionStore.get_instance()
                    curr_session_id = getattr(self.app, "current_session_id", None) if self.app else None
                    subagents = (
                        store.children(curr_session_id)
                        if curr_session_id and store
                        else (store.list(kind="subagent") if store else [])
                    )
                    has_active = any(getattr(s, "status", "") == "running" for s in (subagents or []))
                    if has_active:
                        try:
                            from widgets.presentation.screens.tasks import SubagentsScreen

                            self.app.push_screen(SubagentsScreen())
                            event.stop()
                            return
                        except Exception:
                            pass
        if self.canonical_tool == "manage_shell":
            args = self.args if isinstance(self.args, dict) else {}
            action = (args.get("action") or "list").lower()
            if action == "list":
                app = getattr(self, "app", None)
                tasks = getattr(app, "task_manager", []) if app else []
                curr_sid = getattr(app, "current_session_id", None) if app else None
                has_active = any(
                    getattr(t, "kind", "") == "shell"
                    and getattr(t, "is_background", False)
                    and (getattr(t, "session_id", None) == curr_sid if curr_sid else True)
                    for t in (tasks or [])
                )
                if has_active:
                    try:
                        from widgets.presentation.screens.tasks import ShellTasksScreen

                        self.app.push_screen(ShellTasksScreen())
                        event.stop()
                        return
                    except Exception:
                        pass
        if self.canonical_tool == "ask_user":
            if getattr(self.app, "_pending_ask_user", None) is not None:
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
        args = self.args if isinstance(self.args, dict) else {}
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
        # Answers come from the wizard summary as sequential "Question:" / "Answer:" lines.
        # Parse line-by-line so answers containing "Question:" don't break pairing.
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

    _RAW_BASH_LIMIT = 200 * 1024  # 200 KB retained raw buffer
    _RAW_BASH_TRUNC = "[…[truncated]]\n"

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
            self._shell_update_handle = loop.call_later(0.05, self._flush_shell_update)
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

    def flush_shell_output(self) -> None:
        if getattr(self, "_shell_update_handle", None) is not None:
            try:
                self._shell_update_handle.cancel()
            except Exception:
                pass
            self._shell_update_handle = None
        if getattr(self, "_shell_update_scheduled", False) or hasattr(self, "_raw_bash_buffer"):
            self._flush_shell_update()

    def _compute_content(self) -> tuple:
        """Pure content computation (safe to run in a thread); returns (kind, value).

        ``kind`` is one of ``"raw"`` (rich renderable for ``content_widget``),
        ``"markup"`` (plain/re-escaped string for ``content_widget``) or
        ``"md"`` (markdown text for ``md_widget``). No widget mutation here — the
        caller applies the result on the event loop.
        """
        try:
            nargs = self.args if isinstance(self.args, dict) else {}
            file_path = nargs.get("path") or self.target
            if self.tool_type == "create":
                raw_text = (self.result_text or "").strip()
                if self._is_error(raw_text):
                    return "markup", self._clean_markup_text(raw_text or "(Error)")
                if raw_text and (
                    "@@" in raw_text
                    or "--- a/" in raw_text
                    or "+++ b/" in raw_text
                    or " updated " in raw_text
                    or " updated (" in raw_text
                ):
                    diff_text = raw_text
                    if "@@" not in diff_text and "--- a/" not in diff_text:
                        content = self.args.get("content") or ""
                        diff_text = build_synthetic_create_diff(file_path, content)
                    formatted_diff = self._format_edit_diff(diff_text, file_path)
                    return "raw", formatted_diff
                content = self.args.get("content")
                if content is None:
                    from widgets.utils.file_reader import read_file_content

                    content = read_file_content(file_path)
                if content is None and raw_text:
                    content = raw_text

                if content is not None:
                    content = content.rstrip("\r\n")
                    lexer = self._guess_lexer(file_path)
                    try:
                        syntax = TransparentSyntax(
                            content,
                            lexer,
                            theme=CODE_THEME,
                            line_numbers=True,
                            word_wrap=True,
                            background_color="default",
                        )
                        return "raw", syntax
                    except Exception:
                        return "raw", self._format_code_with_line_numbers(content)
                return "markup", self._clean_markup_text(self.result_text or "(No content)")
            elif self.tool_type == "edit":
                raw_text = (self.result_text or "").strip()
                if self._is_error(raw_text):
                    return "markup", self._clean_markup_text(raw_text or "(Error)")
                diff_text = raw_text
                if not diff_text or "@@" not in diff_text:
                    from widgets.lexer_utils import build_edit_diff_text

                    diff_text = build_edit_diff_text(self.args, file_path or "file")

                if diff_text:
                    return "raw", self._format_edit_diff(diff_text, file_path)
                return "markup", self._clean_markup_text(self.result_text or "(No diff)")
            elif self.tool_type == "update_plan":
                raw_text = (self.result_text or "").strip()
                if self._is_error(raw_text):
                    return "markup", self._clean_markup_text(raw_text or "(Error)")
                plan_items = self.args.get("plan") or []
                explanation = self.args.get("explanation", "")
                return "raw", self._format_plan_display(plan_items, explanation)
            elif self.canonical_tool == "ask_user":
                return "raw", self._format_ask_user_display()
            elif self.canonical_tool == "manage_shell":
                args = self.args if isinstance(self.args, dict) else {}
                action = (args.get("action") or "list").lower()
                if action == "list":
                    return "raw", self._format_manage_shell_display()
                clean_res = self._clean_hints_for_ui(self.result_text or "(No result)")
                return "markup", self._clean_markup_text(clean_res)
            elif self.canonical_tool == "manage_subagent":
                args = self.args if isinstance(self.args, dict) else {}
                action = (args.get("action") or "list").lower()
                if action == "list":
                    return "raw", self._format_manage_subagent_display()
                clean_res = self._clean_hints_for_ui(self.result_text or "(No result)")
                return "markup", self._clean_markup_text(clean_res)
            elif self.tool_type == "shell":
                output_text = self._clean_bash_output(self.result_text)
                log_match = re.search(r"Full Log:\s*([^\s\(\)]+)", self.result_text or "")
                if log_match:
                    log_path = log_match.group(1)
                    if os.path.isfile(log_path):
                        try:
                            from widgets.utils.file_reader import read_file_content

                            log_content = read_file_content(log_path)
                            if log_content and log_content.strip():
                                output_text = log_content.rstrip("\r\n")
                        except Exception:
                            pass
                if not output_text.strip():
                    output_text = "(No output)"
                return "markup", self._clean_markup_text(output_text)
            else:
                clean_res = self._clean_hints_for_ui(self.result_text or "(No result)")
                syntax = self._format_json_result(clean_res)
                if syntax:
                    return "raw", syntax
                return "markup", self._clean_markup_text(clean_res)
        except Exception:
            return "markup", self._clean_markup_text(self.result_text or "")

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
        """Render the tool's terminal content into the widgets.

        The heavy path (disk reads, pygments) is pushed to a worker thread when
        a running event loop is available (real app on the UI thread). When no
        loop is running (unit tests / sync callers), the content is computed and
        applied synchronously so the widgets are populated before the call
        returns.
        """
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
                # Invalidation counter: a superseded render (or an unmount that
                # left a cancelled gate's worker thread still running) must not
                # overwrite fresher content when its thread eventually returns.
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
        # A newer render superseded this one (or the widget was unmounted): the
        # stale result must never overwrite fresher content.
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
