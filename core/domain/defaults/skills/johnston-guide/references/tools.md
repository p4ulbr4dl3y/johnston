# Johnston Builtin Tools Reference

## Overview
Johnston equips the primary agent and subagents with a suite of 10 builtin tools for codebase navigation, file manipulation, execution, subagent orchestration, and external research.

## Core Filesystem & Execution Tools
1. **`read`**: Read file contents, inspect directory listings, view archive contents (ZIP/TAR), inspect line slices, and convert documents (PDF, DOCX, XLSX, PPTX, EPUB, IPYNB, images) to markdown.
2. **`create`**: Atomically create new files or overwrite existing files with full contents.
3. **`edit`**: Apply precise, surgical search-and-replace edits to existing files using exact content matching.
4. **`shell`**: Execute synchronous shell commands or spawn long-running background tasks.
5. **`manage_shell`**: List, inspect status, send stdin input to, or terminate background shell tasks.

## Delegation & Subagents
6. **`invoke_subagent`**: Spawn a specialized child subagent with dedicated instructions, isolated worktree branch, and role definition.
7. **`manage_subagent`**: List active subagents, monitor progress, send follow-up instructions, or terminate subagents.

## Workflow & Research
8. **`ask_user`**: Prompt the user with interactive single-choice or multi-choice questions to resolve design ambiguity.
9. **`update_plan`**: Maintain and update structured multi-step task execution plans in the UI.
10. **`web_fetch`**: Fetch and extract web page content as clean markdown via HTTP requests.

## Subagent Tool Exclusions
To prevent nested delegation loops, interactive stalls, and background task collision, the following tools are strictly disabled inside child subagents:
- `invoke_subagent`
- `manage_subagent`
- `manage_shell`
- `ask_user`

## Permissions & Policies
- **Storage**: Configured in `~/.johnston/config.json` under `permissions.tools` and `permissions.default`.
- **Modes**:
  - `allow`: Execute automatically without prompting.
  - `ask`: Prompt user for interactive confirmation in the TUI before execution.
  - `deny`: Block execution immediately and return an error result to the agent.
- **Read-Only Roles**: When `read_only: true` (e.g. `explorer` role), `create` and `edit` are strictly denied, and `shell` is sandboxed.