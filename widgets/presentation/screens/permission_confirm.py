import json
import os
from typing import Any, Dict, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, Static

from core.domain.policies.permission_policy import suggest_pattern
from widgets.chat_toolcall import ToolScrollBox, build_synthetic_create_diff, format_plan_display
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.utils.key_aliases import expand_bindings


class RejectReasonInput(Input):
    """Input widget that forwards vertical navigation and scroll keys to modal scroll box."""

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key in ("up", "key_up"):
            if self.screen and hasattr(self.screen, "action_scroll_up"):
                self.screen.action_scroll_up()
                event.stop()
                event.prevent_default()
                return
        elif key in ("down", "key_down"):
            if self.screen and hasattr(self.screen, "action_scroll_down"):
                self.screen.action_scroll_down()
                event.stop()
                event.prevent_default()
                return
        elif key in ("pageup", "key_pageup"):
            if self.screen and hasattr(self.screen, "action_page_up"):
                self.screen.action_page_up()
                event.stop()
                event.prevent_default()
                return
        elif key in ("pagedown", "key_pagedown"):
            if self.screen and hasattr(self.screen, "action_page_down"):
                self.screen.action_page_down()
                event.stop()
                event.prevent_default()
                return

        await super()._on_key(event)


class PermissionConfirmScreen(BaseModalScreen[str]):
    """Modal screen asking user for permission before executing a tool in human-friendly format."""

    AUTO_FOCUS = ""
    ALLOW_SELECT = False
    BINDINGS = expand_bindings([
        ("enter", "approve", "Approve Once"),
        ("p", "allow_pattern", "Allow Pattern (Session)"),
        ("a", "always_allow", "Always Allow (Session)"),
        ("r", "reject_with_reason", "Reject with Reason"),
        ("escape", "deny", "Deny"),
        ("d", "deny", "Deny"),
        ("up", "scroll_up", "Scroll Up"),
        ("down", "scroll_down", "Scroll Down"),
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
        is_subagent: bool = False,
        subagent_role: str = "",
    ):
        super().__init__()
        self.tool_name = tool_name
        self.args = args or {}
        self.reason = reason
        self.diff = diff
        self.is_subagent = is_subagent
        self.subagent_role = subagent_role or ("worker" if is_subagent else "")
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
        actor = (
            f"Subagent ({self.subagent_role})"
            if (self.is_subagent and self.subagent_role)
            else ("Subagent" if self.is_subagent else "Agent")
        )

        if self.tool_name == "create":
            file_exists = bool(target_path and os.path.isfile(target_path))
            if file_exists or self.diff:
                action_desc = f"{actor} wants to overwrite `{target_path or 'file'}` with diff:"
            else:
                action_desc = f"{actor} wants to create `{target_path or 'file'}`:"
        elif self.tool_name in ("edit", "multi_edit"):
            action_desc = f"{actor} wants to edit `{target_path or 'file'}` with diff:"
        elif self.tool_name == "read":
            action_desc = f"{actor} wants to read `{target_path or 'file'}`"
        elif self.tool_name == "web_fetch":
            url = nargs.get("url") or ""
            action_desc = f"{actor} wants to fetch `{url or 'URL'}`"
        elif self.tool_name == "invoke_subagent":
            role = nargs.get("type") or nargs.get("role") or "Subagent"
            title = nargs.get("title") or ""
            prompt = nargs.get("prompt") or ""
            target_desc = f"`{role}` (\"{title}\")" if title else f"`{role}`"
            if prompt:
                action_desc = f"{actor} wants to launch subagent {target_desc} with prompt:"
            else:
                action_desc = f"{actor} wants to launch subagent {target_desc}"
        elif self.tool_name in ("manage_shell",):
            act = (nargs.get("action") or "manage").lower()
            t_id = nargs.get("task_id") or ""

            if act == "kill":
                action_desc = (
                    f"{actor} wants to cancel task `{t_id}`" if t_id else f"{actor} wants to cancel background task"
                )
            elif act == "list":
                action_desc = f"{actor} wants to list background tasks"
            elif act == "send_input":
                target_str = f" to task `{t_id}`" if t_id else ""
                action_desc = f"{actor} wants to send input{target_str}:"
            else:
                action_desc = (
                    f"{actor} wants to `{act}` task `{t_id}`" if t_id else f"{actor} wants to manage background tasks"
                )
        elif self.tool_name in ("manage_subagent",):
            act = (nargs.get("action") or "manage").lower()
            s_id = nargs.get("session_id") or ""

            if act == "kill":
                action_desc = (
                    f"{actor} wants to cancel subagent `{s_id}`" if s_id else f"{actor} wants to cancel a subagent"
                )
            elif act == "list":
                action_desc = f"{actor} wants to list subagents"
            elif act == "send_message":
                target_str = f" to subagent `{s_id}`" if s_id else ""
                action_desc = f"{actor} wants to send a message{target_str}:"
            else:
                action_desc = (
                    f"{actor} wants to `{act}` subagent `{s_id}`" if s_id else f"{actor} wants to manage subagents"
                )
        elif self.tool_name == "update_plan":
            plan_val = nargs.get("plan")
            has_plan = bool(plan_val)
            action_desc = f"{actor} wants to update the plan:" if has_plan else f"{actor} wants to update the plan"
        elif self.tool_name == "ask_user":
            qs = nargs.get("questions") or []
            q_count = len(qs) if isinstance(qs, list) else 0
            if q_count > 1:
                action_desc = f"{actor} wants to ask {q_count} questions:"
            elif q_count == 1:
                q0 = qs[0]
                raw_q = q0.get("question") if isinstance(q0, dict) else q0
                q_text = str(raw_q or "").strip()
                if q_text and not (isinstance(q0, dict) and q0.get("options")):
                    action_desc = f"{actor} wants to ask: `{q_text}`"
                else:
                    action_desc = f"{actor} wants to ask a question:"
            else:
                action_desc = f"{actor} wants to ask a question"
        elif self.tool_name == "shell":
            action_desc = f"{actor} wants to run shell command:"
        else:
            if self.args:
                action_desc = f"{actor} wants to execute `{self.tool_name}` with parameters:"
            else:
                action_desc = f"{actor} wants to execute `{self.tool_name}`"

        is_wide = (
            self.tool_name in ("create", "edit", "multi_edit", "shell", "update_plan")
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
                plan_val = nargs.get("plan")
                explanation = (nargs.get("explanation") or "").strip()
                if plan_val:
                    formatted_plan = format_plan_display(plan_val, explanation)
                    with ToolScrollBox(classes="tool-scroll-box"):
                        yield Static(formatted_plan, classes="modal-diff-view")
            elif self.tool_name == "ask_user":
                qs = nargs.get("questions") or []
                if isinstance(qs, list) and qs:
                    lines = []
                    for i, q in enumerate(qs, 1):
                        prefix = f"{i}. " if len(qs) > 1 else ""
                        if isinstance(q, dict):
                            q_text = (q.get("question") or "").strip()
                            opts = q.get("options") or []
                            block = [f"**{prefix}{q_text}**" if q_text else ""]
                            for opt in opts:
                                block.append(f"- {opt}")
                            lines.append("\n".join(b for b in block if b))
                        elif len(qs) > 1:
                            lines.append(f"**{prefix}{str(q).strip()}**")
                    if lines:
                        with ToolScrollBox(classes="tool-scroll-box"):
                            for i, block_str in enumerate(lines):
                                cls = "modal-diff-view" if i == len(lines) - 1 else "modal-diff-view modal-qa-block"
                                yield Markdown(block_str, classes=cls)
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

            inp = RejectReasonInput(placeholder="Type reason for denial and press Enter...", id="reject-reason-input")
            inp.display = False
            inp.can_focus = False
            yield inp
            yield Label(self._build_hint_text(), id="modal-hint")

    def on_mount(self) -> None:
        self.focus()

    def _build_hint_text(self, width: Optional[int] = None) -> str:
        if not self.suggested_pattern:
            if width is not None and width < 48:
                return "enter: allow • r: reason • esc: deny"
            return "enter: allow • a: session • r: reason • esc/d: deny"

        pat = self.suggested_pattern
        if len(pat) > 18:
            pat = pat[:15] + "..."

        if width is not None and width < 62:
            return f"enter: allow • p: ({pat}) • r: reason • esc: deny"
        return f"enter: allow • p: pat ({pat}) • a: all • r: reason • esc/d: deny"

    def on_resize(self, event) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if not inp.display:
                hint_label = self.query_one("#modal-hint", Label)
                hint_label.update(self._build_hint_text(event.size.width))
        except Exception:
            pass

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

    def action_approve(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if inp.display and inp.has_focus:
                self.on_input_submitted(Input.Submitted(inp, inp.value))
                return
        except Exception:
            pass
        self.dismiss("allow")

    def action_allow_pattern(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if inp.display and inp.has_focus:
                return
        except Exception:
            pass
        if self.suggested_pattern:
            self.dismiss(f"pattern:{self.suggested_pattern}")
        else:
            self.dismiss("always_allow")

    def action_always_allow(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if inp.display and inp.has_focus:
                return
        except Exception:
            pass
        self.dismiss("always_allow")

    def action_reject_with_reason(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            inp.display = True
            inp.can_focus = True
            inp.value = ""
            inp.focus()
            hint = self.query_one("#modal-hint", Label)
            hint.update("enter: submit denial • esc: cancel reason")
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "reject-reason-input":
            reason = event.value.strip()
            if reason:
                self.dismiss(f"deny:{reason}")
            else:
                self.dismiss("deny")

    def action_deny(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if inp.display:
                inp.display = False
                inp.can_focus = False
                inp.value = ""
                self.focus()
                hint = self.query_one("#modal-hint", Label)
                hint.update(self._build_hint_text())
                return
        except Exception:
            pass
        self.dismiss("deny")

    def action_cancel(self) -> None:
        self.action_deny()


