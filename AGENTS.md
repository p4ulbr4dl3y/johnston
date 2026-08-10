# Repository Guidelines

Johnston: Python terminal AI assistant, Textual UI. Entry: `app.py` (app), `cli.py` (CLI). Logic in `core/`, tools in `tools/`, widgets in `widgets/`. Tests in `tests/` mirror areas (`tests/core/`, `tests/tools/`, `tests/ui/`, `tests/adapters/`). Styling `app.tcss`; install `install.sh`/`install.ps1`.

## Build & Test

`uv` for all Python/deps.

- `uv run python cli.py` — CLI entry.
- `uv run python app.py` — app during UI work.
- `uv run pytest -n auto` — test suite, parallel (all cores).
- `uv run coverage run -m pytest && uv run coverage report -m` — coverage.
- `uv run ruff check .` — lint.
- `uv build` — build artifacts.

Prefix shell commands with `rtk` where practical (`rtk git status`).

## Style

Python 3.10+. Ruff: 120-char line, `py310`, checks `E,F,W,I`. snake_case modules/funcs, PascalCase classes. Keep helpers typed, near subsystem. Avoid broad refactors in UI widgets/core managers/tools; scope changes, keep testable.

## Testing

Pytest + `pytest-asyncio` (auto). Tests in `tests/`, named `test_*.py`, mirror source area (e.g. `tests/core/test_session_manager.py`). Add regression tests for bug fixes, focused unit tests for new behavior.

## Commits & PRs

Conventional Commits: `type(scope): desc` (`fix(tools): handle empty command output`). PRs: concise summary, tests run, linked issues, screenshots/terminal output for UI changes.

## Refactoring

No backward compatibility for refactors/cleanups — break freely, update callers/tests.

## Reuse Before New Code

Before implementing/refactoring/changing a feature, check for existing project code to reuse — avoid duplication.

## Security

No secrets/API keys/env files in git. Provider config/credentials outside source control; prefer documented env vars or git-ignored local config.