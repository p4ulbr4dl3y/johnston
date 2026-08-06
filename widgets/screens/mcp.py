import asyncio
from typing import Any, Dict

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList

from core.mcp_manager import get_mcp_manager


class MCPScreen(ModalScreen[None]):
    """Modal screen for enabling/disabling and toggling Eager/Lazy modes of MCP servers"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
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
        self.filtered_servers: list[Dict[str, Any]] = []
        self.search_query = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Manage MCP Servers**", classes="modal-markdown")
            yield Input(placeholder="Search MCP servers...", id="modal-search-input")
            yield OptionList(id="mcp-option-list")
            yield Label("enter: toggle • tab: mode • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        opt_list = self.query_one("#mcp-option-list", OptionList)
        if self.filtered_servers:
            opt_list.highlighted = 0
        try:
            self.query_one("#modal-search-input", Input).focus()
        except Exception:
            pass

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
            self.filtered_servers = []
            return

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_servers = list(self.servers)
        else:
            self.filtered_servers = [
                s for s in self.servers
                if q in s.get("name", "").lower()
                or q in s.get("scope", "").lower()
                or q in s.get("command", "").lower()
                or q in s.get("url", "").lower()
            ]

        if not self.filtered_servers:
            opt_list.add_option("*No matching MCP servers found*")
            return

        tools_per_server: Dict[str, int] = {}
        try:
            if hasattr(self.mm, "clients"):
                for s_name, client in self.mm.clients.items():
                    if client and hasattr(client, "tools") and client.tools:
                        tools_per_server[s_name] = len(client.tools)
        except Exception:
            pass

        for s in self.filtered_servers:
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

        if prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_servers):
            opt_list.highlighted = prev_highlighted
        elif self.filtered_servers and opt_list.highlighted is None:
            opt_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "modal-search-input":
            self.search_query = event.value
            self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "modal-search-input":
            opt_list = self.query_one("#mcp-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_servers):
                target = self.filtered_servers[idx]
                s_name = target["name"]
                self.mm.toggle_server(s_name)
                self.refresh_list()
                if hasattr(self.app, "refresh_status_footer"):
                    self.app.refresh_status_footer()

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one("#mcp-option-list", OptionList)
                    if opt_list.highlighted is None and self.filtered_servers:
                        opt_list.highlighted = 0
                    elif opt_list.highlighted is not None:
                        if event.key == "down":
                            opt_list.action_cursor_down()
                        else:
                            opt_list.action_cursor_up()
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def action_toggle_mode(self) -> None:
        opt_list = self.query_one("#mcp-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.filtered_servers):
            target = self.filtered_servers[highlighted]
            s_name = target["name"]
            self.mm.toggle_mode(s_name)
            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()
            self.refresh_list()
            opt_list.highlighted = highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_servers):
            target = self.filtered_servers[event.option_index]
            s_name = target["name"]
            self.mm.toggle_server(s_name)
            self.refresh_list()
            opt_list = self.query_one("#mcp-option-list", OptionList)
            opt_list.highlighted = event.option_index

            if hasattr(self.app, "refresh_status_footer"):
                self.app.refresh_status_footer()


