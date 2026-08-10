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

from widgets.chat_diff import format_edit_diff
from widgets.chat_markdown import (
    CODE_THEME,
    TransparentSyntax,
    safe_update_markdown,
    to_snake_case,
)
from widgets.lexer_utils import guess_lexer_name
from widgets.screens.constants import TOOL_HEADER, TOOL_HEADER_EXPANDABLE, TOOL_SCROLL_BOX


def _strip_hints_and_background(text: str) -> str:
    """Strip [Hint:…] and [Background Task:…] markers from tool output."""
    if not text:
        return ""
    cleaned = re.sub(r"\s*\[Hint:[\s\S]*$", "", text)
    cleaned = re.sub(r"\s*\[Hint:[^\]]+\]", "", cleaned)
    cleaned = re.sub(r"\[Background Task ID:[^\]]+\][^\[\n]*", "", cleaned)
    cleaned = re.sub(r"Command is running in the background[^\n]*", "", cleaned)
    cleaned = re.sub(r"You will be notified automatically[^\n]*", "", cleaned)
    cleaned = re.sub(r"Use (manage_shell|ManageShell) to inspect[^\n]*", "", cleaned)
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

    def _guess_lexer(self, path_str: str) -> str:
        return guess_lexer_name(path_str)

    def _format_plan_display(self, plan_items: list, explanation: str) -> Text:
        t = Text()
        if explanation:
            t.append(f"{explanation}\n\n", style="bold #ffffff")

        plan_lines = []
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            step = item.get("step") or item.get("text") or ""
            status = str(item.get("status") or "pending").lower()

            if status in ("completed", "done"):
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
            q_text = q.get("question_text", "")
            ans = answers.get(i, {}).get("answer", "")
            t.append(f"Q: {q_text}\n", style="bold #ffffff")
            t.append(f"A: {ans}", style="#a1a1aa" if not ans else None)
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

    def _try_parse_json(self, text: str) -> Any:
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
                pretty_json, "json", theme=CODE_THEME, word_wrap=False, background_color="default"
            )
            if footer:
                return Group(syntax, Text("\n" + footer.strip()))
            return syntax
        return None

    def _check_is_error(self, text: str) -> bool:
        if isinstance(self.args, dict) and self.args.get("is_error"):
            return True
        if not text:
            return False
        cleaned = text.strip().lower()
        if cleaned.startswith(
            (
                "err:",
                "error:",
                "[error]",
                "exception:",
                "failed:",
                "failure:",
                "fatal:",
                "permission denied",
                "command failed",
            )
        ):
            return True
        if self.canonical_tool in ("read", "create", "edit", "multi_edit"):
            return False
        if "traceback (most recent call last):" in cleaned[:200] or "error:" in cleaned[:80] or "exception:" in cleaned[:80]:
            return True
        return False

    def _get_status_color(self) -> str:
        if self.status == "running":
            return "#e5c07b"
        elif self.status == "error":
            return "#e06c75"
        else:
            return "#98c379"

    def _extract_mcp_call_info(self) -> tuple[str, str, dict]:
        args = self.args if isinstance(self.args, dict) else {}
        tool_name = (
            args.get("tool")
            or args.get("Tool")
            or args.get("tool_name")
            or args.get("ToolName")
            or args.get("name")
            or args.get("Name")
            or "call_mcp"
        )
        server = args.get("server") or args.get("Server") or args.get("server_name") or args.get("ServerName") or ""
        mcp_args = None
        for k in ("arguments", "Arguments", "args", "Args"):
            if k in args and isinstance(args[k], dict):
                mcp_args = args[k]
                break

        if mcp_args is None:
            meta_keys = {
                "tool",
                "Tool",
                "tool_name",
                "ToolName",
                "name",
                "Name",
                "server",
                "Server",
                "server_name",
                "ServerName",
                "arguments",
                "Arguments",
                "args",
                "Args",
            }
            mcp_args = {k: v for k, v in args.items() if k not in meta_keys}

        return str(tool_name), str(server), mcp_args

    def _format_compact_dict(self, d: dict) -> str:
        if not isinstance(d, dict) or not d:
            return ""

        items = []
        total_len = 0
        overflow = False
        for k, v in d.items():
            k_str = str(k)
            if len(k_str) > 20:
                k_str = k_str[:17] + "..."

            if isinstance(v, str):
                v_clean = v.replace("\n", "\\n")
                if len(v_clean) > 35:
                    v_clean = v_clean[:32] + "..."
                v_str = f'"{v_clean}"'
            else:
                v_str = json.dumps(v, ensure_ascii=False)
                if len(v_str) > 35:
                    v_str = v_str[:32] + "..."

            item_str = f"{k_str}: {v_str}"
            if total_len + len(item_str) > 70:
                overflow = True
                break
            items.append(item_str)
            total_len += len(item_str) + 2

        if overflow and items:
            return "{" + ", ".join(items) + ", ...}"
        elif items:
            return "{" + ", ".join(items) + "}"
        else:
            return "{...}"


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
        "call_mcp": "CallMCP",
    }

    def get(self, key, default=None):
        from tools.registry import normalize_tool_name

        canonical = normalize_tool_name(key)
        if canonical in self.CANONICAL_NAMES:
            return self.CANONICAL_NAMES[canonical]
        return super().get(key, default)

    def __getitem__(self, key):
        res = self.get(key, None)
        if res is None:
            raise KeyError(key)
        return res

    def __contains__(self, key):
        return True


class _SystemToolsSet(set):
    def __contains__(self, item):
        if not isinstance(item, str):
            return False
        from tools.registry import REGISTRY, normalize_tool_name

        lower = item.lower()
        canonical = normalize_tool_name(lower)
        if canonical in REGISTRY or canonical in ("get_mcp_schema", "call_mcp", "update_plan"):
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
        "bash",
        "update_plan",
        "plan",
        "replace_file_content",
        "multi_replace_file_content",
        "replace",
        "multi_replace",
        "write_to_file",
        "call_mcp_tool",
        "call_mcp",
        "Create",
        "Edit",
        "MultiEdit",
        "Shell",
        "Bash",
        "Plan",
        "CallMCPTool",
        "CallMCP",
    }

    def is_expandable(self) -> bool:
        try:
            if hasattr(self, "screen") and type(self.screen).__name__ == "SubagentViewScreen":
                return False
        except Exception:
            pass
        from tools.registry import normalize_tool_name

        canonical = getattr(self, "canonical_tool", None) or normalize_tool_name(self.tool_type)
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
        try:
            if hasattr(self, "screen") and type(self.screen).__name__ == "SubagentViewScreen":
                return False
        except Exception:
            pass
        return self.is_expandable() or self.canonical_tool in ("invoke_subagent", "ask_user")

    def __init__(
        self, tool_type: str, target: str, result_text: str = "", is_sequential: bool = False, args: dict = None
    ):
        classes = f"tool-call tool-{tool_type.lower()}"
        if is_sequential:
            classes += " tool-sequential"
        super().__init__(classes=classes)
        from tools.registry import normalize_tool_name

        self.tool_type = tool_type
        self.canonical_tool = normalize_tool_name(tool_type)
        if isinstance(target, str):
            target = re.sub(r"\s+", " ", target.replace("\n", " ").replace("\r", " ")).strip()
        self.target = target
        self.result_text = result_text
        self.args = args or {}
        self.icon_name = tool_type
        self.is_expanded = False
        self.status = "running"
        if result_text:
            self.status = "error" if self._check_is_error(result_text) else "done"

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
        return escape(clean)

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.scroll_box

    def on_mount(self) -> None:
        self.content_widget.display = False
        self.md_widget.display = False
        self.render_header()

    def set_result(self, result_text: str, is_error: bool = False) -> None:
        cleaned = result_text.strip()
        if self.tool_type in ("shell", "Shell", "bash", "Bash"):
            if "[Background Task ID:" in cleaned or "Command is running in the background" in cleaned:
                self.status = "running"
                self.render_header()
                return
            if cleaned:
                self.result_text = cleaned
        else:
            self.result_text = cleaned

        if is_error or self._check_is_error(cleaned):
            self.status = "error"
        else:
            self.status = "done"

        if not self.is_clickable_header():
            self.is_expanded = False
            self.header_label.remove_class(TOOL_HEADER_EXPANDABLE)
            self.header_label.add_class(TOOL_HEADER)
            self.content_widget.display = False
            self.md_widget.display = False
        self.render_header()
        if self.is_expanded:
            self.render_content()

    DISPLAY_NAMES = _DisplayNamesDict()
    SYSTEM_TOOLS = _SystemToolsSet()

    def render_header(self) -> None:
        c = self._get_status_color()
        if self.canonical_tool == "update_plan":
            target_str = "Plan"
            if self.args and isinstance(self.args, dict):
                plan_data = self.args.get("plan")
                if isinstance(plan_data, dict):
                    entries = plan_data.get("entries", [])
                    total = len(entries)
                    completed = sum(1 for e in entries if isinstance(e, dict) and e.get("status") == "completed")
                    target_str = f"[{completed}/{total} completed]"
                elif isinstance(plan_data, list):
                    total = len(plan_data)
                    completed = sum(
                        1
                        for item in plan_data
                        if isinstance(item, dict) and item.get("status") in ("completed", "done")
                    )
                    target_str = f"[{completed}/{total} completed]"
            self.header_label.update(f"[{c}]⚙ [bold]UpdatePlan[/bold][/{c}]({escape(target_str)})")
        elif self.canonical_tool == "call_mcp" and self.tool_type.lower() in ("get_mcp_schema", "getmcpschema"):
            tool_name = self.args.get("tool") or self.target
            tool_name_snake = to_snake_case(str(tool_name))
            compact = self._format_compact_dict(self.args if isinstance(self.args, dict) else {})
            escaped_compact = escape(compact) if compact else "{}"
            self.header_label.update(f"[{c}]⚙ [bold]get_mcp_schema[/bold][/{c}]({escaped_compact})")
        elif self.canonical_tool == "call_mcp":
            tool_name, server, mcp_args = self._extract_mcp_call_info()
            tool_name_snake = to_snake_case(str(tool_name))
            compact = self._format_compact_dict(mcp_args)
            if not compact:
                compact = f'{{server: "{server}"}}' if server else "{}"
            escaped_compact = escape(compact)
            self.header_label.update(f"[{c}]⚙ [bold]{tool_name_snake}[/bold][/{c}]({escaped_compact})")
        elif self.tool_type in self.SYSTEM_TOOLS or self.canonical_tool in (
            "invoke_subagent",
            "manage_subagent",
            "ask_user",
        ):
            display_name = self.DISPLAY_NAMES.get(self.tool_type, self.tool_type)
            from core.tool_display import extract_tool_display

            project_dir = None
            try:
                project_dir = getattr(self.app, "project_dir", None)
            except Exception:
                pass
            target_str = extract_tool_display(self.tool_type, self.args, cwd=project_dir) if self.args else self.target
            self.header_label.update(f"[{c}]⚙ [bold]{display_name}[/bold][/{c}]({escape(str(target_str))})")
        else:
            # Eager MCP tool or custom external tool
            mcp_args = self.args if isinstance(self.args, dict) else {}
            compact = self._format_compact_dict(mcp_args)
            is_mcp = self.tool_type.startswith("mcp_") or getattr(self, "is_mcp", False)
            if compact or is_mcp:
                tool_name_display = to_snake_case(self.tool_type) if is_mcp else self.tool_type
                escaped_compact = escape(compact)
                self.header_label.update(f"[{c}]⚙ [bold]{tool_name_display}[/bold][/{c}]({escaped_compact})")
            else:
                display_name = self.DISPLAY_NAMES.get(self.tool_type, self.tool_type)
                self.header_label.update(f"[{c}]⚙ [bold]{display_name}[/bold][/{c}]({escape(self.target)})")

    def on_click(self, event) -> None:
        if not self.is_clickable_header():
            return
        if self.canonical_tool in ("invoke_subagent", "ask_user"):
            if self.canonical_tool == "invoke_subagent":
                args = self.args if isinstance(self.args, dict) else {}
                from tools.registry import normalize_tool_args

                nargs = normalize_tool_args(self.canonical_tool, args)
                session_id = nargs.get("task_id") or getattr(self, "subagent_session_id", None)
                identifier = session_id or nargs.get("description") or nargs.get("prompt") or self.target
                try:
                    from widgets.screens.subagent_screen import SubagentViewScreen

                    self.app.push_screen(SubagentViewScreen(identifier))
                except Exception:
                    pass
                event.stop()
                return
            if getattr(self.app, "_pending_ask_user", None) is not None:
                self._resume_ask_user_wizard()
                event.stop()
                return
            # No pending wizard: fall through to inline expand/collapse.

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
        if not isinstance(qs, list):
            single = args.get("question") or args.get("question_text")
            if isinstance(single, str):
                qs = [
                    {
                        "question_text": single,
                        "options": args.get("options") or args.get("choices"),
                    }
                ]
        out = []
        if isinstance(qs, list):
            for q in qs:
                if not isinstance(q, dict):
                    continue
                q_text = q.get("question_text") or q.get("question") or ""
                opts = q.get("options")
                if opts is None:
                    opts = q.get("choices")
                if q_text and isinstance(opts, list):
                    out.append({"question_text": str(q_text), "options": [str(o) for o in opts]})
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
                if (q.get("question_text") or "").strip() == q_text.strip():
                    answers[i] = {"answer": ans.strip()}
                    used.add(i)
                    break
        for i in range(len(questions)):
            if i not in answers:
                answers[i] = {"answer": "(No response)"}
        return answers

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

    def append_shell_output(self, text: str) -> None:
        if not hasattr(self, "_raw_bash_buffer"):
            self._raw_bash_buffer = ""
        self._raw_bash_buffer += text
        from core.background_task import process_carriage_returns

        cleaned = self._clean_bash_output(self._raw_bash_buffer)
        self.result_text = process_carriage_returns(cleaned)
        if self.is_expanded:
            self.render_content()

    def render_content(self) -> None:
        try:
            self.content_widget.display = True
            self.md_widget.display = False
            from tools.registry import normalize_tool_args

            nargs = normalize_tool_args(self.canonical_tool, self.args)
            file_path = nargs.get("path") or nargs.get("target_file") or self.target
            if self.tool_type in ("create", "Create", "write_to_file"):
                raw_text = (self.result_text or "").strip()
                if self.status == "error" or self._check_is_error(raw_text):
                    self.content_widget.update(self._clean_markup_text(raw_text or "(Error)"))
                elif raw_text and (
                    "@@" in raw_text
                    or "--- a/" in raw_text
                    or "+++ b/" in raw_text
                    or " updated " in raw_text
                    or " updated (" in raw_text
                ):
                    diff_text = raw_text
                    if "@@" not in diff_text and "--- a/" not in diff_text:
                        content = (
                            self.args.get("content")
                            or self.args.get("CodeContent")
                            or self.args.get("code_content")
                            or ""
                        )
                        diff_text = build_synthetic_create_diff(file_path, content)

                    formatted_diff = self._format_edit_diff(diff_text, file_path)
                    self.content_widget.update(formatted_diff)
                else:
                    content = self.args.get("content") or self.args.get("CodeContent") or self.args.get("code_content")
                    if content is None:
                        if file_path and os.path.isfile(file_path):
                            try:
                                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                                    content = f.read()
                            except Exception:
                                content = None

                    if content is not None:
                        content = content.rstrip("\r\n")
                        lexer = self._guess_lexer(file_path)
                        try:
                            syntax = TransparentSyntax(
                                content,
                                lexer,
                                theme=CODE_THEME,
                                line_numbers=True,
                                word_wrap=False,
                                background_color="default",
                            )
                            self.content_widget.update(syntax)
                        except Exception:
                            rendered = self._format_code_with_line_numbers(content)
                            self.content_widget.update(rendered)
                    else:
                        self.content_widget.update(self._clean_markup_text(self.result_text or "(No content)"))
            elif self.tool_type in (
                "edit",
                "Edit",
                "multi_edit",
                "MultiEdit",
                "replace_file_content",
                "multi_replace_file_content",
                "replace",
                "multi_replace",
            ):
                raw_text = (self.result_text or "").strip()
                if self.status == "error" or self._check_is_error(raw_text):
                    self.content_widget.update(self._clean_markup_text(raw_text or "(Error)"))
                else:
                    diff_text = raw_text
                    if not diff_text or "@@" not in diff_text:
                        from widgets.lexer_utils import build_edit_diff_text

                        diff_text = build_edit_diff_text(self.args, file_path or "file", self.tool_type)

                    if diff_text:
                        formatted_diff = self._format_edit_diff(diff_text, file_path)
                        self.content_widget.update(formatted_diff)
                    else:
                        self.content_widget.update(self._clean_markup_text(self.result_text or "(No diff)"))
            elif self.tool_type in ("update_plan", "Plan", "plan"):
                raw_text = (self.result_text or "").strip()
                if self.status == "error" or self._check_is_error(raw_text):
                    self.content_widget.update(self._clean_markup_text(raw_text or "(Error)"))
                else:
                    plan_items = self.args.get("plan") or []
                    explanation = self.args.get("explanation", "")
                    formatted_plan = self._format_plan_display(plan_items, explanation)
                    self.content_widget.update(formatted_plan)
            elif self.canonical_tool == "ask_user":
                self.content_widget.update(self._format_ask_user_display())
            elif self.tool_type in ("web_fetch", "WebFetch"):
                raw_text = self.result_text or ""
                if raw_text.strip().lower().startswith("error"):
                    t = Text(raw_text.strip(), style="bold #ffffff")
                    self.content_widget.update(t)
                    self.content_widget.display = True
                    self.md_widget.display = False
                else:
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
                                    word_wrap=False,
                                    background_color="default",
                                )
                                self.content_widget.update(syntax)
                            except Exception:
                                rendered = self._format_code_with_line_numbers(clean_code)
                                self.content_widget.update(rendered)
                        else:
                            self.content_widget.update(self._clean_markup_text(self.result_text or "(No content)"))
                        self.content_widget.display = True
                        self.md_widget.display = False
                    else:
                        clean_code = self._fix_markdown_nested_lists(clean_code)
                        safe_update_markdown(self.md_widget, clean_code.rstrip("\r\n") or "(No content)")
                        self.md_widget.display = True
                        self.content_widget.display = False
            elif self.tool_type in ("read", "Read"):
                raw_text = self.result_text or ""
                if raw_text.strip().lower().startswith("error"):
                    t = Text(raw_text.strip(), style="bold #ffffff")
                    self.content_widget.update(t)
                    self.content_widget.display = True
                    self.md_widget.display = False
                else:
                    default_target = file_path or "file.txt"
                    clean_code, start_line, fpath = self._format_read_content(raw_text, default_target)

                    if not clean_code.strip() and fpath and os.path.isfile(fpath):
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                                clean_code = f.read()
                                start_line = 1
                        except Exception:
                            clean_code = ""

                    lexer = self._guess_lexer(fpath)
                    if lexer == "markdown":
                        clean_code = self._fix_markdown_nested_lists(clean_code)
                        safe_update_markdown(self.md_widget, clean_code.rstrip("\r\n") or "(No content)")
                        self.md_widget.display = True
                        self.content_widget.display = False
                    else:
                        if clean_code:
                            clean_code = clean_code.rstrip("\r\n")
                            try:
                                syntax = TransparentSyntax(
                                    clean_code,
                                    lexer,
                                    theme=CODE_THEME,
                                    line_numbers=True,
                                    start_line=start_line,
                                    word_wrap=False,
                                    background_color="default",
                                )
                                self.content_widget.update(syntax)
                            except Exception:
                                rendered = self._format_code_with_line_numbers(clean_code)
                                self.content_widget.update(rendered)
                        else:
                            self.content_widget.update(self._clean_markup_text(self.result_text or "(No content)"))
                        self.content_widget.display = True
                        self.md_widget.display = False
            elif self.tool_type in ("shell", "Shell", "bash", "Bash"):
                output_text = self._clean_bash_output(self.result_text)
                if not output_text.strip():
                    is_running = False
                    if self.app and hasattr(self.app, "background_tasks"):
                        bg_match = re.search(r"Background Task ID:\s*([^\s\]]+)", self.result_text or "")
                        if bg_match:
                            tid = bg_match.group(1)
                            for t in self.app.background_tasks:
                                if getattr(t, "task_id", "") == tid and getattr(t, "is_running", False):
                                    is_running = True
                                    break
                    if is_running:
                        output_text = "(Running command...)"
                    else:
                        output_text = "(No output)"
                self.content_widget.update(self._clean_markup_text(output_text))
            elif self.tool_type.lower() in ("get_mcp_schema", "getmcpschema"):
                server = self.args.get("server", "")
                tool = self.args.get("tool", "")
                display_parts = [f"Server: {server}", f"Tool: {tool}"]
                if self.result_text:
                    display_parts.append(f"\nSchema:\n{self.result_text.strip()}")
                full_display = "\n".join(display_parts)
                try:
                    syntax = TransparentSyntax(
                        full_display, "json", theme=CODE_THEME, word_wrap=False, background_color="default"
                    )
                    self.content_widget.update(syntax)
                except Exception:
                    self.content_widget.update(self._clean_markup_text(full_display))
            elif self.tool_type in ("call_mcp", "CallMCP", "call_mcp_tool", "CallMCPTool"):
                clean_res = self._clean_hints_for_ui(self.result_text or "(No result)")
                syntax = self._format_json_result(clean_res)
                if syntax:
                    self.content_widget.update(syntax)
                else:
                    self.content_widget.update(self._clean_markup_text(clean_res))
            else:
                clean_res = self._clean_hints_for_ui(self.result_text or "(No result)")
                syntax = self._format_json_result(clean_res)
                if syntax:
                    self.content_widget.update(syntax)
                else:
                    self.content_widget.update(self._clean_markup_text(clean_res))
        except Exception:
            pass
