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
  "model": "openai/gpt-4o",
  "theme": "github-dark",
  "sandbox_enabled": false,
  "provider_thinking_efforts": {
    "anthropic/claude-3-7-sonnet-latest": "medium"
  },
  "disabled_providers": [],
  "permissions": {
    "mode": "review",
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
  "llm": {
    "compaction_threshold_ratio": 0.75,
    "compaction_user_budget": 20000,
    "stream_timeout": 60.0,
    "chunk_timeout": 30.0,
    "max_retries": 3,
    "retry_delay": 1.0,
    "cb_failure_threshold": 3,
    "cb_cooldown_seconds": 30.0
  },
  "tools": {
    "shell_default_timeout": 120.0,
    "shell_max_cap": 600.0,
    "shell_output_chars": 4000,
    "max_tool_output_chars": 8000,
    "max_tool_payload_bytes": 10485760,
    "mcp_call_timeout": 120.0,
    "mcp_init_timeout": 5.0,
    "web_fetch_timeout": 20.0
  },
  "subagents": {
    "max_concurrent": 5,
    "result_max_chars": 15000,
    "worktree_timeout": 15.0
  },
  "ui": {
    "max_prompt_history": 500,
    "stream_flush_interval": 0.05,
    "chat_page_size": 50
  },
  "storage": {
    "log_max_bytes": 5242880,
    "log_max_age_days": 7,
    "disk_cache_ttl": 2.0
  }
}
```

## Environment Variable Overrides
All section parameters can be overridden at runtime via environment variables:
- `JOHNSTON_MAX_CONCURRENT_SUBAGENTS`: Concurrency cap for background subagents.
- `JOHNSTON_STREAM_TIMEOUT` / `JOHNSTON_CHUNK_TIMEOUT`: HTTP streaming timeouts.
- `JOHNSTON_MAX_RETRIES` / `JOHNSTON_RETRY_DELAY`: LLM provider retry policy.
- `JOHNSTON_SHELL_TIMEOUT` / `JOHNSTON_SHELL_MAX_CAP`: Shell command timeouts.
- `JOHNSTON_SHELL_OUTPUT_CHARS` / `JOHNSTON_MAX_TOOL_OUTPUT_CHARS`: Output truncation caps.
- `JOHNSTON_SANDBOX_ENABLED`: Enable/disable OS-level process sandboxing (`true`/`false`).

## Security & Sandbox Policy
- **Sandbox Mode**: When enabled, enforces strict filesystem and network boundaries, preventing unauthorized mutations and blocking access to sensitive config files (`secrets.json`, `config.json`).
- **Read-Only Roles**: The `explorer` role and roles marked `read_only: true` disable `create` and `edit` tools and restrict `shell` execution to safe read-only commands.
- **Permission Modes**: Each tool action can be set to `allow` (auto-execute), `ask` (prompt user for confirmation), or `deny` (block execution).
