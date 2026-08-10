"""Shared DOM id/class string constants for widgets and screens.

Centralises selectors and CSS class names that are referenced in multiple
places so they stay consistent and easy to rename.

Each widget id has two forms:
* ``*_ID``  - the bare id used in ``id=`` compose declarations
* ``*_SEL`` - the CSS selector (``#id``) used in ``query_one`` calls
"""

# Modal dialog container / common widgets
MODAL_DIALOG_ID = "modal-dialog"
MODAL_DIALOG_SEL = "#modal-dialog"
MODAL_DIALOG = MODAL_DIALOG_SEL

MODAL_HINT_ID = "modal-hint"
MODAL_HINT_SEL = "#modal-hint"
MODAL_HINT = MODAL_HINT_SEL

MODAL_SEARCH_INPUT_ID = "modal-search-input"
MODAL_SEARCH_INPUT_SEL = "#modal-search-input"
MODAL_SEARCH_INPUT = MODAL_SEARCH_INPUT_SEL

MODAL_OPTION_LIST_ID = "modal-option-list"
MODAL_OPTION_LIST_SEL = "#modal-option-list"
MODAL_OPTION_LIST = MODAL_OPTION_LIST_SEL

# Modal CSS classes
MODAL_MARKDOWN = "modal-markdown"
MODAL_MARKDOWN_CENTERED = "modal-markdown-centered"

# Tool / diff display
TOOL_SCROLL_BOX = "tool-scroll-box"
MODAL_DIFF_VIEW = "modal-diff-view"

# Tool call widget header classes
TOOL_HEADER = "tool-header"
TOOL_HEADER_EXPANDABLE = "tool-header-expandable"

# Shift+Tab key aliases (used to dismiss/escape modal focus)
SHIFT_TAB_KEYS = ("shift+tab", "backtab", "shift_tab")

# Main app widgets
STATUS_FOOTER_ID = "status-footer"
STATUS_FOOTER_SEL = "#status-footer"
STATUS_FOOTER = STATUS_FOOTER_SEL

MESSAGE_INPUT_ID = "message-input"
MESSAGE_INPUT_SEL = "#message-input"
MESSAGE_INPUT = MESSAGE_INPUT_SEL

COMMAND_SUGGESTIONS_ID = "command-suggestions"
COMMAND_SUGGESTIONS_SEL = "#command-suggestions"
COMMAND_SUGGESTIONS = COMMAND_SUGGESTIONS_SEL

# AskUser wizard widgets
OPTIONS_LIST_ID = "options-list"
OPTIONS_LIST_SEL = "#options-list"
OPTIONS_LIST = OPTIONS_LIST_SEL

WRITE_IN_INPUT_ID = "write-in-input"
WRITE_IN_INPUT_SEL = "#write-in-input"
WRITE_IN_INPUT = WRITE_IN_INPUT_SEL
