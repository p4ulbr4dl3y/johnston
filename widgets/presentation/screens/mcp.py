import asyncio
from typing import Any, Dict

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList
from textual.widgets.option_list import Option

from core.domain.defaults.config import THEME_MUTED
from core.infrastructure.mcp import MCPManager, get_mcp_manager
from core.infrastructure.platform.paths import CONFIG_DIR
from widgets.presentation.screens.base_modal import BaseModalScreen, status_tag
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
)


class MCPScreen(ModalSearchNavMixin, BaseModalScreen[None]):
    """Modal screen for enabling/disabling MCP servers"""

    search_nav_option_list_id = "mcp-option-list"
    search_nav_filtered_attr = "filtered_servers"

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.mm = get_mcp_manager()
        try:
            self.servers = self.mm.load_servers()
        except Exception:
            self.servers = []
        self.filtered_servers: list[Dict[str, Any]] = []
        self.search_query = ""
        self._warmup_task: asyncio.Task | None = None
        self._pending_toggles: set[str] = set()
        self._toggle_tasks: set[asyncio.Task] = set()

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown("### **Manage MCP Servers**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(placeholder="Search MCP servers...", id=MODAL_SEARCH_INPUT_ID)
            yield HeaderWrapOptionList(id="mcp-option-list")
            yield Label("enter: toggle • esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.refresh_list()
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            pass

        # Non-blocking background warmup for unstarted MCP servers
        self._warmup_task = asyncio.create_task(self._warmup_tools())

    def on_unmount(self) -> None:
        if self._warmup_task and not self._warmup_task.done():
            self._warmup_task.cancel()
        for task in list(self._toggle_tasks):
            task.cancel()

    async def _warmup_tools(self) -> None:
        try:
            # Coalesced background warmup: reuses an in-flight fetch and never
            # blocks on a cold (npx/uvx) server. Tools are rendered from cache
            # once the warmup finishes.
            await self.mm.ensure_tools_ready_async()
            task = getattr(self.mm, "_tools_refresh_task", None)
            if task is not None and not task.done():
                await task
            if getattr(self, "is_mounted", True):
                self.refresh_list()
        except Exception:
            pass

    def _load_servers_bg(self, refresh: bool = True) -> None:
        """Load MCP servers off the event loop and refresh the list when ready."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        def _load() -> None:
            try:
                servers = self.mm.load_servers()
            except Exception:
                servers = getattr(self, "servers", []) or []
            self.servers = servers
            # Re-schedule the render on the loop that submitted the executor
            # work: get_running_loop() inside this worker thread raises
            # RuntimeError, so the loop must be captured up front.
            if refresh and loop is not None and getattr(self, "is_mounted", True):
                try:
                    loop.call_soon_threadsafe(self._render_from_cache)
                except RuntimeError:
                    pass

        if loop is not None:
            loop.run_in_executor(None, _load)
        else:
            _load()

    def refresh_list(self) -> None:
        """Refresh the MCP server list. Disk/file loading runs off the event loop."""
        # Always render immediately (even with a cold cache, so the modal never
        # shows an empty box while a background load is queued behind other
        # worker-thread work); the background loader refreshes the rows without
        # blocking keystroke handling.
        self._render_from_cache()
        self._load_servers_bg(refresh=True)

    def _render_from_cache(self) -> None:
        try:
            opt_list = self.query_one("#mcp-option-list", OptionList)
            prev_highlighted = opt_list.highlighted
            opt_list.clear_options()

            if not self.servers:
                opt_list.add_option(
                    Text(f"No MCP servers configured ({CONFIG_DIR}/mcp.json or .johnston/mcp.json).", style=THEME_MUTED)
                )
                self.filtered_servers = []
                return

            q = self.search_query.strip().lower()

            def _matches(s: Dict[str, Any]) -> bool:
                if not q:
                    return True
                return (
                    q in s.get("name", "").lower()
                    or q in s.get("scope", "").lower()
                    or q in s.get("command", "").lower()
                    or q in s.get("url", "").lower()
                )

            tools_per_server: Dict[str, int] = {}
            try:
                get_status = getattr(self.mm, "get_server_status", None)
                if callable(get_status):
                    for s in self.servers:
                        st = get_status(s.get("name", ""))
                        if st.get("tools"):
                            tools_per_server[s["name"]] = st["tools"]
            except Exception:
                pass

            # self.filtered_servers grows in lockstep with option rows: a Group header
            # is represented by None, a real server by its dict (like BaseSelectionScreen).
            self.filtered_servers = []
            first_group = True
            for scope in ("global", "project"):
                group = [s for s in self.servers if s.get("scope") == scope and _matches(s)]
                if not group:
                    continue
                if not first_group:
                    opt_list.add_option(Option("", disabled=True))
                    self.filtered_servers.append(None)
                first_group = False
                opt_list.add_option(Option(scope.capitalize(), disabled=True))
                self.filtered_servers.append(None)
                for s in group:
                    self._add_server_row(opt_list, s, tools_per_server)
                    self.filtered_servers.append(s)

            if not self.filtered_servers:
                opt_list.highlighted = None
                return

            if prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_servers):
                server = self.filtered_servers[prev_highlighted]
                if server is not None:
                    opt_list.highlighted = prev_highlighted
                    return

            # First selectable (non-header) row — like SkillsScreen does
            for i, s in enumerate(self.filtered_servers):
                if s is not None:
                    opt_list.highlighted = i
                    break
        except Exception:
            pass

    def _add_server_row(self, opt_list: OptionList, s: Dict[str, Any], tools_per_server: Dict[str, int]) -> None:
        name = s["name"]
        if not MCPManager.server_enabled(s):
            opt_list.add_option(f"   {status_tag('OFF')} {name}")
            return

        tool_cnt = tools_per_server.get(name, 0)
        url = s.get("url")
        cmd = s.get("command")

        if tool_cnt > 0:
            tool_info = f"{tool_cnt} tool" if tool_cnt == 1 else f"{tool_cnt} tools"
            opt_list.add_option(f"   {status_tag('ON')} {name} — {tool_info}")
        elif url and not cmd:
            opt_list.add_option(f"   {status_tag('ERR')} {name} — URL unsupported")
        else:
            try:
                st = self.mm.get_server_status(name) if hasattr(self.mm, "get_server_status") else {}
            except Exception:
                st = {}
            err = st.get("error") if isinstance(st, dict) else None
            if err:
                e_lower = err.lower()
                if "timeout" in e_lower or "timed out" in e_lower:
                    opt_list.add_option(f"   {status_tag('ERR')} {name} — Timeout")
                elif "start" in e_lower:
                    opt_list.add_option(f"   {status_tag('ERR')} {name} — Start failed")
                else:
                    opt_list.add_option(f"   {status_tag('ERR')} {name} — Error")
            else:
                stag = status_tag("ERR") if (not cmd and not url) else status_tag("ON")
                opt_list.add_option(f"   {stag} {name}")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            self.search_query = event.value
            self.refresh_list()

    def _toggle_server_async(self, name: str) -> None:
        """Toggle a server off the UI thread; duplicate toggles for the same
        server while one is in flight are dropped (enter-spam guard).

        ``toggle_server`` performs a blocking file read-modify-write and, for a
        running client, a blocking process teardown (up to a few seconds) — both
        must never run on the UI thread or the modal freezes.
        """
        if name in self._pending_toggles:
            return
        self._pending_toggles.add(name)
        task = asyncio.create_task(self._do_toggle(name))
        self._toggle_tasks.add(task)
        task.add_done_callback(self._toggle_tasks.discard)

    async def _do_toggle(self, name: str) -> None:
        try:
            enabled = await asyncio.to_thread(self.mm.toggle_server, name)
            if enabled:
                # Freshly-enabled server: kick the (coalesced, async) warmup so
                # the row can show "N tools" without reopening the modal.
                try:
                    await self.mm.ensure_tools_ready_async()
                    warm_task = getattr(self.mm, "_tools_refresh_task", None)
                    if warm_task is not None and not warm_task.done():
                        def _on_warmed(_done):
                            if getattr(self, "is_mounted", True):
                                self.refresh_list()
                                if hasattr(self.app, "refresh_status_footer"):
                                    self.app.refresh_status_footer()

                        warm_task.add_done_callback(_on_warmed)
                except Exception:
                    pass
        except asyncio.CancelledError:
            raise
        except Exception as err:
            if hasattr(self, "notify"):
                self.notify(f"Failed to toggle {name}: {err}", severity="error")
        finally:
            self._pending_toggles.discard(name)
            if getattr(self, "is_mounted", True):
                self.refresh_list()
                if hasattr(self.app, "refresh_status_footer"):
                    self.app.refresh_status_footer()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            opt_list = self.query_one("#mcp-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_servers):
                target = self.filtered_servers[idx]
                if target is None:
                    return
                self._toggle_server_async(target["name"])

    def _on_key(self, event: events.Key) -> None:
        self._handle_search_navigation(event)

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_servers):
            target = self.filtered_servers[event.option_index]
            if target is None:
                return
            self._toggle_server_async(target["name"])
            opt_list = self.query_one("#mcp-option-list", OptionList)
            opt_list.highlighted = event.option_index
