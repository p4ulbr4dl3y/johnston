# Johnston CLI Commands & Flags Reference

## Overview
Johnston CLI provides subcommands for managing configurations, LLM providers, MCP servers, chat sessions, environment diagnostics, and headless execution, alongside the interactive Textual TUI.

## Interactive TUI Launch (`johnston`)
Start the interactive Textual UI application:
- `johnston`: Start interactive Textual UI application.
- `uv run python cli.py`: Run locally from a repository checkout.

### TUI Startup Flags
- `-c`, `--continue`: Resume the most recent conversation session directly without picker.
  ```bash
  johnston -c
  ```
- `--resume [session_id]`: Resume a conversation session by ID (opens interactive picker if ID is omitted).
  ```bash
  johnston --resume
  johnston --resume sess_abc123
  ```
- `-p`, `--prompt <text>`: Initial prompt to post and submit automatically on startup.
  ```bash
  johnston -p "Analyze current git diff and summarize changes"
  ```
- `-m`, `--model <model>`: Override active LLM model.
  ```bash
  johnston -m claude-3-7-sonnet-20250219
  ```
- `-r`, `--role <role>`: Specify initial agent execution role.
  ```bash
  johnston -r planner
  ```
- `--mode {review,edits,yolo}`: Specify initial permission execution mode.
  ```bash
  johnston --mode yolo
  ```
- `--effort {low,medium,high}`: Set thinking / reasoning effort level.
  ```bash
  johnston --effort high
  ```
- `--sandbox` / `--no-sandbox`: Enable or disable shell command execution sandboxing.
  ```bash
  johnston --sandbox
  johnston --no-sandbox
  ```
- `-w`, `--workspace <dir>`: Additional allowed workspace root directory (repeatable for multi-root workspaces).
  ```bash
  johnston -w /path/to/extra/root
  ```
- `-C`, `--cwd <dir>`: Change working directory before running.
  ```bash
  johnston -C /path/to/project
  ```
- `--theme <theme>`: Override active UI theme.
  ```bash
  johnston --theme nord
  ```
- `--debug`: Enable DEBUG logging level in `~/.johnston/logs/johnston.log`.
  ```bash
  johnston --debug
  ```
- `-v`, `--version`: Show application version and exit.
- `-h`, `--help`: Show CLI help and exit.

## Headless Execution (`johnston run`)
Execute an agent turn directly in the terminal without launching the Textual TUI:
- `johnston run "<prompt>"`: Run prompt and stream assistant output to stdout.
- `echo "prompt" | johnston run`: Read prompt from stdin pipe.
- `johnston run -`: Explicitly read prompt from stdin.

### Headless Execution Flags
- `-c`, `--continue`: Continue conversation history from the most recent session.
  ```bash
  johnston run -c "What was the last test we discussed?"
  ```
- `--resume [session_id]`: Resume conversation history from a specific session ID (latest if ID omitted).
  ```bash
  johnston run --resume sess_abc123 "Refactor the authentication middleware"
  ```
- `--effort {low,medium,high}`: Set thinking / reasoning effort level.
  ```bash
  johnston run --effort medium "Explain quantum entanglement in simple terms"
  ```
- `--sandbox` / `--no-sandbox`: Force enable or disable tool execution sandboxing.
  ```bash
  johnston run --sandbox "Run make test and report results"
  ```
- `-C`, `--cwd <dir>`: Change working directory before running.
  ```bash
  johnston run -C /path/to/repo "Check git status"
  ```
- `--debug`: Enable DEBUG level logging during execution.
  ```bash
  johnston run --debug "Diagnose dependencies"
  ```
- `--provider <name>`: Override active provider profile.
  ```bash
  johnston run --provider anthropic "Hello"
  ```
- `--model <model>`: Override active model.
  ```bash
  johnston run --model gpt-4o "Hello"
  ```
- `--role <role>`: Specify agent execution role (default: `worker`).
  ```bash
  johnston run --role planner "Draft implementation plan"
  ```
- `--mode {review,edits,yolo}`: Permission mode (`review`, `edits`, `yolo`).
  ```bash
  johnston run --mode yolo "Run automated test suite"
  ```
- `-y`, `--yolo`: Shortcut for `--mode yolo` (allow all tool actions without confirmation).
  ```bash
  johnston run -y "Install dependencies and run tests"
  ```
- `-w`, `--workspace <dir>`: Additional allowed workspace root directory (repeatable for multi-root workspaces).
  ```bash
  johnston run -w /path/to/extra/root "Analyze code across workspaces"
  ```
- `-s`, `--skill <name>`: Activate skill(s) by name (repeatable).
  ```bash
  johnston run -s refactoring "Clean up models"
  ```
- `--json`: Output final structured JSON payload containing `response`, `tool_calls`, and `usage`.
  ```bash
  johnston run --json "List the top 3 files in src"
  ```
- `--stream-json`: Stream real-time NDJSON events to stdout.
  ```bash
  johnston run --stream-json "Generate implementation plan"
  ```
- `-q`, `--quiet`: Output only assistant response text, suppressing tool call status lines.
  ```bash
  johnston run -q "What is 2 + 2?"
  ```

## Subcommands

### 1. `johnston config` — Application Settings
Inspect and modify settings stored in `~/.johnston/config.json`:
- `johnston config list [--json]`: Show all settings, current values, and sources (default vs config; `--json` for structured output).
- `johnston config get <key> [--json]`: Print setting value (e.g. `llm.context_limit`, `theme`, `sandbox.enabled`; `--json` for structured output).
- `johnston config set <key> <value>`: Validate and update setting value.
- `johnston config unset <key>`: Reset setting to system default.

### 2. `johnston provider` — LLM Providers & Models
Manage provider profiles and API keys in `~/.johnston/providers.json`:
- `johnston provider list [--json]`: Show table of providers, active models, key status, and states (`--json` for structured output).
- `johnston provider set-key <name> [key]`: Set provider API key (secure masked prompt if omitted; reads stdin if `-`).
- `johnston provider set-model <name> <model>`: Set active model for provider.
- `johnston provider add <name> --model <model> [--api-key <k>] [--base-url <u>]`: Register custom provider.
- `johnston provider rm <name>`: Remove custom provider profile.
- `johnston provider enable <name>`: Enable disabled provider.
- `johnston provider disable <name>`: Disable provider.

### 3. `johnston mcp` — Model Context Protocol Servers
Manage MCP server configs in `~/.johnston/mcp.json` (global) or `.johnston/mcp.json` (project):
- `johnston mcp list [--json]`: Show configured servers, scope, status (enabled/disabled), tool counts, and commands (`--json` for structured output).
- `johnston mcp add <name> (--cmd <cmd> | --url <url>) [--args ...] [--scope global|project]`: Add/update MCP server.
- `johnston mcp rm <name> [--scope global|project]`: Remove MCP server definition.
- `johnston mcp enable <name> [--scope global|project]`: Enable MCP server.
- `johnston mcp disable <name> [--scope global|project]`: Disable MCP server.

### 4. `johnston session` — Conversation Sessions
Inspect and manage persisted chat sessions:
- `johnston session list [--limit N] [--all] [--json]`: Show table of sessions (ID, title, message count, updated time; `--all` lists without limit, `--json` for structured output).
- `johnston session rm <id>`: Delete session.
- `johnston session prune [--days N]`: Prune sessions older than N days (default: 14).
- `johnston session export <id> [--format md|json] [--output file]`: Export conversation transcript.

### 5. `johnston doctor` — Diagnostics
- `johnston doctor [--json]`: Run comprehensive health check (`--json` for structured output):
  - Python runtime (3.10+) and `uv` package manager
  - Global and project config directories write access
  - Git repository detection and working tree status
  - LLM providers API keys and local endpoint connectivity
  - MCP servers command/URL validation and tool count checks

### 6. Inspection Commands
- `johnston roles [--json]`: List available agent roles (execution modes and subagent roles; `--json` for structured output).
- `johnston skills [--json]`: List registered global and project skills (`--json` for structured output).
- `johnston rules [--json]`: List active project instructions and rules (`--json` for structured output).

## Session Resume Hint
Upon exiting an active conversation session in TUI mode, Johnston prints:
```text
To resume this session, run:
  johnston --resume <session_id>
```