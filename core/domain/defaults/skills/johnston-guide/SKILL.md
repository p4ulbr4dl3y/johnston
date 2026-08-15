---
name: johnston-guide
description: Master Johnston system manual and reference. Manages CLI flags, MCP servers, roles, rules, LLM providers, tools, and custom subagent definitions.
---

# Johnston System Guide

You are operating inside Johnston CLI. Use this master guide to understand and configure Johnston's capabilities.

## Master Index & References

When performing specific configuration tasks, inspect ONLY the relevant reference document:

1. **CLI Flags & Startup Options**: [references/cli_flags.md](file://references/cli_flags.md)
   - Command line flags (`--models`, `--skills`, `--mcp`, `--roles`, `--rules`, `--subagents`, `--resume`, `--version`).

2. **MCP Servers**: [references/mcp.md](file://references/mcp.md)
   - Configuration files, JSON schema, stdio commands, registration, and debugging (`johnston --mcp`).

3. **Roles (Execution Modes & Subagents)**: [references/roles.md](file://references/roles.md)
   - Unified role definitions for execution modes and subagents (`~/.johnston/roles/` or `.johnston/roles/`, `johnston --roles`).

4. **Rules & Project Guidelines**: [references/rules.md](file://references/rules.md)
   - Global rules (`~/.johnston/rules/`), project rules (`.johnston/rules/`), role filtering, and `AGENTS.md` integration (`johnston --rules`).

5. **LLM Providers & Keys**: [references/providers.md](file://references/providers.md)
   - Provider settings (`~/.johnston/providers.json`), API keys, base URLs, and model aliases (`johnston --models`).

6. **Custom & Builtin Tools**: [references/tools.md](file://references/tools.md)
   - Builtin tool execution, shell permissions, and adding custom tools.

## Token Optimization & Execution Rules

1. **Selective Reading Only**: DO NOT load or view all `references/*.md` files at once.
2. **On-Demand Inspection**: Inspect ONLY the single `references/<topic>.md` file directly required for the current user task.