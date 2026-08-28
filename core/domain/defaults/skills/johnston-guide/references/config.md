# Configuration & Security Reference

## Overview
Johnston separates application settings, provider profiles, secrets, and project configurations across dedicated files.

## Configuration Files & Locations
- App Settings: `~/.johnston/config.json` (blocked from agent modification in sandbox mode)
- Centralized Secrets: `~/.johnston/secrets.json` (blocked from agent modification in sandbox mode)
- LLM Provider Profiles: `~/.johnston/providers.json`
- MCP Server Configs: `~/.johnston/mcp.json` (global) and `.johnston/mcp.json` (project)
- Roles: `~/.johnston/roles/*.md` (global) and `.johnston/roles/*.md` (project)
- Rules: `~/.johnston/rules/*.md` (global) and `.johnston/rules/*.md` (project)
- Skills: `~/.johnston/skills/<name>/` (global) and `.johnston/skills/<name>/` (project)

## Secrets Management (`~/.johnston/secrets.json`)
Store sensitive API keys, auth tokens, and credentials outside project repositories:
```json
{
  "OPENAI_API_KEY": "sk-...",
  "ANTHROPIC_API_KEY": "sk-ant-...",
  "GITHUB_TOKEN": "ghp_..."
}
```
Credential resolution precedence:
1. Environment variables (`os.environ`)
2. `~/.johnston/secrets.json`
3. Provider default key convention (`<PROVIDER>_API_KEY`)

## App Settings Schema (`~/.johnston/config.json`)
```json
{
  "active_provider": "openai",
  "provider_models": {
    "openai": "gpt-4o",
    "anthropic": "claude-3-7-sonnet-latest"
  },
  "provider_thinking_efforts": {
    "anthropic/claude-3-7-sonnet-latest": "medium"
  },
  "disabled_providers": [],
  "permissions": {
    "default": "allow",
    "tools": {
      "shell": "ask",
      "create": "allow",
      "edit": "allow"
    },
    "patterns": {
      "rm -rf *": "deny"
    }
  },
  "sandbox": {
    "enabled": false
  }
}
```

## Security & Sandbox Policy
- **Sandbox Mode**: When enabled, enforces strict filesystem and network boundaries, preventing unauthorized mutations and blocking access to sensitive config files (`secrets.json`, `config.json`).
- **Read-Only Roles**: The `explorer` role and roles marked `read_only: true` disable `create` and `edit` tools and restrict `shell` execution to safe read-only commands.
- **Permission Modes**: Each tool action can be set to `allow` (auto-execute), `ask` (prompt user for confirmation), or `deny` (block execution).
