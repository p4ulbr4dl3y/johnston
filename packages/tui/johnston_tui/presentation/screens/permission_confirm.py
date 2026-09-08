import json
import os
from typing import Any, Dict, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList, Static

from johnston_core.domain.policies.permission_policy import suggest_pattern
from johnston_tui.chat_toolcall import ToolScrollBox
from johnston_tui.presentation.screens.base_modal import BaseModalScreen
from johnston_tui.presentation.screens.base_selection import HeaderWrapOptionList
from johnston_tui.presentation.tool_renderers import build_synthetic_create_diff
from johnston_tui.presentation.widgets.chat_diff import format_edit_diff
from johnston_tui.presentation.widgets.modal_header import ModalHeader
from johnston_tui.presentation.widgets.modal_hint import ModalHint
from johnston_tui.utils.key_aliases import expand_bindings
from johnston_tui.utils.responsive import (
    BREAKPOINT_HINT,
    MODAL_CONTENT_GUTTER,
    MODAL_MIN_WIDTH,
    MODAL_WIDE_MAX_WIDTH,
    apply_modal_fit,
    fit_modal_dialog,
    is_compact_width,
    modal_content_width,
    resolve_width,
)
from johnston_tui.utils.row_format import display_width, ellipsize


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
        ("enter", "approve", "Select"),
        ("1", "select_1", "Option 1"),
        ("2", "select_2", "Option 2"),
        ("3", "select_3", "Option 3"),
        ("4", "select_4", "Option 4"),
        ("5", "select_5", "Option 5"),
        ("6", "select_6", "Option 6"),
        ("7", "select_7", "Option 7"),
        ("8", "select_8", "Option 8"),
        ("9", "select_9", "Option 9"),
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
        subagent_role: str = "",
        server_name: Optional[str] = None,
    ):
        super().__init__()
        self.tool_name = tool_name
        self.args = args or {}
        self.diff = diff
        self.is_subagent = is_subagent
        self.subagent_role = (subagent_role or "").strip()
        if server_name and isinstance(server_name, str) and server_name.strip():
            self.server_name = server_name.strip()
        elif "__" in self.tool_name:
            self.server_name = self.tool_name.split("__", 1)[0].strip()
        else:
            self.server_name = ""
        self.suggested_pattern = suggest_pattern(self.tool_name, self.args)
        self._options, self._option_keys = self._build_options()

    def _build_options(self) -> tuple[list[str], list[str]]:
        raw_options: list[tuple[str, str]] = []
        raw_options.append(("Allow once", "allow"))

        is_mcp = bool(self.server_name or "__" in self.tool_name)
        server_name = self.server_name or (self.tool_name.split("__", 1)[0] if is_mcp else "")

        if self.suggested_pattern:
            pat_clean = " ".join(self.suggested_pattern.split())
            raw_options.append((f'Allow pattern "{pat_clean}" [dim](session)[/]', f"pattern:{self.suggested_pattern}"))

        raw_options.append((f'Always allow "{self.tool_name}" [dim](session)[/]', "always_allow"))

        if is_mcp and server_name:
            raw_options.append((f'Always allow ALL tools from "{server_name}" [dim](session)[/]', f"server_allow:{server_name}__*"))

        if self.suggested_pattern:
            pat_clean = " ".join(self.suggested_pattern.split())
            raw_options.append((f'Allow pattern "{pat_clean}" [dim](project)[/]', f"pattern:{self.suggested_pattern}:project"))

        raw_options.append((f'Always allow "{self.tool_name}" [dim](project)[/]', "always_allow:project"))

        if is_mcp and server_name:
            raw_options.append((f'Always allow ALL tools from "{server_name}" [dim](project)[/]', f"server_allow:{server_name}__*:project"))

        nargs = self.args if isinstance(self.args, dict) else {}
        from johnston_core.domain.policies.permission_policy import extract_tool_target_value, is_path_within_workspace
        from johnston_core.permission_manager import PermissionManager

        pm = PermissionManager.get_instance()
        target_path = (
            (nargs.get("cwd") if self.tool_name == "shell" else "")
            or extract_tool_target_value(self.tool_name, self.args)
            or nargs.get("path")
            or ""
        )
        if target_path and isinstance(target_path, str) and not is_path_within_workspace(target_path, pm.get_workspace_roots()):
            if os.path.isdir(target_path) or (self.tool_name == "shell" and nargs.get("cwd") == target_path):
                root_to_add = target_path
            else:
                root_to_add = os.path.dirname(target_path) or target_path
            norm_root = os.path.realpath(os.path.abspath(os.path.expanduser(root_to_add)))
            # Never offer the filesystem root (e.g. "/" for a nonexistent
            # top-level file — it would unboundedly widen the workspace), and
            # never offer a path already inside the workspace.
            if (
                norm_root
                and norm_root != os.path.abspath(os.sep)
                and not is_path_within_workspace(norm_root, pm.get_workspace_roots())
            ):
                raw_options.append(
                    (f'Add "{ellipsize(root_to_add, 36)}" to roots [dim](workspace)[/]', f"add_root:{root_to_add}")
                )

        raw_options.append(("Deny", "deny"))
        raw_options.append(("Reject with feedback...", "reject_reason"))

        options: list[str] = []
        keys: list[str] = []
        for i, (label, key) in enumerate(raw_options):
            options.append(f"[bold]{i + 1}.[/bold] {label}")
            keys.append(key)
        return options, keys

    def _build_diff_text(self, target_path: str) -> str:

        if self.diff:
            return self.diff

        # Generate diff for Create/Write tools updating existing file
        if self.tool_name == "create":
            content = self.args.get("content") or ""
            return build_synthetic_create_diff(target_path, content)

        # Generate diff for Edit tools
        if self.tool_name == "edit":
            from johnston_tui.lexer_utils import build_edit_diff_text

            return build_edit_diff_text(self.args, target_path or "file")

        return ""

    def compose(self) -> ComposeResult:
        nargs = self.args if isinstance(self.args, dict) else {}
        target_path = nargs.get("path") or ""
        if self.is_subagent:
            actor = f"Subagent ({self.subagent_role})" if self.subagent_role else "Subagent"
        else:
            actor = "Agent"

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
        elif self.tool_name == "kill":
            target_id = nargs.get("id") or nargs.get("task_id") or nargs.get("session_id") or ""
            if target_id:
                action_desc = f"{actor} wants to terminate `{target_id}`"
            else:
                action_desc = f"{actor} wants to terminate task or subagent"
        elif self.tool_name == "message_subagent":
            s_id = nargs.get("id") or nargs.get("session_id") or ""
            target_str = f" `{s_id}`" if s_id else " subagent"
            message = (nargs.get("message") or "").strip()
            colon = ":" if message else ""
            action_desc = f"{actor} wants to message{target_str}{colon}"
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
        elif self.server_name or "__" in self.tool_name:
            server_name = self.server_name or self.tool_name.split("__", 1)[0]
            tool_subname = self.tool_name.split("__", 1)[1] if "__" in self.tool_name else self.tool_name
            if self.args:
                action_desc = f"{actor} wants to call `{tool_subname}` from MCP server `{server_name}` with parameters:"
            else:
                action_desc = f"{actor} wants to call `{tool_subname}` from MCP server `{server_name}`"
        else:
            if self.args:
                action_desc = f"{actor} wants to execute `{self.tool_name}` with parameters:"
            else:
                action_desc = f"{actor} wants to execute `{self.tool_name}`"

        self._action_desc = action_desc
        header_title = (
            f"Confirm MCP Action: {self.server_name or self.tool_name.split('__', 1)[0]}"
            if (self.server_name or "__" in self.tool_name)
            else "Confirm Tool Action"
        )
        with Vertical(id="modal-dialog", classes="bash-confirm-dialog"):
            yield ModalHeader(header_title, esc_hint="")
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
                from johnston_core.infrastructure.platform.platform_utils import is_windows

                lang = "powershell" if is_windows() else "bash"
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```{lang}\n{cmd.strip()}\n```", classes="modal-diff-view")
            elif self.tool_name == "message_subagent":
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
                "kill",
                "message_subagent",
                "invoke_subagent",
                "update_plan",
                "ask_user",
            ):
                args_str = json.dumps(self.args, indent=2, ensure_ascii=False)
                with ToolScrollBox(classes="tool-scroll-box"):
                    yield Markdown(f"```json\n{args_str}\n```", classes="modal-diff-view")

            yield PermissionOptionList(*self._options, id="permission-options-list")

            inp = RejectReasonInput(
                placeholder="Type feedback for agent and press Enter...",
                id="reject-reason-input",
                classes="modal-input",
            )
            inp.display = False
            inp.can_focus = False
            yield inp
            yield ModalHint(self._build_hint_text(), id="modal-hint")

    def _calculate_content_width(self) -> int:
        options = getattr(self, "_options", None)
        if not options:
            self._options, self._option_keys = self._build_options()
            options = self._options

        hint = self._build_hint_text()
        title = (
            f"Confirm MCP Action: {self.server_name or self.tool_name.split('__', 1)[0]}"
            if (getattr(self, "server_name", None) or "__" in self.tool_name)
            else "Confirm Tool Action"
        )
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
        elif self.tool_name == "message_subagent":
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
            "kill",
            "message_subagent",
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

            usable_h = fit_modal_dialog(dialog, screen_h, height_factor=0.92)
            if screen_h < 18:
                opt_h = min(num_opts, max(2, screen_h - 10 - input_overhead))
                overhead = 8 + opt_h + input_overhead
                opt_list_h = opt_h
            else:
                overhead = 12 + num_opts + input_overhead
                opt_list_h = None

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
        num = len(getattr(self, "_options", []))
        num_part = f" • 1-{num}" if num > 1 else (" • 1" if num == 1 else "")
        if isinstance(width, int) and is_compact_width(width, breakpoint=BREAKPOINT_HINT):
            return f"enter{num_part} • r • esc"
        return f"enter Select{num_part} • r Feedback • esc Deny"

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

    def _select_option_by_index(self, idx: int) -> None:
        keys = getattr(self, "_option_keys", [])
        if 0 <= idx < len(keys):
            key = keys[idx]
            if key == "allow":
                self.dismiss("allow")
            elif key.startswith("pattern:"):
                self.dismiss(key)
            elif key == "always_allow":
                self.dismiss("always_allow")
            elif key.startswith("always_allow:"):
                self.dismiss(key)
            elif key.startswith("server_allow:"):
                self.dismiss(key)
            elif key.startswith("add_root:"):
                self.dismiss(key)
            elif key == "deny":
                self.dismiss("deny")
            elif key == "reject_reason":
                self.focus_reject_input()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._select_option_by_index(event.option_index)

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

    def _is_input_active(self) -> bool:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            return bool(inp.display and inp.has_focus)
        except Exception:
            return False

    def action_approve(self) -> None:
        if self._is_input_active():
            try:
                inp = self.query_one("#reject-reason-input", Input)
                self.on_input_submitted(Input.Submitted(inp, inp.value))
                return
            except Exception:
                pass
        try:
            opt_list = self.query_one("#permission-options-list", OptionList)
            if opt_list.highlighted is not None:
                self._select_option_by_index(opt_list.highlighted)
                return
        except Exception:
            pass
        self.dismiss("allow")

    def action_select_1(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(0)

    def action_select_2(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(1)

    def action_select_3(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(2)

    def action_select_4(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(3)

    def action_select_5(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(4)

    def action_select_6(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(5)

    def action_select_7(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(6)

    def action_select_8(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(7)

    def action_select_9(self) -> None:
        if not self._is_input_active():
            self._select_option_by_index(8)

    def action_allow_pattern(self) -> None:
        try:
            inp = self.query_one("#reject-reason-input", Input)
            if inp.display and inp.has_focus:
                return
        except Exception:
            pass
        # No suggested pattern: pressing 'p' must NOT silently escalate to a
        # broader 'always allow'; the binding simply does nothing.
        if self.suggested_pattern:
            self.dismiss(f"pattern:{self.suggested_pattern}")

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


