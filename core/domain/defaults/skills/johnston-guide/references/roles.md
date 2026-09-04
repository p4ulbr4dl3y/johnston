# Roles Reference (Execution Modes & Subagents)

## Locations
- Global roles: `~/.johnston/roles/<key>.md` (or `.markdown`)
- Project roles: `.johnston/roles/<key>.md` (or `.markdown`)

## Frontmatter Format
```markdown
---
key: reviewer
name: Code Reviewer
description: Code reviewer subagent
scope: subagent
allowed_tools: [read, shell, web_fetch]
model: deepseek/deepseek-chat
read_only: true
---

System prompt instructions for the role...
```

## Scope
- `any` (default): Available as both main execution role and subagent type.
- `subagent`: Usable only as `type` in `invoke_subagent`.
- `main`: Usable only as main agent execution role (not selectable for subagents).

## Frontmatter Fields
- `key`: Unique role identifier (defaults to filename without extension).
- `name`: Display title in UI (defaults to capitalized `key`).
- `description`: Summary of role purpose.
- `scope`: `any`, `subagent`, or `main`.
- `read_only`: `true` to disable mutating tools (`create`, `edit`). For builtin `explorer`, additionally forces OS-level sandbox.
- `allowed_tools`: Whitelist of permitted tool names or glob patterns (e.g. `read, shell, mcp__*` or `[read, shell]`).
- `disallowed_tools`: Blacklist of blocked tool names or glob patterns (e.g. `create, edit, mcp__*`).
- `model`: Specific model or `provider/model` override. If provider omitted, defaults to parent's active provider.

## Tool Isolation & Worktree Modes
Subagents are invoked via `invoke_subagent(type="<role_key>", branch="<branch_name>")`:
- **Branch omitted or same as main tree**: Subagent works directly in the workspace.
- **Different branch**: Subagent executes inside an isolated Git worktree on that branch and auto-commits on completion.
- **Subagent Exclusions**: `invoke_subagent`, `manage_subagent`, `manage_shell`, `ask_user`, and `shell(wait_seconds=...)` are automatically disabled in all subagent roles.