"""Shared DOM id/class string constants for widgets and screens.

Centralises selectors and CSS class names that are referenced in multiple
places so they stay consistent and easy to rename.

Each widget id has two forms:
* ``*_ID``  - the bare id used in ``id=`` compose declarations
* ``*_SEL`` - the CSS selector (``#id``) used in ``query_one`` calls
"""

from widgets.utils.key_aliases import SHIFT_TAB_KEYS, TAB_KEYS

__all__ = [
    "ESC_HINT_BACK",
    "ESC_HINT_CANCEL",
    "ESC_HINT_CLOSE",
    "SHIFT_TAB_KEYS",
    "TAB_KEYS",
]

# Modal dialog container / common widgets
MODAL_DIALOG_ID = "modal-dialog"

MODAL_HINT_ID = "modal-hint"
MODAL_HINT = "#modal-hint"

MODAL_SEARCH_INPUT_ID = "modal-search-input"
MODAL_SEARCH_INPUT = "#modal-search-input"

MODAL_OPTION_LIST_ID = "modal-option-list"
MODAL_OPTION_LIST = "#modal-option-list"

# Modal CSS classes
MODAL_MARKDOWN = "modal-markdown"
MODAL_MARKDOWN_CENTERED = "modal-markdown-centered"

# Esc wording in hints (P2-11).
#
# "cancel" = the screen discards something: text the user typed, or an action
# they started that has side effects (saving a key, renaming, forking a
# session, answering a question). "close" = the screen is a viewer or a
# selector and esc only dismisses it.
ESC_HINT_CLOSE = "esc: close"
ESC_HINT_CANCEL = "esc: cancel"
# "back" = pushed on top of another screen and returns to it.
ESC_HINT_BACK = "esc: back"

# Tool / diff display
TOOL_SCROLL_BOX = "tool-scroll-box"

# Tool call widget header classes
TOOL_HEADER = "tool-header"
TOOL_HEADER_EXPANDABLE = "tool-header-expandable"

# Main app widgets
STATUS_FOOTER = "#status-footer"

MESSAGE_INPUT = "#message-input"

COMMAND_SUGGESTIONS = "#command-suggestions"

# AskUser wizard widgets
OPTIONS_LIST_ID = "options-list"
OPTIONS_LIST = "#options-list"

WRITE_IN_INPUT_ID = "write-in-input"
WRITE_IN_INPUT = "#write-in-input"
