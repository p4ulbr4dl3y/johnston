from typing import Dict

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.policy_config import get_policy_config, set_policy_action, toggle_policy_action

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


class PolicyScreen(ModalScreen[None]):
    """Modal screen for configuring security policies (allow / ask / block) for tools & capabilities."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("enter", "toggle_action", "Cycle Action"),
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

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# Policy & Security Rules (`.johnston/policy.json`)", classes="modal-markdown")
            yield OptionList(id="policy-option-list")
            yield Label("enter: cycle • a: allow • s: ask • b: block • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        opt_list = self.query_one("#policy-option-list", OptionList)
        if self.items:
            opt_list.highlighted = 0

    def refresh_list(self) -> None:
        config = get_policy_config()
        opt_list = self.query_one("#policy-option-list", OptionList)
        opt_list.clear_options()

        for item in self.items:
            ktype = item["type"]
            name = item["name"]
            desc = item["desc"]

            if ktype == "tool":
                action = config.tool_actions.get(name, "allow")
            else:
                action = config.capability_actions.get(name, "allow")

            action_upper = action.upper()
            prefix = f"[{action_upper}]".ljust(7)
            kind_tag = f"[{ktype.upper()}]".ljust(14)
            opt_list.add_option(f"{prefix} {kind_tag} {name} — {desc}")

        opt_list.focus()

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def action_toggle_action(self) -> None:
        opt_list = self.query_one("#policy-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.items):
            target = self.items[highlighted]
            new_action = toggle_policy_action(target["type"], target["name"])
            self.app.notify(f"{target['type'].capitalize()} '{target['name']}' set to {new_action.upper()}")
            self.refresh_list()
            opt_list.highlighted = highlighted

    def _set_action(self, action: str) -> None:
        opt_list = self.query_one("#policy-option-list", OptionList)
        highlighted = opt_list.highlighted
        if highlighted is not None and 0 <= highlighted < len(self.items):
            target = self.items[highlighted]
            new_action = set_policy_action(target["type"], target["name"], action)
            self.app.notify(f"{target['type'].capitalize()} '{target['name']}' set to {new_action.upper()}")
            self.refresh_list()
            opt_list.highlighted = highlighted

    def action_set_allow(self) -> None:
        self._set_action("allow")

    def action_set_ask(self) -> None:
        self._set_action("ask")

    def action_set_block(self) -> None:
        self._set_action("block")
