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
allowed_tools: read, shell, web_fetch
model: deepseek-chat
provider: deepseek
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
Subagents are invoked via `invoke_subagent` with an optional `branch='<name>'` parameter:
- Omitted or same branch as main tree: subagent works directly in the main workspace.
- Different branch: subagent runs in an isolated Git worktree on that branch (created if missing).