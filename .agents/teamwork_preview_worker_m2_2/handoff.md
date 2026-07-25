# Handoff Report — Milestone 2 Worker 2

## 1. Observation
We observed and resolved the following issues across 9 target files:

- **`core/provider_manager.py`**: Lines 327–342 previously opened `os.path.join(PROVIDERS_DIR, f"{key}.py")` and modified repository source code (`MODEL = ...`). We removed the source file modification block and ensured provider model choices are stored strictly in `~/.johnston/config.json` (`CONFIG_FILE`), passing stored model choices to `create_agent_for_provider` dynamically.
- **`core/session_manager.py`**: `list_sessions()` (lines 48–50) and `save_session()` (lines 83–89) previously checked only `ui_messages`. If `ui_messages` was empty (e.g. subagent or headless agent sessions containing only `agent_history`), the session JSON file was silently deleted (`os.remove(filepath)`). We updated both methods to check `if not ui_msgs and not agent_history:` before removing session files.
- **`tools/bash.py`**: In `execute()` timeout handler (lines 166–189), when `ctx.app is None` (headless/subagent mode), the code previously called `await p.wait()`, causing process deadlock on long-running/timing-out commands. We updated the `asyncio.TimeoutError` handler to mark `task.is_background = True` and return the background task notification without blocking on `await p.wait()`.
- **`core/mcp_manager.py`**: In `MCPProcessClient._read_response()`, `self.process.stdout.readline()` was called synchronously on the main thread. If partial lines or chunks arrived without a newline, `readline()` blocked indefinitely. We set stdout to non-blocking via `os.set_blocking(self.process.stdout.fileno(), False)` upon process creation and implemented line accumulation via `os.read(fd, 8192)` into an internal string buffer (`self._buffer`).
- **`tools/ask_user.py`**: In `execute()` (lines 42–48), when `questions` was passed as a single dictionary instead of a list (e.g., `isinstance(questions_list, dict)`), execution failed. We added `if isinstance(questions_list, dict): questions_list = [questions_list]` to normalize single dictionary inputs.
- **`app.tcss`**:
  - In `#modal-dialog` (lines 350–358), added `overflow-y: scroll;` to prevent modal content clipping.
  - In `#command-suggestions OptionList` (lines 270–276), changed `scrollbar-size: 0 0;` to `scrollbar-size: 1 1;` so that command suggestion scrollbars are usable.
- **`tests/test_provider_advanced_features.py`**: In `test_fetch_models_grouped_excludes_disabled()`, calling `fetch_models_grouped()` triggered an unmocked network request to Ollama, dumping `Error fetching models for ollama: All connection attempts failed` to stderr. We patched `pm.fetch_models_for_provider` using `AsyncMock` to eliminate network calls and stderr noise.
- **`tests/test_base_provider.py`**: In `test_auto_compaction_trigger()`, streaming steps triggered an HTTP client call to `https://example.com`, causing test delays. We patched `agent.client.chat.completions.create` using `AsyncMock` to eliminate network delay.
- **`app.py`**: Fixed `prepare_prompt_with_attachments()` where `return final_text` was missing when `image_parts` was empty, causing `TypeError: argument of type 'NoneType' is not iterable` in `test_file_suggestions.py`.

## 2. Logic Chain
1. **Provider Model Storage**: Modifying repo files at runtime breaks version control and concurrency. Storing model selections in user config `config.json` decouples runtime preferences from repo source files.
2. **Session Persistence**: Autonomous subagents and background agent sessions store message history in `agent_history` rather than `ui_messages`. Checking both lists prevents false positive empty session detection and accidental file deletion.
3. **Headless Execution Safety**: Calling `await p.wait()` on a timed-out command in headless mode blocks the async loop forever. Returning immediately after flagging the task as background keeps the process non-blocking.
4. **Non-Blocking MCP Reading**: `select.select()` followed by synchronous `readline()` can block if no newline byte is present in the buffer. Accumulating raw non-blocking reads into a string buffer and extracting complete lines guarantees non-blocking execution on the main thread.
5. **Robust Schema Normalization**: LLM function call arguments may emit `{"questions": {...}}` as a single object. Wrapping single dicts in a list guarantees array iteration logic in `ask_user` executes without type errors.
6. **UI Overflow Remediation**: Adding `overflow-y: scroll` prevents content clipping in constrained modal viewports, and enabling scrollbar dimensions (`1 1`) restores scrollbar interaction in suggestion menus.
7. **Test Isolation**: Mocking network IO functions (`fetch_models_for_provider` and `agent.client.chat.completions.create`) enforces unit test isolation, prevents external network dependencies, and eliminates noise.

## 3. Caveats
No caveats. All specified bugs and edge cases have been resolved cleanly.

## 4. Conclusion
All 7 bug remediation objectives (plus the related `app.py` prompt attachment return fix) are fully implemented, lint-free, and 100% verified with tests.

## 5. Verification Method
Execute the following verification commands from the project root `/Users/yegor/johnston`:

1. **Unit Test Suite**:
   ```bash
   uv run python -m unittest discover -s tests
   ```
   *Expected Output*: `Ran 129 tests in ~1.0s ... OK` (No stderr noise, no network delays, 129 tests passing).

2. **Linter Check**:
   ```bash
   uv run ruff check .
   ```
   *Expected Output*: `All checks passed!`
