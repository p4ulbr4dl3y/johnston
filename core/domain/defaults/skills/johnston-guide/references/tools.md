# Johnston Builtin Tools Reference

## Overview
Johnston equips the primary agent and subagents with a suite of 11 builtin tools for codebase navigation, file manipulation, execution, subagent orchestration, and external research.

## Core Filesystem & Execution Tools
1. **`read`**: Read file contents, inspect directory listings, view archive contents (ZIP/TAR), and inspect line slices (`path`, `start_line`, `end_line`, `content_offset`, `detail`).
   - Rich documents (PDF, DOCX, XLSX, PPTX, EPUB, IPYNB) automatically convert to clean markdown.
   - Images are processed into base64 JSON payloads with configurable `detail` (`"low"`, `"high"`, `"original"`).
   - MCP resources can be read via `read(path="resource://...")`.
2. **`search`**: Fast codebase search across files (`query`, `path`, `mode`, `glob`, `case_sensitive`, `max_results`, `context_lines`).
   - `mode="content"`: Regex/text grep across files with context lines (uses `ripgrep` with pure Python fallback).
   - `mode="filename"`: Find files and directories by glob/regex pattern.
   - `mode="outline"`: Extract code symbol definitions (classes, functions, methods) via AST/regex without reading full files.
3. **`create`**: Atomically create new files or overwrite existing files with full contents (`path`, `content`).
4. **`edit`**: Apply precise search-and-replace edits (`path`, `old_str`, `new_str`, `replace_all`). Omit `new_str` or set empty to delete `old_str`.
5. **`shell`**: Execute shell commands (`command`, `cwd`, `timeout`, `wait_seconds`).
   - `cwd`: Target subdirectory to run command in (default: current workspace root). Omit when working in project root.
   - `wait_seconds=0` spawns async background processes immediately (servers/daemons) and returns a task ID.
   - `wait_seconds=N` waits up to N seconds before transitioning to background with hang detection.
6. **`manage_shell`**: Manage background shell tasks (`action` in `["list", "send_input", "kill"]`, `task_id`, `input`).

## Delegation & Subagents
7. **`invoke_subagent`**: Spawn a specialized background subagent (`title`, `prompt`, `type`).
   - Non-read-only roles (e.g. `worker`) automatically run in an isolated git worktree with an auto-generated branch (`subagent/<title>-<id>`), auto-committing on completion.
   - Read-only roles (e.g. `explorer`) run directly in the main workspace.
8. **`manage_subagent`**: Manage active subagents (`action` in `["list", "send_message", "kill"]`, `session_id`, `message`).

## Workflow & Research
9. **`ask_user`**: Prompt the user with interactive single-choice or multi-choice questions (`questions`).
10. **`update_plan`**: Maintain and update structured multi-step task execution plans (`plan`: `[{"step": "...", "status": "pending|in_progress|completed"}]`, `explanation`).
11. **`web_fetch`**: Fetch and extract web page content and documents as clean markdown via HTTP requests (`url`, `raw`).

## Subagent Tool Exclusions
To prevent recursive spawning, interactive stalls, and process collisions, the following tools/options are strictly disabled inside subagents:
- `invoke_subagent`
- `manage_subagent`
- `manage_shell`
- `ask_user`
- `shell(wait_seconds=...)` (subagents may only run synchronous shell commands)

## Execution Modes & Permissions
- **Execution Modes (`permissions.mode`)**:
  - `review`: Prompts user confirmation for `create`, `edit`, `shell`, and MCP tools.
  - `edits`: Auto-allows `create` and `edit`; prompts for `shell` and MCP tools.
  - `yolo`: Auto-allows all tool executions without interactive prompts.
- **Permission Actions (`PermissionAction`)**:
  - `allow`: Execute automatically without prompting.
  - `ask`: Prompt user for interactive confirmation in the TUI.
  - `deny`: Block execution immediately and return an error result.
- **Granular Rules**: Specific patterns (`permissions.patterns`) and per-tool rules (`permissions.tools`) override baseline mode actions.
- **Read-Only Roles**: When `read_only: true` (e.g. `explorer` role), `create` and `edit` are strictly denied, and `shell` is sandboxed.