import asyncio
import inspect
from typing import Any, Dict, List

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList
from textual.widgets.option_list import Option

from core.permission_manager import PermissionManager
from tools.registry import REGISTRY
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

_SELECTABLE_TYPES = ("tool", "shell_guard")


class PermissionsScreen(ModalSearchNavMixin, BaseModalScreen[None]):
    """Modal screen for managing per-tool permissions (allow, ask, deny) and Shell Guard.

    Builtin tools are grouped under a "Builtin" section, MCP tools under their
    server sections (rendered from cache first, refreshed in the background), and
    Shell Guard is a standalone binary toggle at the top of the list.
    """

    search_nav_option_list_id = "permissions-option-list"
    search_nav_filtered_attr = "filtered_items"

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.pm = PermissionManager.get_instance()
        self.search_query = ""
        self.filtered_items: List[Dict[str, Any]] = []
        # MCP tools fetched in the background; empty until the background task ran.
        self.mcp_tools: List[Dict[str, Any]] = []
        self._mcp_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown(
                "### **Manage Tool Permissions**",
                id="permissions-header-md",
                classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}",
            )
            yield Input(placeholder="Search permissions...", id=MODAL_SEARCH_INPUT_ID)
            yield OptionList(id="permissions-option-list")
            yield Label("enter: toggle • esc: close", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.refresh_list()
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            pass
        # Non-blocking background refresh of MCP tools (server connect may be slow).
        self._mcp_task = asyncio.create_task(self._load_mcp_tools_async())

    def on_unmount(self) -> None:
        if self._mcp_task and not self._mcp_task.done():
            self._mcp_task.cancel()

    async def _load_mcp_tools_async(self) -> None:
        try:
            from core.mcp_manager import get_mcp_manager

            mcp_mgr = get_mcp_manager()
            ready = getattr(mcp_mgr, "ensure_tools_ready_async", None)
            if callable(ready):
                res = ready()
                if inspect.isawaitable(res):
                    await res
            res = mcp_mgr.get_active_tools_async()
            tools = await res if inspect.isawaitable(res) else res
        except Exception:
            return
        self.mcp_tools = tools or []
        if getattr(self, "is_mounted", True):
            self.refresh_list()

    def _get_cached_mcp_tools(self) -> List[Dict[str, Any]]:
        """Synchronously returns tools from already-connected MCP clients (no I/O)."""
        try:
            from core.mcp_manager import get_mcp_manager

            return get_mcp_manager().get_cached_tools() or []
        except Exception:
            return []

    @staticmethod
    def _header_item(name: str, label: str) -> Dict[str, Any]:
        return {"type": "group_header", "name": name, "label": label, "desc": "", "action": "", "is_override": False}

    @staticmethod
    def _separator_item() -> Dict[str, Any]:
        return {"type": "separator", "name": "", "label": "", "desc": "", "action": "", "is_override": False}

    def _tool_item(self, name: str, act: str, tools_cfg: Dict[str, Any], desc: str = "") -> Dict[str, Any]:
        return {
            "type": "tool",
            "name": name,
            "label": name,
            "desc": desc,
            "action": act,
            "is_override": name in tools_cfg,
        }

    def _get_items(self) -> List[Dict[str, Any]]:
        perms = self.pm.get_effective_permissions()
        tools_cfg = perms.get("tools", {})
        default_act = perms.get("default", "ask")
        items: List[Dict[str, Any]] = []

        # --- Shell Guard: standalone binary toggle (no group), at the top ---
        sg_enabled = perms.get("shell_guard", True)
        items.append(
            {
                "type": "shell_guard",
                "name": "shell_guard",
                "label": "Shell Guard",
                "desc": "",
                "action": "allow" if sg_enabled else "deny",
                "is_override": "shell_guard" in perms,
            }
        )

        # --- Builtin tools section ---
        items.append(self._separator_item())
        items.append(self._header_item("builtin", "Builtin"))
        for t in sorted(REGISTRY):
            act = tools_cfg.get(t) or default_act
            items.append(self._tool_item(t, act, tools_cfg))

        # --- MCP tool sections, grouped by server ---
        mcp_tools = self.mcp_tools or self._get_cached_mcp_tools()
        if mcp_tools:
            by_server: Dict[str, List[Dict[str, Any]]] = {}
            for t in mcp_tools:
                by_server.setdefault(t.get("_mcp_server") or "mcp", []).append(t)

            for server_name in sorted(by_server):
                items.append(self._separator_item())
                items.append(self._header_item(server_name, server_name))
                server_tools = sorted(
                    by_server[server_name],
                    key=lambda x: (x.get("function", {}) or {}).get("name", ""),
                )
                for t in server_tools:
                    fn = t.get("function", {}) or {}
                    exposed = fn.get("name", "")
                    if not exposed:
                        continue
                    act = tools_cfg.get(exposed) or default_act
                    items.append(self._tool_item(exposed, act, tools_cfg, desc=fn.get("description", "") or ""))

        return items

    def _first_selectable_index(self) -> int | None:
        for i, it in enumerate(self.filtered_items):
            if it["type"] in _SELECTABLE_TYPES:
                return i
        return None

    def refresh_list(self, reset_highlight: bool = False) -> None:
        raw_items = self._get_items()
        opt_list = self.query_one("#permissions-option-list", OptionList)
        prev_highlighted = opt_list.highlighted if not reset_highlight else None
        opt_list.clear_options()

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_items = list(raw_items)
        else:
            # Search: flat list of matches, without group headers / separators.
            self.filtered_items = [
                it
                for it in raw_items
                if it["type"] in _SELECTABLE_TYPES
                and (q in it["name"].lower() or q in it["label"].lower() or q in it["desc"].lower())
            ]

        if not self.filtered_items:
            opt_list.add_option("*No items found*")
            return

        for it in self.filtered_items:
            if it["type"] == "group_header":
                opt_list.add_option(Option(it["label"], disabled=True))
            elif it["type"] == "separator":
                opt_list.add_option(Option("", disabled=True))
            elif it["type"] == "shell_guard":
                status = status_tag("ON" if it["action"] == "allow" else "OFF")
                opt_list.add_option(f"{status} {it['label']}")
            else:
                act = it["action"].upper()
                status = status_tag(act if act in ("ALLOW", "DENY") else "ASK")
                opt_list.add_option(f"   {status} {it['label']}")

        if reset_highlight:
            opt_list.highlighted = self._first_selectable_index()
        elif prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_items):
            opt_list.highlighted = prev_highlighted
        elif self.filtered_items:
            opt_list.highlighted = self._first_selectable_index()

    def _cycle_action(self, current: str) -> str:
        cur = current.lower()
        if cur == "allow":
            return "ask"
        elif cur == "ask":
            return "deny"
        return "allow"

    def toggle_selected_permission(self, idx: int) -> None:
        if not (0 <= idx < len(self.filtered_items)):
            return
        target = self.filtered_items[idx]
        if target["type"] not in _SELECTABLE_TYPES:
            # Group headers / separators are not toggleable.
            return
        if target["type"] == "shell_guard":
            # Shell Guard is a binary toggle: allow (enabled) <-> deny (disabled). 'ask' has no meaning here.
            next_act = "deny" if target["action"] == "allow" else "allow"
        else:
            next_act = self._cycle_action(target["action"])
        self.pm.update_permission(target["type"], target["name"], next_act)
        self.refresh_list()
        new_idx = next(
            (i for i, it in enumerate(self.filtered_items) if it["type"] == target["type"] and it["name"] == target["name"]),
            None,
        )
        if new_idx is not None:
            opt_list = self.query_one("#permissions-option-list", OptionList)
            opt_list.highlighted = new_idx

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            self.search_query = event.value
            self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            opt_list = self.query_one("#permissions-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None:
                self.toggle_selected_permission(idx)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.toggle_selected_permission(event.option_index)

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            self._handle_search_navigation(event)

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)
