from typing import Dict

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList, TabbedContent, TabPane

from core.policy_config import (
    cycle_budget_limit,
    get_policy_config,
    set_policy_action,
    toggle_policy_action,
)

DEFAULT_POLICY_ITEMS = [
    {"type": "tool", "name": "shell", "desc": "Execute shell commands"},
    {"type": "tool", "name": "read", "desc": "Read workspace files"},
    {"type": "tool", "name": "create", "desc": "Create workspace files"},
    {"type": "tool", "name": "edit", "desc": "Edit workspace files"},
    {"type": "tool", "name": "ask_user", "desc": "Prompt user interactively"},
    {"type": "tool", "name": "call_mcp_tool", "desc": "Execute MCP tools"},
    {"type": "tool", "name": "manage_task", "desc": "Manage background tasks"},
    {"type": "tool", "name": "subagent", "desc": "Launch subagents"},
    {"type": "capability", "name": "fs.read", "desc": "Filesystem read access"},
    {"type": "capability", "name": "fs.write", "desc": "Filesystem write access"},
    {"type": "capability", "name": "shell.execute", "desc": "Shell command capability"},
    {"type": "capability", "name": "net.connect", "desc": "Network connectivity capability"},
    {"type": "capability", "name": "user.prompt", "desc": "User prompt capability"},
]

DEFAULT_BUDGET_ITEMS = [
    {"name": "max_steps", "desc": "Agent loop max steps"},
    {"name": "max_tool_calls", "desc": "Max tool calls per session"},
    {"name": "max_wall_seconds", "desc": "Max execution time (sec)"},
    {"name": "max_writes", "desc": "Max file write operations"},
    {"name": "max_changed_files", "desc": "Max changed files count"},
    {"name": "max_diff_lines", "desc": "Max total diff lines"},
    {"name": "max_tool_result_chars", "desc": "Max tool output characters"},
]


class PolicyScreen(ModalScreen[None]):
    """Modal screen with tabs for configuring security rules and resource budget limits."""

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

    def __init__(self):
        super().__init__()
        self.items: list[Dict[str, str]] = DEFAULT_POLICY_ITEMS
        self.budget_items: list[Dict[str, str]] = DEFAULT_BUDGET_ITEMS

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# Security & Policy (`.johnston/policy.json`)", classes="modal-markdown")
            with TabbedContent(id="policy-tabs"):
                with TabPane("Rules & Permissions", id="tab-rules"):
                    yield OptionList(id="policy-option-list")
                with TabPane("Resource Budgets", id="tab-budgets"):
                    yield OptionList(id="budget-option-list")
            yield Label("enter: cycle • a: allow • s: ask • b: block • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_rules_list()
        self.refresh_budgets_list()
        opt_list = self.query_one("#policy-option-list", OptionList)
        if self.items:
            opt_list.highlighted = 0

    def refresh_rules_list(self) -> None:
        config = get_policy_config()
        opt_list = self.query_one("#policy-option-list", OptionList)
        opt_list.clear_options()

        for item in self.items:
            ktype = item["type"]
            name = item["name"]
            desc = item["desc"]

            if ktype == "tool":
                action = config.tool_actions.get(name, "allow")
                kind_tag = r"\[TOOL]"
            else:
                action = config.capability_actions.get(name, "allow")
                kind_tag = r"\[CAP]"

            act_tag = rf"\[{action.upper()}]"
            opt_list.add_option(f"{act_tag} {kind_tag} {name} — {desc}")

    def refresh_budgets_list(self) -> None:
        config = get_policy_config()
        opt_list = self.query_one("#budget-option-list", OptionList)
        opt_list.clear_options()

        for item in self.budget_items:
            name = item["name"]
            desc = item["desc"]
            val = getattr(config.budgets, name, None)
            val_str = "UNLIMITED" if val is None else str(val)
            tag = rf"\[{val_str}]"
            opt_list.add_option(f"{tag} {name} — {desc}")

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def _get_active_tab(self) -> str:
        try:
            tabs = self.query_one("#policy-tabs", TabbedContent)
            return tabs.active or "tab-rules"
        except Exception:
            return "tab-rules"

    def action_toggle_action(self) -> None:
        active_tab = self._get_active_tab()
        if active_tab == "tab-budgets":
            opt_list = self.query_one("#budget-option-list", OptionList)
            highlighted = opt_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(self.budget_items):
                target = self.budget_items[highlighted]
                new_val = cycle_budget_limit(target["name"])
                val_display = "UNLIMITED" if new_val is None else str(new_val)
                self.app.notify(f"Budget '{target['name']}' set to {val_display}")
                self.refresh_budgets_list()
                opt_list.highlighted = highlighted
        else:
            opt_list = self.query_one("#policy-option-list", OptionList)
            highlighted = opt_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(self.items):
                target = self.items[highlighted]
                new_action = toggle_policy_action(target["type"], target["name"])
                self.app.notify(f"{target['type'].capitalize()} '{target['name']}' set to {new_action.upper()}")
                self.refresh_rules_list()
                opt_list.highlighted = highlighted

    def _set_action(self, action: str) -> None:
        if self._get_active_tab() != "tab-rules":
            return
        opt_list = self.query_one("#policy-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.items):
            target = self.items[highlighted]
            new_action = set_policy_action(target["type"], target["name"], action)
            self.app.notify(f"{target['type'].capitalize()} '{target['name']}' set to {new_action.upper()}")
            self.refresh_rules_list()
            opt_list.highlighted = highlighted

    def action_set_allow(self) -> None:
        self._set_action("allow")

    def action_set_ask(self) -> None:
        self._set_action("ask")

    def action_set_block(self) -> None:
        self._set_action("block")
