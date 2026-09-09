"""Default builtin tool sets for Johnston agent roles."""

# Delegation/UI-orchestration tools that are removed from non-interactive (subagent and headless)
# tool sets to prevent nested subagent spawning, background task management, and interactive
# user questions without a UI host.
NON_INTERACTIVE_EXCLUDED_TOOLS = {
    "invoke_subagent",
    "message_subagent",
    "kill",
    "ask_user",
}
SUBAGENT_EXCLUDED_TOOLS = NON_INTERACTIVE_EXCLUDED_TOOLS

