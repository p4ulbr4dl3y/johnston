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
model: deepseek/deepseek-chat
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
- `read_only`: `true` to make role strictly read-only (blocks `create`/`edit` and enforces kernel-level read-only sandbox for `shell`).
- `allowed_tools`: Comma-separated whitelist of permitted tool names or glob patterns (e.g. `read, shell, mcp__*`).
- `disallowed_tools`: Comma-separated list of blocked tool names or glob patterns (e.g. `create, edit, mcp__*`).
- `model`: Specific model or `provider/model` override (subagents). If provider omitted, defaults to parent's active provider.

## Tool Isolation & Worktree Modes
Subagents are invoked via `invoke_subagent` with an optional `branch='<name>'` parameter:
- Omitted or same branch as main tree: subagent works directly in the main workspace.
- Different branch: subagent runs in an isolated Git worktree on that branch (created if missing).
- `explorer` role or roles with `read_only: true`: mutations blocked across both tools and shell commands via OS-level sandbox.