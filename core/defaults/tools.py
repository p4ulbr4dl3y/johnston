"""Default builtin tool sets for Johnston agent roles."""

# Tools that mutate state; disabled in read-only roles.
WRITE_TOOLS = {"create", "edit", "multi_edit"}
