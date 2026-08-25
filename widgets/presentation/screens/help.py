from rich.table import Table
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, Static

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
)
from widgets.utils.key_aliases import expand_bindings

COMMANDS_DATA: list[tuple[str, str]] = [
    ("/connect", "Connect AI provider & set API key"),
    ("/models", "Switch active model across providers"),
    ("/thinking", "Set reasoning effort / thinking budget"),
    ("/new", "Start a new chat session"),
    ("/compact", "Compact session conversation history"),
    ("/copy", "Copy last assistant response to clipboard"),
    ("/diff", "View workspace diff since session checkpoint"),
    ("/sandbox", "Toggle shell command sandbox (ON/OFF)"),
    ("/permissions", "Manage tool permissions (allow, ask, deny)"),
    ("/subagents", "View and manage subagents"),
    ("/shell", "View and manage background shell tasks"),
    ("/skills", "Browse and activate available skills"),
    ("/mcp", "Manage MCP servers & tools"),
    ("/questions", "Resume pending user questions wizard"),
    ("/rewind", "Rollback chat history to a selected message"),
    ("/resume", "Switch and resume saved session dialogs"),
    ("/help", "Open this help screen"),
]

KEYBINDINGS_DATA: list[tuple[str, str]] = [
    ("Shift+Tab", "Toggle Action / Explore mode"),
    ("Ctrl+B", "Move active shell tasks to background"),
    ("Ctrl+O", "Expand / collapse tool output & thinking"),
    ("PageUp / PgDn", "Scroll chat history"),
    ("Shift+PgUp / Shift+PgDn", "Scroll to top / bottom of chat"),
    ("Enter", "Send message"),
    ("Ctrl+Enter", "Insert new line in input (also Shift+Enter)"),
    ("Ctrl+V", "Paste text or clipboard image"),
    ("Ctrl+X", "Cut selected text"),
    ("Ctrl+D", "Detach last attached clipboard image"),
    ("↑ / ↓", "History navigation (looping)"),
    ("@", "Attach workspace file (autocompletion)"),
    ("/", "Slash command menu (autocompletion)"),
    ("Esc", "Cancel response generation / Close modals"),
    ("Ctrl+C / Ctrl+Q", "Exit application"),
]


def _format_help_key(key: str, is_compact: bool) -> str:
    if not is_compact:
        return key
    replacements = {
        "Shift+PgUp / Shift+PgDn": "S-PgUp/Dn",
        "PageUp / PgDn": "PgUp/Dn",
        "Shift+Tab": "S-Tab",
        "Ctrl+Enter": "C-Enter",
        "Ctrl+C / Ctrl+Q": "C-C/C-Q",
        "Ctrl+B": "C-B",
        "Ctrl+O": "C-O",
        "Ctrl+V": "C-V",
        "Ctrl+X": "C-X",
        "Ctrl+D": "C-D",
    }
    return replacements.get(key, key)


def _build_help_table(items: list[tuple[str, str]], is_compact: bool = False) -> Table:
    table = Table.grid(expand=True, padding=(0, 2 if not is_compact else 1))
    table.add_column(style="bold #f4f4f5", no_wrap=True)
    table.add_column(style="#a1a1aa", ratio=1)
    for key, desc in items:
        table.add_row(_format_help_key(key, is_compact), desc)
    return table


class HelpScreen(BaseModalScreen[None]):
    """Modal help screen with 2 tabs: Commands & Keybindings in Shadcn pill badge layout"""

    BINDINGS = expand_bindings([
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self):
        super().__init__()
        self.active_tab = 0  # 0: Commands, 1: Keybindings

    def _get_tabs_markup(self) -> str:
        if self.active_tab == 0:
            return "[bold #ffffff on #27272a]  Commands  [/]   [#71717a]  Keybindings  [/]"
        return "[#71717a]  Commands  [/]   [bold #ffffff on #27272a]  Keybindings  [/]"

    def _get_active_table(self) -> Table:
        from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

        is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
        return _build_help_table(
            KEYBINDINGS_DATA if self.active_tab == 1 else COMMANDS_DATA, is_compact=is_compact
        )

    def _apply_dialog_fit(self) -> None:
        try:
            from widgets.utils.responsive import apply_modal_fit, modal_content_width

            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            # Max width across commands/keybindings with generous column gap
            sample_items = [f"{k}        {d}" for k, d in COMMANDS_DATA + KEYBINDINGS_DATA]
            content_w = modal_content_width(sample_items, "### **Johnston Help**", "tab / ←→: switch • esc: close")
            apply_modal_fit(dialog, content_w, min_width=70, max_width=92)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        from widgets.chat_toolcall import ToolScrollBox

        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield Markdown(
                "### **Johnston Help**",
                id="help-header-md",
                classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}",
            )
            yield Static(self._get_tabs_markup(), id="help-tabs", classes=MODAL_MARKDOWN)
            with ToolScrollBox(id="help-scroll-box"):
                yield Static(self._get_active_table(), id="help-body", classes=MODAL_MARKDOWN)
            yield Label("tab / ←→: switch • esc: close", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self._apply_dialog_fit()
        self._refresh_view()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self._refresh_view()

    def _refresh_view(self) -> None:
        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            tabs_static = self.query_one("#help-tabs", Static)
            tabs_static.update(self._get_tabs_markup())
            body_static = self.query_one("#help-body", Static)
            body_static.update(self._get_active_table())

            hint_lbl = self.query_one(f"#{MODAL_HINT_ID}", Label)
            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            hint_lbl.update("tab/←→: switch • esc" if is_compact else "tab / ←→: switch • esc: close")
        except Exception:
            pass

    async def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right", "tab", "backtab"):
            self.active_tab = 1 if self.active_tab == 0 else 0
            self._refresh_view()
            event.prevent_default()
            event.stop()
            return
        if event.key in ("up", "down", "pageup", "pagedown"):
            from widgets.chat_toolcall import ToolScrollBox

            try:
                scroll_box = self.query_one("#help-scroll-box", ToolScrollBox)
                if event.key == "up":
                    scroll_box.scroll_up(animate=False)
                elif event.key == "down":
                    scroll_box.scroll_down(animate=False)
                elif event.key == "pageup":
                    scroll_box.scroll_page_up(animate=False)
                elif event.key == "pagedown":
                    scroll_box.scroll_page_down(animate=False)
                event.prevent_default()
                event.stop()
                return
            except Exception:
                pass
        await super()._on_key(event)

    def action_close(self) -> None:
        self.dismiss(None)
