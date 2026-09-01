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
Credential resolution precedence (`get_secret`):
1. Exact match in `~/.johnston/secrets.json`
2. Exact match in environment variables (`os.environ`)
3. Normalized variations (`<KEY>_API_KEY`, `<KEY>`, `<KEY>_TOKEN`) in `secrets.json`
4. Normalized variations in `os.environ`

## App Settings Schema (`~/.johnston/config.json`)
> **Note**: `model` (`"provider/model"` or `"provider"`) is the single source of truth for active provider and model. The legacy key `active_provider` is not used.

```json
{
  "model": "openai/gpt-4o",
  "theme": "github-dark",
  "sandbox": {
    "enabled": false
  },
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
    "context_limit": 128000,
    "compaction_threshold_ratio": 0.75,
    "compaction_summarize_ratio": 0.90,
    "compaction_user_budget": 20000,
    "stream_timeout": 60.0,
    "chunk_timeout": 30.0,
    "default_max_tokens": 32768,
    "max_retries": 3,
    "retry_delay": 1.0,
    "retry_backoff": 2.0,
    "max_retry_delay": 10.0,
    "cb_failure_threshold": 3,
    "cb_cooldown_seconds": 30.0,
    "auto_title": false,
    "auto_title_timeout": 15.0,
    "auto_title_max_len": 100,
    "auto_title_model": null,
    "catalog_cache_ttl": 86400.0,
    "agent_md_max_chars": 20000,
    "thinking_efforts": {
      "anthropic": {
        "claude-3-7-sonnet-latest": "medium"
      }
    }
  },
  "tools": {
    "shell_default_timeout": 120.0,
    "shell_max_cap": 600.0,
    "max_shell_output_chars": 4000,
    "max_tool_output_chars": 8000,
    "max_tool_payload_bytes": 10485760,
    "max_snapshot_log_bytes": 52428800,
    "shell_stream_buffer_bytes": 204800,
    "mcp_call_timeout": 120.0,
    "mcp_init_timeout": 5.0,
    "mcp_miss_ttl": 30.0,
    "mcp_miss_max": 512,
    "web_fetch_timeout": 20.0,
    "web_user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Johnston/0.1",
    "dns_cache_ttl": 60.0,
    "dns_cache_max": 512,
    "read_line_window": 800,
    "max_dir_entries": 60,
    "doc_conversion_timeout": 30.0,
    "max_image_dimension": 1568,
    "image_dimension_low": 512,
    "image_dimension_high": 2048,
    "image_png_keep_bytes": 1048576,
    "max_doc_cache": 50,
    "doc_cache_ttl": 600.0,
    "line_count_cache_max": 500
  },
  "subagents": {
    "max_concurrent": 5,
    "max_result_chars": 15000,
    "worktree_timeout": 15.0
  },
  "ui": {
    "max_prompt_history": 500,
    "max_chat_input_lines": 6,
    "stream_flush_interval": 0.05,
    "chat_page_size": 50,
    "paste_line_threshold": 10,
    "autocomplete_max_files": 1000
  },
  "storage": {
    "max_log_bytes": 5242880,
    "max_log_age_days": 7,
    "disk_cache_ttl": 2.0
  }
}
```

## Environment Variable Overrides (`JOHNSTON_*`)
Parameters can be overridden via environment variables:
- **LLM**: `JOHNSTON_CONTEXT_LIMIT`, `JOHNSTON_COMPACTION_RATIO`, `JOHNSTON_COMPACTION_SUMMARIZE_RATIO`, `JOHNSTON_COMPACTION_USER_BUDGET`, `JOHNSTON_STREAM_TIMEOUT`, `JOHNSTON_CHUNK_TIMEOUT`, `JOHNSTON_MAX_TOKENS`, `JOHNSTON_MAX_RETRIES`, `JOHNSTON_RETRY_DELAY`, `JOHNSTON_RETRY_BACKOFF`, `JOHNSTON_MAX_RETRY_DELAY`, `JOHNSTON_CB_THRESHOLD`, `JOHNSTON_CB_COOLDOWN`, `JOHNSTON_AUTO_TITLE`, `JOHNSTON_AUTO_TITLE_TIMEOUT`, `JOHNSTON_AUTO_TITLE_MAX_LEN`, `JOHNSTON_AUTO_TITLE_MODEL`, `JOHNSTON_CATALOG_CACHE_TTL`, `JOHNSTON_AGENT_MD_MAX_CHARS`.
- **Tools**: `JOHNSTON_SHELL_TIMEOUT`, `JOHNSTON_SHELL_MAX_CAP`, `JOHNSTON_SHELL_OUTPUT_CHARS`, `JOHNSTON_MAX_TOOL_OUTPUT_CHARS`, `JOHNSTON_MAX_TOOL_PAYLOAD_BYTES`, `JOHNSTON_MAX_SNAPSHOT_LOG_BYTES`, `JOHNSTON_MCP_CALL_TIMEOUT`, `JOHNSTON_MCP_INIT_TIMEOUT`, `JOHNSTON_WEB_FETCH_TIMEOUT`, `JOHNSTON_READ_LINE_WINDOW`, `JOHNSTON_MAX_DIR_ENTRIES`, `JOHNSTON_DOC_CONVERSION_TIMEOUT`, `JOHNSTON_IMAGE_MAX_DIMENSION`, `JOHNSTON_IMAGE_DIMENSION_LOW`, `JOHNSTON_IMAGE_DIMENSION_HIGH`, `JOHNSTON_IMAGE_PNG_KEEP_BYTES`, `JOHNSTON_MAX_DOC_CACHE`, `JOHNSTON_DOC_CACHE_TTL`, `JOHNSTON_LINE_COUNT_CACHE_MAX`, `JOHNSTON_DNS_CACHE_TTL`, `JOHNSTON_DNS_CACHE_MAX`, `JOHNSTON_MCP_MISS_TTL`, `JOHNSTON_MCP_MISS_MAX`, `JOHNSTON_SHELL_STREAM_BUFFER_BYTES`, `JOHNSTON_WEB_USER_AGENT`.
- **Subagents**: `JOHNSTON_MAX_CONCURRENT_SUBAGENTS`, `JOHNSTON_SUBAGENT_RESULT_MAX_CHARS`, `JOHNSTON_SUBAGENT_WORKTREE_TIMEOUT`.
- **UI**: `JOHNSTON_MAX_PROMPT_HISTORY`, `JOHNSTON_CHAT_INPUT_MAX_LINES`, `JOHNSTON_STREAM_FLUSH_INTERVAL`, `JOHNSTON_CHAT_PAGE_SIZE`, `JOHNSTON_PASTE_LINE_THRESHOLD`, `JOHNSTON_AUTOCOMPLETE_MAX_FILES`.
- **Storage & Security**: `JOHNSTON_LOG_MAX_BYTES`, `JOHNSTON_LOG_MAX_AGE_DAYS`, `JOHNSTON_DISK_CACHE_TTL`, `JOHNSTON_SANDBOX_ENABLED`.

## Security, Sandbox & Execution Modes
- **Sandbox Mode**: When enabled (`sandbox.enabled: true` or `JOHNSTON_SANDBOX_ENABLED=true`), enforces strict OS-level filesystem/network sandbox boundaries. Blocks write access to `secrets.json` and `config.json`.
- **Execution Modes (`permissions.mode`)**:
  - `review`: Prompts for confirmation on `create`, `edit`, `shell`, `mcp` tools.
  - `edits`: Auto-allows `create`/`edit`, prompts for `shell`/`mcp`.
  - `yolo`: Auto-allows all standard tool executions.
- **Permission Actions**: `allow` (auto-execute), `ask` (prompt user), `deny` (block execution).
- **Read-Only Roles**: The `explorer` role enforces kernel sandbox. Roles with `read_only: true` disable `create` and `edit` tools.
