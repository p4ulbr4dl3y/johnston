# Johnston CLI Commands & Flags Reference

## Overview
Johnston CLI provides subcommands for managing configurations, LLM providers, MCP servers, chat sessions, environment diagnostics, and headless execution, alongside the interactive Textual TUI.

## Interactive TUI Launch
- `johnston`: Start interactive Textual UI application (entry point `cli:main`).
- `uv run python cli.py`: Run locally from a repository checkout.
- `johnston --resume [session_id]`: Resume previous conversation session (interactive picker if ID omitted).

## Subcommands

### 1. `johnston config` — Application Settings
Inspect and modify settings stored in `~/.johnston/config.json`:
- `johnston config list`: Show all settings, current values, and sources (default vs config).
- `johnston config get <key>`: Print setting value (e.g. `llm.context_limit`, `theme`, `sandbox.enabled`).
- `johnston config set <key> <value>`: Validate and update setting value.
- `johnston config unset <key>`: Reset setting to system default.

### 2. `johnston provider` — LLM Providers & Models
Manage provider profiles and API keys in `~/.johnston/providers.json`:
- `johnston provider list`: Show table of providers, active models, key status, and states.
- `johnston provider set-key <name> [key]`: Set provider API key (secure masked prompt if omitted; reads stdin if `-`).
- `johnston provider set-model <name> <model>`: Set active model for provider.
- `johnston provider add <name> --model <model> [--api-key <k>] [--base-url <u>]`: Register custom provider.
- `johnston provider rm <name>`: Remove custom provider profile.
- `johnston provider enable <name>`: Enable disabled provider.
- `johnston provider disable <name>`: Disable provider.

### 3. `johnston mcp` — Model Context Protocol Servers
Manage MCP server configs in `~/.johnston/mcp.json` (global) or `.johnston/mcp.json` (project):
- `johnston mcp list`: Show configured servers, scope, status (enabled/disabled), tool counts, and commands.
- `johnston mcp add <name> (--cmd <cmd> | --url <url>) [--args ...] [--scope global|project]`: Add/update MCP server.
- `johnston mcp rm <name> [--scope global|project]`: Remove MCP server definition.
- `johnston mcp enable <name> [--scope global|project]`: Enable MCP server.
- `johnston mcp disable <name> [--scope global|project]`: Disable MCP server.

### 4. `johnston session` — Conversation Sessions
Inspect and manage persisted chat sessions:
- `johnston session list [--limit N]`: Show table of recent sessions (ID, title, message count, updated time).
- `johnston session rm <id>`: Delete session.
- `johnston session prune [--days N]`: Prune sessions older than N days (default: 14).
- `johnston session export <id> [--format md|json] [--output file]`: Export conversation transcript.

### 5. `johnston doctor` — Diagnostics
- `johnston doctor`: Run comprehensive health check:
  - Python runtime (3.10+) and `uv` package manager
  - Global and project config directories write access
  - Git repository detection and working tree status
  - LLM providers API keys and local endpoint connectivity
  - MCP servers command/URL validation and tool count checks

### 6. `johnston run` — Headless / One-shot Execution
Execute agent turn directly in terminal without Textual TUI:
- `johnston run "<prompt>"`: Run prompt and stream assistant output to stdout.
- `echo "prompt" | johnston run`: Read prompt from stdin pipe.
- Flags:
  - `--provider <name>`: Override active provider.
  - `--model <model>`: Override active model.
  - `--role <role>`: Specify agent execution role (default: `worker`).
  - `--json`: Output final structured JSON payload (`response`, `tool_calls`, `usage`).
  - `-q`, `--quiet`: Output only assistant text, suppressing tool call status headers.

### 7. Inspection Commands
- `johnston roles`: List available agent roles (execution modes and subagent roles).
- `johnston skills`: List registered global and project skills.
- `johnston rules`: List active project instructions and rules.

## Backward-Compatible Legacy Flags
- `johnston -v` / `johnston --version`: Show application version.
- `johnston --models`: Alias for `johnston provider list`.
- `johnston --skills`: Alias for `johnston skills`.
- `johnston --mcp`: Alias for `johnston mcp list`.
- `johnston --roles`: Alias for `johnston roles`.
- `johnston --rules`: Alias for `johnston rules`.

## Session Resume Hint
Upon exiting an active conversation session in TUI mode, Johnston prints:
```text
To resume this session, run:
  johnston --resume <session_id>
```