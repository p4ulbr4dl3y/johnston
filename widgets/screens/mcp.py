from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Markdown, OptionList

from core.mcp_manager import MCPManager


class MCPScreen(ModalScreen[None]):
    """Модальное окно выключения/включения MCP серверов"""

    ALLOW_SELECT = False
    BINDINGS = [("escape", "cancel", "Close")]

    def __init__(self):
        super().__init__()
        self.mm = MCPManager()
        self.servers: list[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# MCP Servers", classes="modal-markdown")
            yield OptionList(id="mcp-option-list")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        self.servers = self.mm.load_servers()
        opt_list = self.query_one("#mcp-option-list", OptionList)
        opt_list.clear_options()

        if not self.servers:
            opt_list.add_option("*No MCP servers configured (~/.johnston/mcp.json or .johnston/mcp.json)*")
            return

        for s in self.servers:
            disabled = s.get("disabled", False)
            status_tag = r"\[OFF]" if disabled else r"\[ON]"
            scope_tag = rf"\[{s['scope'].upper()}]"
            cmd_info = s.get("url") or s.get("command") or ""
            if isinstance(cmd_info, list):
                cmd_info = " ".join(cmd_info)
            opt_list.add_option(f"{status_tag} {scope_tag} {s['name']} — {cmd_info}")

        opt_list.focus()

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.servers):
            target = self.servers[event.option_index]
            s_name = target["name"]
            is_enabled = self.mm.toggle_server(s_name)
            state_str = "enabled" if is_enabled else "disabled"
            self.app.notify(f"MCP server '{s_name}' {state_str}")
            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()
            self.refresh_list()
