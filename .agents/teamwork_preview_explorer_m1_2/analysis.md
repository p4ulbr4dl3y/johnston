# Comprehensive Static Code Analysis & Logic Audit Report

**Target Repository:** `johnston` (`/Users/yegor/johnston`)  
**Explorer:** Explorer 2 (Milestone 1 — Static Code Analysis & Logic Audit)  
**Date:** 2026-07-25  

---

## 1. Executive Summary

Static code analysis and logic audit was conducted across all Python source modules in `core/`, `tools/`, `providers/`, `app.py`, and stylesheet `app.tcss`. Automated linting (`uv run ruff check .`) and test discovery (`uv run python -m unittest discover -s tests`) were executed alongside deep manual AST and flow inspections.

While all unit tests currently pass and linting checks succeed, static code analysis revealed **13 critical, high, and medium severity architectural flaws, contract violations, unhandled edge cases, resource leaks, and data loss risks** that can cause runtime crashes, corrupted outputs, or file corruption in production scenarios.

---

## 2. Inventory of Audited Scope

| Category | Component Files | Status |
|---|---|---|
| **Entrypoint & UI** | `app.py`, `app.tcss` | Audited |
| **Core Infrastructure** | `core/base_provider.py`, `core/provider_manager.py`, `core/prompt_builder.py`, `core/session_manager.py`, `core/mcp_manager.py`, `core/background_task.py`, `core/adapters.py`, `core/bash_guard.py`, `core/commands.py`, `core/models_catalog.py`, `core/rtk_manager.py`, `core/rules_manager.py`, `core/skill_manager.py`, `core/subagent_registry.py`, `core/subagent_tracker.py`, `core/token_util.py` | Audited |
| **Tools Suite** | `tools/ask_user.py`, `tools/base.py`, `tools/bash.py`, `tools/call_mcp.py`, `tools/context.py`, `tools/create.py`, `tools/edit.py`, `tools/linter.py`, `tools/manage_subagent.py`, `tools/manage_task.py`, `tools/read.py`, `tools/registry.py`, `tools/skill.py`, `tools/subagent.py`, `tools/view_image.py` | Audited |
| **Providers** | `providers/clinepass.py` | Audited |

---

## 3. Detailed Findings & Bug Matrix

### Issue 1: `AttributeError` in Headless Mode when Provider Returns `None`
- **File & Lines:** `app.py:644-652`
- **Severity:** High
- **Description:** In `run_headless_prompt`, `agent = pm.create_active_agent()` can return `None` if provider initialization fails or provider key is unconfigured. The function then attempts `async for step in agent.stream_steps(prompt):` without checking if `agent is None`, raising an unhandled `AttributeError: 'NoneType' object has no attribute 'stream_steps'`.
- **Impact:** CLI prompt commands (`johnston -p "..."` or `johnston --init`) crash with unhandled stack trace instead of presenting a clean user error message.

### Issue 2: Incorrect Headless Output Truncation / Chunk Streaming Logic
- **File & Lines:** `app.py:657-662`
- **Severity:** Medium
- **Description:** `run_headless_prompt` tracks `last_printed_len` and slices `val1[last_printed_len:]`. For standard `bot_delta` events (which contain accumulated text), this slicing works. However, `SubagentTool` and `ManageSubagentTool` yield `bot_chunk` (incremental deltas), and `BaseAgent` yields `bot_text` (full final response). When `bot_chunk` or `bot_text` arrives, slicing with `last_printed_len` based on accumulated length distorts or drops text.
- **Impact:** Headless output stream gets corrupted or truncated when subagent steps or final summary chunks are printed.

### Issue 3: Runtime Mutation of Project Repository Files (`providers/*.py`)
- **File & Lines:** `core/provider_manager.py:327-342`
- **Severity:** High
- **Description:** `set_provider_model(key, model_name)` writes directly into `PROVIDERS_DIR` (`os.path.join(PROJECT_DIR, "providers")`). When a user switches models in the UI or CLI via `/models`, line 335 rewrites `MODEL = "..."` directly inside git-tracked Python source code files (`providers/clinepass.py`).
- **Impact:** Violates isolation of application code vs user state. Causes git dirty working trees (`git status` shows modified files) during normal app runtime.

### Issue 4: Type Mismatch and Attribute Errors in `BaseAgent.compact_history`
- **File & Lines:** `core/base_provider.py:608-627` & `641-648`
- **Severity:** High
- **Description:** `compact_history()` attempts dict-style `.get()` calls (`chunk.get("choices")` and `res.get("choices")`) on OpenAI SDK Pydantic models (`ChatCompletionChunk` and `ChatCompletion`). Pydantic objects do not implement `.get()`, raising `AttributeError` which silently forces fallback or aborts compaction.
- **Impact:** Automated context compaction fails or behaves unpredictably under standard OpenAI client response objects.

### Issue 5: OpenAI API Contract Violation for `role: "tool"` Content Type
- **File & Lines:** `core/base_provider.py:434-452`
- **Severity:** High
- **Description:** When `ViewImageTool` returns image data, `tool_content` becomes a list of dicts: `[{"type": "text", ...}, {"type": "image_url", ...}]`. Line 448 appends this list as `content` for `role: "tool"`. The OpenAI Chat Completions API specification mandates that `role: "tool"` content MUST be a string, not an array.
- **Impact:** Subsequent API requests to OpenAI / OpenAI-compatible backends fail with HTTP 400 (`Invalid type for 'messages[...].content': expected a string`).

### Issue 6: Data Loss Risk in `SessionManager.list_sessions()`
- **File & Lines:** `core/session_manager.py:48-50`
- **Severity:** High
- **Description:** `list_sessions()` inspects session JSON files in `~/.johnston/projects/<project>/sessions/`. If `ui_messages` is empty (for instance, a session created programmatically or one with background subagents where only `agent_history` is populated), line 49 executes `os.remove(filepath)`.
- **Impact:** Reading session lists permanently deletes user session files from disk if UI messages have not been flushed yet.

### Issue 7: Unhandled Endless Block & Resource Leak in `BashTool` Timeout
- **File & Lines:** `tools/bash.py:166-189`
- **Severity:** High
- **Description:** In headless/non-GUI mode (`ctx.app` is `None`), when a bash command exceeds the 10-second timeout, execution falls through to `else: await p.wait()`. If the command is long-running or interactive (e.g. `top` or a dev server), `await p.wait()` blocks execution indefinitely. Furthermore, `master_fd` PTY file descriptor is not closed prior to `wait()`.
- **Impact:** CLI processes hang indefinitely when running commands exceeding 10 seconds in headless mode, wasting system file descriptors.

### Issue 8: Synchronous Main-Thread Blocking in `MCPProcessClient._read_response`
- **File & Lines:** `core/mcp_manager.py:115`
- **Severity:** High
- **Description:** `_read_response` uses `select.select()` to check stdout readiness, but then calls `self.process.stdout.readline()`. Because standard Popen `stdout` text wrapper buffers data, if an MCP server emits bytes without a trailing `\n`, `readline()` blocks synchronously. Since this happens on the main thread, the entire Textual UI and event loop freezes.
- **Impact:** Unresponsive UI freezing whenever an MCP server sends partial stdout or hangs.

### Issue 9: Invalid JSON Generation in `SubagentTracker.save_session` on `NaN`/`Inf` Floats
- **File & Lines:** `tools/subagent.py:115-118`, `tools/manage_subagent.py:157-160`, `core/subagent_tracker.py:116`
- **Severity:** Medium
- **Description:** `_record_step` records thinking duration (`dur = float(val1)`). If `val1` is empty or mathematically invalid, floating point values or unhandled exceptions can produce non-standard float values. When `SubagentTracker.save_session` calls `json.dump(..., indent=2)`, non-finite floats cause `ValueError: Out of range float values are not JSON compliant`.
- **Impact:** Subagent tracking crashes on session save when recording thinking metrics.

### Issue 10: Incomplete Input Parameter Handling in `AskUserTool`
- **File & Lines:** `tools/ask_user.py:42-47` & `54-55`
- **Severity:** Medium
- **Description:** `AskUserTool.execute` checks `if not questions_list and question:`. If an LLM passes `questions` as a single dictionary object rather than a list of dicts, `isinstance(questions_list, list)` evaluates to `False`, aborting with `"Error: App instance not available or no valid questions provided."` without normalizing dict input. Additionally, if `questions_list` is empty, `q_idx = 0` triggers `ConfirmScreen` with empty questions.
- **Impact:** `ask_user` tool call fails when model passes dictionary arguments instead of list.

### Issue 11: Imperfect Mutation Scope in `PromptBuilder.build_tools`
- **File & Lines:** `core/prompt_builder.py:170-189`
- **Severity:** Low
- **Description:** When substituting vision-capable tool schemas for models lacking vision support, `PromptBuilder.build_tools` mutates `all_tools` by inserting a new dict. While it does not mutate global `TOOL_CLASSES` directly, `clean_mcp_tools` items retain references that could lead to unexpected schema drift across mode switches.
- **Impact:** Potential side effects on tool schema parameters during dynamic mode switching.

### Issue 12: Inconsistent PTY Pipe Closing in `BackgroundTask`
- **File & Lines:** `core/background_task.py:81-86`
- **Severity:** Medium
- **Description:** `BackgroundTask._read` closes `master_fd` in a `finally:` block, but if an exception occurs in `os.read(self.master_fd)` prior to process exit, `master_fd` can be closed while `reader` protocol is still attached, causing silent `OSError: Bad file descriptor` exceptions in the event loop.
- **Impact:** Intermittent bad file descriptor errors in background task logs.

### Issue 13: `app.tcss` Command Suggestions Scrollbar Visibility
- **File & Lines:** `app.tcss:256-276`
- **Severity:** Low
- **Description:** `#command-suggestions OptionList` sets `scrollbar-size: 0 0;` while restricting `max-height: 5;`. When multiple slash command suggestions match, users receive no visual indicator that the list is scrollable.
- **Impact:** Minor UI usability degradation when navigating slash command suggestions with keyboard/mouse.

---

## 4. Verification Baseline

- Linter run (`uv run ruff check .`): All checks passed.
- Unit tests (`uv run python -m unittest discover -s tests`): 129 tests passed in 1.18s.
- Conclusion: The identified issues are logic edge cases, contract violations, and resource management bugs that manifest during interactive GUI operations, CLI headless executions, or provider switching.
