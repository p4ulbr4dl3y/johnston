import asyncio
from typing import Any, Dict

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from core.config import CONFIG_DIR
from core.mcp_manager import get_mcp_manager
from widgets.screens.base_modal import BaseModalScreen, status_tag
from widgets.screens.base_selection import ModalSearchNavMixin
from widgets.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
)


class MCPScreen(ModalSearchNavMixin, BaseModalScreen[None]):
    """Modal screen for enabling/disabling and toggling Eager/Lazy modes of MCP servers"""

    search_nav_option_list_id = "mcp-option-list"
    search_nav_filtered_attr = "filtered_servers"

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("tab", "toggle_mode", "Toggle Eager/Lazy"),
    ]

    def __init__(self):
        super().__init__()
        self.mm = get_mcp_manager()
        self.servers: list[Dict[str, Any]] = []
        self.filtered_servers: list[Dict[str, Any]] = []
        self.search_query = ""
        self._warmup_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown("### **Manage MCP Servers**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(placeholder="Search MCP servers...", id=MODAL_SEARCH_INPUT_ID)
            yield OptionList(id="mcp-option-list")
            yield Label("enter: toggle • tab: mode • esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.refresh_list()
        opt_list = self.query_one("#mcp-option-list", OptionList)
        if self.filtered_servers:
            opt_list.highlighted = 0
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            pass

        # Non-blocking background warmup for unstarted MCP servers
        self._warmup_task = asyncio.create_task(self._warmup_tools())

    def on_unmount(self) -> None:
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()

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
            opt_list.add_option(f"*No MCP servers configured ({CONFIG_DIR}/mcp.json or .johnston/mcp.json)*")
            self.filtered_servers = []
            return

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_servers = list(self.servers)
        else:
            self.filtered_servers = [
                s
                for s in self.servers
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
            scope_tag = status_tag(s["scope"])
            mode_tag = status_tag(s.get("mode", "eager"))
            name = s["name"]

            if disabled:
                opt_list.add_option(f"{status_tag('OFF')} {scope_tag} {mode_tag} {name}")
                continue

            tool_cnt = tools_per_server.get(name, 0)
            url = s.get("url")
            cmd = s.get("command")

            if tool_cnt > 0:
                tool_info = f"{tool_cnt} tool" if tool_cnt == 1 else f"{tool_cnt} tools"
                opt_list.add_option(f"{status_tag('ON')} {scope_tag} {mode_tag} {name} — {tool_info}")
            elif url and not cmd:
                opt_list.add_option(f"{status_tag('ERR')} {scope_tag} {mode_tag} {name} — URL unsupported")
            else:
                client = self.mm.clients.get(name) if hasattr(self.mm, "clients") else None
                err = getattr(client, "last_error", None) if client else None
                if err and "Process start failed" in err:
                    opt_list.add_option(f"{status_tag('ERR')} {scope_tag} {mode_tag} {name} — Start failed")
                elif err and "timeout" in err.lower():
                    opt_list.add_option(f"{status_tag('ERR')} {scope_tag} {mode_tag} {name} — Timeout")
                elif err:
                    opt_list.add_option(f"{status_tag('ERR')} {scope_tag} {mode_tag} {name} — Error")
                else:
                    stag = status_tag("ERR") if (not cmd and not url) else status_tag("ON")
                    opt_list.add_option(f"{stag} {scope_tag} {mode_tag} {name}")

        if prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_servers):
            opt_list.highlighted = prev_highlighted
        elif self.filtered_servers and opt_list.highlighted is None:
            opt_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            self.search_query = event.value
            self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
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
        self._handle_search_navigation(event)

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
