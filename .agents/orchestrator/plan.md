# Master Execution Plan: Johnston Bug Audit, Fix & Verification

## Objective
Audit the entire `johnston` codebase for static/dynamic errors, fix all unit test failures and linter errors (`uv run python -m unittest discover -s tests` and `uv run ruff check .`), verify all fixes rigorously, perform forensic audit, and deliver a comprehensive final audit report.

## Milestones & Strategy

### Milestone 1: Exploration & Test Baseline
- Spawn `teamwork_preview_explorer` subagents to perform static analysis, check test failures (`uv run python -m unittest discover -s tests`), run `uv run ruff check .`, and catalog all syntax, import, runtime, and logic bugs across core/, tools/, providers/, app.tcss, etc.

### Milestone 2: Fix Implementation & Unit Testing
- Spawn `teamwork_preview_worker` subagents to implement fixes for all identified bugs and lint issues.
- Require workers to run test suite and linter after fixes and document pass/fail results.

### Milestone 3: Review & Adversarial Stress Testing
- Spawn `teamwork_preview_reviewer` and `teamwork_preview_challenger` subagents to verify fixes, inspect code quality, edge cases, and regression risks.

### Milestone 4: Forensic Audit
- Spawn `teamwork_preview_auditor` subagent to conduct independent forensic verification ensuring clean implementation without hardcoded results, dummy code, or integrity violations.

### Milestone 5: Final Documentation & Sentinel Reporting
- Create `/Users/yegor/johnston/AUDIT_REPORT.md` (or in orchestrator folder / root as required) detailing all issues, root causes, fixes, and verification evidence.
- Send final report to parent/Sentinel.
