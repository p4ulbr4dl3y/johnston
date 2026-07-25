# Project: johnston

## Architecture
- `core/`: Base agent (`base_provider.py`), provider manager (`provider_manager.py`), prompt builder (`prompt_builder.py`), config (`config.py`), commands (`commands.py`).
- `tools/`: Tool registry (`registry.py`), base tool (`base.py`), context (`context.py`), built-in tools (`read`, `create`, `edit`, `bash`, `ask_user`, `skill`, `call_mcp_tool`, `manage_task`, `subagent`, `manage_subagent`, `view_image`).
- `providers/`: Provider configurations (`opencode.py`, etc.).
- `tests/`: Unittest test suite.
- `app.py`, `app.tcss`: Textual TUI interface and styling.

## Code Layout
- Root directory: `/Users/yegor/johnston`
- Code modules: `core/`, `tools/`, `providers/`
- Test suite: `tests/`

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Baseline Exploration & Audit | Full repository static & dynamic analysis, test & lint failure inventory | None | DONE |
| 2 | Bug & Lint Remediation | Fix test failures, unmocked I/O, linter issues, logic & syntax bugs | M1 | DONE |
| 3 | Review & Stress Testing | Adversarial verification, edge cases, regression check | M2 | DONE |
| 4 | Forensic Audit | Independent verification of authenticity & compliance | M3 | DONE |
| 5 | Final Documentation | Produce final audit report and deliver summary | M4 | DONE |

## Interface Contracts
- Test execution: `uv run python -m unittest discover -s tests`
- Linter execution: `uv run ruff check .`
