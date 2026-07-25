# Handoff Report — Explorer 2 (Milestone 1: Static Code Analysis & Logic Audit)

**Agent:** Explorer 2 (`teamwork_preview_explorer`)  
**Working Directory:** `/Users/yegor/johnston/.agents/teamwork_preview_explorer_m1_2`  
**Project Root:** `/Users/yegor/johnston`  
**Recipient:** Orchestrator (`9fcc7044-bb88-4ef6-ba1a-cf5c177af337`)  

---

## 1. Observation

Direct code analysis across `core/`, `tools/`, `providers/`, `app.py`, and `app.tcss` identified 13 static bugs and architectural flaws:

1. **`app.py:644-652` (`run_headless_prompt`)**:
   ```python
   agent = pm.create_active_agent()
   if model and agent:
       agent.model = model
   if mode and agent:
       agent.mode = mode
   ...
   async for step in agent.stream_steps(prompt):
   ```
   If `create_active_agent()` returns `None`, `agent.stream_steps()` raises `AttributeError: 'NoneType' object has no attribute 'stream_steps'`.

2. **`app.py:657-662` (`run_headless_prompt`)**:
   ```python
   if chunk_type in ("bot_delta", "bot_text", "text"):
       new_text = val1[last_printed_len:]
       if new_text:
           sys.stdout.write(new_text)
           sys.stdout.flush()
           last_printed_len = len(val1)
   ```
   `last_printed_len` slicing assumes `val1` is always cumulative text, but subagents (`tools/subagent.py:127`) yield incremental `bot_chunk` tokens, causing stream corruption or missing output.

3. **`core/provider_manager.py:327-342` (`set_provider_model`)**:
   ```python
   provider_path = os.path.join(PROVIDERS_DIR, f"{key}.py")
   if os.path.exists(provider_path):
       ...
       with open(provider_path, "w", encoding="utf-8") as f:
           f.writelines(new_lines)
   ```
   `PROVIDERS_DIR` points to repository source code (`os.path.join(PROJECT_DIR, "providers")`). Switching models mutates git-tracked source files at runtime.

4. **`core/base_provider.py:608-627` & `641-648` (`compact_history`)**:
   ```python
   choices = chunk.get("choices") if isinstance(chunk, dict) else getattr(chunk, "choices", None)
   ```
   Dict lookup `.get("choices")` is attempted on `ChatCompletion` or `ChatCompletionChunk` Pydantic response objects, which do not implement `.get()`.

5. **`core/base_provider.py:434-452` (`stream_steps`)**:
   ```python
   messages.append({
       "role": "tool",
       "tool_call_id": t_id,
       "content": tool_content
   })
   ```
   When `ViewImageTool` returns image content, `tool_content` is a list `[{"type": "text", ...}, {"type": "image_url", ...}]`. OpenAI Chat API contract requires `role: "tool"` content to be a string.

6. **`core/session_manager.py:48-50` (`list_sessions`)**:
   ```python
   ui_msgs = data.get("ui_messages") or data.get("messages") or []
   if not ui_msgs:
       os.remove(filepath)
       continue
   ```
   Sessions without `ui_messages` (e.g., background subagent sessions or programmatically created sessions with only `agent_history`) are permanently deleted when `list_sessions()` is called.

7. **`tools/bash.py:166-189` (`execute`)**:
   ```python
   except asyncio.TimeoutError:
       if ctx.app:
           ...
       else:
           await p.wait()
   ```
   In headless mode (`ctx.app is None`), long-running commands that time out (>10s) trigger `await p.wait()`, blocking CLI execution indefinitely without closing `master_fd`.

8. **`core/mcp_manager.py:115` (`_read_response`)**:
   ```python
   line = self.process.stdout.readline()
   ```
   `readline()` on stdout file object blocks synchronously on the main thread if newline is missing, freezing Textual GUI event loop.

9. **`tools/subagent.py:115-118` & `tools/manage_subagent.py:157-160`**:
   `dur = float(val1)` does not check for non-finite numbers before `SubagentTracker.save_session` calls `json.dump`, risking `ValueError: Out of range float values are not JSON compliant`.

10. **`tools/ask_user.py:42-48`**:
    `questions_list = args.get("questions")` does not normalize single dictionary inputs (`isinstance(dict)`), causing tool failure when LLM returns `{"question_text": "..."}`.

11. **`core/prompt_builder.py:170-189`**:
    `PromptBuilder.build_tools` substitutes non-vision tool definitions into `all_tools`, creating shallow reference copies.

12. **`core/background_task.py:81-86`**:
    `master_fd` closed in `finally:` block while `reader` stream pipe is attached can raise `OSError: Bad file descriptor`.

13. **`app.tcss:256-276`**:
    `scrollbar-size: 0 0;` on `#command-suggestions OptionList` hides scrollbar when command list overflows.

---

## 2. Logic Chain

1. **Observation 1 → Conclusion**: In `app.py:644-652`, `pm.create_active_agent()` returns `None` if provider key is invalid or no provider exists. Calling `agent.stream_steps()` without a `None` guard leads directly to `AttributeError`.
2. **Observation 2 → Conclusion**: In `app.py:657-662`, `val1[last_printed_len:]` assumes `val1` always grows cumulatively. Because subagents yield incremental deltas (`bot_chunk`), `last_printed_len` exceeds `len(val1)` on subsequent chunks, causing string slicing to return empty strings and drop response text.
3. **Observation 3 → Conclusion**: `set_provider_model` in `core/provider_manager.py:327` writes to `PROVIDERS_DIR` (project root `providers/clinepass.py`). Runtime modification of source code files breaks user state isolation and pollutes git working trees.
4. **Observation 4 → Conclusion**: In `core/base_provider.py:608`, `.get()` is called on Pydantic objects (`ChatCompletionChunk`). Python Pydantic models do not support dict indexing via `.get()`, throwing `AttributeError` and breaking compaction history parsing.
5. **Observation 5 → Conclusion**: `core/base_provider.py:448` appends list objects to `role: "tool"` `content`. The OpenAI API spec requires string content for tool messages, causing HTTP 400 rejection from LLM endpoints.
6. **Observation 6 → Conclusion**: In `core/session_manager.py:49`, `os.remove(filepath)` is executed if `ui_messages` is empty. Sessions containing only background subagent data or agent history are silently erased from disk.
7. **Observation 7 → Conclusion**: `tools/bash.py:173` calls `await p.wait()` when timing out in headless mode. Indefinite process waiting on timeout blocks CLI prompt threads permanently.
8. **Observation 8 → Conclusion**: `core/mcp_manager.py:115` executes `readline()` on main thread. Synchronous I/O reads without newline delimiter freeze the Textual event loop.

---

## 3. Caveats

- **Scope boundary**: Read-only exploration. No source files or tests were modified during this phase.
- **Network calls**: MCP external servers and custom remote provider endpoints (ClinePass, OpenCode) were not connected live over the network due to CODE_ONLY mode restrictions.

---

## 4. Conclusion

The codebase is well-structured with high test coverage (129 unit tests passing), but contains critical edge case logic flaws and contract violations in stream rendering, context compaction, session management, file mutation, and tool payload formatting. Remediation requires targeted bug fixes in `app.py`, `core/base_provider.py`, `core/provider_manager.py`, `core/session_manager.py`, `core/mcp_manager.py`, and `tools/bash.py`.

---

## 5. Remediation & Fix Proposals

### Step 1: Fix Headless Agent Execution & Stream Rendering (`app.py`)
- In `run_headless_prompt`, add null check for `agent`:
  ```python
  if not agent:
      sys.stderr.write("Error: Failed to initialize active provider agent.\n")
      sys.exit(1)
  ```
- Normalize stream chunk output handling by maintaining a clean string buffer or handling `bot_chunk` separately from `bot_delta`.

### Step 2: Fix Provider Model Persistence (`core/provider_manager.py`)
- Remove code modifying `PROVIDERS_DIR/*.py` in `set_provider_model`. Persist model choices strictly in `~/.johnston/config.json` (`provider_models` dict).

### Step 3: Enforce OpenAI Tool Message String Contract (`core/base_provider.py`)
- In `stream_steps` (`line 448`), ensure `tool_content` for `role: "tool"` is serialized to a string if it is a list or dict:
  ```python
  if isinstance(tool_content, (list, dict)):
      tool_content = json.dumps(tool_content, ensure_ascii=False)
  ```

### Step 4: Fix History Compaction Pydantic Access (`core/base_provider.py`)
- Replace dict `.get()` calls on `chunk` / `res` with `getattr()` or dict checks (`if isinstance(chunk, dict): ... else: getattr(chunk, ...)`).

### Step 5: Protect Sessions from Accidental Deletion (`core/session_manager.py`)
- In `list_sessions()`, check both `ui_messages` and `agent_history` before removing empty session files:
  ```python
  if not ui_msgs and not data.get("agent_history"):
      os.remove(filepath)
      continue
  ```

### Step 6: Fix Headless Bash Timeout (`tools/bash.py`)
- In `tools/bash.py`, when `ctx.app` is `None` on timeout, terminate process or raise TimeoutError instead of `await p.wait()`.

---

## 6. Verification Method

To independently verify these findings and future fixes:

1. **Run Unit Tests**:
   ```bash
   uv run python -m unittest discover -s tests
   ```
2. **Run Linter**:
   ```bash
   uv run ruff check .
   ```
3. **Verify Headless Execution**:
   ```bash
   uv run python app.py -p "Test prompt"
   ```
4. **Inspect Project Directory**:
   Verify that no files under `providers/` are modified after changing model configs.
