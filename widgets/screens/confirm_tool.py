import json
import time
from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown


class ConfirmToolScreen(ModalScreen[str]):
    """Modal screen asking user for permission before executing a tool."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("enter", "approve", "Approve Once"),
        ("a", "always_allow", "Always Allow (Session)"),
        ("escape", "deny", "Deny"),
        ("d", "deny", "Deny"),
        ("ctrl+c", "quit", "Exit"),
    ]

    def __init__(self, tool_name: str, args: Optional[Dict[str, Any]] = None, reason: str = ""):
        super().__init__()
        self.tool_name = tool_name
        self.args = args or {}
        self.reason = reason

    def compose(self) -> ComposeResult:
        args_str = json.dumps(self.args, indent=2, ensure_ascii=False) if self.args else "{}"
        content = (
            f"### **Tool Permission Request**\n\n"
            f"Tool **`{self.tool_name}`** requires confirmation.\n\n"
            f"**Reason:** {self.reason}\n\n"
            f"```json\n{args_str}\n```"
        )
        with Vertical(id="modal-dialog"):
            yield Markdown(content, classes="modal-markdown")
            yield Label("enter: Approve • a: Always Allow Session • esc/d: Deny", id="modal-hint")

    def on_mount(self) -> None:
        self._mount_time = time.time()

    def action_approve(self) -> None:
        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        self.dismiss("allow")

    def action_always_allow(self) -> None:
        if hasattr(self, "_mount_time") and (time.time() - self._mount_time < 0.25):
            return
        self.dismiss("always_allow")

    def action_deny(self) -> None:
        self.dismiss("deny")

    def action_quit(self) -> None:
        self.app.exit()
