"""Default agent execution constants and configuration values for Johnston."""

# Agent Execution Limits & Timeouts
DEFAULT_CONTEXT_LIMIT = 128000
CONTEXT_COMPACTION_THRESHOLD_RATIO = 0.75
MAX_CONCURRENT_SUBAGENTS = 5

# Theme Palette Constants (Monochrome Slate)
THEME_PRIMARY = "#ffffff"
THEME_SECONDARY = "#f4f4f5"
THEME_MUTED = "#71717a"
THEME_SUBTLE = "#e4e4e7"

# Permissions Defaults
DEFAULT_PERMISSIONS = {
    "default": "allow",
    "tools": {
        "create": "ask",
        "edit": "ask",
        "multi_edit": "ask",
        "shell": "ask",
    },
}
