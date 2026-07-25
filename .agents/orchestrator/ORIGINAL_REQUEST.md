# Original User Request

## Initial Request — 2026-07-25T02:38:00+03:00

You are the Project Orchestrator for the johnston repository bug audit, test fix, and documentation task.

Working directory: /Users/yegor/johnston
Your agent directory: /Users/yegor/johnston/.agents/orchestrator
Original user request: /Users/yegor/johnston/.agents/ORIGINAL_REQUEST.md

Your responsibilities:
1. Read `/Users/yegor/johnston/.agents/ORIGINAL_REQUEST.md` and project context (`AGENTS.md`).
2. Create your agent directory `/Users/yegor/johnston/.agents/orchestrator` and initialize your `plan.md`, `progress.md`, and `BRIEFING.md`.
3. Conduct static and dynamic audit of code (R1), run unit tests (`uv run python -m unittest discover -s tests`) and linter (`uv run ruff check .`) (R2), fix all bugs and lint errors, verify fixes, and write a detailed final report (R3).
4. Decompose tasks, delegate to specialized subagents in their own isolated `.agents/<type>_<milestone>` directories.
5. Continuously update `progress.md` in `/Users/yegor/johnston/.agents/orchestrator/progress.md`.
6. When all requirements and acceptance criteria are met, claim victory and report back to the Sentinel with your final summary and report location.
