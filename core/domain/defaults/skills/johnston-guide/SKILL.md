---
name: johnston-guide
description: Master Johnston system manual and reference. Manages CLI flags, MCP servers, roles, rules, skills, LLM providers, config, tools, and slash commands.
---

# Johnston System Guide

You are operating inside Johnston CLI. Use this master guide to understand and configure Johnston's capabilities.

## Master Index & References

When performing specific configuration tasks, inspect ONLY the relevant reference document:

1. **CLI Flags & Startup Options**: [references/cli_flags.md](references/cli_flags.md)
   - Command line flags (`--models`, `--skills`, `--mcp`, `--roles`, `--rules`, `--resume`, `--version`).

2. **MCP Servers**: [references/mcp.md](references/mcp.md)
   - Configuration files, JSON schema, stdio commands, registration, and debugging (`johnston --mcp`).

3. **Roles (Execution Modes & Subagents)**: [references/roles.md](references/roles.md)
   - Unified role definitions for execution modes and subagents (`~/.johnston/roles/` or `.johnston/roles/`, `johnston --roles`).

4. **Rules & Project Guidelines**: [references/rules.md](references/rules.md)
   - Global rules (`~/.johnston/rules/`), project rules (`.johnston/rules/`), role filtering, and `AGENTS.md` integration (`johnston --rules`).

5. **Skills (Modular Capabilities & References)**: [references/skills.md](references/skills.md)
   - Global skills (`~/.johnston/skills/`), project skills (`.johnston/skills/`), `SKILL.md` format, and subfolder organization (`johnston --skills`, `/skills`).

6. **LLM Providers & Keys**: [references/providers.md](references/providers.md)
   - Provider settings (`~/.johnston/providers.json`), API keys, base URLs, and model aliases (`johnston --models`).

7. **Configuration & Security**: [references/config.md](references/config.md)
   - App settings (`~/.johnston/config.json`), centralized secrets (`~/.johnston/secrets.json`), permissions, and sandbox mode.

8. **Builtin Tools**: [references/tools.md](references/tools.md)
   - Builtin tool execution, subagent restrictions, shell permissions, and per-tool permission config.

9. **Slash Commands & Keybindings**: [references/commands.md](references/commands.md)
   - Interactive TUI slash commands (`/new`, `/resume`, `/compact`, `/fork`, `/rewind`, `/providers`, etc.) and keyboard shortcuts.

## Token Optimization & Execution Rules

1. **Selective Reading Only**: DO NOT load or view all `references/*.md` files at once.
2. **On-Demand Inspection**: Inspect ONLY the single `references/<topic>.md` file directly required for the current user task.