import json
import os
from typing import Any, Dict, Optional

from rich.markup import escape
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList, Static

from core.domain.policies.permission_policy import suggest_pattern
from widgets.chat_toolcall import ToolScrollBox
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.tool_renderers import build_synthetic_create_diff
from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.responsive import (
    BREAKPOINT_HINT,
    MODAL_CONTENT_GUTTER,
    MODAL_MIN_WIDTH,
    MODAL_WIDE_MAX_WIDTH,
    apply_modal_fit,
    is_compact_width,
    modal_content_width,
    resolve_width,
)
from widgets.utils.row_format import display_width, ellipsize


class RejectReasonInput(Input):
    """Input widget that forwards vertical navigation keys to OptionList."""

    def _clear_selection(self) -> None:
        try:
            self.selection = self.selection.cursor(self.cursor_position)
        except Exception:
            pass

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        self._clear_selection()
        self.call_after_refresh(self._clear_selection)

    async def _on_key(self, event: events.Key) -> None:
        key = (event.key or "").lower()

        if key in ("up", "key_up"):
            if self.screen and hasattr(self.screen, "focus_options_list"):
                getattr(self.screen, "focus_options_list")()
                event.stop()
                event.prevent_default()
                return

        elif key in ("down", "key_down"):
            if self.screen and hasattr(self.screen, "focus_first_option"):
                getattr(self.screen, "focus_first_option")()
                event.stop()
                event.prevent_default()
                return

        await super()._on_key(event)


class PermissionOptionList(HeaderWrapOptionList):
    """OptionList that routes PageUp/PageDown to the inner tool code scroll box."""

    def action_page_up(self) -> None:
        if self.screen and hasattr(self.screen, "_get_scroll_target"):
            target = getattr(self.screen, "_get_scroll_target")()
            if target is not None:
                target.scroll_page_up(animate=False)
                return
        super().action_page_up()

    def action_page_down(self) -> None:
        if self.screen and hasattr(self.screen, "_get_scroll_target"):
            target = getattr(self.screen, "_get_scroll_target")()
            if target is not None:
                target.scroll_page_down(animate=False)
                return
        super().action_page_down()


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
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(
        self,
        tool_name: str,
        args: Optional[Dict[str, Any]] = None,
        diff: str = "",
        is_subagent: bool = False,
    ):
        super().__init__()
        self.tool_name = tool_name
        self.args = args or {}
        self.diff = diff
        self.is_subagent = is_subagent
        self.suggested_pattern = suggest_pattern(self.tool_name, self.args)

    def _build_diff_text(self, target_path: str) -> str:

        if self.diff:
            return self.diff

        # Generate diff for Create/Write tools updating existing file
        if self.tool_name == "create":
            content = self.args.get("content") or ""
            return build_synthetic_create_diff(target_path, content)

        # Generate diff for Edit tools
        if self.tool_name == "edit":
            from widgets.lexer_utils import build_edit_diff_text

            return build_edit_diff_text(self.args, target_path or "file")

        return ""

    def compose(self) -> ComposeResult:
        nargs = self.args if isinstance(self.args, dict) else {}
        target_path = nargs.get("path") or ""
        actor = "Subagent" if self.is_subagent else "Agent"

        if self.tool_name == "create":
            file_exists = bool(target_path and os.path.isfile(target_path))
            if file_exists or self.diff:
                action_desc = f"{actor} wants to overwrite `{target_path or 'file'}` with diff:"
            else:
                action_desc = f"{actor} wants to create `{target_path or 'file'}`:"
        elif self.tool_name == "edit":
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
            explanation = (nargs.get("explanation") or "").strip()
            if explanation:
                action_desc = f'{actor} wants to update the plan: "{explanation}"'
            else:
                action_desc = f"{actor} wants to update the plan"
        elif self.tool_name == "ask_user":
            qs = nargs.get("questions") or []
            if isinstance(qs, list) and qs:
                q_texts = []
                for q in qs:
                    raw_q = q.get("question") if isinstance(q, dict) else q
                    txt = str(raw_q or "").strip()
                    if txt:
                        q_texts.append(txt)
                if q_texts:
                    joined_qs = ", ".join(f"`{q}`" for q in q_texts)
                    action_desc = f"{actor} wants to ask: {joined_qs}"
                else:
                    action_desc = f"{actor} wants to ask a question"
            else:
                action_desc = f"{actor} wants to ask a question"
        elif self.tool_name == "shell":
            action_desc = f"{actor} wants to run shell command:"
        else:
            if self.args:
                action_desc = f"{actor} wants to execute `{self.tool_name}` with parameters:"
            else:
                action_desc = f"{actor} wants to execute `{self.tool_name}`"

        self._action_desc = action_desc
        with Vertical(id="modal-dialog", classes="bash-confirm-dialog"):
            yield ModalHeader("Confirm Tool Action", esc_hint="")
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
                self.tool_name == "edit"
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

            options = ["Allow once"]
            self._option_keys = ["allow"]

            if self.suggested_pattern:
                pat_clean = " ".join(self.suggested_pattern.split())
                pat_escaped = escape(ellipsize(pat_clean, 56))
                options.append(f"Allow pattern [dim]({pat_escaped})[/dim]")
                self._option_keys.append(f"pattern:{self.suggested_pattern}")

            options.append("Always allow for session")
            self._option_keys.append("always_allow")

            options.append("Deny")
            self._option_keys.append("deny")

            options.append("Reject with feedback...")
            self._option_keys.append("reject_reason")

            yield PermissionOptionList(*options, id="permission-options-list")

            inp = RejectReasonInput(placeholder="Type feedback for agent and press Enter...", id="reject-reason-input")
            inp.display = False
            inp.can_focus = False
            yield inp
            yield ModalHint(self._build_hint_text(), id="modal-hint")

    def _calculate_content_width(self) -> int:
        options = [
            "Allow once",
            "Always allow for session",
            "Deny",
            "Reject with feedback...",
        ]
        if self.suggested_pattern:
            pat_clean = " ".join(self.suggested_pattern.split())
            options.append(f"Allow pattern ({ellipsize(pat_clean, 56)})")

        hint = self._build_hint_text()
        title = "Confirm Tool Action"
        base_width = modal_content_width(
            options=options, title=title, hint=hint, extra=MODAL_CONTENT_GUTTER
        )

        # Cap natural language descriptions so they wrap gracefully rather than ballooning modal width
        TEXT_DESC_CAP = 64
        max_line = 0
        if getattr(self, "_action_desc", None):
            max_line = max(max_line, min(display_width(self._action_desc), TEXT_DESC_CAP))

        nargs = self.args if isinstance(self.args, dict) else {}
        target_path = nargs.get("path") or ""

        is_code_or_diff = False
        content_lines: list[str] = []
        if self.tool_name == "create":
            is_code_or_diff = True
            file_exists = bool(target_path and os.path.isfile(target_path))
            if file_exists or self.diff:
                diff_text = self._build_diff_text(target_path)
                content_lines = diff_text.splitlines()
            else:
                code_content = nargs.get("content") or ""
                content_lines = code_content.splitlines()
        elif self.tool_name == "edit" or self.diff:
            is_code_or_diff = True
            diff_text = self._build_diff_text(target_path)
            content_lines = diff_text.splitlines()
        elif self.tool_name == "shell":
            is_code_or_diff = True
            cmd = nargs.get("command") or ""
            content_lines = cmd.splitlines()
        elif self.tool_name == "manage_shell" and (nargs.get("action") or "").lower() == "send_input":
            is_code_or_diff = True
            inp = nargs.get("input") or ""
            content_lines = inp.splitlines()
        elif self.tool_name == "manage_subagent" and (nargs.get("action") or "").lower() == "send_message":
            is_code_or_diff = False
            msg = nargs.get("message") or ""
            content_lines = msg.splitlines()
        elif self.tool_name == "invoke_subagent":
            is_code_or_diff = False
            prompt = nargs.get("prompt") or ""
            content_lines = prompt.splitlines()
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
            is_code_or_diff = True
            try:
                args_str = json.dumps(self.args, indent=2, ensure_ascii=False)
                content_lines = args_str.splitlines()
            except Exception:
                pass

        line_cap = 104 if is_code_or_diff else TEXT_DESC_CAP
        for line in content_lines[:200]:
            line_w = min(display_width(line.rstrip()) + 4, line_cap)
            max_line = max(max_line, line_w)

        return max(base_width, max_line + MODAL_CONTENT_GUTTER)

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one("#modal-dialog")
            content_w = self._calculate_content_width()
            apply_modal_fit(dialog, content_w, min_width=MODAL_MIN_WIDTH, max_width=MODAL_WIDE_MAX_WIDTH)
            screen_h = self.app.size.height if getattr(self, "app", None) else 24
            if not isinstance(screen_h, int) or screen_h <= 0:
                screen_h = 24
            num_opts = len(self._option_keys) if hasattr(self, "_option_keys") else 4

            input_overhead = 0
            try:
                inp = self.query_one("#reject-reason-input", Input)
                if inp.display:
                    input_overhead = 2
            except Exception:
                pass

            if screen_h < 18:
                dialog.styles.padding = (0, 1)
                dialog.styles.max_height = max(7, screen_h - 1)
                opt_h = min(num_opts, max(2, screen_h - 10 - input_overhead))
                overhead = 8 + opt_h + input_overhead
                opt_list_h = opt_h
                usable_h = screen_h - 1
            else:
                dialog.styles.padding = (1, 2)
                dialog.styles.max_height = max(8, min(screen_h - 2, int(screen_h * 0.92)))
                overhead = 12 + num_opts + input_overhead
                opt_list_h = None
                usable_h = screen_h - 2

            scroll_box_h = max(1, min(18, usable_h - overhead))

            try:
                scroll_box = self.query_one(".tool-scroll-box")
                scroll_box.styles.max_height = scroll_box_h
            except Exception:
                pass

            try:
                opt_list = self.query_one("#permission-options-list", OptionList)
                opt_list.styles.max_height = opt_list_h
            except Exception:
                pass
        except Exception:
            pass

    def on_mount(self) -> None:
        try:
            self.query_one("#permission-options-list", OptionList).focus()
        except Exception:
            self.focus()
        try:
            self.query_one("#modal-hint", Label).update(self._build_hint_text(resolve_width(self)))
        except Exception:
            pass
        self._apply_dialog_fit()

    def _build_hint_text(self, width: Optional[int] = None) -> str:
        if isinstance(width, int) and is_compact_width(width, breakpoint=BREAKPOINT_HINT):
            return "enter • r • esc"
        return "enter: select • r: feedback • esc: deny"

    def on_resize(self, event) -> None:
        self._apply_dialog_fit()
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if inp.display:
                self.focus_reject_input()
        except Exception:
            pass
        try:
            self.query_one("#modal-hint", Label).update(self._build_hint_text(resolve_width(self)))
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if not self.is_mounted:
            return
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if hasattr(self, "_option_keys") and event.option_index == len(self._option_keys) - 1:
                self.focus_reject_input()
            else:
                if inp.display:
                    inp.display = False
                    inp.can_focus = False
                    self._apply_dialog_fit()
                self.query_one("#modal-hint", Label).update(self._build_hint_text(resolve_width(self)))
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        keys = getattr(self, "_option_keys", [])
        if 0 <= idx < len(keys):
            key = keys[idx]
            if key == "allow":
                self.dismiss("allow")
            elif key.startswith("pattern:"):
                self.dismiss(key)
            elif key == "always_allow":
                self.dismiss("always_allow")
            elif key == "deny":
                self.dismiss("deny")
            elif key == "reject_reason":
                self.focus_reject_input()

    def focus_reject_input(self) -> None:
        try:
            opt_list = self.query_one("#permission-options-list", OptionList)
            if hasattr(self, "_option_keys") and "reject_reason" in self._option_keys:
                opt_list.highlighted = self._option_keys.index("reject_reason")
            inp = self.query_one("#reject-reason-input", Input)
            inp.display = True
            inp.can_focus = True
            inp.focus()
            self._apply_dialog_fit()
            hint = self.query_one("#modal-hint", Label)
            hint.update("enter: send feedback • ↑: options • esc: deny")
        except Exception:
            pass

    def focus_options_list(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            inp.display = False
            inp.can_focus = False
            opt_list = self.query_one("#permission-options-list", OptionList)
            if hasattr(self, "_option_keys"):
                opt_list.highlighted = max(0, len(self._option_keys) - 2)
            opt_list.focus()
            self._apply_dialog_fit()
            hint = self.query_one("#modal-hint", Label)
            hint.update(self._build_hint_text(resolve_width(self)))
        except Exception:
            self.focus()

    def focus_first_option(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            inp.display = False
            inp.can_focus = False
            opt_list = self.query_one("#permission-options-list", OptionList)
            opt_list.highlighted = 0
            opt_list.focus()
            self._apply_dialog_fit()
        except Exception:
            self.focus()

    def _get_scroll_target(self):
        try:
            return self.query_one(".tool-scroll-box")
        except Exception:
            return None

    def action_page_up(self) -> None:
        try:
            target = self._get_scroll_target()
            if target is not None:
                target.scroll_page_up(animate=False)
        except Exception:
            pass

    def action_page_down(self) -> None:
        try:
            target = self._get_scroll_target()
            if target is not None:
                target.scroll_page_down(animate=False)
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
        self.focus_reject_input()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "reject-reason-input":
            reason = event.value.strip()
            if reason:
                self.dismiss(f"deny:{reason}")
            else:
                self.dismiss("deny")

    def action_deny(self) -> None:
        self.dismiss("deny")

    def action_cancel(self) -> None:
        self.dismiss("deny")


