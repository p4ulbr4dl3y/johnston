import os
from typing import Any, Dict, List, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList

from core.config import PROJECT_PERMISSIONS_FILE
from core.permission_manager import PermissionManager


class PermissionsScreen(ModalScreen[None]):
    """Tabbed Modal screen for managing tool permissions (Groups, Tools, Scope)."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self, project_dir: Optional[str] = None):
        super().__init__()
        self.pm = PermissionManager.get_instance()
        self.project_dir = project_dir
        self.use_project_scope = bool(project_dir)
        self.active_tab = 0  # 0: Groups, 1: Tools, 2: Scope
        self.search_query = ""
        self.filtered_items: List[Dict[str, Any]] = []

    def _get_header_md(self) -> str:
        t0 = "**[ Groups ]**" if self.active_tab == 0 else "Groups"
        t1 = "**[ Tools ]**" if self.active_tab == 1 else "Tools"
        t2 = "**[ Scope ]**" if self.active_tab == 2 else "Scope"
        return f"### {t0} &nbsp;&nbsp;&nbsp;&nbsp; {t1} &nbsp;&nbsp;&nbsp;&nbsp; {t2}"

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self._get_header_md(), id="permissions-header-md", classes="modal-markdown")
            yield Input(placeholder="Search permissions...", id="modal-search-input")
            yield OptionList(id="permissions-option-list")
            yield Label("enter: toggle • tab / ←/→: switch tab • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        try:
            self.query_one("#modal-search-input", Input).focus()
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
                items.append({
                    "type": "group",
                    "name": grp,
                    "label": grp.upper(),
                    "desc": group_descriptions.get(grp, ""),
                    "action": act,
                })

        elif self.active_tab == 1:
            # Tools Tab
            tool_descriptions = {
                "read": "Read files and directories",
                "create": "Create new files",
                "edit": "Modify file content",
                "multi_edit": "Multiple file edits",
                "shell": "Execute shell commands",
                "ask_user": "Ask user questions",
                "call_mcp": "Invoke MCP tools",
                "manage_task": "Manage background tasks",
                "invoke_subagent": "Spawn background subagent",
                "manage_subagent": "Control active subagents",
                "update_plan": "Update task plan",
                "web_fetch": "Fetch web page content",
            }
            tools_cfg = perms.get("tools", {})
            for grp, tool_set in self.pm.GROUPS.items():
                for t in sorted(tool_set):
                    act = tools_cfg.get(t) or perms.get("groups", {}).get(grp, "ask")
                    is_override = t in tools_cfg
                    items.append({
                        "type": "tool",
                        "name": t,
                        "group": grp,
                        "label": t,
                        "desc": tool_descriptions.get(t, ""),
                        "action": act,
                        "is_override": is_override,
                    })

        else:
            # Scope Tab
            items.append({
                "type": "scope",
                "name": "global",
                "label": "Global Configuration",
                "desc": "~/.johnston/config.json",
                "action": "active" if not self.use_project_scope else "on",
            })
            if self.project_dir:
                proj_perm_path = os.path.join(self.project_dir, PROJECT_PERMISSIONS_FILE)
                exists = os.path.exists(proj_perm_path)
                desc = ".johnston/permissions.json" if exists else ".johnston/permissions.json (inherits global, created on edit)"
                items.append({
                    "type": "scope",
                    "name": "project",
                    "label": "Project Configuration",
                    "desc": desc,
                    "action": "active" if self.use_project_scope else "on",
                })
            else:
                items.append({
                    "type": "scope",
                    "name": "project",
                    "label": "Project Configuration",
                    "desc": "No active project directory",
                    "action": "off",
                })

        return items

    def refresh_list(self) -> None:
        raw_items = self._get_items_for_active_tab()
        opt_list = self.query_one("#permissions-option-list", OptionList)
        prev_highlighted = opt_list.highlighted
        opt_list.clear_options()

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_items = list(raw_items)
        else:
            self.filtered_items = [
                it for it in raw_items
                if q in it["name"].lower()
                or q in it["label"].lower()
                or q in it["desc"].lower()
            ]

        if not self.filtered_items:
            opt_list.add_option("*No items found*")
            return

        for it in self.filtered_items:
            if it["type"] == "scope":
                status = r"\[ACTIVE]" if it["action"] == "active" else (r"\[ON]" if it["action"] == "on" else r"\[N/A]")
                opt_list.add_option(f"{status} {it['label']} — {it['desc']}")
            else:
                act = it["action"].upper()
                if act == "ALLOW":
                    status = r"\[ALLOW]"
                elif act == "DENY":
                    status = r"\[DENY]"
                else:
                    status = r"\[ASK]"

                override_tag = r" \[OVERRIDE]" if it.get("is_override") else ""
                desc = f" — {it['desc']}" if it.get("desc") else ""
                opt_list.add_option(f"{status} {it['label']}{override_tag}{desc}")

        if prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_items):
            opt_list.highlighted = prev_highlighted
        elif self.filtered_items and opt_list.highlighted is None:
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
                if target["name"] == "project" and self.project_dir:
                    self.use_project_scope = True
                elif target["name"] == "global":
                    self.use_project_scope = False
                header_md = self.query_one("#permissions-header-md", Markdown)
                header_md.update(self._get_header_md())
                self.refresh_list()
                return

            next_act = self._cycle_action(target["action"])
            target_dir = self.project_dir if self.use_project_scope else None
            self.pm.update_permission(target["type"], target["name"], next_act, project_dir=target_dir)
            self.refresh_list()
            opt_list = self.query_one("#permissions-option-list", OptionList)
            opt_list.highlighted = idx

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "modal-search-input":
            self.search_query = event.value
            self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "modal-search-input":
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
        self.refresh_list()

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
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one("#permissions-option-list", OptionList)
                    if opt_list.highlighted is None and self.filtered_items:
                        opt_list.highlighted = 0
                    elif opt_list.highlighted is not None:
                        if key == "down":
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
