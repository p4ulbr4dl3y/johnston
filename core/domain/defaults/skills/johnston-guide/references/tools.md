# Johnston Builtin Tools Reference

## Overview
Johnston equips the primary agent and subagents with a suite of 11 builtin tools for codebase navigation, file manipulation, execution, subagent orchestration, and external research.

## Core Filesystem & Execution Tools
1. **`read`**: Read file contents, inspect directory listings, view/extract archive contents (ZIP, TAR, WHL, JAR), read paths inside archives (`file.zip/path/foo.py`, `pkg.whl/mod.py`), and inspect line slices (`path`, `start_line`, `end_line`, `content_offset`, `detail`).
   - Output window limit: up to 800 lines (`DEFAULT_LINE_WINDOW = 800`) with line numbers per call; paginate large files using `start_line` and `end_line`.
   - Rich documents (PDF, DOCX, XLSX, PPTX, EPUB, IPYNB) automatically convert to clean markdown.
   - Images are processed into base64 JSON payloads with configurable `detail` (`"low"`, `"high"`, `"original"`).
   - MCP resources can be read via `read(path="resource://...")`.
2. **`search`**: Fast codebase search across files (`query`, `path`, `mode`, `glob`, `case_sensitive`, `max_results`, `context_lines`, `before`, `after`, `include_hidden`).
   - `query`: required for `mode="content"`; optional for `mode="filename"` (filepath pattern) and `mode="outline"` (symbol name filter; empty matches all symbols).
   - `before`: int (0..20), context lines before matches (`mode="content"` only, overrides `context_lines`).
   - `after`: int (0..20), context lines after matches (`mode="content"` only, overrides `context_lines`).
   - `include_hidden`: bool (default `false`), include hidden files/directories starting with `.`.
   - `mode="content"`: Regex/text grep across files with context lines (uses `ripgrep` with pure Python fallback).
   - `mode="filename"`: Find files and directories by glob/regex pattern.
   - `mode="outline"`: Extract code symbol definitions (classes, functions, methods) via Tree-sitter (Python, TS/TSX, JS, Go, Rust) with fallback to regex/AST.
3. **`create`**: Atomically create new files or overwrite existing files with full contents (`path`, `content`).
4. **`edit`**: Apply precise search-and-replace edits (`path`, `old_str`, `new_str`, `replace_all`). Omit `new_str` or set empty to delete `old_str`.
5. **`shell`**: Execute shell commands (`command`, `cwd`, `timeout`, `wait_seconds`).
   - `command`: Run commands directly without `cd` or piping (`| grep`, `| tail`, `| head`, etc.). Runtime auto-truncates and logs full output; piping breaks streaming and swallows exit codes.
   - `cwd`: Target subdirectory to run command in (default: current workspace root). Always use this parameter instead of `cd`. Omit when working in project root.
   - `wait_seconds=0` spawns async background processes immediately (servers/daemons) and returns a task ID.
   - `wait_seconds=N` waits up to N seconds before transitioning to background with hang detection.
6. **`kill`**: Terminate a running background shell task or subagent session by ID (`id`).

## Delegation & Subagents
7. **`invoke_subagent`**: Spawn a specialized background subagent (`title`, `task`, `role`).
   - Non-read-only roles (e.g. `worker`) automatically run in an isolated git worktree with an auto-generated branch, auto-committing on completion.
   - Read-only roles (e.g. `explorer`) run directly in the main workspace.
8. **`message_subagent`**: Send follow-up instructions to an active or completed subagent session (`id`, `message`).

## Workflow & Research
9. **`ask_user`**: Prompt user with interactive modal for ambiguous requirements or decisions (`questions`).
   - Schema for `questions` items:
     - `question` (str, required): Question text ending with `?`.
     - `header` (str, optional): Short tag (≤12 chars) shown above question.
     - `is_multi_select` (bool, optional, default `false`): Allow selecting multiple choices.
     - `options` (array of objects, 2-4 choices, required):
       - `label` (str, required): Short choice text (1-5 words).
       - `description` (str, optional): Trade-offs or implications.
     - Auto-sorting: options prefixed or marked with `(Recommended)` automatically float to the top.
10. **`update_plan`**: Maintain and update structured multi-step task execution plans (`plan`: `[{"step": "...", "status": "pending|in_progress|completed"}]`, `explanation`).
11. **`web_fetch`**: Fetch and extract web page content and documents as clean markdown via HTTP requests (`url`, `raw`).

## Subagent & Non-Interactive Exclusions
To prevent recursive spawning, interactive stalls, and process collisions, the delegation and UI-orchestration tools (`NON_INTERACTIVE_EXCLUDED_TOOLS`) are strictly disabled in all non-interactive modes (subagent + headless execution):
- `invoke_subagent`
- `message_subagent`
- `kill`
- `ask_user`
- `shell(wait_seconds=...)` (non-interactive modes may only run synchronous shell commands)

## Execution Modes & Permissions
- **Execution Modes (`permissions.mode`)**:
  - `review`: Prompts user confirmation for `create`, `edit`, `shell`, `web_fetch`, and MCP tools.
  - `edits`: Auto-allows `create` and `edit`; prompts for `shell`, `web_fetch`, and MCP tools (or per baseline: `web_fetch` allowed in `edits`, prompted in `review`).
  - `yolo`: Auto-allows all tool executions without interactive prompts.
- **Permission Actions (`PermissionAction`)**:
  - `allow`: Execute automatically without prompting.
  - `ask`: Prompt user for interactive confirmation in the TUI.
  - `deny`: Block execution immediately and return an error result.
- **Granular Rules**: Specific patterns (`permissions.patterns`) and per-tool rules (`permissions.tools`) override baseline mode actions.
- **Read-Only Roles**: When `read_only: true` (e.g. `explorer` role), `create` and `edit` are strictly denied, and `shell` is sandboxed.