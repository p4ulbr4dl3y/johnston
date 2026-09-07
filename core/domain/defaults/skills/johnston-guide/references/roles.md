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
- `any` (default): Available in all modes (interactive TUI, headless CLI, subagents).
- `subagent`: Usable only as `type` in `invoke_subagent`.
- `main`: Usable only as main agent execution role (interactive + headless, not selectable for subagents).
- `interactive`: Usable only in interactive TUI sessions.
- `headless`: Usable only in headless/non-interactive CLI runs.

## Frontmatter Fields
- `key`: Unique role identifier (defaults to filename without extension).
- `name`: Display title in UI (defaults to capitalized `key`).
- `description`: Summary of role purpose.
- `scope`: `any`, `subagent`, `main`, `interactive`, or `headless`.
- `model`: Model override in `provider/model` format (e.g. `anthropic/claude-3-7-sonnet`, `deepseek/deepseek-chat`, `openai/gpt-4o`). Roles only accept `provider/model`; a separate `provider` field is not supported. If omitted, inherits active session provider/model.
- `read_only`: Boolean or string (`"true"`, `"1"`, `"yes"`, `"on"`). When true, mutating tools (`create`, `edit`) are stripped and OS-level sandbox is enforced.
- `allowed_tools`: Whitelist of permitted tool names or glob patterns (bracketed `[read, shell]` or comma-separated `read, shell`; YAML bullet lists `- item` are not supported).
- `disallowed_tools`: Blacklist of blocked tool names or glob patterns.

## System Prompt Injection
Role instructions are wrapped inside a `<role name="...">` block in the agent's system prompt:
```xml
<role name="reviewer">
<scope>
...
</scope>
<rules>
...
</rules>
</role>
```
> **Prompt Formatting**: The prompt body must start directly with `<scope>`, `<rules>`, or `<anti_patterns>` to preserve XML tags. If arbitrary text precedes them, the body is safely XML-escaped.

## CLI & TUI Interaction
- List available roles: `johnston roles` (or `johnston roles --json` for structured metadata including models and read-only flags).
- Launch with specific role: `johnston -r <role>` / `johnston --role <role>`.
- Switch role in TUI: press `Tab` to cycle between active `any`, `main`, and `interactive` roles (there is no `/role` slash command).

## Builtin Roles
Johnston ships with 3 builtin roles:
- `worker` (scope: `any`): Default execution mode with write permissions (`create`, `edit`, `shell`).
- `explorer` (scope: `any`): Read-only research, investigation, and action planning.
- `reviewer` (scope: `any`): Read-only defect-first code review and verification (`[P0]`-`[P3]`, `VERDICT: APPROVE`/`REJECT`).

## Tool Isolation & Worktree Modes
Subagents are invoked via `invoke_subagent(title="...", prompt="...", type="<role_key>")`:
- **Write roles (e.g. `worker`)**: automatically execute inside an isolated Git worktree on an auto-generated branch (`subagent/<title>-<id>`), auto-committing on completion. Requires workspace to be a Git repository; in non-Git directories, runs directly in the workspace.
- **Read-only roles (e.g. `explorer`, `reviewer`)**: execute directly in the main workspace without worktree isolation, with OS sandbox enabled.
- **Non-Interactive Exclusions**: `invoke_subagent`, `manage_subagent`, `manage_shell`, `ask_user`, and `shell(wait_seconds=...)` are automatically disabled in all non-interactive contexts (subagent roles and headless mode).