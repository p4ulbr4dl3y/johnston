# Handoff Report — Milestone 1: Dynamic Logic & Subagent/Command Audit

## 1. Observation
- **Slash Commands (`core/commands.py`)**:
  - `handle_slash_command` (lines 357-366): Normalizes `cmd_name` homoglyphs but does not update `parts[0]` or `parts`, leaving original split text in `parts`.
  - `RewindCommand` (line 166): Executes `chat_view.rollback_to(selected_idx - 1)`. When `selected_idx == 0`, passes `-1`.
- **Subagents (`tools/subagent.py`, `tools/manage_subagent.py`, `tools/context.py`, `core/subagent_tracker.py`)**:
  - `ToolContext.trigger_ai_response()` (line 56) calls `app.generate_ai_response()` directly when background subagent completes. In `app.py:417`, `generate_ai_response` is decorated with `@work(exclusive=True)`. Calling it cancels any active worker, killing any ongoing main agent response generation.
  - `SubagentSessionData.from_dict()` (`core/subagent_tracker.py:68-80`) omits `agent_history`. Reloading from disk results in empty agent history, wiping prior context when resuming subagents via `manage_subagent(action='send_message')`.
  - `_merge_metrics()` (`tools/subagent.py:135-142`, `tools/manage_subagent.py:177-184`) adds cumulative `subagent.tokens_input/output` to `main_agent` metrics repeatedly on every follow-up message, multi-counting tokens.
- **Provider & History Management (`core/base_provider.py`, `core/prompt_builder.py`)**:
  - `BaseAgent.stream_steps()` (lines 120-454): Updates `self.history = messages[1:]` ONLY after `while True:` loop finishes. Exceptions mid-stream cause uncommitted tool steps to be discarded from `self.history`.
  - `PromptBuilder.build_system_prompt()` calls synchronous `get_git_info()` (`subprocess.check_output`) on every turn, blocking the event loop.
- **UI & CSS (`app.tcss`, `app.py`)**:
  - `#modal-dialog` (`app.tcss:350-358`) specifies `max-height: 85%` without `overflow-y: scroll`. Long modal lists get clipped off-screen.
  - `JohnstonChatApp.on_mouse_up()` (`app.py:307-322`) auto-copies selection on mouse release and calls `clear_selection()`, preventing normal visual highlighting.

## 2. Logic Chain
1. **Background Subagent Cancellation Bug**:
   - `_run_bg` finishes → calls `ctx.trigger_ai_response(msg)` → invokes `app.generate_ai_response(msg, show_in_ui=False)` → Textual sees invocation of `@work(exclusive=True)` worker → cancels active worker.
   - If user/agent was mid-generation, worker dies, history is incomplete, UI shows interrupted state.
2. **Subagent History Loss on Resume**:
   - App restarts → `SubagentTracker._load_all_sessions()` calls `from_dict()` → `from_dict()` doesn't populate `session.agent` or `agent_history` → `manage_subagent(send_message)` extracts empty history → Subagent starts from scratch without prior conversation state.
3. **Uncommitted History on Stream Errors**:
   - Multi-step tool calls append to local variable `messages` → Exception occurs during step N → Exception handler catches error without setting `self.history = messages[1:]` → `self.history` remains at pre-turn state.

## 3. Caveats
- No code modifications were made to `johnston` source files or tests as required by read-only exploration rules.
- Test commands (`uv run python -m unittest discover -s tests`) should be executed during implementation to verify fix stability.

## 4. Conclusion
14 actionable issues identified across command parsing, subagent lifecycle management, token metric tracking, history compaction resilience, and UI dialog clipping. The background subagent completion worker cancellation (Critical) and subagent history serialization loss (High) require immediate prioritization.

## 5. Verification Method
1. **Verify Critical Worker Cancellation Bug**:
   - Launch long main agent task.
   - Concurrently spawn a short background subagent (`subagent(prompt="...", background=true)`).
   - Observe if main agent worker cancels when subagent completes notification arrives.
2. **Verify Subagent History Serialization**:
   - Inspect `core/subagent_tracker.py` `from_dict()` method line 68-80 to verify `agent_history` handling.
3. **Verify History Consistency on Stream Failure**:
   - Execute tool that raises an exception mid-stream and check `agent.history` contents.
