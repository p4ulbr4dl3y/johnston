## 2026-07-25T02:51:08Z
<USER_REQUEST>
You are Worker 2 for Milestone 2 (Providers, Session, Tools, UI & Test Noise Remediation) of the johnston repository bug audit.

Your identity and scope:
- Archetype: teamwork_preview_worker
- Working directory: /Users/yegor/johnston/.agents/teamwork_preview_worker_m2_2
- Project root: /Users/yegor/johnston
- Scope document: /Users/yegor/johnston/.agents/orchestrator/PROJECT.md

OBJECTIVE:
Fix the following specific provider, session, tool, UI, and test isolation bugs:
1. `core/provider_manager.py`:
   - In `set_provider_model` (lines 327-342), remove code that writes to `PROVIDERS_DIR/*.py` source files. Store provider model choices strictly in user config (`~/.johnston/config.json`).
2. `core/session_manager.py`:
   - In `list_sessions()` (lines 48-50), check both `ui_messages` and `agent_history` before removing empty session files, preventing silent deletion of subagent/agent sessions.
3. `tools/bash.py`:
   - In `execute()` timeout handler (lines 166-189), handle headless mode (`ctx.app is None`) without calling `await p.wait()`, preventing process deadlock.
4. `core/mcp_manager.py`:
   - Fix synchronous blocking `readline()` call on main thread.
5. `tools/ask_user.py`:
   - In `execute()` (lines 42-48), normalize single dictionary input for `questions` to a list.
6. `app.tcss`:
   - In `#modal-dialog` (lines 350-358), add `overflow-y: scroll` to prevent modal content clipping.
   - In `#command-suggestions OptionList` (lines 256-276), ensure scrollbar is usable.
7. `tests/test_provider_advanced_features.py` & `tests/test_base_provider.py`:
   - Mock Ollama `fetch_models_for_provider` call in `test_fetch_models_grouped_excludes_disabled` to eliminate unmocked network GET attempt and stderr noise.
   - Mock `stream_steps` HTTP client call in `test_auto_compaction_trigger` to prevent network call delay.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

STEPS TO EXECUTE:
1. Initialize progress.md and BRIEFING.md in `/Users/yegor/johnston/.agents/teamwork_preview_worker_m2_2/`.
2. Modify the code files carefully using replace_file_content / multi_replace_file_content.
3. Run `uv run python -m unittest discover -s tests` and `uv run ruff check .` to verify all fixes pass.
4. Create `/Users/yegor/johnston/.agents/teamwork_preview_worker_m2_2/handoff.md` detailing:
   - Modifications made per file.
   - Build and test results (`uv run python -m unittest discover -s tests`).
   - Lint results (`uv run ruff check .`).
5. Send a completion message back to parent orchestrator (conversation ID: 9fcc7044-bb88-4ef6-ba1a-cf5c177af337).

</USER_REQUEST>
