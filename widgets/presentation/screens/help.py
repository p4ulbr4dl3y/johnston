from rich.table import Table
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Label, Static

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    ESC_HINT_CLOSE,
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
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
    ("/subagents", "View and manage subagents"),
    ("/shell", "View and manage background shell tasks"),
    ("/skills", "Browse and activate available skills"),
    ("/mcp", "Manage MCP servers & tools"),
    ("/questions", "Resume pending user questions wizard"),
    ("/rewind", "Rollback chat history to a selected message"),
    ("/fork", "Fork session from a selected message"),
    ("/rename", "Rename the active chat session"),
    ("/resume", "Switch and resume saved session dialogs"),
    ("/help", "Open this help screen"),
]

KEYBINDINGS_DATA: list[tuple[str, str]] = [
    ("Tab", "Toggle agent role (Worker / Explorer / ...)"),
    ("Shift+Tab", "Cycle execution mode (review / edits / yolo)"),
    ("Ctrl+B", "Move active shell tasks to background"),
    ("Ctrl+O", "Expand / collapse tool output & thinking"),
    ("Ctrl+P", "Expand / collapse active plan checklist"),
    ("Ctrl+H", "Hide / show plan notch at top of screen"),
    ("PageUp / PgDn", "Scroll chat history"),
    ("Shift+PgUp / PgDn", "Scroll to top / bottom of chat"),
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
        "Shift+PgUp / PgDn": "S-PgUp/Dn",
        "Shift+PgUp / Shift+PgDn": "S-PgUp/Dn",
        "PageUp / PgDn": "PgUp/Dn",
        "Shift+Tab": "S-Tab",
        "Ctrl+Enter": "C-Enter",
        "Ctrl+C / Ctrl+Q": "C-C/C-Q",
        "Ctrl+B": "C-B",
        "Ctrl+O": "C-O",
        "Ctrl+P": "C-P",
        "Ctrl+H": "C-H",
        "Ctrl+V": "C-V",
        "Ctrl+X": "C-X",
        "Ctrl+D": "C-D",
    }
    return replacements.get(key, key)


def _build_help_table(items: list[tuple[str, str]], is_compact: bool = False) -> Table:
    table = Table.grid(expand=True, padding=(0, 2 if not is_compact else 1))
    table.add_column(style="bold", no_wrap=True)
    table.add_column(style="dim", ratio=1)
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
            max_cmd_w = max(len(k) for k, _ in COMMANDS_DATA) + 2 + max(len(d) for _, d in COMMANDS_DATA)
            max_kb_w = max(len(k) for k, _ in KEYBINDINGS_DATA) + 2 + max(len(d) for _, d in KEYBINDINGS_DATA)
            sample_items = ["x" * max(max_cmd_w, max_kb_w)]
            content_w = modal_content_width(
                sample_items, "Johnston Help", f"tab/←→: switch • {ESC_HINT_CLOSE}"
            )
            apply_modal_fit(dialog, content_w, min_width=76, max_width=96)

            screen_h = self.app.size.height if getattr(self, "app", None) else 24
            if not isinstance(screen_h, int) or screen_h <= 0:
                screen_h = 24

            if screen_h < 18:
                dialog.styles.padding = (0, 1)
                dialog.styles.max_height = max(7, screen_h - 1)
                usable_h = screen_h - 1
                overhead = 7
            else:
                dialog.styles.padding = (1, 2)
                dialog.styles.max_height = max(8, min(screen_h - 2, int(screen_h * 0.95)))
                usable_h = int(dialog.styles.max_height.value) if dialog.styles.max_height else screen_h - 2
                overhead = 10

            scroll_box = self.query_one("#help-scroll-box")
            max_items = max(len(COMMANDS_DATA), len(KEYBINDINGS_DATA))
            scroll_box.styles.max_height = max(3, min(max_items, usable_h - overhead))
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        from widgets.chat_toolcall import ToolScrollBox

        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield ModalHeader("Johnston Help", esc_hint="", id="help-header-md")
            with Horizontal(id="help-tabs"):
                yield Static("Commands", id="help-tab-commands", classes="help-tab active")
                yield Static("Keybindings", id="help-tab-keybindings", classes="help-tab")
            with ToolScrollBox(id="help-scroll-box"):
                yield Static(self._get_active_table(), id="help-body", classes=MODAL_MARKDOWN)
            yield ModalHint(f"tab/←→: switch • {ESC_HINT_CLOSE}", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self._apply_dialog_fit()
        self._refresh_view()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self._refresh_view()

    def _refresh_view(self) -> None:
        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            tab_cmd = self.query_one("#help-tab-commands", Static)
            tab_keys = self.query_one("#help-tab-keybindings", Static)
            if self.active_tab == 0:
                tab_cmd.set_class(True, "active")
                tab_keys.set_class(False, "active")
            else:
                tab_cmd.set_class(False, "active")
                tab_keys.set_class(True, "active")

            body_static = self.query_one("#help-body", Static)
            body_static.update(self._get_active_table())

            hint_lbl = self.query_one(f"#{MODAL_HINT_ID}", Label)
            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            hint_lbl.update("tab/←→ • esc" if is_compact else f"tab/←→: switch • {ESC_HINT_CLOSE}")
        except Exception:
            pass

    def on_click(self, event: events.Click) -> None:
        target = event.widget
        if target is None:
            return
        if target.id == "help-tab-commands":
            if self.active_tab != 0:
                self.active_tab = 0
                self._refresh_view()
            event.stop()
        elif target.id == "help-tab-keybindings":
            if self.active_tab != 1:
                self.active_tab = 1
                self._refresh_view()
            event.stop()

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
