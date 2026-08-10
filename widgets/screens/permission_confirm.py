import json
import os
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, Static

from widgets.chat_toolcall import build_synthetic_create_diff
from widgets.chat_view import ToolScrollBox, format_edit_diff


class PermissionConfirmScreen(ModalScreen[str]):
    """Modal screen asking user for permission before executing a tool in human-friendly format."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("enter", "approve", "Approve Once"),
        ("a", "always_allow", "Always Allow (Session)"),
        ("escape", "deny", "Deny"),
        ("d", "deny", "Deny"),
        ("up", "scroll_up", "Scroll Up"),
        ("down", "scroll_down", "Scroll Down"),
        ("left", "scroll_left", "Scroll Left"),
        ("right", "scroll_right", "Scroll Right"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("ctrl+c", "quit", "Exit"),
    ]

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

    def _build_diff_text(self, target_path: str) -> str:
        if self.diff:
            return self.diff

        # Generate diff for Create/Write tools updating existing file
        if self.tool_name in ("create", "write", "write_to_file"):
            content = (
                self.args.get("content")
                or self.args.get("CodeContent")
                or self.args.get("code_content")
                or self.args.get("code")
                or ""
            )
            return build_synthetic_create_diff(target_path, content)

        # Generate diff for Edit tools
        if self.tool_name in ("edit", "replace_file_content", "multi_replace_file_content", "multi_edit"):
            from widgets.lexer_utils import build_edit_diff_text

            return build_edit_diff_text(self.args, target_path or "file", self.tool_name)

        return ""

    def compose(self) -> ComposeResult:
        from tools.registry import normalize_tool_args

        nargs = normalize_tool_args(self.tool_name, self.args)
        target_path = nargs.get("path") or nargs.get("target_file") or ""

        if self.tool_name in ("create", "write", "write_to_file"):
            file_exists = bool(target_path and os.path.isfile(target_path))
            if file_exists or self.diff:
                action_desc = f"Agent wants to write `{target_path or 'file'}` with diff:"
            else:
                action_desc = f"Agent wants to write `{target_path or 'file'}`:"
        elif self.tool_name in ("edit", "replace_file_content", "multi_replace_file_content", "multi_edit"):
            action_desc = f"Agent wants to edit `{target_path or 'file'}` with diff:"
        elif self.tool_name in ("read", "view_file", "read_file"):
            action_desc = f"Agent wants to read `{target_path or 'file'}`"
        elif self.tool_name in ("web_fetch", "fetch_url"):
            url = nargs.get("url") or ""
            action_desc = f"Agent wants to fetch `{url or 'URL'}`"
        elif self.tool_name in ("invoke_subagent", "subagent"):
            role = nargs.get("type") or nargs.get("subagent_type") or "Subagent"
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
            elif act == "status":
                action_desc = (
                    f"Agent wants to check status of task `{t_id}`" if t_id else "Agent wants to check task status"
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
        elif self.tool_name in ("shell", "run_command", "bash"):
            action_desc = "Agent wants to run shell command:"
        else:
            if self.args:
                action_desc = f"Agent wants to execute `{self.tool_name}` with parameters:"
            else:
                action_desc = f"Agent wants to execute `{self.tool_name}`"

        with Vertical(id="modal-dialog", classes="bash-confirm-dialog"):
            yield Markdown("### **Confirm Tool Action**", classes="modal-markdown modal-markdown-centered")
            yield Markdown(action_desc, classes="modal-markdown")

            if self.tool_name in ("create", "write", "write_to_file"):
                file_exists = bool(target_path and os.path.isfile(target_path))
                if file_exists or self.diff:
                    diff_text = self._build_diff_text(target_path)
                    formatted_diff = format_edit_diff(diff_text, target_path)
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Static(formatted_diff, classes="modal-diff-view")
                else:
                    code_content = nargs.get("content") or nargs.get("code") or ""
                    ext = os.path.splitext(target_path)[1].lstrip(".") or "py"
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Markdown(f"```{ext}\n{code_content.strip()}\n```", classes="modal-diff-view")
            elif (
                self.tool_name in ("edit", "replace_file_content", "multi_replace_file_content", "multi_edit")
                or self.diff
            ):
                diff_text = self._build_diff_text(target_path)
                formatted_diff = format_edit_diff(diff_text, target_path)
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Static(formatted_diff, classes="modal-diff-view")
            elif self.tool_name in ("shell", "run_command", "bash"):
                cmd = nargs.get("command") or ""
                from core.platform_utils import is_windows

                lang = "powershell" if is_windows() else "bash"
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```{lang}\n{cmd.strip()}\n```", classes="modal-diff-view")
            elif self.tool_name in ("manage_shell",) and (nargs.get("action") or "").lower() == "send_input":
                inp = nargs.get("input") or ""
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```text\n{inp.strip()}\n```", classes="modal-diff-view")
            elif self.tool_name in ("invoke_subagent", "subagent"):
                prompt = nargs.get("prompt") or ""
                if prompt:
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Markdown(f"```text\n{prompt.strip()}\n```", classes="modal-diff-view")
            elif self.args and self.tool_name not in (
                "shell",
                "run_command",
                "bash",
                "read",
                "view_file",
                "read_file",
                "web_fetch",
                "fetch_url",
                "manage_shell",
                "invoke_subagent",
                "subagent",
            ):
                args_str = json.dumps(self.args, indent=2, ensure_ascii=False)
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```json\n{args_str}\n```", classes="modal-diff-view")

            yield Label("enter: approve • a: always allow session • esc/d: deny", id="modal-hint")

    def action_scroll_up(self) -> None:
        try:
            self.query_one("#modal-dialog").scroll_up(animate=False)
        except Exception:
            pass

    def action_scroll_down(self) -> None:
        try:
            self.query_one("#modal-dialog").scroll_down(animate=False)
        except Exception:
            pass

    def action_page_up(self) -> None:
        try:
            self.query_one("#modal-dialog").scroll_page_up(animate=False)
        except Exception:
            pass

    def action_page_down(self) -> None:
        try:
            self.query_one("#modal-dialog").scroll_page_down(animate=False)
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

    def action_always_allow(self) -> None:
        self.dismiss("always_allow")

    def action_deny(self) -> None:
        self.dismiss("deny")

    def action_quit(self) -> None:
        self.app.exit()
