from typing import Any, Dict, List, Tuple

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.policy_config import (
    cycle_budget_limit,
    get_policy_config,
    set_policy_action,
    toggle_policy_action,
)

DEFAULT_POLICY_ITEMS = [
    {"type": "tool", "name": "shell", "title": "Shell Commands", "desc": "Execute terminal commands"},
    {"type": "tool", "name": "read", "title": "Read Files", "desc": "Read workspace files"},
    {"type": "tool", "name": "create", "title": "Create Files", "desc": "Create new files in workspace"},
    {"type": "tool", "name": "edit", "title": "Edit Files", "desc": "Modify existing workspace files"},
    {"type": "tool", "name": "ask_user", "title": "Ask User", "desc": "Prompt user for input"},
    {"type": "tool", "name": "call_mcp_tool", "title": "MCP Tools", "desc": "Execute external MCP server tools"},
    {"type": "tool", "name": "manage_task", "title": "Background Tasks", "desc": "Manage async background tasks"},
    {"type": "tool", "name": "subagent", "title": "Subagents", "desc": "Launch subagent workers"},
    {"type": "capability", "name": "fs.read", "title": "Filesystem Read", "desc": "Read access capability"},
    {"type": "capability", "name": "fs.write", "title": "Filesystem Write", "desc": "Write access capability"},
    {"type": "capability", "name": "shell.execute", "title": "Shell Execution", "desc": "Shell process execution capability"},
    {"type": "capability", "name": "net.connect", "title": "Network Access", "desc": "Network connection capability"},
    {"type": "capability", "name": "user.prompt", "title": "User Interaction", "desc": "Interactive prompt capability"},
]

DEFAULT_BUDGET_ITEMS = [
    {"name": "max_steps", "title": "Max Loop Steps", "desc": "Max agent iteration steps"},
    {"name": "max_tool_calls", "title": "Max Tool Calls", "desc": "Max tool executions per session"},
    {"name": "max_wall_seconds", "title": "Execution Timeout", "desc": "Max runtime duration in seconds"},
    {"name": "max_writes", "title": "Max File Writes", "desc": "Max file write operations"},
    {"name": "max_changed_files", "title": "Max Changed Files", "desc": "Max modified files limit"},
    {"name": "max_diff_lines", "title": "Max Diff Lines", "desc": "Max modified line changes limit"},
    {"name": "max_tool_result_chars", "title": "Max Output Length", "desc": "Max tool result character limit"},
]


class PolicyScreen(ModalScreen[None]):
    """Modal policy & security screen matching ModelScreen tab header style."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("enter", "toggle_action", "Cycle Setting"),
        ("a", "set_allow", "Allow"),
        ("s", "set_ask", "Ask"),
        ("b", "set_block", "Block"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self, initial_tab: str = "rules"):
        super().__init__()
        self.active_tab = initial_tab
        self.items: list[Dict[str, str]] = DEFAULT_POLICY_ITEMS
        self.budget_items: list[Dict[str, str]] = DEFAULT_BUDGET_ITEMS

    @staticmethod
    def _get_header_title_text(tab: str) -> str:
        if tab == "rules":
            return "### **[ Rules & Permissions ]** &nbsp;&nbsp;&nbsp;&nbsp; Resource Budgets"
        else:
            return "### &nbsp;&nbsp; Rules & Permissions &nbsp;&nbsp;&nbsp;&nbsp; **[ Resource Budgets ]**"

    def _build_data(self, tab: str) -> Tuple[List[str], List[Any]]:
        config = get_policy_config()
        options: List[str] = []
        items: List[Any] = []

        if tab == "rules":
            for item in self.items:
                ktype = item["type"]
                name = item["name"]
                title = item.get("title", name)

                if ktype == "tool":
                    action = config.tool_actions.get(name, "allow")
                    kind_tag = r"\[TOOL]"
                else:
                    action = config.capability_actions.get(name, "allow")
                    kind_tag = r"\[CAP]"

                act_tag = rf"\[{action.upper()}]"
                options.append(f"{act_tag} {kind_tag} {title}")
                items.append(item)
        else:
            for item in self.budget_items:
                name = item["name"]
                title = item.get("title", name)
                val = getattr(config.budgets, name, None)
                val_str = "UNLIMITED" if val is None else str(val)
                tag = rf"\[{val_str}]"
                options.append(f"{tag} {title}")
                items.append(item)

        return options, items

    def compose(self) -> ComposeResult:
        options, _ = self._build_data(self.active_tab)
        with Vertical(id="modal-dialog"):
            yield Markdown(self._get_header_title_text(self.active_tab), id="policy-title", classes="modal-markdown")
            yield OptionList(*options, id="modal-option-list")
            yield Label("←/→/tab: switch tab • enter: cycle • a: allow • s: ask • b: block • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        options, self.current_items = self._build_data(self.active_tab)
        opt_list = self.query_one("#modal-option-list", OptionList)
        highlighted = opt_list.highlighted
        opt_list.clear_options()
        for opt in options:
            opt_list.add_option(opt)

        if highlighted is not None and 0 <= highlighted < len(options):
            opt_list.highlighted = highlighted
        elif options:
            opt_list.highlighted = 0
        opt_list.focus()

    def switch_tab(self, new_tab: str) -> None:
        self.active_tab = new_tab
        try:
            title_md = self.query_one("#policy-title", Markdown)
            title_md.update(self._get_header_title_text(new_tab))
        except Exception:
            pass
        self.refresh_list()

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right", "tab", "backtab", "shift+tab"):
            new_tab = "budgets" if self.active_tab == "rules" else "rules"
            self.switch_tab(new_tab)
            event.stop()
            event.prevent_default()

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.action_toggle_action()

    def action_toggle_action(self) -> None:
        opt_list = self.query_one("#modal-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.current_items):
            target = self.current_items[highlighted]
            if self.active_tab == "budgets":
                new_val = cycle_budget_limit(target["name"])
                val_display = "UNLIMITED" if new_val is None else str(new_val)
                self.app.notify(f"Budget '{target['name']}' set to {val_display}")
            else:
                new_action = toggle_policy_action(target["type"], target["name"])
                self.app.notify(f"{target['type'].capitalize()} '{target['name']}' set to {new_action.upper()}")
            self.refresh_list()

    def _set_action(self, action: str) -> None:
        if self.active_tab != "rules":
            return
        opt_list = self.query_one("#modal-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.current_items):
            target = self.current_items[highlighted]
            new_action = set_policy_action(target["type"], target["name"], action)
            self.app.notify(f"{target['type'].capitalize()} '{target['name']}' set to {new_action.upper()}")
            self.refresh_list()

    def action_set_allow(self) -> None:
        self._set_action("allow")

    def action_set_ask(self) -> None:
        self._set_action("ask")

    def action_set_block(self) -> None:
        self._set_action("block")
