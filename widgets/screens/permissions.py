from typing import Any, Dict, List

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
    """Modal screen for managing global per-tool permissions (allow, ask, deny) and ShellGuard."""

    search_nav_option_list_id = "permissions-option-list"
    search_nav_filtered_attr = "filtered_items"

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    TOOL_LABELS = {
        "read": "Read",
        "create": "Create",
        "edit": "Edit",
        "multi_edit": "MultiEdit",
        "shell": "Shell",
        "ask_user": "AskUser",
        "manage_shell": "ManageShell",
        "invoke_subagent": "InvokeSubagent",
        "manage_subagent": "ManageSubagent",
        "update_plan": "UpdatePlan",
        "web_fetch": "WebFetch",
    }

    def __init__(self):
        super().__init__()
        self.pm = PermissionManager.get_instance()
        self.search_query = ""
        self.filtered_items: List[Dict[str, Any]] = []

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

    def _get_items(self) -> List[Dict[str, Any]]:
        perms = self.pm.get_effective_permissions()

        items = []
        tools_cfg = perms.get("tools", {})
        for t in sorted(self.TOOL_LABELS):
            act = tools_cfg.get(t) or perms.get("default", "ask")
            items.append(
                {
                    "type": "tool",
                    "name": t,
                    "label": self.TOOL_LABELS[t],
                    "desc": "",
                    "action": act,
                    "is_override": t in tools_cfg,
                }
            )
            if t == "shell":
                sg_cfg = perms.get("shell_guard", {})
                sg_enabled = sg_cfg.get("enabled", True)
                items.append(
                    {
                        "type": "shell_guard",
                        "name": "shell_guard",
                        "label": "ShellGuard",
                        "desc": "",
                        "action": "allow" if sg_enabled else "deny",
                        "is_override": "enabled" in sg_cfg,
                    }
                )

        return items

    def refresh_list(self, reset_highlight: bool = False) -> None:
        raw_items = self._get_items()
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
            if it["type"] == "shell_guard":
                status = status_tag("ON" if it["action"] == "allow" else "OFF")
                opt_list.add_option(f"{status} {it['label']}")
            else:
                act = it["action"].upper()
                status = status_tag(act if act in ("ALLOW", "DENY") else "ASK")
                opt_list.add_option(f"{status} {it['label']}")

        if reset_highlight:
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
            if target["type"] == "shell_guard":
                # ShellGuard is a binary toggle: allow (enabled) <-> deny (disabled). 'ask' has no meaning here.
                next_act = "deny" if target["action"] == "allow" else "allow"
            else:
                next_act = self._cycle_action(target["action"])
            self.pm.update_permission(target["type"], target["name"], next_act)
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

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            self._handle_search_navigation(event)

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)
