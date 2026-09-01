# Johnston CLI Flags & Commands Reference

## Key CLI Commands & Startup Flags

- `johnston`: Start interactive Textual UI application (entry point `cli:main`).
- `uv run python cli.py`: Run locally from a checkout.
- `johnston --models`: List available providers and configured models.
- `johnston --skills`: List registered global and project skills.
- `johnston --mcp`: List configured Model Context Protocol (MCP) servers and tool status.
- `johnston --roles`: List available agent roles (execution modes + subagents).
- `johnston --rules`: Display active rules and project instructions (`AGENTS.md`, `CLAUDE.md`, `.johnston/rules/`).
- `johnston --resume <session_id>`: Resume a previous conversation session directly by ID.
- `johnston -v` / `johnston --version`: Show Johnston application version.

## Session Resume Hint
Upon exiting an active conversation session, Johnston prints a resume command hint to stdout:
```
To resume this session, run:
  johnston --resume <session_id>
```