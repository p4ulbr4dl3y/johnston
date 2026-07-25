# Baseline Exploration & Test Inventory Analysis

**Date**: 2026-07-25  
**Repository**: `johnston` (`/Users/yegor/johnston`)  
**Explorer**: Explorer 1 (Milestone 1)  

---

## Executive Summary

1. **Unit Test Suite Status**:
   - Total Tests Executed: **129**
   - Passed: **129**
   - Failed: **0**
   - Errors: **0**
   - Execution Time: **~1.28 seconds**
   - Command: `uv run python -m unittest discover -s tests`

2. **Linter Status**:
   - Standard Config Command: `uv run ruff check .`
   - Config file: `pyproject.toml` (`select = ["E", "F", "W", "I"]`, `ignore = ["E501"]`)
   - Violation Count (Default): **0 errors** (`All checks passed!`)
   - Strict Line Length Violation Count (`E501` enabled): **96 line length violations** (> 120 characters)

3. **Test Isolation & Side-Effect Findings**:
   - **Finding 1 (Unmocked Network Request in `test_provider_advanced_features.py`)**: During `test_fetch_models_grouped_excludes_disabled`, `ProviderManager.fetch_models_grouped()` triggers `fetch_models_for_provider("ollama")` which attempts a live HTTP connection to `http://localhost:11434/v1/models`. Because Ollama is not active, `httpx` raises a connection failure, resulting in stderr pollution: `Error fetching models for ollama: All connection attempts failed`.
   - **Finding 2 (Unmocked Network Request in `test_base_provider.py`)**: In `test_auto_compaction_trigger`, `agent.stream_steps("trigger")` executes an unmocked LLM API stream call targeting `https://example.com`, causing unnecessary network I/O attempt during unit testing (taking ~0.155s).

---

## Detailed Test Suite Inventory

Below is a breakdown of the 34 test modules located in `tests/`:

| Test Module File | Test Class(es) | Test Count | Pass/Fail | Side Effects / Notes |
|---|---|---|---|---|
| `tests/test_adapters.py` | `TestAdapters` | 4 | 4 Pass | Mocks streaming adapters |
| `tests/test_app.py` | `TestApp` | 5 | 5 Pass | TUI integration unit tests |
| `tests/test_base_provider.py` | `TestBaseProvider`, `TestBaseProviderTools` | 8 | 8 Pass | Unmocked `stream_steps` network attempt in `test_auto_compaction_trigger` |
| `tests/test_bash_confirm_screen.py` | `TestBashConfirmScreen` | 2 | 2 Pass | GUI modal tests |
| `tests/test_bash_guard.py` | `TestBashGuard` | 3 | 3 Pass | Command safety checks |
| `tests/test_bash_sleep.py` | `TestBashSleep` | 1 | 1 Pass | Async sleep handling |
| `tests/test_cli.py` | `TestCLI` | 3 | 3 Pass | CLI argument parser |
| `tests/test_code_block_copy.py` | `TestCodeBlockCopy` | 2 | 2 Pass | Widget copy functionality |
| `tests/test_commands.py` | `TestCommands` | 6 | 6 Pass | Slash command execution |
| `tests/test_core_extra.py` | `TestCoreExtra` | 3 | 3 Pass | Context & config tests |
| `tests/test_file_suggestions.py` | `TestFileSuggestions` | 3 | 3 Pass | Auto-complete logic |
| `tests/test_manage_subagent.py` | `TestManageSubagent` | 4 | 4 Pass | Subagent control tool |
| `tests/test_manage_task_input.py` | `TestManageTaskInput` | 2 | 2 Pass | Task input streaming |
| `tests/test_mcp_manager.py` | `TestMCPManager` | 4 | 4 Pass | MCP config loading |
| `tests/test_prompt_builder.py` | `TestPromptBuilder` | 6 | 6 Pass | System prompt formatting |
| `tests/test_provider_advanced_features.py` | `TestProviderAdvancedFeatures` | 4 | 4 Pass | Unmocked network call in `test_fetch_models_grouped_excludes_disabled` |
| `tests/test_provider_manager.py` | `TestProviderManager` | 6 | 6 Pass | Provider loading & keys |
| `tests/test_provider_manager_json.py` | `TestProviderManagerJson` | 2 | 2 Pass | Custom JSON provider definitions |
| `tests/test_rewind_screen.py` | `TestRewindScreen` | 1 | 1 Pass | History rewind UI |
| `tests/test_rules_manager.py` | `TestRulesManager` | 2 | 2 Pass | Rules parsing |
| `tests/test_rules_screen.py` | `TestRulesScreen` | 1 | 1 Pass | Rules display UI |
| `tests/test_search_screens.py` | `TestModalSearchShiftTab` | 3 | 3 Pass | Keybinding isolation in modals |
| `tests/test_session_manager.py` | `TestSessionManager` | 7 | 7 Pass | Session state serialization |
| `tests/test_skill_manager.py` | `TestSkillManager` | 6 | 6 Pass | Skill discovery & runner |
| `tests/test_subagent_registry.py` | `TestSubagentRegistry` | 2 | 2 Pass | Subagent YAML/MD definitions |
| `tests/test_subagent_screen.py` | `TestSubagentTrackerAndScreen` | 5 | 5 Pass | Subagent UI tracker |
| `tests/test_subagent_tool.py` | `TestSubagentTool` | 2 | 2 Pass | Subagent execution tool |
| `tests/test_subagents_screen.py` | `TestSubagentsScreen` | 1 | 1 Pass | Subagents dashboard UI |
| `tests/test_token_util.py` | `TestTokenUtil` | 4 | 4 Pass | Token estimation algorithms |
| `tests/test_tool_context.py` | `TestToolContext` | 2 | 2 Pass | Tool context delegation |
| `tests/test_tool_expansion.py` | `TestToolExpansion` | 10 | 10 Pass | Rich UI tool call rendering |
| `tests/test_tools.py` | `TestTools` | 6 | 6 Pass | Tool execution suites |
| `tests/test_truncate_output.py` | `TestTruncateOutput` | 1 | 1 Pass | Output truncation logic |
| `tests/test_view_image_tool.py` | `TestViewImageTool` | 2 | 2 Pass | Image inspection tool |

---

## Detailed Linting Analysis (`ruff`)

### Default Configuration (`pyproject.toml`)
```toml
[tool.ruff]
line-length = 120
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I"]
ignore = ["E501"]

[tool.ruff.lint.per-file-ignores]
"app.py" = ["E402"]
```

Result: **0 violations** (`All checks passed!`).

### Extended Strict Analysis (`E501` line-length check enabled)
When `E501` is evaluated, **96 violations** are detected across 18 source files:
- `tools/read.py`: 2 lines > 120 chars
- `tools/skill.py`: 1 line > 120 chars
- `tools/subagent.py`: 2 lines > 120 chars
- `tools/view_image.py`: 3 lines > 120 chars
- `widgets/chat_input.py`: 3 lines > 120 chars
- `widgets/chat_view.py`: 2 lines > 120 chars
- `widgets/screens/providers.py`: 1 line > 120 chars
- `widgets/screens/tasks.py`: 1 line > 120 chars
- `widgets/status_footer.py`: 3 lines > 120 chars
- (Additional files in `core/` and `widgets/`)

All other lint checks (`F` Pyflakes, `E` Syntax/Indentation, `W` Warnings, `I` Isort) pass 100% cleanly without any violations.

---

## Test Side-Effect Root Cause Analysis & Fix Strategies

### 1. Ollama Connection Error during `test_fetch_models_grouped_excludes_disabled`
- **File**: `tests/test_provider_advanced_features.py:75-84`
- **Root Cause**: `pm.fetch_models_grouped()` calls `fetch_models_for_provider` for every loaded provider. When checking provider `"ollama"`, it executes `httpx.AsyncClient().get("http://localhost:11434/v1/models", ...)` which fails with a connection error and prints `Error fetching models for ollama: All connection attempts failed`.
- **Recommended Fix**: Patch `fetch_models_for_provider` or mock `httpx.AsyncClient` inside `test_fetch_models_grouped_excludes_disabled` so that unit tests run in isolation without network I/O.

### 2. Slow Unmocked Stream Step in `test_auto_compaction_trigger`
- **File**: `tests/test_base_provider.py:166`
- **Root Cause**: `agent.stream_steps("trigger")` invokes OpenAI AsyncClient stream creation pointing to `https://example.com`, which initiates an unmocked network request and outputs an asyncio long execution warning.
- **Recommended Fix**: Patch `openai.AsyncOpenAI` or `BaseAgent.stream_steps` dependencies during the compaction test so network attempts are avoided.
