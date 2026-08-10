import os
from typing import Any, Dict, List, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from core.permission_manager import PermissionManager
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


class PermissionsScreen(ModalSearchNavMixin, BaseModalScreen[None]):
    """Tabbed Modal screen for managing tool permissions (Groups, Tools, Scope)."""

    search_nav_option_list_id = "permissions-option-list"
    search_nav_filtered_attr = "filtered_items"

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("tab", "next_tab", "Switch Tab"),
    ]

    def __init__(self, project_dir: Optional[str] = None, use_project_scope: bool = False):
        super().__init__()
        self.pm = PermissionManager.get_instance()
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.use_project_scope = use_project_scope
        self.active_tab = 0  # 0: Groups, 1: Tools, 2: Scope
        self.search_query = ""
        self.filtered_items: List[Dict[str, Any]] = []

    def _get_header_md(self) -> str:
        t0 = "**[ Groups ]**" if self.active_tab == 0 else "**Groups**"
        t1 = "**[ Tools ]**" if self.active_tab == 1 else "**Tools**"
        t2 = "**[ Scope ]**" if self.active_tab == 2 else "**Scope**"
        return f"### **Manage Tool Permissions**\n{t0} &nbsp;&nbsp;&nbsp;&nbsp; {t1} &nbsp;&nbsp;&nbsp;&nbsp; {t2}"

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown(
                self._get_header_md(), id="permissions-header-md", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}"
            )
            yield Input(placeholder="Search permissions...", id=MODAL_SEARCH_INPUT_ID)
            yield OptionList(id="permissions-option-list")
            yield Label("enter: toggle • tab / ←/→: switch tab • esc: close", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.refresh_list()
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            pass

    def _get_items_for_active_tab(self) -> List[Dict[str, Any]]:
        target_dir = self.project_dir if self.use_project_scope else None
        perms = self.pm.get_effective_permissions(target_dir)

        items = []

        if self.active_tab == 0:
            # Groups Tab
            group_descriptions = {
                "read": "Read-only & state operations",
                "write": "Filesystem modifications",
                "net": "Network & MCP requests",
                "exec": "Terminal & subagent execution",
            }
            for grp in ["read", "write", "net", "exec"]:
                act = perms.get("groups", {}).get(grp, "ask")
                items.append(
                    {
                        "type": "group",
                        "name": grp,
                        "label": grp.capitalize(),
                        "desc": group_descriptions.get(grp, ""),
                        "action": act,
                    }
                )

        elif self.active_tab == 1:
            tool_labels = {
                "read": "Read",
                "create": "Create",
                "edit": "Edit",
                "multi_edit": "MultiEdit",
                "shell": "Shell",
                "ask_user": "AskUser",
                "call_mcp": "CallMCP",
                "manage_shell": "ManageShell",
                "invoke_subagent": "InvokeSubagent",
                "manage_subagent": "ManageSubagent",
                "update_plan": "UpdatePlan",
                "web_fetch": "WebFetch",
            }
            tools_cfg = perms.get("tools", {})
            for grp, tool_set in self.pm.GROUPS.items():
                for t in sorted(tool_set):
                    act = tools_cfg.get(t) or perms.get("groups", {}).get(grp, "ask")
                    is_override = t in tools_cfg
                    items.append(
                        {
                            "type": "tool",
                            "name": t,
                            "group": grp,
                            "label": tool_labels.get(t, t.capitalize()),
                            "desc": "",
                            "action": act,
                            "is_override": is_override,
                        }
                    )
                    if t == "shell":
                        sg_cfg = perms.get("shell_guard", {})
                        sg_enabled = sg_cfg.get("enabled", True)
                        items.append(
                            {
                                "type": "shell_guard",
                                "name": "shell_guard",
                                "group": "exec",
                                "label": "ShellGuard",
                                "desc": "",
                                "action": "allow" if sg_enabled else "deny",
                                "is_override": "enabled" in sg_cfg,
                            }
                        )

        else:
            # Scope Tab
            items.append(
                {
                    "type": "scope",
                    "name": "global",
                    "label": "Global Configuration",
                    "desc": "",
                    "action": "active" if not self.use_project_scope else "on",
                }
            )
            if self.project_dir:
                items.append(
                    {
                        "type": "scope",
                        "name": "project",
                        "label": "Project Configuration",
                        "desc": "",
                        "action": "active" if self.use_project_scope else "on",
                    }
                )
            else:
                items.append(
                    {
                        "type": "scope",
                        "name": "project",
                        "label": "Project Configuration",
                        "desc": "",
                        "action": "off",
                    }
                )

        return items

    def refresh_list(self, reset_highlight: bool = False) -> None:
        raw_items = self._get_items_for_active_tab()
        opt_list = self.query_one("#permissions-option-list", OptionList)
        prev_highlighted = opt_list.highlighted if not reset_highlight else None
        opt_list.clear_options()

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_items = list(raw_items)
        else:
            self.filtered_items = [
                it for it in raw_items if q in it["name"].lower() or q in it["label"].lower() or q in it["desc"].lower()
            ]

        if not self.filtered_items:
            opt_list.add_option("*No items found*")
            return

        for it in self.filtered_items:
            if it["type"] == "scope":
                status = (
                    status_tag("ACTIVE")
                    if it["action"] == "active"
                    else (status_tag("ON") if it["action"] == "on" else status_tag("N/A"))
                )
                desc = f" — {it['desc']}" if it.get("desc") else ""
                opt_list.add_option(f"{status} {it['label']}{desc}")
            elif it["type"] == "shell_guard":
                status = status_tag("ON" if it["action"] == "allow" else "OFF")
                opt_list.add_option(f"{status} {it['label']}")
            else:
                act = it["action"].upper()
                status = status_tag(act if act in ("ALLOW", "DENY") else "ASK")
                desc = f" — {it['desc']}" if (it.get("desc") and it.get("type") == "group") else ""
                opt_list.add_option(f"{status} {it['label']}{desc}")

        if reset_highlight:
            if self.active_tab == 2:  # Scope tab: highlight active scope
                active_idx = 0
                for idx, it in enumerate(self.filtered_items):
                    if it.get("action") == "active":
                        active_idx = idx
                        break
                opt_list.highlighted = active_idx
            else:  # Groups or Tools tab: highlight first item
                opt_list.highlighted = 0
        elif prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_items):
            opt_list.highlighted = prev_highlighted
        elif self.filtered_items:
            opt_list.highlighted = 0

    def _cycle_action(self, current: str) -> str:
        cur = current.lower()
        if cur == "allow":
            return "ask"
        elif cur == "ask":
            return "deny"
        return "allow"

    def toggle_selected_permission(self, idx: int) -> None:
        if 0 <= idx < len(self.filtered_items):
            target = self.filtered_items[idx]
            if target["type"] == "scope":
                if target["name"] == "project":
                    self.use_project_scope = True
                elif target["name"] == "global":
                    self.use_project_scope = False
                header_md = self.query_one("#permissions-header-md", Markdown)
                header_md.update(self._get_header_md())
                self.refresh_list(reset_highlight=True)
                return

            if target["type"] == "shell_guard":
                # ShellGuard is a binary toggle: allow (enabled) <-> deny (disabled). 'ask' has no meaning here.
                next_act = "deny" if target["action"] == "allow" else "allow"
            else:
                next_act = self._cycle_action(target["action"])
            target_dir = self.project_dir if self.use_project_scope else None
            self.pm.update_permission(target["type"], target["name"], next_act, project_dir=target_dir)
            self.refresh_list()
            opt_list = self.query_one("#permissions-option-list", OptionList)
            opt_list.highlighted = idx

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

    def switch_tab(self, delta: int = 1) -> None:
        self.active_tab = (self.active_tab + delta) % 3
        header_md = self.query_one("#permissions-header-md", Markdown)
        header_md.update(self._get_header_md())
        self.refresh_list(reset_highlight=True)

    def _on_key(self, event: events.Key) -> None:
        key = event.key
        if key in ("right", "tab", "key_right"):
            self.switch_tab(1)
            event.prevent_default()
            event.stop()
            return
        elif key in ("left", "shift+tab", "backtab", "key_left"):
            self.switch_tab(-1)
            event.prevent_default()
            event.stop()
            return

        if key in ("down", "up"):
            self._handle_search_navigation(event)

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)
