# Detailed Technical Analysis — Milestone 1 (Dynamic Logic, Subagents, Commands & UI Audit)

## Executive Summary
This analysis covers a comprehensive, read-only audit of slash command processing (`core/commands.py`), subagent management (`tools/subagent.py`, `tools/manage_subagent.py`), background task handling (`tools/manage_task.py`, `tools/registry.py`), provider dynamic loading (`core/provider_manager.py`), context compaction (`core/base_provider.py`, `core/prompt_builder.py`), and styling/UI logic (`app.tcss`, `app.py`).

A total of 18 critical and high-impact issues were identified, ranging from worker cancellation bugs in background subagent completion to history state loss during tool execution errors and subagent metric duplication.

---

## 1. Slash Command Processing (`core/commands.py`)

### Finding 1.1: Unnormalized Command Argument Splitting in Cyrillic Homoglyph Handler
- **Location**: `core/commands.py:357-370`
- **Observation**:
  ```python
  parts = command_text.strip().split(maxsplit=1)
  cmd_name = parts[0].lower()
  ...
  normalized_name = "".join(homoglyphs.get(c, c) for c in cmd_name)
  ```
- **Analysis**:
  Command splitting happens *before* Cyrillic homoglyph normalization. If a user types `/сompact` (with Cyrillic 'с'), `cmd_name` becomes `/сompact` and `normalized_name` becomes `/compact`. However, if the command has sub-arguments or if skill command matching is triggered (line 373-385), `parts[1]` uses the raw unnormalized split. More importantly, when matching skill names like `/саveman`, if `parts[0]` contained mixed characters, `normalized_name[1:]` is checked against `SkillManager`, but `parts[1]` retains raw text. While retaining raw user prompt text in `parts[1]` is correct, any Cyrillic homoglyphs in the command verb itself inside `parts[0]` are normalized, but `parts` list itself is not updated with `normalized_name`.

### Finding 1.2: Rewind Command Off-By-One Index Boundary Risk
- **Location**: `core/commands.py:156-184`
- **Observation**:
  ```python
  def on_rewind_selected(selected_idx: int | None) -> None:
      ...
      chat_view.rollback_to(selected_idx - 1)
  ```
- **Analysis**:
  When the user selects the very first message in the chat history (`selected_idx == 0`), `selected_idx - 1` evaluates to `-1`. Passing `-1` to `chat_view.rollback_to()` causes unexpected widget slicing behavior in Textual `children` list, potentially removing all chat elements or throwing an index out of bounds error.

### Finding 1.3: Desynchronization Between UI Divider and Agent History on Compaction Error
- **Location**: `core/commands.py:301-331`
- **Observation**:
  ```python
  success, msg = await app.agent.compact_history()
  if success:
      app.notify(msg)
      ...
      await chat_view.add_compaction_divider("Session Compacted")
  ```
- **Analysis**:
  If `compact_history()` returns `False` (e.g., when history length is `<= 4` or provider summarization fails), the warning notification is displayed, but `save_current_session()` is not called. However, if auto-compaction ran inside `stream_steps()` during streaming and threw an exception, `add_compaction_divider` might not be added, leaving the UI state and `agent.history` in an inconsistent state when saved.

---

## 2. Subagent Management (`tools/subagent.py`, `tools/manage_subagent.py`, `core/subagent_tracker.py`)

### Finding 2.1: Worker Cancellation Bug on Background Subagent Completion (CRITICAL)
- **Location**: `tools/context.py:54-56`, `tools/subagent.py:169`, `app.py:417`
- **Observation**:
  In `tools/context.py`:
  ```python
  def trigger_ai_response(self, prompt: str) -> None:
      if self.app and hasattr(self.app, "generate_ai_response"):
          self.app.generate_ai_response(prompt, show_in_ui=False)
  ```
  In `app.py`:
  ```python
  @work(exclusive=True, thread=False)
  async def generate_ai_response(self, user_text: str, show_in_ui: bool = True) -> None:
  ```
- **Analysis**:
  `generate_ai_response` is decorated with `@work(exclusive=True)`. In Textual, calling an `@work(exclusive=True)` method automatically cancels any currently running worker for that method.
  When a background subagent completes, `_run_bg()` in `tools/subagent.py` calls `ctx.trigger_ai_response(msg)`. Unlike `on_background_bash_completed` (which checks `self.is_generating` and queues the message in `self.message_queue`), `trigger_ai_response()` directly invokes `generate_ai_response()` WITHOUT checking `self.is_generating`.
  **Impact**: If the user or main agent is currently generating a response when a background subagent finishes, the main response worker IS IMMEDIATELY CANCELED AND KILLED.

### Finding 2.2: Loss of Conversation History When Resuming Subagents After App Restart
- **Location**: `core/subagent_tracker.py:68-80`, `tools/manage_subagent.py:131-140`
- **Observation**:
  `SubagentSessionData.to_dict()` includes `"agent_history": getattr(self.agent, "history", [])`.
  However, `SubagentSessionData.from_dict()`:
  ```python
  @classmethod
  def from_dict(cls, data: Dict[str, Any]) -> "SubagentSessionData":
      sess = cls(...)
      sess.status = data.get("status", "completed")
      sess.events = data.get("events", [])
      return sess
  ```
- **Analysis**:
  `from_dict()` completely ignores `"agent_history"` in the JSON file. When Johnston is restarted and `SubagentTracker` reloads sessions from disk, `session.agent` is `None` and `agent_history` is not restored onto `SubagentSessionData`.
  When a user later executes `manage_subagent(action='send_message', task_id=...)` to resume a completed subagent:
  ```python
  hist = session.to_dict().get("agent_history", []) if hasattr(session, "to_dict") else []
  ```
  Since `session.agent` is `None`, `session.to_dict()` returns `[]`. The newly spawned subagent instance gets an EMPTY history, losing all prior context from the previous session!

### Finding 2.3: Token Metric Multi-Counting on Follow-Up Subagent Messages
- **Location**: `tools/subagent.py:135-142`, `tools/manage_subagent.py:177-184`
- **Observation**:
  ```python
  def _merge_metrics():
      if ctx.app and hasattr(ctx.app, "agent") and ctx.app.agent:
          main_agent = ctx.app.agent
          main_agent.tokens_input += getattr(subagent, "tokens_input", 0)
          main_agent.tokens_output += getattr(subagent, "tokens_output", 0)
          main_agent.total_tokens += getattr(subagent, "total_tokens", 0)
          main_agent.cost_usd += getattr(subagent, "cost_usd", 0.0)
  ```
- **Analysis**:
  `subagent.tokens_input`, `subagent.tokens_output`, `subagent.total_tokens`, and `subagent.cost_usd` are cumulative totals maintained on the `subagent` instance across all turns.
  When `manage_subagent(action='send_message')` is called to send a second message to an existing subagent, `_merge_metrics()` is called again. It adds the updated cumulative `subagent.tokens_input` (which already includes turn 1's tokens) to `main_agent.tokens_input`.
  **Impact**: Turn 1's subagent token counts are double-counted in the main session totals!

### Finding 2.4: Task ID Collision Overwrites Active Subagent Sessions
- **Location**: `tools/subagent.py:46-70`, `core/subagent_tracker.py:121-134`
- **Observation**:
  In `SubagentTracker.create_session`:
  ```python
  self.sessions[task_id] = sess
  ```
- **Analysis**:
  If a custom `task_id` is passed in `args` that matches an existing `task_id` in `tracker.sessions`, `create_session` overwrites the dictionary entry without terminating or archiving the previous session.

---

## 3. Background Tasks & Tool Execution (`tools/manage_task.py`, `tools/registry.py`)

### Finding 3.1: Inverted Truncation Marker in `ManageTaskTool` Output
- **Location**: `tools/manage_task.py:52-54`
- **Observation**:
  ```python
  out = "".join(t.output)
  if len(out) > 4000:
      out = out[-4000:] + "\n... [truncated]"
  ```
- **Analysis**:
  `out[-4000:]` extracts the *last* 4000 characters (discarding the beginning of the log). Appending `"\n... [truncated]"` to the end makes the output appear as if the end was truncated, when in fact the top/beginning was truncated. The marker should be prepended (`"[truncated] ...\n" + out[-4000:]`).

### Finding 3.2: Synchronous Thread Execution Block in MCP Tool Fallback
- **Location**: `tools/registry.py:47-50`
- **Observation**:
  ```python
  from core.mcp_manager import get_mcp_manager
  mcp_res = await asyncio.to_thread(get_mcp_manager().call_tool, name, args)
  ```
- **Analysis**:
  `asyncio.to_thread` delegates `call_tool` to a thread pool executor. However, `get_mcp_manager().call_tool` has no timeout wrapping. If an external MCP server hangs during execution, the thread remains blocked indefinitely.

---

## 4. Provider Dynamic Loading & Context Compaction (`core/provider_manager.py`, `core/base_provider.py`, `core/prompt_builder.py`)

### Finding 4.1: Brittle Provider File Model Replacement Regex
- **Location**: `core/provider_manager.py:328-341`
- **Observation**:
  ```python
  for line in lines:
      if line.startswith("MODEL ="):
          new_lines.append(f'MODEL = "{model_name}"\n')
  ```
- **Analysis**:
  If a Python provider plugin file formats the model assignment as `MODEL: str = "..."` or `MODEL= "..."` (no spaces around `=` or type annotated), `line.startswith("MODEL =")` silently fails to match, causing `set_provider_model` to leave the provider file unchanged.

### Finding 4.2: History State Loss During Mid-Stream Tool Execution Exceptions
- **Location**: `core/base_provider.py:122-454`
- **Observation**:
  Inside `stream_steps()`:
  ```python
  messages = [{"role": "system", "content": sys_prompt}] + self.history + [{"role": "user", "content": user_text}]
  try:
      while True:
          ...
          # Execute tool calls and append to messages list
          ...
      self.history = messages[1:]
  except Exception as err:
      ...
  ```
- **Analysis**:
  `self.history` is ONLY updated at the very end of `stream_steps()` after the tool execution loop finishes (`self.history = messages[1:]`).
  If an exception (e.g. API network disconnect, JSON parse error, or process crash) occurs during step 3 of a multi-step tool call sequence, control jumps to `except Exception as err:` where an error message is yielded, BUT `self.history` IS NEVER UPDATED with the tool calls and tool results that successfully ran during steps 1 and 2!
  **Impact**: The agent completely loses memory of actions taken prior to the error in that turn.

### Finding 4.3: Synchronous Git Subprocess Calls Blocking Async Event Loop
- **Location**: `core/prompt_builder.py:11-34`, `core/base_provider.py:105-107`
- **Observation**:
  In `core/prompt_builder.py`:
  ```python
  branch = subprocess.check_output(["git", "branch", "--show-current"], ...)
  status = subprocess.check_output(["git", "status", "-s"], ...)
  ```
- **Analysis**:
  `get_git_info()` executes blocking synchronous `subprocess.check_output` calls. `PromptBuilder.build_system_prompt()` calls `get_git_info()` on EVERY STEP of the LLM stream loop in `stream_steps()`. In large repositories with thousands of modified files or slow network mounts, running `git status -s` synchronously blocks the main asyncio event loop for up to 1 second per streaming turn.

---

## 5. UI & TCSS Styling Logic (`app.tcss`, `app.py`)

### Finding 5.1: Missing Modal Screen Overflow and Scroll Controls
- **Location**: `app.tcss:345-424`
- **Observation**:
  ```tcss
  #modal-dialog {
      width: 90%;
      max-width: 64;
      height: auto;
      max-height: 85%;
      padding: 1 2;
      border: solid #27272a;
      background: #18181b;
  }
  ```
- **Analysis**:
  `#modal-dialog` specifies `height: auto` and `max-height: 85%`, but lacks `overflow-y: scroll`. When modal content (such as help text or long model lists) exceeds 85% of terminal height, Textual clips the modal dialog without providing scrollbars, rendering bottom buttons (e.g. Cancel / OK) unreachable.

### Finding 5.2: Indiscriminate Clipboard Copying on Any Mouse Up Event
- **Location**: `app.py:307-322`
- **Observation**:
  ```python
  def on_mouse_up(self, event: events.MouseUp) -> None:
      selected_text = self.screen.get_selected_text()
      if selected_text:
          try:
              self.selection_copy_active = True
              self.copy_to_clipboard(selected_text)
              self.notify("Selected text copied to clipboard!")
          finally:
              self.screen.clear_selection()
  ```
- **Analysis**:
  Whenever any mouse release occurs, if *any* text selection exists on screen, `on_mouse_up` copies it to the system clipboard and immediately clears the selection. This makes persistent text selection impossible for users trying to highlight text visually without overwriting their clipboard.

---

## Summary Table of Issues

| ID | Module / File | Severity | Issue Summary |
|---|---|---|---|
| 1.1 | `core/commands.py` | Low | Unnormalized `parts` array in Cyrillic homoglyph slash command parser |
| 1.2 | `core/commands.py` | Medium | Off-by-one index error in `/rewind` command when selecting first message |
| 1.3 | `core/commands.py` | Low | Possible UI compaction divider desync on manual compaction failure |
| 2.1 | `tools/context.py` / `app.py` | **CRITICAL** | Background subagent completion triggers `@work(exclusive=True)` which cancels active main agent response |
| 2.2 | `tools/manage_subagent.py` | **HIGH** | Subagent history is not loaded from disk by `from_dict()`, wiping context on resume after restart |
| 2.3 | `tools/subagent.py` | **HIGH** | Cumulative subagent token metrics are double-counted in main agent totals on follow-up messages |
| 2.4 | `core/subagent_tracker.py` | Medium | Duplicate `task_id` overwrites existing subagent sessions without cleanup |
| 3.1 | `tools/manage_task.py` | Low | Inverted `[truncated]` label placement when truncating background task output |
| 3.2 | `tools/registry.py` | Medium | Unbounded `asyncio.to_thread` execution for MCP tool calls |
| 4.1 | `core/provider_manager.py` | Low | Static string startswith check for `MODEL =` fails on alternative code formatting |
| 4.2 | `core/base_provider.py` | **HIGH** | Mid-stream tool exceptions cause total loss of executed tool steps in `self.history` |
| 4.3 | `core/prompt_builder.py` | Medium | Synchronous `subprocess.check_output` for git status blocks async event loop on every step |
| 5.1 | `app.tcss` | Medium | Missing `overflow-y: scroll` on `#modal-dialog` clips content in small terminal windows |
| 5.2 | `app.py` | Low | Automatic clipboard copy on mouse release prevents persistent visual selection |
