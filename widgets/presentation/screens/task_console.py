import asyncio
import inspect
from typing import Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, RichLog

from core.infrastructure.platform.platform_utils import is_windows
from core.infrastructure.tasks.output import process_carriage_returns, strip_ansi
from widgets.chat_toolcall import ToolScrollBox
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import MODAL_DIALOG_ID, MODAL_HINT_ID
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.responsive import fit_modal_dialog


class TaskStdinInput(Input):
    """Input widget for task stdin that routes scroll keys to the screen's log."""

    async def _on_key(self, event: events.Key) -> None:
        key = (event.key or "").lower()
        if key in ("pageup", "page_up"):
            if self.screen and hasattr(self.screen, "action_scroll_page_up"):
                getattr(self.screen, "action_scroll_page_up")()
                event.stop()
                event.prevent_default()
                return
        elif key in ("pagedown", "page_down"):
            if self.screen and hasattr(self.screen, "action_scroll_page_down"):
                getattr(self.screen, "action_scroll_page_down")()
                event.stop()
                event.prevent_default()
                return
        elif key in ("shift+up", "ctrl+up"):
            if self.screen and hasattr(self.screen, "action_scroll_up"):
                getattr(self.screen, "action_scroll_up")()
                event.stop()
                event.prevent_default()
                return
        elif key in ("shift+down", "ctrl+down"):
            if self.screen and hasattr(self.screen, "action_scroll_down"):
                getattr(self.screen, "action_scroll_down")()
                event.stop()
                event.prevent_default()
                return
        await super()._on_key(event)


class TaskConsoleScreen(BaseModalScreen[None]):
    """Modal screen for viewing console output of a specific task in real-time, with stdin and kill."""

    BINDINGS = expand_bindings([
        ("escape", "back", "Back to list"),
        ("ctrl+k", "kill_task", "Kill Task"),
        ("pageup", "scroll_page_up", "Page Up"),
        ("pagedown", "scroll_page_down", "Page Down"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, bg_task):
        super().__init__()
        self.bg_task = bg_task
        self.log_widget: Optional[RichLog] = None
        self._pending_line = ""

    def compose(self) -> ComposeResult:
        cmd = getattr(self.bg_task, "command", "") or "(shell task)"
        is_running = getattr(self.bg_task, "is_running", False)
        lang = "powershell" if is_windows() else "bash"

        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide task-console-dialog"):
            yield ModalHeader("### **Shell Task**", esc_hint="")
            with ToolScrollBox(classes="tool-scroll-box"):
                yield Markdown(f"```{lang}\n{cmd.strip()}\n```", classes="modal-diff-view")
            yield RichLog(id="console-log", highlight=False, markup=False, auto_scroll=False)
            yield TaskStdinInput(
                placeholder="Send input to stdin (Enter)...", id="shell-stdin-input", classes="modal-input"
            )
            yield ModalHint(
                "enter Stdin • pgup/dn Scroll • ctrl+k Kill • esc Back"
                if is_running
                else "pgup/dn Scroll • esc Back",
                id=MODAL_HINT_ID,
            )

    def _apply_dynamic_log_height(self) -> None:
        if not self.log_widget:
            return
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
        except Exception:
            dialog = None

        screen_h = self.app.size.height if getattr(self, "app", None) else 24
        if not isinstance(screen_h, int) or screen_h <= 0:
            screen_h = 24

        is_running = getattr(self.bg_task, "is_running", False)

        cmd = getattr(self.bg_task, "command", "") or ""
        cmd_lines = max(1, len(cmd.strip().splitlines()))
        cmd_h = min(4, cmd_lines)

        try:
            cmd_box = self.query_one(".tool-scroll-box")
            cmd_box.styles.max_height = cmd_h
        except Exception:
            pass

        usable_h = fit_modal_dialog(dialog, screen_h)
        if screen_h < 18:
            overhead = 8 + cmd_h + (2 if is_running else 0)
        else:
            overhead = 11 + cmd_h + (2 if is_running else 0)

        target_h = max(2, min(14, usable_h - overhead))

        if is_running:
            self.log_widget.styles.height = target_h
        else:
            self.log_widget.styles.height = "auto"
        self.log_widget.styles.max_height = target_h

    def _update_hint(self) -> None:
        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            hint = self.query_one(f"#{MODAL_HINT_ID}", Label)
            is_running = getattr(self.bg_task, "is_running", False)
            if is_running:
                hint_str = (
                    "enter Stdin • ctrl+k Kill • esc"
                    if is_compact
                    else "enter Stdin • pgup/dn Scroll • ctrl+k Kill • esc Back"
                )
            else:
                hint_str = "pgup/dn • esc" if is_compact else "pgup/dn Scroll • esc Back"
            hint.update(hint_str)
        except Exception:
            pass

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#console-log", RichLog)
        self._apply_dynamic_log_height()
        self.log_widget.auto_scroll = False

        self._update_state()

        has_history = False
        for chunk in getattr(getattr(self.bg_task, "output", None), "history", []):
            if chunk.strip():
                has_history = True
            self._consume(strip_ansi(chunk))
        if not has_history:
            if getattr(self.bg_task, "is_running", False):
                self.log_widget.write("(Waiting for command output...)")
            else:
                self.log_widget.write("(No output produced)")
        self.log_widget.scroll_end(animate=False)
        if hasattr(self.bg_task, "add_listener"):
            self.bg_task.add_listener(self._on_output)

    def _update_state(self) -> None:
        self._apply_dynamic_log_height()
        is_running = getattr(self.bg_task, "is_running", False)
        try:
            stdin_inp = self.query_one("#shell-stdin-input", Input)
            if is_running:
                stdin_inp.display = True
                stdin_inp.focus()
            else:
                stdin_inp.display = False
                if self.log_widget:
                    self.log_widget.focus()
        except Exception:
            pass
        self._update_hint()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dynamic_log_height()
        self._update_hint()

    def on_unmount(self) -> None:
        if self.bg_task is not None and hasattr(self.bg_task, "remove_listener"):
            self.bg_task.remove_listener(self._on_output)

    def _is_at_bottom(self, threshold: int = 2) -> bool:
        if not self.log_widget:
            return True
        return (self.log_widget.max_scroll_y - self.log_widget.scroll_y) <= threshold

    def _on_output(self, text: str) -> None:
        """Live chunk from the task; the final empty signal flushes the tail."""
        if hasattr(self, "app") and self.app and self.is_mounted:
            try:
                self.app.call_from_thread(self._handle_live_chunk, text)
            except Exception:
                try:
                    self._handle_live_chunk(text)
                except Exception:
                    pass
        else:
            self._handle_live_chunk(text)

    def _handle_live_chunk(self, text: str) -> None:
        if text:
            self._consume(text)
        else:
            self._flush_pending()
            self._update_state()

    def _consume(self, text: str) -> None:
        if not self.log_widget:
            return
        combined = self._pending_line + text
        parts = combined.split("\n")
        self._pending_line = parts.pop()
        at_bottom = self._is_at_bottom()
        for line in parts:
            self.log_widget.write(process_carriage_returns(line), scroll_end=at_bottom)

    def _flush_pending(self) -> None:
        if self._pending_line and self.log_widget:
            at_bottom = self._is_at_bottom()
            self.log_widget.write(process_carriage_returns(self._pending_line), scroll_end=at_bottom)
            self._pending_line = ""

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "shell-stdin-input":
            val = event.value
            event.input.value = ""
            if self.bg_task and getattr(self.bg_task, "is_running", False):
                if hasattr(self.bg_task, "send_input"):
                    asyncio.create_task(self.bg_task.send_input(val))

    def action_scroll_page_up(self) -> None:
        if self.log_widget:
            self.log_widget.scroll_page_up(animate=False)

    def action_scroll_page_down(self) -> None:
        if self.log_widget:
            self.log_widget.scroll_page_down(animate=False)

    def action_scroll_up(self) -> None:
        if self.log_widget:
            self.log_widget.scroll_up(animate=False)

    def action_scroll_down(self) -> None:
        if self.log_widget:
            self.log_widget.scroll_down(animate=False)

    async def action_kill_task(self) -> None:
        if self.bg_task and getattr(self.bg_task, "is_running", False):
            res = self.bg_task.kill()
            if inspect.isawaitable(res):
                await res
            self._update_state()

    def action_back(self) -> None:
        self.dismiss()
