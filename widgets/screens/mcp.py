import asyncio
from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.mcp_manager import get_mcp_manager


class MCPScreen(ModalScreen[None]):
    """Modal screen for enabling/disabling and toggling Eager/Lazy modes of MCP servers"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("m", "toggle_mode", "Toggle Eager/Lazy"),
        ("tab", "toggle_mode", "Toggle Eager/Lazy"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.mm = get_mcp_manager()
        self.servers: list[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Manage MCP Servers**", classes="modal-markdown")
            yield OptionList(id="mcp-option-list")
            yield Label("enter: toggle • m/tab: mode • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        opt_list = self.query_one("#mcp-option-list", OptionList)
        if self.servers:
            opt_list.highlighted = 0

        # Non-blocking background warmup for unstarted MCP servers
        asyncio.create_task(self._warmup_tools())

    async def _warmup_tools(self) -> None:
        try:
            await asyncio.to_thread(self.mm.get_active_tools, "all")
            if getattr(self, "is_mounted", True):
                self.refresh_list()
        except Exception:
            pass

    def refresh_list(self) -> None:
        self.servers = self.mm.load_servers()
        opt_list = self.query_one("#mcp-option-list", OptionList)
        prev_highlighted = opt_list.highlighted
        opt_list.clear_options()

        if not self.servers:
            opt_list.add_option("*No MCP servers configured (~/.johnston/mcp.json or .johnston/mcp.json)*")
            return

        tools_per_server: Dict[str, int] = {}
        try:
            if hasattr(self.mm, "clients"):
                for s_name, client in self.mm.clients.items():
                    if client and hasattr(client, "tools") and client.tools:
                        tools_per_server[s_name] = len(client.tools)
        except Exception:
            pass

        for s in self.servers:
            disabled = s.get("disabled", False)
            scope_tag = rf"\[{s['scope'].upper()}]"
            mode_tag = rf"\[{s.get('mode', 'eager').upper()}]"
            name = s["name"]

            if disabled:
                status_tag = r"\[OFF]"
                opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name}")
                continue

            tool_cnt = tools_per_server.get(name, 0)
            url = s.get("url")
            cmd = s.get("command")

            if tool_cnt > 0:
                status_tag = r"\[ON]"
                tool_info = f"{tool_cnt} tool" if tool_cnt == 1 else f"{tool_cnt} tools"
                opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name} — {tool_info}")
            elif url and not cmd:
                status_tag = r"\[ERR]"
                opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name} — URL unsupported")
            else:
                client = self.mm.clients.get(name) if hasattr(self.mm, "clients") else None
                err = getattr(client, "last_error", None) if client else None
                if err and "Process start failed" in err:
                    status_tag = r"\[ERR]"
                    opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name} — Start failed")
                elif err and "timeout" in err.lower():
                    status_tag = r"\[ERR]"
                    opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name} — Timeout")
                elif err:
                    status_tag = r"\[ERR]"
                    opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name} — Error")
                else:
                    status_tag = r"\[ERR]" if (not cmd and not url) else r"\[ON]"
                    opt_list.add_option(f"{status_tag} {scope_tag} {mode_tag} {name}")

        opt_list.focus()
        if prev_highlighted is not None and 0 <= prev_highlighted < len(self.servers):
            opt_list.highlighted = prev_highlighted
        elif self.servers and opt_list.highlighted is None:
            opt_list.highlighted = 0

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def action_toggle_mode(self) -> None:
        opt_list = self.query_one("#mcp-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.servers):
            target = self.servers[highlighted]
            s_name = target["name"]
            self.mm.toggle_mode(s_name)
            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()
            self.refresh_list()
            opt_list.highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.servers):
            target = self.servers[event.option_index]
            s_name = target["name"]
            self.mm.toggle_server(s_name)
            self.refresh_list()
            opt_list = self.query_one("#mcp-option-list", OptionList)
            opt_list.highlighted = event.option_index

            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()

