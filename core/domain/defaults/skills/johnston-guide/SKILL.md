---
name: johnston-guide
description: Master Johnston system manual and reference. Manages CLI flags, MCP servers, roles, rules, skills, LLM providers, config, tools, and slash commands.
---

# Johnston System Guide

You are operating inside Johnston CLI. Use this master guide to understand and configure Johnston's capabilities.

## Master Index & References

When performing specific configuration tasks, inspect ONLY the relevant reference document:

1. **CLI Flags & Startup Options**: [references/cli_flags.md](references/cli_flags.md)
   - Command line flags (`--models`, `--skills`, `--mcp`, `--roles`, `--rules`, `--resume`, `--version`) and session resume hints.

2. **MCP Servers**: [references/mcp.md](references/mcp.md)
   - Configuration files, JSON schema, stdio/SSE transports, secret substitution, namespacing, and verification (`johnston --mcp`).

3. **Roles (Execution Modes & Subagents)**: [references/roles.md](references/roles.md)
   - Unified role definitions (`key`, `name`, `scope`, `allowed_tools`, `disallowed_tools`, `read_only`), worktrees, and discovery (`johnston --roles`).

4. **Rules & Project Guidelines**: [references/rules.md](references/rules.md)
   - Global rules (`~/.johnston/rules/`), project rules (`.johnston/rules/`), repository instructions (`AGENTS.md`, `CLAUDE.md`, `.cursorrules`), and scoping (`johnston --rules`).

5. **Skills (Modular Capabilities & References)**: [references/skills.md](references/skills.md)
   - Global skills (`~/.johnston/skills/`), project skills (`.johnston/skills/`), `SKILL.md` format, and subfolder organization (`johnston --skills`, `/skills`).

6. **LLM Providers & Keys**: [references/providers.md](references/providers.md)
   - Provider settings (`~/.johnston/providers.json`), `ProviderDef` schema, API keys, base URLs, reasoning effort, and models catalog (`johnston --models`).

7. **Configuration & Security**: [references/config.md](references/config.md)
   - App settings (`~/.johnston/config.json`), secrets priority (`~/.johnston/secrets.json`), `model` source of truth, permissions, sandbox, and `JOHNSTON_*` env vars.

8. **Builtin Tools**: [references/tools.md](references/tools.md)
   - 10 builtin tools, schemas, subagent tool exclusions (`SUBAGENT_EXCLUDED_TOOLS`), execution modes (`review`, `edits`, `yolo`), and permission policies.

9. **Slash Commands & Keybindings**: [references/commands.md](references/commands.md)
   - Interactive TUI slash commands, aliases, keybindings, multi-skill execution, and MCP prompts.

## Token Optimization & Execution Rules

1. **Selective Reading Only**: DO NOT load or view all `references/*.md` files at once.
2. **On-Demand Inspection**: Inspect ONLY the single `references/<topic>.md` file directly required for the current user task.