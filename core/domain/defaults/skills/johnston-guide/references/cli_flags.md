# Johnston CLI Flags & Commands Reference

## Key CLI Commands & Startup Flags

- `johnston`: Start interactive Textual UI application (entry point `cli:main`).
- `uv run python cli.py`: Run locally from a checkout.
- `johnston --models`: List available providers and configured models.
- `johnston --skills`: List registered global and project skills.
- `johnston --mcp`: List configured Model Context Protocol (MCP) servers and tool status.
- `johnston --roles`: List available agent roles (execution modes + subagents).
- `johnston --rules`: Display active rules and project instructions (`AGENTS.md`, `CLAUDE.md`, `.johnston/rules/`).
- `johnston --resume <session_id>`: Resume a previous conversation session.
- `johnston -v` / `johnston --version`: Show Johnston application version.