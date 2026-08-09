"""Default johnston-guide skill definitions and modular reference files."""

SKILL_MD = """---
name: johnston-guide
description: Master Johnston system manual and reference. Manages CLI flags, MCP servers, roles, rules, LLM providers, linters, tools, and custom subagent definitions.
---

# Johnston System Guide

You are operating inside Johnston CLI. Use this master guide to understand and configure Johnston's capabilities.

## Master Index & References

When performing specific configuration tasks, inspect ONLY the relevant reference document:

1. **CLI Flags & Startup Options**: [references/cli_flags.md](file://references/cli_flags.md)
   - Command line flags (`--models`, `--skills`, `--mcp`, `--roles`, `--rules`, `--subagents`, `--linters`, `--resume`, `--version`).

2. **MCP Servers**: [references/mcp.md](file://references/mcp.md)
   - Configuration files, JSON schema, stdio commands, registration, and debugging (`johnston --mcp`).

3. **Roles (Execution Modes & Subagents)**: [references/roles.md](file://references/roles.md)
   - Unified role definitions for execution modes and subagents (`~/.johnston/roles/` or `.johnston/roles/`, `johnston --roles`).

4. **Rules & Project Guidelines**: [references/rules.md](file://references/rules.md)
   - Global rules (`~/.johnston/rules/`), project rules (`.johnston/rules/`), mode filtering, and `AGENTS.md` integration (`johnston --rules`).

5. **LLM Providers & Keys**: [references/providers.md](file://references/providers.md)
   - Provider settings (`~/.johnston/providers.json`), API keys, base URLs, and model aliases (`johnston --models`).

6. **Linters & Syntax Guards**: [references/linters.md](file://references/linters.md)
   - Syntax linters (`~/.johnston/linters.json`), presets (ruff, eslint, biome, rustc), auto-scan, and verification (`johnston --linters`).

7. **Custom & Builtin Tools**: [references/tools.md](file://references/tools.md)
   - Builtin tool execution, shell permissions, and adding custom tools.

## Token Optimization & Execution Rules

1. **Selective Reading Only**: DO NOT load or view all `references/*.md` files at once.
2. **On-Demand Inspection**: Inspect ONLY the single `references/<topic>.md` file directly required for the current user task.
"""

CLI_FLAGS_MD = """# Johnston CLI Flags & Commands Reference

## Key CLI Commands & Startup Flags

- `johnston`: Start interactive Textual UI application (entry point `cli:main`).
- `uv run python cli.py`: Run locally from a checkout.
- `johnston --models`: List available providers and configured models.
- `johnston --skills`: List registered global and project skills.
- `johnston --mcp`: List configured Model Context Protocol (MCP) servers and tool status.
- `johnston --roles`: List available agent roles (execution modes + subagents).
- `johnston --rules`: Display active rules and project instructions (`AGENTS.md`, `CLAUDE.md`, `.johnston/rules/`).
- `johnston --subagents`: List available subagent roles (builtin + custom).
- `johnston --linters`: List configured linters and their availability (`ruff`, `eslint`, `rustc`, etc.).
- `johnston --resume <session_id>`: Resume a previous conversation session.
- `johnston -v` / `johnston --version`: Show Johnston application version.
"""

MCP_MD = """# MCP (Model Context Protocol) Server Configuration Reference

## Locations
- Global config: `~/.johnston/mcp.json`
- Project config: `.johnston/mcp.json`

## Config Format
```json
{
  "mcpServers": {
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": {},
      "disabled": false,
      "mode": "eager"
    }
  }
}
```

## Verification
- Run `johnston --mcp` via shell tool to verify server registration and readiness.
"""

ROLES_MD = """# Roles Reference (Execution Modes & Subagents)

## Locations
- Global roles: `~/.johnston/roles/<name>.md`
- Project roles: `.johnston/roles/<name>.md`

## Frontmatter Format
```markdown
---
name: reviewer
description: Code reviewer subagent
scope: subagent_only
tools: read, grep, glob
model: deepseek-v4-flash
---

System prompt instructions for the role...
```

## Scope
- `any` (default): available as both execution mode and subagent type.
- `subagent_only`: usable only as `subagent_type` in `invoke_subagent`.
- `main_only`: usable only as main agent execution mode (not a subagent).

## Frontmatter Fields
- `name`: Role identifier (defaults to filename).
- `description`: Summary of purpose.
- `scope`: `any`, `subagent_only`, or `main_only`.
- `tools` / `allowed_tools`: Comma-separated whitelist of permitted tool names.
- `disallowed_tools`: Comma-separated list of blocked tool names.
- `read_only`: Boolean flag blocking state-changing operations.
- `model`: Specific LLM model override (subagents).

## Tool Isolation & Worktree Modes
Subagents can be invoked via `invoke_subagent` tool with:
- `workspace='branch'`: Spawns subagent in an isolated Git worktree.
- `workspace='inherit'`: Shares current working directory.
"""

RULES_MD = """# Rules & Directives Reference

## Locations
- Global rules: `~/.johnston/rules/<name>.md`
- Project rules: `.johnston/rules/<name>.md`
- Repository rules: `AGENTS.md`, `CLAUDE.md`, `.cursorrules` in repository root.

## Frontmatter Format
```markdown
---
name: python_style
mode: act, explore
globs: "*.py"
---
Rule instructions here...
```
"""

PROVIDERS_MD = """# LLM Providers Configuration Reference

## Location
- Global provider config: `~/.johnston/providers.json`

## Supported API Types
- `openai` (OpenAI, OpenRouter, Groq, xAI, DeepSeek, custom OpenAI-compatible endpoints)
- `anthropic` (Anthropic Claude API)
- `gemini` (Google Gemini REST API)
- `ollama` (local Ollama)

## API Keys
- Keys are stored in `~/.johnston/config.json` under `api_keys` (managed via `johnston --models`), not in environment variables.
"""


LINTERS_MD = """# Linters & Syntax Guards Reference

## Location
- Global linter config: `~/.johnston/linters.json`

## Presets Supported
- Python (`ruff`), JS/TS (`eslint`, `biome`), Rust (`rustc`), C/C++ (`gcc`), Ruby, PHP, JSON (`jq`), YAML (`yamllint`), TOML (`taplo`).

## Format
```json
{
  "linters": {
    "python": {
      "cmd": ["ruff", "check", "--select", "E9,F", "{file}"],
      "extensions": [".py"],
      "enabled": true
    }
  }
}
```

## Verification
- Run `johnston --linters` via shell tool to verify configured linters and system availability.
"""

TOOLS_MD = """# Johnston Tools Reference

## Builtin Tools
- `read`, `create`, `edit`, `multi_edit`, `shell`, `ask_user`
- `call_mcp`, `invoke_subagent`, `manage_subagent`, `manage_task`, `update_plan`, `web_fetch`
- Common aliases: `write_file` → `create`, `replace_file_content` → `edit`, `terminal`/`bash` → `shell`, `fetch` → `web_fetch`.

## Permissions
- Global permissions stored in `~/.johnston/config.json` (`permissions` section); project overrides in `.johnston/permissions.json`.
- Shell command guard validates safety of commands run via `shell` tool.
"""

JOHNSTON_GUIDE_FILES = {
    "SKILL.md": SKILL_MD,
    "references/cli_flags.md": CLI_FLAGS_MD,
    "references/mcp.md": MCP_MD,
    "references/roles.md": ROLES_MD,
    "references/rules.md": RULES_MD,
    "references/providers.md": PROVIDERS_MD,
    "references/linters.md": LINTERS_MD,
    "references/tools.md": TOOLS_MD,
}
