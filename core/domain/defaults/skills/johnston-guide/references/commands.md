# Slash Commands & Keybindings Reference

## Overview
Johnston TUI provides slash commands entered directly in the message input and keyboard shortcuts for rapid workflow management.

## Session & History Management
- `/new` (aliases: `/clear`, `/reset`): Start a new chat session (cancels background workers/tasks/subagents and resets context).
- `/resume` (aliases: `/sessions`, `/continue`, `/load`): Open session picker modal to resume a previous session from disk.
- `/fork` (alias: `/branch`): Fork conversation message chain from a selected message in session store into an independent branched session (does not branch git tree).
- `/rename` (aliases: `/title`, `/name`): Open rename session modal.
- `/compact` (aliases: `/compress`, `/summarize`, `/smol`): Summarize prior conversation turns and compact context history.
- `/rewind` (aliases: `/undo`, `/history`): Select an earlier conversation turn to restore context and revert disk changes via git snapshots.

## Model & Provider Controls
- `/providers` (aliases: `/provider`, `/connect`): Open interactive provider selection and credential configuration modal.
- `/models` (alias: `/model`): Switch active model for the current LLM provider.
- `/thinking` (aliases: `/effort`, `/reasoning`): Adjust reasoning effort level (`none`, `low`, `medium`, `high`, or custom token budget).

## Integration & Inspection
- `/skills` (alias: `/skill`): Open interactive browser to inspect global and project skills.
- `/mcp` (alias: `/mcps`): Open MCP server dashboard to view registered servers, tools, and connection statuses.
- `/workspace` (alias: `/ws`): Manage allowed workspace roots (inspect and manage multi-root paths).
- `/subagents` (aliases: `/agents`, `/subagent`): Open monitoring screen for running and completed background subagents.
- `/shell` (aliases: `/tasks`, `/shelltasks`, `/ps`): Monitor background shell processes and async command execution.
- `/diff` (aliases: `/changes`, `/patch`): View workspace diff for files modified during the active session (`_touched_files`), not general repository git diff.
- `/questions` (aliases: `/q`, `/ask`): View pending interactive user clarification prompts.
- `/sandbox` (alias: `/sb`): Toggle kernel sandbox enforcement for tool execution and shell commands.
- `/copy` (aliases: `/cp`, `/yank`): Copy last assistant response text to system clipboard.
- `/theme` (aliases: `/themes`, `/color`, `/colors`): Open theme switcher modal.
- `/commands` (alias: `/cmds`): List all available slash commands in interactive help modal.
- `/keybinds` (aliases: `/keys`, `/shortcuts`, `/keybindings`): List all hotkeys and keybindings in interactive help modal.
- `/help` (aliases: `/h`, `/?`): Display interactive help screen and keybindings overview.

## Dynamic Slash Capabilities
- **Skill Invocations**: Execute single or multiple skills directly via `/<skill_name> <prompt>` or `/<skill1> /<skill2> <prompt>`. Includes bundled workflow skills (`/init`, `/handoff`, `/goal`, `/review-loop`).
- **MCP Prompts**: Run registered MCP prompts via `/<prompt_name>` or `/<server>__<prompt_name>` with optional `key=value` args.
- **Homoglyph Normalization**: Auto-translates accidental Cyrillic homoglyphs (`с`, `а`, `о`, `е`...) in slash commands to Latin.

## Keyboard Shortcuts
- `Esc`: Abort ongoing generation, close active modal / overlay, or exit shell mode.
- `Ctrl+C` / `Ctrl+Q`: Exit Johnston application.
- `Ctrl+D`: Detach last attached image from input buffer.
- `Tab`: Cycle agent role across all available roles in registry (Worker / Explorer / ...), or accept selected autocomplete item.
- `Shift+Tab`: Cycle execution mode (`review` / `edits` / `yolo`).
- `Enter`: Send message, or accept selected autocomplete suggestion.
- `Ctrl+Enter` / `Shift+Enter`: Insert newline in multi-line chat input without sending.
- `Up` / `Down` (during autocomplete): Navigate suggestions menu items.
- `Up` / `Down` (on empty input): Browse message and command history (looping).
- `!` (on empty input): Toggle shell command mode.
- `?` (on empty input): Open interactive help modal.
- `Ctrl+B`: Background active shell tasks.
- `Ctrl+O`: Toggle folded/expanded state of tool calls and thinking blocks.
- `Ctrl+P`: Toggle task execution plan checklist modal.
- `Ctrl+H`: Toggle top header plan summary.
- `PageUp` / `PageDown`: Scroll chat view history.
- `Shift+PageUp` / `Shift+PageDown`: Jump to very top / bottom of chat.
- `Ctrl+V`: Paste clipboard text or image into chat input.
- `Ctrl+X`: Cut selected text.
- `@`: Open file autocomplete popup.
- `/`: Open slash command and skill autocomplete popup.
