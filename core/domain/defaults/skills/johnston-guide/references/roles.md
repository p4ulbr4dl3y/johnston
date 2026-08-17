# Roles Reference (Execution Modes & Subagents)

## Locations
- Global roles: `~/.johnston/roles/<name>.md`
- Project roles: `.johnston/roles/<name>.md`

## Frontmatter Format
```markdown
---
name: reviewer
description: Code reviewer subagent
scope: subagent
allowed_tools: read, grep, glob
model: deepseek-v4-flash
provider: clinepass
---

System prompt instructions for the role...
```

## Scope
- `any` (default): available as both execution role and subagent type.
- `subagent`: usable only as `type` in `invoke_subagent`.
- `main`: usable only as main agent execution role (not a subagent).

## Frontmatter Fields
- `name`: Role identifier (defaults to filename).
- `description`: Summary of purpose.
- `scope`: `any`, `subagent`, or `main`.
- `allowed_tools`: Comma-separated whitelist of permitted tool names.
- `disallowed_tools`: Comma-separated list of blocked tool names.
- `model`: Specific LLM model override (subagents).
- `provider`: Specific provider override (subagents). Defaults to parent's active provider.

## Tool Isolation & Worktree Modes
Subagents can be invoked via `invoke_subagent` tool with:
- `workspace='branch'`: Spawns subagent in an isolated Git worktree.
- `workspace='inherit'`: Shares current working directory.