# Johnston Codebase Bug Audit, Test Remediation & Forensic Report

**Date**: 2026-07-25  
**Target Repository**: `/Users/yegor/johnston`  
**Orchestrator**: Project Orchestrator (`.agents/orchestrator`)  
**Forensic Integrity Verdict**: **CLEAN** (0 Integrity Violations)  
**Unit Test Suite**: **134 / 134 PASSED** (`uv run python -m unittest discover -s tests`)  
**Linter Status**: **0 Violations / PASS** (`uv run ruff check app.py core tools providers widgets tests`)  

---

## 1. Executive Summary

A comprehensive multi-phase static, dynamic, empirical, and forensic audit of the `johnston` AI Agent Terminal repository was conducted by a team of specialized subagents under the Project Orchestration Pattern. 

A total of **22 distinct issues, contract violations, and edge-case bugs** were discovered, cataloged, remediated, independently reviewed, empirically stress-tested, and forensically audited. All 134 unit tests pass cleanly in under 1 second without network delays or stderr noise, and the codebase satisfies all linter rules under project settings.

---

## 2. Comprehensive Inventory of Cataloged & Fixed Issues

| # | Category | File Path & Lines | Problem Description | Remediation Applied | Status |
|---|----------|-------------------|---------------------|---------------------|--------|
| 1 | Subagent & UI | `app.py:417` & `tools/context.py:56` | `trigger_ai_response()` called `@work(exclusive=True)` worker directly upon background subagent completion, canceling active main agent generation. | Updated `app.trigger_ai_response()` to check `self.is_generating` and queue messages to `self.message_queue` when generating. | FIXED |
| 2 | CLI & Headless | `app.py:644-652` | Missing null check when `pm.create_active_agent()` returns `None` in `run_headless_prompt()`. | Added explicit `if not agent:` check writing error to stderr and exiting cleanly. | FIXED |
| 3 | CLI & Headless | `app.py:657-662` | Stream slice tracking (`last_printed_len`) dropped incremental `bot_chunk` text across multi-step tool calls. | Reset `last_printed_len = 0` on tool execution or when `len(val1) < last_printed_len`. | FIXED |
| 4 | UI Interaction | `app.py:307-322` | `on_mouse_up()` wiped visual text selection on mouse release. | Removed redundant `self.screen.clear_selection()` call on mouse release. | FIXED |
| 5 | Subagent State | `core/subagent_tracker.py:68-80` | `SubagentSessionData.from_dict()` omitted restoring `agent_history` from session JSON. | Restored `agent_history` deserialization in `from_dict()`. | FIXED |
| 6 | Subagent Metrics | `tools/subagent.py:135-142` & `tools/manage_subagent.py:177-184` | `_merge_metrics()` repeatedly added total subagent token metrics to main agent on follow-ups. | Implemented differential delta tracking (`_merged_*` attributes) for input/output tokens. | FIXED |
| 7 | Subagent Metrics | `tools/subagent.py:115` & `app.py:512` | Unsanitized `float(val1)` passed to `json.dump()` risked non-finite float serialization error. | Guarded duration float conversions with `math.isfinite()` checks. | FIXED |
| 8 | OpenAI API Spec | `core/base_provider.py:448` | `role: "tool"` content passed dict/list objects instead of stringified JSON when handling multimodal outputs. | Enforced string serialization via `json.dumps()` for dict/list `tool_content`. | FIXED |
| 9 | State Resilience | `core/base_provider.py:454` | `self.history = messages[1:]` was uncommitted if stream exceptions occurred mid-turn. | Wrapped history sync in a `finally` block to preserve completed turns upon stream failure. | FIXED |
| 10 | History Compaction | `core/base_provider.py:608-627` | `compact_history()` called `.get("choices")` on Pydantic `ChatCompletionChunk` instances. | Replaced dict `.get()` calls with `getattr()` and type guards. | FIXED |
| 11 | Provider Config | `core/provider_manager.py:327-342` | `set_provider_model` mutated git-tracked source `.py` files in `providers/` directory at runtime. | Removed source file mutation. Model selections are stored strictly in `~/.johnston/config.json`. | FIXED |
| 12 | Session Manager | `core/session_manager.py:48-50` | `list_sessions()` deleted session files missing `ui_messages` even if `agent_history` was present. | Updated cleanup condition to `if not ui_msgs and not agent_history:`. | FIXED |
| 13 | Commands | `core/commands.py:357-366` | Cyrillic homoglyph normalization updated `cmd_name` but left original split text in `parts[0]`. | Updated `parts[0] = normalized_name` in `handle_slash_command()`. | FIXED |
| 14 | Commands & UI | `core/commands.py:166` & `widgets/chat_view.py:120` | `RewindCommand` calculated `selected_idx - 1` (`-1`) for index 0, triggering negative slice bounds error. | Safely handled `target_index == -1` in `rollback_to()` by placing first user message in prompt. | FIXED |
| 15 | Headless Process | `tools/bash.py:166-189` | `execute()` timeout handler called `await p.wait()` in headless mode (`ctx.app is None`), causing deadlock. | Marked task as background task and returned immediately without blocking on `await p.wait()`. | FIXED |
| 16 | Event Loop | `core/mcp_manager.py:115` | `readline()` on stdout file descriptor blocked synchronously on main event loop thread. | Set stdout to non-blocking via `os.set_blocking` and implemented line accumulator buffer. | FIXED |
| 17 | Tool Schema | `tools/ask_user.py:42-48` | `questions` passed as single dictionary failed iteration logic. | Wrapped single dictionary inputs in a list (`questions_list = [questions_list]`). | FIXED |
| 18 | UI Styling | `app.tcss:350-358` | `#modal-dialog` lacked vertical scrollability, clipping long modal screens. | Added `overflow-y: scroll;` to `#modal-dialog` ruleset. | FIXED |
| 19 | UI Styling | `app.tcss:256-276` | `#command-suggestions OptionList` hid scrollbars (`scrollbar-size: 0 0`). | Restored scrollbar visibility (`scrollbar-size: 1 1`). | FIXED |
| 20 | Test Isolation | `tests/test_provider_advanced_features.py:75-84` | Unmocked Ollama model fetch attempt printed connection failure noise to stderr. | Mocked `pm.fetch_models_for_provider` using `AsyncMock`. | FIXED |
| 21 | Test Performance | `tests/test_base_provider.py:166` | Unmocked streaming call to `https://example.com` caused artificial test execution delay. | Mocked `agent.client.chat.completions.create` using `AsyncMock`. | FIXED |
| 22 | Stream Provider | `core/base_provider.py:133` | `step_usage` referenced without initialization when stream chunks omitted `chunk.usage` (`UnboundLocalError`). | Initialized `step_usage = None` per turn loop and added unit test `test_stream_steps_without_chunk_usage`. | FIXED |

---

## 3. Subagent Team Workflow & Verification Matrix

| Phase | Milestone | Subagents Dispatched | Output Artifacts | Status |
|-------|-----------|----------------------|------------------|--------|
| Phase 1 | Baseline Exploration & Audit | `teamwork_preview_explorer_m1_1`<br>`teamwork_preview_explorer_m1_2`<br>`teamwork_preview_explorer_m1_3` | `.agents/teamwork_preview_explorer_m1_*/handoff.md` | COMPLETE |
| Phase 2 | Bug Fixes & Remediation | `teamwork_preview_worker_m2_1`<br>`teamwork_preview_worker_m2_2` | `.agents/teamwork_preview_worker_m2_*/handoff.md` | COMPLETE |
| Phase 3 | Review & Stress Testing | `teamwork_preview_reviewer_m3_1`<br>`teamwork_preview_reviewer_m3_2`<br>`teamwork_preview_challenger_m3_1`<br>`teamwork_preview_challenger_m3_2`<br>`teamwork_preview_worker_m3_fix` | `.agents/teamwork_preview_reviewer_m3_*/handoff.md`<br>`.agents/teamwork_preview_challenger_m3_*/handoff.md` | COMPLETE |
| Phase 4 | Forensic Integrity Audit | `teamwork_preview_auditor_m4` | `.agents/teamwork_preview_auditor_m4/handoff.md` | **CLEAN** |
| Phase 5 | Final Documentation | Orchestrator | `.agents/orchestrator/AUDIT_REPORT.md` | COMPLETE |

---

## 4. Forensic Audit & Integrity Verification

The Forensic Auditor (`teamwork_preview_auditor_m4`) conducted static code analysis, git diff audits, and behavioral execution checks across all production and test modules:
- **Hardcoded Test Results**: 0 instances detected. All methods execute real business logic.
- **Facade Implementations**: 0 instances detected. `NotImplementedError` is limited strictly to abstract base classes.
- **Mock Isolation**: 0 mocks in production code (`core/`, `tools/`, `providers/`, `widgets/`, `app.py`). Mocks exist exclusively in `tests/`.
- **Suppressed Assertions / Skip Abuse**: 0 skipped tests (`@unittest.skip` count = 0).
- **Final Verdict**: **CLEAN**.

---

## 5. Verification Commands

To independently verify the complete test suite and linter status:

```bash
# 1. Run full unit test suite (134 tests)
uv run python -m unittest discover -s tests

# 2. Run linter across all project source & test modules
uv run ruff check app.py core tools providers widgets tests
```

**Expected Results**:
- `Ran 134 tests in ~1.0s ... OK`
- `All checks passed!`
