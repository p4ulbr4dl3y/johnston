"""Specialized tool rendering and formatting helpers for tool calls."""
from __future__ import annotations

import os
import re
from typing import Any, Callable

from rich.text import Text

from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.presentation.widgets.chat_markdown import TransparentSyntax, get_current_syntax_theme


def clean_truncation_marker(match: re.Match) -> str:
    """Format a regex match of a truncation tag into a clean UI string."""
    prefix = match.group(1) or ""
    tag_name = match.group(2) or "Truncated"
    inner = match.group(3)
    if "|" in inner:
        parts = [p.strip() for p in inner.split("|") if p.strip()]
        ui_parts = []
        for p in parts:
            if re.match(r"^(?:Next:?|next)\s*", p, re.IGNORECASE):
                continue
            if re.match(r"^Use\s+.*to inspect", p, re.IGNORECASE):
                continue
            ui_parts.append(p)
        if ui_parts:
            if tag_name.lower() == "truncated":
                return f"{prefix}[truncated | {' | '.join(ui_parts)}]"
            return f"{prefix}[{tag_name}: {' | '.join(ui_parts)}]"
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


def format_truncation_for_ui(text: str) -> str:
    """Format truncation banners for UI display."""
    if not text:
        return ""
    return re.sub(
        r"(\.\.\.\s*)?\[(Output\s+truncated|Truncated):?\s*([^\]]*)\]",
        clean_truncation_marker,
        text,
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
        t.append(f"{explanation}\n\n", style="italic dim")

    if isinstance(plan_items, list):
        plan_lines = []
        for item in plan_items:
            if not isinstance(item, dict):
                continue
            step = str(item.get("step") or "").strip()
            status = str(item.get("status") or "pending").lower()

            if status == "completed":
                line = Text("[✓] ", style="dim") + Text(step, style="strike dim")
            elif status == "in_progress":
                line = Text("[▶] ", style="bold") + Text(step, style="bold")
            else:
                line = Text("[ ] ") + Text(step)
            plan_lines.append(line)

        for i, pl in enumerate(plan_lines):
            t.append(pl)
            if i < len(plan_lines) - 1:
                t.append("\n")
    elif isinstance(plan_items, str) and plan_items.strip():
        t.append(plan_items.strip())

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
        t.append(f"{prefix}{q_text}\n", style="bold")
        ans_info = answers.get(i, {})
        ans = ans_info.get("answer", "") if isinstance(ans_info, dict) else str(ans_info or "")
        if ans:
            t.append(ans)
        else:
            t.append("(No response)", style="italic dim")
    return t


def format_manage_shell_display(result_text: str) -> Text:
    """Format manage_shell list output into a monochrome rich Text renderable."""
    raw = (result_text or "").strip()
    if not raw or raw.lower() in ("no tasks active", "no active tasks", "(no active tasks)"):
        return Text("(No active tasks)")

    t = Text()
    lines = raw.splitlines()
    task_lines = []
    for line in lines:
        line_clean = line.strip()
        if not line_clean or line_clean.lower().startswith("active background tasks:"):
            continue
        # Pattern: "- ID: {id} | Status: {status} | Command: {cmd}"
        m = re.match(
            r"^[-\*]?\s*ID:\s*([^|]+?)\s*\|\s*Status:\s*([^|]+?)\s*\|\s*Command:\s*(.*)$",
            line_clean,
            re.IGNORECASE,
        )
        if m:
            t_id, status, cmd = m.group(1).strip(), m.group(2).strip().upper(), m.group(3).strip()
            if status.startswith("RUNNING"):
                task_t = Text("[▶] ", style="bold") + Text(f"{t_id}  ", style="bold") + Text(cmd)
            else:
                task_t = Text("[✓] ", style="dim") + Text(f"{t_id}  ", style="dim") + Text(cmd, style="dim")
            task_lines.append(task_t)
        else:
            task_lines.append(Text(line_clean))

    if not task_lines:
        return Text("(No active tasks)")

    for i, tl in enumerate(task_lines):
        t.append(tl)
        if i < len(task_lines) - 1:
            t.append("\n")
    return t


def format_manage_subagent_display(result_text: str) -> Text:
    """Format manage_subagent list output into a monochrome rich Text renderable."""
    raw = (result_text or "").strip()
    if not raw or "no subagent sessions found" in raw.lower() or raw.lower() in ("no tasks active", "(no active subagents)"):
        return Text("(No active subagents)")

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
            from core.role_registry import get_role_display_name

            role_cap = get_role_display_name(role) if role else "Worker"
            desc = f"{role_cap}: {title}" if title else (role_cap or "(no description)")
            if status == "RUNNING":
                item_t = (
                    Text("[▶] ", style="bold")
                    + Text(f"{s_id}  ", style="bold")
                    + Text(desc)
                )
            else:
                item_t = (
                    Text("[✓] ", style="dim")
                    + Text(f"{s_id}  ", style="dim")
                    + Text(desc, style="dim")
                )
            subagent_lines.append(item_t)
        else:
            subagent_lines.append(Text(line_clean))

    if not subagent_lines:
        return Text("(No active subagents)")

    for i, sl in enumerate(subagent_lines):
        t.append(sl)
        if i < len(subagent_lines) - 1:
            t.append("\n")
    return t


def format_code_with_line_numbers(code: str) -> str:
    """Format code with fallback line numbers."""
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


def compute_tool_call_content(
    *,
    tool_type: str,
    canonical_tool: str,
    args: dict,
    target: str,
    result_text: str,
    is_error: bool,
    guess_lexer: Callable[[str], str],
    clean_markup: Callable[[str], str],
    clean_hints: Callable[[str], str],
    clean_bash_output: Callable[[str], str],
    format_json_result_fn: Callable[[str], str | None],
) -> tuple[str, Any]:
    """Compute (kind, value) representation for expanded tool-call content."""
    try:
        file_path = args.get("path") or target
        if tool_type == "create":
            raw_text = (result_text or "").strip()
            if is_error:
                return "markup", clean_markup(raw_text or "(Error)")
            if raw_text and (
                "@@" in raw_text
                or "--- a/" in raw_text
                or "+++ b/" in raw_text
                or " updated " in raw_text
                or " updated (" in raw_text
            ):
                diff_text = raw_text
                if "@@" not in diff_text and "--- a/" not in diff_text:
                    content = args.get("content") or ""
                    diff_text = build_synthetic_create_diff(file_path, content)
                formatted_diff = format_edit_diff(clean_hints(diff_text), file_path)
                return "raw", formatted_diff
            content = args.get("content")
            if content is None:
                from widgets.utils.file_reader import read_file_content

                content = read_file_content(file_path)
            if content is None and raw_text:
                content = raw_text

            if content is not None:
                content = content.rstrip("\r\n")
                lexer = guess_lexer(file_path)
                try:
                    from widgets.app.theme_manager import theme_manager

                    curr_theme = getattr(theme_manager, "current_theme", None)
                    is_dark = getattr(curr_theme, "dark", True) if curr_theme else True
                    syntax_theme = get_current_syntax_theme(dark=is_dark)
                    syntax = TransparentSyntax(
                        content,
                        lexer,
                        theme=syntax_theme,
                        line_numbers=True,
                        word_wrap=True,
                        background_color="default",
                    )
                    return "raw", syntax
                except Exception:
                    return "raw", format_code_with_line_numbers(content)
            return "markup", clean_markup(result_text or "(No content)")
        elif tool_type == "edit":
            raw_text = (result_text or "").strip()
            if is_error:
                return "markup", clean_markup(raw_text or "(Error)")
            diff_text = raw_text
            if not diff_text or "@@" not in diff_text:
                from widgets.lexer_utils import build_edit_diff_text

                diff_text = build_edit_diff_text(args, file_path or "file")

            if diff_text:
                return "raw", format_edit_diff(clean_hints(diff_text), file_path)
            return "markup", clean_markup(result_text or "(No diff)")
        elif tool_type == "update_plan":
            raw_text = (result_text or "").strip()
            if is_error:
                return "markup", clean_markup(raw_text or "(Error)")
            plan_items = args.get("plan") or []
            explanation = args.get("explanation", "")
            return "raw", format_plan_display(plan_items, explanation)
        elif canonical_tool == "ask_user":
            raw_text = clean_hints(result_text or "(No response)")
            t = Text()
            blocks = raw_text.split("\n\n")
            for i, block in enumerate(blocks):
                if i > 0:
                    t.append("\n\n")
                lines = block.split("\n", 1)
                if len(lines) == 2:
                    q_line, ans_line = lines
                    t.append(f"{q_line.strip()}\n", style="bold")
                    t.append(ans_line.strip(), style="dim" if ans_line.strip() == "(No response)" else "")
                else:
                    t.append(block)
            return "raw", t
        elif canonical_tool == "manage_shell":
            action = (args.get("action") or "list").lower()
            if action == "list":
                return "raw", format_manage_shell_display(result_text or "")
            clean_res = clean_hints(result_text or "(No result)")
            return "markup", clean_markup(clean_res)
        elif canonical_tool == "manage_subagent":
            action = (args.get("action") or "list").lower()
            if action == "list":
                return "raw", format_manage_subagent_display(result_text or "")
            clean_res = clean_hints(result_text or "(No result)")
            return "markup", clean_markup(clean_res)
        elif canonical_tool == "invoke_subagent":
            clean_res = clean_hints(result_text or "")
            if not clean_res.strip():
                prompt = args.get("prompt", "")
                clean_res = prompt or "(Subagent task)"
            return "markup", clean_markup(clean_res)
        elif tool_type == "shell":
            output_text = clean_bash_output(result_text)
            log_match = re.search(r"Full Log:\s*([^\s\(\)\]]+)", result_text or "")
            if log_match:
                log_path = log_match.group(1).rstrip(".]")
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
            return "markup", clean_markup(output_text)
        else:
            clean_res = clean_hints(result_text or "(No result)")
            json_res = format_json_result_fn(clean_res)
            if json_res:
                return "markup", clean_markup(json_res)
            return "markup", clean_markup(clean_res)
    except Exception:
        return "markup", clean_markup(result_text or "")
