# Slash Commands & Keybindings Reference

## Overview
Johnston TUI provides slash commands entered directly in the message input and keyboard shortcuts for rapid workflow management.

## Session & History Management
- `/new` (aliases: `/clear`, `/reset`): Start a new chat session (cancels background workers/tasks/subagents and resets context).
- `/resume [session_id]`: Resume a previous session from disk (opens interactive session picker or resumes specified ID).
- `/fork`: Fork the current conversation and working tree state into an independent branched session.
- `/rename [title]`: Rename the title of the current chat session.
- `/compact`: Summarize prior conversation turns and compact context history to free up LLM token window.
- `/rewind`: Select an earlier conversation turn to restore context and revert disk changes using git snapshots.

## Model & Provider Controls
- `/providers`: Open interactive provider selection and credential configuration modal.
- `/models`: Switch the active model for the current LLM provider.
- `/thinking`: Adjust reasoning/thinking effort level (`none`, `low`, `medium`, `high`, or custom token budget).

## Integration & Inspection
- `/skills`: Open interactive browser to inspect global and project skills.
- `/mcp`: Open MCP server dashboard to view registered servers, tool lists, and connection statuses.
- `/subagents`: Open monitoring screen for running and completed background subagents.
- `/tasks` (alias: `/shell_tasks`): Monitor background shell processes and async command execution.
- `/diff`: View workspace git diff and uncommitted changes.
- `/questions`: View pending interactive user clarification prompts.
- `/sandbox`: Toggle kernel sandbox enforcement for tool execution and shell commands.
- `/copy`: Copy last assistant response or full session transcript to the system clipboard.
- `/theme`: Open theme switcher modal to change UI color scheme.
- `/help` (aliases: `/h`, `/?`): Display interactive help screen and keybindings overview.

## Common Keybindings
- `Esc` / `Ctrl+C`: Abort ongoing generation or close active modal / overlay screen.
- `Ctrl+D`: Exit Johnston application cleanly.
- `Up` / `Down` (on empty input): Browse previously submitted message and command history.
- `Tab` / `Shift+Tab`: Move focus between input area, chat view, and interactive buttons.
