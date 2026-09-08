from widgets.utils.responsive import BREAKPOINT_BANNER, BREAKPOINT_COMPACT

DEFAULT_PLACEHOLDER = "Type a message (? help, / cmds)..."
COMPACT_PLACEHOLDER = "Type message (? help, / cmds)..."
NARROW_PLACEHOLDER = "Type a message..."
FORK_PLACEHOLDER = "Type a message to fork & continue..."

DEFAULT_SHELL_PLACEHOLDER = "! git status, pytest (esc to exit)..."
COMPACT_SHELL_PLACEHOLDER = "! command (esc to exit)..."
NARROW_SHELL_PLACEHOLDER = "! (esc to exit)..."


def get_placeholder_for_width(width: int) -> str:
    """Return responsive placeholder text based on width."""
    if width < BREAKPOINT_BANNER:
        return NARROW_PLACEHOLDER
    if width < BREAKPOINT_COMPACT:
        return COMPACT_PLACEHOLDER
    return DEFAULT_PLACEHOLDER


def get_shell_placeholder_for_width(width: int) -> str:
    """Return responsive shell mode placeholder text based on width."""
    if width < BREAKPOINT_BANNER:
        return NARROW_SHELL_PLACEHOLDER
    if width < BREAKPOINT_COMPACT:
        return COMPACT_SHELL_PLACEHOLDER
    return DEFAULT_SHELL_PLACEHOLDER
