"""Default johnston-guide skill definitions and modular reference files."""

SKILL_MD = """---
name: johnston-guide
description: Master Johnston system manual and reference. Manages CLI flags, MCP servers, subagent definitions, rules, LLM providers, linters, execution modes, tools, and custom execution modes.
---

# Johnston System Guide

You are operating inside Johnston CLI. Use this master guide to understand and configure Johnston's capabilities.

## Master Index & References

When performing specific configuration tasks, inspect ONLY the relevant reference document:

1. **CLI Flags & Startup Options**: [references/cli_flags.md](file://references/cli_flags.md)
   - Command line flags (`--models`, `--skills`, `--mcp`, `--modes`, `--rules`, `--subagents`, `--linters`, `--resume`, `--version`).

2. **MCP Servers**: [references/mcp.md](file://references/mcp.md)
   - Configuration files, JSON schema, stdio commands, registration, and debugging (`johnston --mcp`).

3. **Custom Subagent Definitions**: [references/subagents.md](file://references/subagents.md)
   - Creating custom subagents (`~/.johnston/subagents/definitions/` or `.johnston/subagents/`), frontmatter schema, roles, and tool restrictions (`johnston --subagents`).

4. **Rules & Project Guidelines**: [references/rules.md](file://references/rules.md)
   - Global rules (`~/.johnston/rules/`), project rules (`.johnston/rules/`), mode filtering, and `AGENTS.md` integration (`johnston --rules`).

5. **LLM Providers & Keys**: [references/providers.md](file://references/providers.md)
   - Provider settings (`~/.johnston/providers.json`), API keys, base URLs, and model aliases (`johnston --models`).

6. **Execution Modes**: [references/modes.md](file://references/modes.md)
   - Read-only, architect, and custom agent execution modes (`~/.johnston/modes/` or `.johnston/modes/`, `johnston --modes`).

7. **Linters & Syntax Guards**: [references/linters.md](file://references/linters.md)
   - Syntax linters (`~/.johnston/linters.json`), presets (ruff, eslint, biome, rustc), auto-scan, and verification (`johnston --linters`).

8. **Custom & Builtin Tools**: [references/tools.md](file://references/tools.md)
   - Builtin tool execution, shell permissions, and adding custom tools.

## Token Optimization & Execution Rules

1. **Selective Reading Only**: DO NOT load or view all `references/*.md` files at once.
2. **On-Demand Inspection**: Inspect ONLY the single `references/<topic>.md` file directly required for the current user task.
"""

CLI_FLAGS_MD = """# Johnston CLI Flags & Commands Reference

## Key CLI Commands & Startup Flags

- `johnston` / `johnston cli`: Start interactive Textual UI application.
- `johnston --models`: List available providers and configured models.
- `johnston --skills`: List registered global and project skills.
- `johnston --mcp`: List configured Model Context Protocol (MCP) servers and tool status.
- `johnston --modes`: List available agent execution modes.
- `johnston --rules`: Display active rules and project instructions (`AGENTS.md`, `CLAUDE.md`, `.johnston/rules/`).
- `johnston --subagents`: List available subagent definitions (builtin + custom).
- `johnston --linters`: List configured linters and their availability (`ruff`, `eslint`, `rustc`, etc.).
- `johnston --resume <session_id>`: Resume a previous conversation session.
- `johnston -v` / `johnston --version`: Show Johnston application version.

## Environment Variables
- `JOHNSTON_CONFIG_DIR`: Override global config root (default: `~/.johnston`).
- `JOHNSTON_MODEL`: Pre-select model alias on launch.
- `JOHNSTON_EFFORT`: Pre-select thinking effort mode (`auto`, `low`, `medium`, `high`).
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

SUBAGENTS_MD = """# Subagent Configuration & Creation Reference

## Locations
- Global definitions: `~/.johnston/subagents/definitions/<name>.md`
- Project definitions: `.johnston/subagents/<name>.md`

## Frontmatter Format
```markdown
---
name: reviewer
description: Code reviewer subagent
tools: read, grep, glob
model: deepseek-v4-flash
---

System prompt instructions for the subagent...
```

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
mode: action, explore
globs: "*.py"
---
Rule instructions here...
```
"""

PROVIDERS_MD = """# LLM Providers Configuration Reference

## Location
- Global provider config: `~/.johnston/providers.json`

## Supported API Types
- `openai` (OpenAI, OpenRouter, Groq, xAI, DeepSeek, LocalAI/Ollama)
- `anthropic` (Anthropic Claude API)
- `gemini` (Google Gemini REST API)

## Environment Keys
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`
"""

MODES_MD = """# Agent Execution Modes Reference

## Locations
- Global modes: `~/.johnston/modes/<name>.md`
- Project modes: `.johnston/modes/<name>.md`

## Format
```markdown
---
name: Architect
description: High-level design mode
read_only: true
disallowed_tools: create, edit
---
Custom system prompt here...
```

## Verification
- Run `johnston --modes` via shell tool to verify active modes.
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
- `read`, `edit`, `multi_edit`, `write_file`, `grep`, `glob`, `find`, `shell`
- `invoke_subagent`, `send_message`, `ask_user`, `update_plan`

## Permissions
- Permissions defined in `~/.johnston/permissions.json` and `.johnston/permissions.json`.
- Shell command guard validates safety of commands run via `shell` tool.
"""

JOHNSTON_GUIDE_FILES = {
    "SKILL.md": SKILL_MD,
    "references/cli_flags.md": CLI_FLAGS_MD,
    "references/mcp.md": MCP_MD,
    "references/subagents.md": SUBAGENTS_MD,
    "references/rules.md": RULES_MD,
    "references/providers.md": PROVIDERS_MD,
    "references/modes.md": MODES_MD,
    "references/linters.md": LINTERS_MD,
    "references/tools.md": TOOLS_MD,
}
