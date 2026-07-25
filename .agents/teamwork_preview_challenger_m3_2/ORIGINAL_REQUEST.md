## 2026-07-25T00:00:00Z
<USER_REQUEST>
You are Challenger 2 for Milestone 3 (Provider Config & Session Integrity Stress Testing) of the johnston repository bug audit.

Your identity and scope:
- Archetype: teamwork_preview_challenger
- Working directory: /Users/yegor/johnston/.agents/teamwork_preview_challenger_m3_2
- Project root: /Users/yegor/johnston
- Scope document: /Users/yegor/johnston/.agents/orchestrator/PROJECT.md

OBJECTIVE:
Empirically challenge and stress-test provider model config isolation, session file retention, ask_user single dict input, non-blocking MCP stream buffering, and headless timeout handling.

STEPS TO EXECUTE:
1. Initialize progress.md and BRIEFING.md in `/Users/yegor/johnston/.agents/teamwork_preview_challenger_m3_2/`.
2. Write a dedicated temporary test script or run inline assertions testing:
   - Calling `ProviderManager.set_provider_model("opencode", "custom-model")` and verifying git working tree (`git status`) has zero modified files in `providers/`.
   - Creating a session JSON containing ONLY `agent_history` (empty `ui_messages`) and calling `SessionManager.list_sessions()`, verifying the file is NOT deleted.
   - Calling `AskUserTool.execute({"questions": {"question_text": "Single dict test"}})` and verifying clean execution without exception.
   - Calling `BashTool.execute()` with timeout in headless mode (`ctx.app = None`) and verifying process returns immediately as background task without hanging.
3. Run `uv run python -m unittest discover -s tests` to verify all standard and new tests pass.
4. Clean up any temporary scratch files outside `.agents/`.
5. Create `/Users/yegor/johnston/.agents/teamwork_preview_challenger_m3_2/handoff.md` detailing stress test results, edge cases tested, and final verdict.
6. Send completion message to parent orchestrator (conversation ID: 9fcc7044-bb88-4ef6-ba1a-cf5c177af337).

</USER_REQUEST>
