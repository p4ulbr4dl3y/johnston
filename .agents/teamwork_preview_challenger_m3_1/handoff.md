# Handoff Report — Challenger 1 (Milestone 3: Subagent & State Stress Testing)

## Observation

1. **SubagentSessionData Serialization & Deserialization**:
   - `SubagentSessionData` in `core/subagent_tracker.py` (lines 55–84) converts session data and `agent_history` (multi-turn tool calls, results, and bot messages) to/from dictionary representation (`to_dict` and `from_dict`).
   - Verified that multi-turn history containing nested tool calls (`role: "assistant"`, `tool_calls: [...]`) and tool results (`role: "tool"`, `tool_call_id: "..."`) serializes to JSON and deserializes back without key loss or schema corruption.

2. **Metric Accumulation (`_merge_metrics`)**:
   - In `tools/subagent.py` (lines 138–160) and `tools/manage_subagent.py` (lines 180–202), `_merge_metrics()` accumulates token usage from subagents into `main_agent` using differential deltas:
     `main_agent.tokens_input += (cur_in - last_in)`
     `subagent._merged_tokens_input = cur_in`
   - Empirical stress testing across 10 sequential follow-up subagent responses confirmed metric accumulation grows linearly (e.g. 1000 input tokens total for 10 x 100 token turns) rather than exponentially or redundantly.

3. **Stream Exceptions & History Recovery in `BaseAgent`**:
   - In `core/base_provider.py` (line 198 and line 263):
     - Line 198: `if getattr(chunk, "usage", None): step_usage = parse_usage(chunk.usage)`
     - Line 263: `if step_usage and step_usage.get("total_tokens", 0) > 0:`
     - **Empirical Bug Discovery**: When streaming responses omit usage objects (`chunk.usage` is `None`), `step_usage` is never bound in local scope, triggering `UnboundLocalError: cannot access local variable 'step_usage' where it is not associated with a value` at line 263.
   - In `core/base_provider.py` (lines 293–308):
     - Assistant tool messages (`assistant_tool_msg`) are constructed and appended to `messages` only AFTER the inner chunk streaming loop finishes. If a stream exception occurs mid-turn during chunk streaming, `tool_calls_dict` accumulates partial tool calls, but `messages` is never updated. The `finally` block sets `self.history = messages[1:]`, dropping any partial mid-turn tool calls while safely preventing corrupted history.
     - Completed turns in multi-turn tool loops (where Turn 1 completed and appended to `messages` before Turn 2 raised a stream exception) successfully retain Turn 1 tool calls and results in `agent.history`.

4. **Slash Command Parsing & Rewind Rollback**:
   - `handle_slash_command` in `core/commands.py` (lines 362–367) normalizes Cyrillic homoglyphs (`'а'->'a'`, `'с'->'c'`, `'е'->'e'`, `'р'->'p'`, `'о'->'o'`, etc.) before checking `COMMAND_REGISTRY`.
   - Commands `/cоmpact`, `/mсp`, `/рroviders`, `/hеlp`, `/nеw` submitted with Cyrillic characters are correctly parsed and executed.
   - `RewindCommand` in `core/commands.py` (lines 156–185) with `selected_idx = 0` calculates `target_idx = selected_idx - 1` (`-1`), correctly executing `chat_view.rollback_to(-1)` and placing the first user message into the input field.

## Logic Chain

1. **Observations 1 & 2** -> Multi-turn `SubagentSessionData` state roundtrips cleanly, and differential tracking in `_merge_metrics()` prevents double-counting tokens during multi-turn subagent execution.
2. **Observation 3** -> In `BaseAgent.stream_steps()`, referencing `step_usage` on line 263 without initializing `step_usage = None` at turn start causes an `UnboundLocalError` when provider streams lack `chunk.usage`. Initializing `step_usage = None` at line 134 prevents stream crashes on usage-less chunks. Additionally, mid-stream exceptions before chunk loop completion leave `messages` unpolluted, whereas prior completed tool turns are preserved in `messages[1:]`.
3. **Observation 4** -> Homoglyph normalization converts Cyrillic lookalikes to ASCII equivalents before registry lookup, ensuring slash commands parse reliably regardless of keyboard layout state. Rewind rollback at `selected_idx = 0` cleanly resets the chat view to index -1.

## Caveats

- Background task subagents relying on network streaming will inherit `BaseAgent` stream behavior. If provider API endpoints drop connection without sending usage metadata, `step_usage` UnboundLocalError occurs unless guarded.
- Tested on standard macOS environment using `uv run python -m unittest discover -s tests`.

## Conclusion

- **Overall Risk Assessment**: MEDIUM
- Core subagent session serialization, token accumulation math, homoglyph slash command parsing, and `selected_idx = 0` rewind rollback pass all stress tests.
- Found 1 implementation bug in `BaseAgent`: `step_usage` unbound local error when `chunk.usage` is missing from stream chunks.

## Verification Method

1. Run standard unit test suite:
   `uv run python -m unittest discover -s tests`
2. All 133 standard tests pass cleanly.
