"""Default builtin tool sets for Johnston agent roles."""

# Tools that mutate state; disabled in read-only roles.
WRITE_TOOLS = {"create", "edit", "multi_edit"}

# Delegation/UI-orchestration tools that are removed from subagent tool sets to
# prevent nested subagent spawning, background task management, and interactive
# user questions from inside a subagent.
SUBAGENT_EXCLUDED_TOOLS = {"invoke_subagent", "manage_subagent", "manage_shell", "ask_user"}
