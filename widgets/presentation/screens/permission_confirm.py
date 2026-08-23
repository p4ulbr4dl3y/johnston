import json
import os
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, Static

from core.domain.policies.permission_policy import suggest_pattern
from widgets.chat_toolcall import ToolScrollBox, build_synthetic_create_diff
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.utils.key_aliases import expand_bindings


class PermissionConfirmScreen(BaseModalScreen[str]):
    """Modal screen asking user for permission before executing a tool in human-friendly format."""

    ALLOW_SELECT = False
    BINDINGS = expand_bindings([
        ("enter", "approve", "Approve Once"),
        ("p", "allow_pattern", "Allow Pattern (Session)"),
        ("a", "always_allow", "Always Allow (Session)"),
        ("escape", "deny", "Deny"),
        ("d", "deny", "Deny"),
        ("up", "scroll_up", "Scroll Up"),
        ("down", "scroll_down", "Scroll Down"),
        ("left", "scroll_left", "Scroll Left"),
        ("right", "scroll_right", "Scroll Right"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        reason: str = "",
        diff: str = "",
    ):
        super().__init__()
        self.tool_name = tool_name
        self.args = args or {}
        self.reason = reason
        self.diff = diff
        self.suggested_pattern = suggest_pattern(self.tool_name, self.args)

    def _build_diff_text(self, target_path: str) -> str:

        if self.diff:
            return self.diff

        # Generate diff for Create/Write tools updating existing file
        if self.tool_name == "create":
            content = self.args.get("content") or ""
            return build_synthetic_create_diff(target_path, content)

        # Generate diff for Edit tools
        if self.tool_name in ("edit", "multi_edit"):
            from widgets.lexer_utils import build_edit_diff_text

            return build_edit_diff_text(self.args, target_path or "file")

        return ""

    def compose(self) -> ComposeResult:
        nargs = self.args if isinstance(self.args, dict) else {}
        target_path = nargs.get("path") or ""

        if self.tool_name == "create":
            file_exists = bool(target_path and os.path.isfile(target_path))
            if file_exists or self.diff:
                action_desc = f"Agent wants to write `{target_path or 'file'}` with diff:"
            else:
                action_desc = f"Agent wants to write `{target_path or 'file'}`:"
        elif self.tool_name in ("edit", "multi_edit"):
            action_desc = f"Agent wants to edit `{target_path or 'file'}` with diff:"
        elif self.tool_name == "read":
            action_desc = f"Agent wants to read `{target_path or 'file'}`"
        elif self.tool_name == "web_fetch":
            url = nargs.get("url") or ""
            action_desc = f"Agent wants to fetch `{url or 'URL'}`"
        elif self.tool_name == "invoke_subagent":
            role = nargs.get("type") or "Subagent"
            prompt = nargs.get("prompt") or ""
            if prompt:
                action_desc = f"Agent wants to launch subagent `{role}` with prompt:"
            else:
                action_desc = f"Agent wants to launch subagent `{role}`"
        elif self.tool_name in ("manage_shell",):
            act = (nargs.get("action") or "manage").lower()
            t_id = nargs.get("task_id") or ""

            if act == "kill":
                action_desc = (
                    f"Agent wants to cancel task `{t_id}`" if t_id else "Agent wants to cancel background task"
                )
            elif act == "list":
                action_desc = "Agent wants to list background tasks"
            elif act == "send_input":
                target_str = f" to task `{t_id}`" if t_id else ""
                action_desc = f"Agent wants to send input{target_str}:"
            else:
                action_desc = (
                    f"Agent wants to `{act}` task `{t_id}`" if t_id else "Agent wants to manage background tasks"
                )
        elif self.tool_name in ("manage_subagent",):
            act = (nargs.get("action") or "manage").lower()
            s_id = nargs.get("session_id") or ""

            if act == "kill":
                action_desc = (
                    f"Agent wants to cancel subagent `{s_id}`" if s_id else "Agent wants to cancel a subagent"
                )
            elif act == "list":
                action_desc = "Agent wants to list subagents"
            elif act == "send_message":
                target_str = f" to subagent `{s_id}`" if s_id else ""
                action_desc = f"Agent wants to send a message{target_str}:"
            else:
                action_desc = (
                    f"Agent wants to `{act}` subagent `{s_id}`" if s_id else "Agent wants to manage subagents"
                )
        elif self.tool_name == "update_plan":
            plan = (nargs.get("plan") or "").strip()
            action_desc = "Agent wants to update the plan:" if plan else "Agent wants to update the plan"
        elif self.tool_name == "ask_user":
            qs = nargs.get("questions") or []
            q_texts = []
            if isinstance(qs, list):
                for q in qs:
                    if isinstance(q, dict):
                        t = q.get("question") or ""
                    else:
                        t = str(q)
                    t = t.strip()
                    if t:
                        q_texts.append(t)
            if q_texts:
                formatted_qs = ", ".join(f"`{t}`" for t in q_texts)
                action_desc = f"Agent wants to ask {formatted_qs}"
            else:
                action_desc = "Agent wants to ask a question"
        elif self.tool_name == "shell":
            action_desc = "Agent wants to run shell command:"
        else:
            if self.args:
                action_desc = f"Agent wants to execute `{self.tool_name}` with parameters:"
            else:
                action_desc = f"Agent wants to execute `{self.tool_name}`"

        is_wide = (
            self.tool_name in ("create", "edit", "multi_edit", "shell")
            or bool(self.diff)
            or (
                bool(self.args)
                and self.tool_name not in (
                    "read",
                    "web_fetch",
                    "manage_shell",
                    "manage_subagent",
                    "invoke_subagent",
                    "update_plan",
                    "ask_user",
                )
            )
        )
        dialog_classes = "bash-confirm-dialog modal-dialog-wide" if is_wide else "bash-confirm-dialog"

        with Vertical(id="modal-dialog", classes=dialog_classes):
            yield Markdown("### **Confirm Tool Action**", classes="modal-markdown modal-markdown-centered")
            yield Markdown(action_desc, classes="modal-markdown")

            if self.tool_name == "create":
                file_exists = bool(target_path and os.path.isfile(target_path))
                if file_exists or self.diff:
                    diff_text = self._build_diff_text(target_path)
                    formatted_diff = format_edit_diff(diff_text, target_path)
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Static(formatted_diff, classes="modal-diff-view")
                else:
                    code_content = nargs.get("content") or ""
                    ext = os.path.splitext(target_path)[1].lstrip(".") or "py"
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Markdown(f"```{ext}\n{code_content.strip()}\n```", classes="modal-diff-view")
            elif (
                self.tool_name in ("edit", "multi_edit")
                or self.diff
            ):
                diff_text = self._build_diff_text(target_path)
                formatted_diff = format_edit_diff(diff_text, target_path)
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Static(formatted_diff, classes="modal-diff-view")
            elif self.tool_name == "shell":
                cmd = nargs.get("command") or ""
                from core.infrastructure.platform.platform_utils import is_windows

                lang = "powershell" if is_windows() else "bash"
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```{lang}\n{cmd.strip()}\n```", classes="modal-diff-view")
            elif (
                self.tool_name in ("manage_shell",) and (nargs.get("action") or "").lower() == "send_input"
            ):
                inp = nargs.get("input") or ""
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```text\n{inp.strip()}\n```", classes="modal-diff-view")
            elif (
                self.tool_name in ("manage_subagent",) and (nargs.get("action") or "").lower() == "send_message"
            ):
                msg = nargs.get("message") or ""
                if msg:
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Markdown(f"```text\n{msg.strip()}\n```", classes="modal-diff-view")
            elif self.tool_name == "invoke_subagent":
                prompt = nargs.get("prompt") or ""
                if prompt:
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Markdown(f"```text\n{prompt.strip()}\n```", classes="modal-diff-view")
            elif self.tool_name == "update_plan":
                plan = nargs.get("plan") or ""
                if plan:
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Markdown(f"```markdown\n{plan.strip()}\n```", classes="modal-diff-view")
            elif self.tool_name == "ask_user":
                qs = nargs.get("questions") or []
                if isinstance(qs, list) and any(isinstance(q, dict) and q.get("options") for q in qs):
                    lines = []
                    for i, q in enumerate(qs, 1):
                        if isinstance(q, dict) and q.get("options"):
                            q_text = q.get("question") or ""
                            opts = q.get("options") or []
                            opts_str = "\n  - " + "\n  - ".join(str(o) for o in opts)
                            prefix = f"{i}. " if len(qs) > 1 else ""
                            lines.append(f"{prefix}`{q_text}`{opts_str}")
                    if lines:
                        with ToolScrollBox(classes="tool-scroll-box"):
                            yield Markdown("\n\n".join(lines), classes="modal-diff-view")
            elif self.args and self.tool_name not in (
                "shell",
                "read",
                "web_fetch",
                "manage_shell",
                "manage_subagent",
                "invoke_subagent",
                "update_plan",
                "ask_user",
            ):
                args_str = json.dumps(self.args, indent=2, ensure_ascii=False)
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```json\n{args_str}\n```", classes="modal-diff-view")

            if self.suggested_pattern:
                yield Label(f"enter: allow • p: pattern ({self.suggested_pattern}) • a: all tool • esc/d: deny", id="modal-hint")
            else:
                yield Label("enter: allow • a: session • esc/d: deny", id="modal-hint")

    def _get_scroll_target(self):
        try:
            return self.query_one(".tool-scroll-box")
        except Exception:
            return self.query_one("#modal-dialog")

    def action_scroll_up(self) -> None:
        try:
            self._get_scroll_target().scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_down(self) -> None:
        try:
            self._get_scroll_target().scroll_down(animate=False)
        except Exception:
            pass

    def action_page_up(self) -> None:
        try:
            self._get_scroll_target().scroll_page_up(animate=False)
        except Exception:
            pass

    def action_page_down(self) -> None:
        try:
            self._get_scroll_target().scroll_page_down(animate=False)
        except Exception:
            pass

    def action_scroll_left(self) -> None:
        try:
            self.query_one(".tool-scroll-box").scroll_left(animate=False)
        except Exception:
            pass

    def action_scroll_right(self) -> None:
        try:
            self.query_one(".tool-scroll-box").scroll_right(animate=False)
        except Exception:
            pass

    def action_approve(self) -> None:
        self.dismiss("allow")

    def action_allow_pattern(self) -> None:
        if self.suggested_pattern:
            self.dismiss(f"pattern:{self.suggested_pattern}")
        else:
            self.dismiss("always_allow")

    def action_always_allow(self) -> None:
        self.dismiss("always_allow")

    def action_deny(self) -> None:
        self.dismiss("deny")

    def action_cancel(self) -> None:
        self.dismiss("deny")


