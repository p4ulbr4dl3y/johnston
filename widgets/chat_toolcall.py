import asyncio
import json
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


def _strip_hints_and_background(text: str) -> str:
    """Strip [Hint:…] and [Background Task:…] markers from tool output."""
    if not text:
        return ""
    cleaned = re.sub(r"\s*\[Hint:[\s\S]*$", "", text)
    cleaned = re.sub(r"\s*\[Hint:[^\]]+\]", "", cleaned)
    cleaned = re.sub(r"\[Background Task ID:[^\]]+\][^\[\n]*", "", cleaned)
    cleaned = re.sub(r"Command is running in the background[^\n]*", "", cleaned)
    cleaned = re.sub(r"You will be notified automatically[^\n]*", "", cleaned)
    return cleaned.strip()


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


class FormattingMixin:
    """Pure formatting helpers for tool output display"""

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
        t = Text()
        if explanation:
            t.append(f"{explanation}\n\n", style="italic #a1a1aa")

        plan_lines = []
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            step = item.get("step") or ""
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

        return t

    def _format_ask_user_display(self) -> Any:
        questions = self._parse_ask_user_questions()
        answers = self._parse_ask_user_answers(questions)
        t = Text()
        for i, q in enumerate(questions):
            if i:
                t.append("\n")
            q_text = q.get("question", "")
            ans = answers.get(i, {}).get("answer", "")
            t.append(f"{q_text}\n", style="bold #ffffff")
            t.append(f"{ans}", style="#a1a1aa" if not ans else None)
        if not t:
            t.append(self._clean_hints_for_ui(self.result_text or "(No answers)"))
        return t

    def _format_edit_diff(self, diff_text: str, file_path: str) -> Any:
        diff_text = self._clean_hints_for_ui(diff_text)
        return format_edit_diff(diff_text, file_path)

    def _format_read_content(self, text: str, default_file_path: str) -> tuple[str, int, str]:
        lines = text.splitlines()
        if not lines:
            return "", 1, default_file_path

        start_line = 1
        file_path = default_file_path

        header_match = re.match(r"^===\s+Lines\s+(\d+)-\d+\s+of\s+\d+\s+in\s+([^\s=]+)", lines[0])
        if header_match:
            start_line = int(header_match.group(1))
            file_path = header_match.group(2)
            lines = lines[1:]

        clean_code_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("[Hint:") and stripped.endswith("]"):
                continue
            cleaned_line = re.sub(r"^(?:\s*\d+\s*\|\s?)+", "", line)
            clean_code_lines.append(cleaned_line)

        return "\n".join(clean_code_lines), start_line, file_path

    def _fix_markdown_nested_lists(self, text: str) -> str:
        if not text:
            return ""
        lines = text.splitlines()
        fixed = []
        for line in lines:
            # Fix double list markers (e.g. "  - * text" or "1. * text") from LLM transcribing
            line = re.sub(r"^(\s*(?:[-*]|\d+\.)\s+)[-*]\s+", r"\1", line)
            fixed.append(line)
        return "\n".join(fixed)

    def _clean_bash_output(self, text: str) -> str:
        return _strip_hints_and_background(text)

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
        """True only when the tool card carries the `status == "error"` state.

        The presentation layer never parses result text to classify a tool's
        outcome: status is received as a structured field from the stream event
        (``is_error``/``status``). The text is left untouched for display. This
        helper is kept for the render paths so the "error branch" is reached for
        both the card's error status and any legacy inline ``ERR:`` marker that
        predates structured status (e.g. legacy session reloads that never
        persisted a status).
        """
        if self.status in ("error", "cancelled"):
            return True
        if not text:
            return False
        return text.lstrip().lower().startswith("err:")

    def _get_status_color(self) -> str:
        if self.status == "running":
            return "#e5c07b"
        elif self.status == "error":
            return "#e06c75"
        elif self.status == "cancelled":
            return "#e06c75"
        else:
            return "#98c379"


class _DisplayNamesDict(dict):
    CANONICAL_NAMES = {
        "read": "Read",
        "create": "Create",
        "edit": "Edit",
        "multi_edit": "Edit",
        "shell": "Shell",
        "ask_user": "AskUser",
        "manage_shell": "ManageShell",
        "invoke_subagent": "InvokeSubagent",
        "manage_subagent": "ManageSubagent",
        "web_fetch": "WebFetch",
        "update_plan": "UpdatePlan",
    }

    def get(self, key, default=None):
        from tools.registry import normalize_tool_name

        canonical = normalize_tool_name(key)
        if canonical in self.CANONICAL_NAMES:
            return self.CANONICAL_NAMES[canonical]
        return super().get(key, default)


class _SystemToolsSet(set):
    def __contains__(self, item):
        if not isinstance(item, str):
            return False
        from tools.registry import normalize_tool_name
        from widgets.tool_helpers import is_system_tool

        lower = item.lower()
        canonical = normalize_tool_name(lower)
        if is_system_tool(canonical):
            return True
        return super().__contains__(item) or super().__contains__(lower)


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
        "multi_edit",
        "shell",
        "update_plan",
    }

    def is_expandable(self) -> bool:
        from tools.registry import normalize_tool_name

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
        if canonical in ("read", "web_fetch", "manage_shell", "manage_subagent", "invoke_subagent"):
            return False
        if canonical in self.EXPANDABLE_TOOLS:
            return True
        if hasattr(self, "SYSTEM_TOOLS") and self.tool_type not in self.SYSTEM_TOOLS:
            return True
        return self.tool_type in self.EXPANDABLE_TOOLS

    def is_clickable_header(self) -> bool:
        return (
            self.is_expandable()
            or self.canonical_tool in ("invoke_subagent", "ask_user")
            or (self.canonical_tool in ("shell", "manage_shell") and self._get_running_shell_task() is not None)
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
        from tools.registry import normalize_tool_name

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
        return _strip_hints_and_background(text)

    def _clean_markup_text(self, text: str) -> str:
        if not text:
            return ""
        clean = self._clean_hints_for_ui(text)
        clean = re.sub(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", clean)
        return clean

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.scroll_box

    def on_mount(self) -> None:
        self.content_widget.display = False
        self.md_widget.display = False
        self.render_header()
        self._sync_sequential_with_prev()

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
            if cleaned:
                self.result_text = cleaned
            if status == "running" and "[Background Task ID:" in cleaned:
                self.collapse()
        elif self.canonical_tool == "invoke_subagent":
            self.result_text = cleaned
            self.render_header()
            if self.is_expanded:
                self.render_content()
            return
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
        self.render_header()
        if self.is_expanded:
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
        self.result_text = "[Tool call interrupted or cancelled]"
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
        self.render_header()

    DISPLAY_NAMES = _DisplayNamesDict()
    SYSTEM_TOOLS = _SystemToolsSet()

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
            self.header_label.update(f"[{c}]⚙ [bold]UpdatePlan[/bold][/{c}]({escape(target_str)})")
        elif self.tool_type in self.SYSTEM_TOOLS or self.canonical_tool in (
            "invoke_subagent",
            "manage_subagent",
            "ask_user",
        ):
            display_name = self.DISPLAY_NAMES.get(self.tool_type, self.tool_type)
            from core.infrastructure.presentation.tool_display import extract_tool_display

            target_str = extract_tool_display(self.tool_type, self.args) if self.args else self.target
            self.header_label.update(f"[{c}]⚙ [bold]{display_name}[/bold][/{c}]({escape(str(target_str))})")
        else:
            # MCP/custom tool: single format — ToolName({k: v, ...}).
            from core.infrastructure.presentation.tool_display import format_compact_dict

            compact = format_compact_dict(self.args if isinstance(self.args, dict) else {})
            is_mcp = (self.tool_type or "").startswith("mcp_") or self.is_mcp
            tool_name_display = to_snake_case(self.tool_type) if is_mcp else self.tool_type
            escaped_compact = escape(compact)
            self.header_label.update(f"[{c}]⚙ [bold]{tool_name_display}[/bold][/{c}]({escaped_compact})")

    def on_click(self, event) -> None:
        if not self.is_clickable_header():
            return
        if self.canonical_tool in ("invoke_subagent", "ask_user", "shell", "manage_shell"):
            if self.canonical_tool == "invoke_subagent":
                args = self.args if isinstance(self.args, dict) else {}
                nargs = args
                session_id = getattr(self, "subagent_session_id", None)
                identifier = session_id or nargs.get("description") or nargs.get("prompt") or self.target
                try:
                    from widgets.presentation.screens.subagent_screen import SubagentViewScreen

                    self.app.push_screen(SubagentViewScreen(identifier))
                except Exception:
                    pass
                event.stop()
                return
            if self.canonical_tool == "ask_user":
                if getattr(self.app, "_pending_ask_user", None) is not None:
                    self._resume_ask_user_wizard()
                    event.stop()
                    return
            if self.canonical_tool in ("shell", "manage_shell"):
                running_task = self._get_running_shell_task()
                if running_task is not None:
                    try:
                        from widgets.presentation.screens.tasks import TaskConsoleScreen

                        self.app.push_screen(TaskConsoleScreen(running_task))
                        event.stop()
                        return
                    except Exception:
                        pass
            # No pending wizard or running bg task: fall through to inline expand/collapse.

        if self.is_expandable():
            self.toggle_expanded()
            event.stop()

    def _get_running_shell_task(self) -> Any:
        """Find active background shell task associated with this tool call, if any."""
        try:
            app = self.app
        except Exception:
            return None
        if not app or not hasattr(app, "task_manager"):
            return None
        tid = None
        if isinstance(self.args, dict):
            tid = self.args.get("task_id") or self.args.get("TaskId")
        if not tid:
            bg_match = re.search(r"Background Task ID:\s*([^\s\]]+)", self.result_text or "")
            if bg_match:
                tid = bg_match.group(1)
        if not tid:
            return None
        for t in app.task_manager:
            if (
                getattr(t, "task_id", "") == tid
                and getattr(t, "kind", "") == "shell"
                and getattr(t, "is_running", False)
            ):
                return t
        return None

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

    def collapse(self) -> None:
        """Collapse expanded content if currently open."""
        if not self.is_expanded:
            return
        self.is_expanded = False
        self.render_header()
        self.content_widget.display = False
        self.md_widget.display = False
        self._update_next_sibling_spacing()

    def toggle_expanded(self) -> None:
        if not self.is_expandable():
            return
        self.is_expanded = not self.is_expanded
        self.render_header()
        if self.is_expanded:
            self.render_content()
        else:
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
        from core.infrastructure.tasks.output import process_carriage_returns

        cleaned = self._clean_bash_output(self._raw_bash_buffer)
        self.result_text = process_carriage_returns(cleaned)
        if self.is_expanded:
            self.render_content()

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
            elif self.tool_type in ("edit", "multi_edit"):
                raw_text = (self.result_text or "").strip()
                if self._is_error(raw_text):
                    return "markup", self._clean_markup_text(raw_text or "(Error)")
                diff_text = raw_text
                if not diff_text or "@@" not in diff_text:
                    from widgets.lexer_utils import build_edit_diff_text

                    diff_text = build_edit_diff_text(self.args, file_path or "file", self.tool_type)

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
            elif self.tool_type in ("web_fetch", "WebFetch"):
                raw_text = self.result_text or ""
                if self._is_error(raw_text):
                    return "raw", Text(raw_text.strip(), style="bold #ffffff")
                default_target = self.args.get("url") or file_path or "page.md"
                clean_code, start_line, fpath = self._format_read_content(raw_text, default_target)
                lexer = self._guess_lexer(fpath)
                raw_mode = bool(self.args.get("raw", False))

                is_code_file = lexer not in ("markdown", "text") and lexer != "html"
                if is_code_file or raw_mode:
                    if clean_code:
                        clean_code = clean_code.rstrip("\r\n")
                        try:
                            syntax = TransparentSyntax(
                                clean_code,
                                lexer if lexer != "html" else "html",
                                theme=CODE_THEME,
                                line_numbers=True,
                                start_line=start_line,
                                word_wrap=True,
                                background_color="default",
                            )
                            return "raw", syntax
                        except Exception:
                            return "raw", self._format_code_with_line_numbers(clean_code)
                    return "markup", self._clean_markup_text(self.result_text or "(No content)")
                clean_code = self._fix_markdown_nested_lists(clean_code)
                return "md", clean_code.rstrip("\r\n") or "(No content)"
            elif self.tool_type in ("read", "Read"):
                raw_text = self.result_text or ""
                if self._is_error(raw_text):
                    return "raw", Text(raw_text.strip(), style="bold #ffffff")
                default_target = file_path or "file.txt"
                clean_code, start_line, fpath = self._format_read_content(raw_text, default_target)

                if not clean_code.strip() and fpath:
                    from widgets.utils.file_reader import read_file_content

                    disk_content = read_file_content(fpath)
                    if disk_content is not None:
                        clean_code = disk_content
                        start_line = 1

                lexer = self._guess_lexer(fpath)
                if lexer == "markdown":
                    clean_code = self._fix_markdown_nested_lists(clean_code)
                    return "md", clean_code.rstrip("\r\n") or "(No content)"
                if clean_code:
                    clean_code = clean_code.rstrip("\r\n")
                    try:
                        syntax = TransparentSyntax(
                            clean_code,
                            lexer,
                            theme=CODE_THEME,
                            line_numbers=True,
                            start_line=start_line,
                            word_wrap=True,
                            background_color="default",
                        )
                        return "raw", syntax
                    except Exception:
                        return "raw", self._format_code_with_line_numbers(clean_code)
                return "markup", self._clean_markup_text(self.result_text or "(No content)")
            elif self.tool_type == "shell":
                output_text = self._clean_bash_output(self.result_text)
                if not output_text.strip():
                    if self.app and hasattr(self.app, "task_manager"):
                        bg_match = re.search(r"Background Task ID:\s*([^\s\]]+)", self.result_text or "")
                        if bg_match:
                            tid = bg_match.group(1)
                            for t in self.app.task_manager:
                                if (
                                    getattr(t, "task_id", "") == tid
                                    and getattr(t, "kind", "") == "shell"
                                    and getattr(t, "is_running", False)
                                ):
                                    output_text = "(Running command...)"
                                    break
                    if not output_text:
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
