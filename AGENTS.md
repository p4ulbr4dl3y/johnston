# Repository Guidelines

## Project Structure & Module Organization

Johnston is a Python terminal AI assistant built around a Textual UI. Top-level entry points are `app.py` for the application and `cli.py` for command-line startup. Core application logic lives in `core/`, tool implementations in `tools/`, and Textual widgets/screens in `widgets/`. Tests mirror the product areas under `tests/` with subdirectories such as `tests/core/`, `tests/tools/`, `tests/ui/`, and `tests/adapters/`. Styling is in `app.tcss`; install helpers are `install.sh` and `install.ps1`.

## Build, Test, and Development Commands

Use `uv` for all Python environment and dependency work.

- `uv run python cli.py`: run the local CLI entry point.
- `uv run python app.py`: launch the app module directly during UI work.
- `uv run pytest`: run the pytest suite configured by `pyproject.toml`.
- `uv run coverage run -m pytest && uv run coverage report -m`: run tests with coverage.
- `uv run ruff check .`: lint imports and Python style.
- `uv build`: build distributable package artifacts.

When using shell commands in this repository, prefix them with `rtk` where practical, for example `rtk git status` or `rtk pytest`.

## Coding Style & Naming Conventions

Target Python 3.10+. Ruff is configured with a 120-character line length, `py310` target, and `E`, `F`, `W`, and `I` checks. Keep modules snake_case, classes PascalCase, and functions/variables snake_case. Prefer typed, focused helpers near the subsystem they support. Avoid broad refactors when changing UI widgets, core managers, or tool implementations; keep behavior changes scoped and testable.

## Testing Guidelines

Pytest is the test runner, with `pytest-asyncio` enabled in auto mode. Place tests under `tests/` and name files `test_*.py`. Match the source area when possible, such as `tests/core/test_session_manager.py` for `core/session_manager.py`. Add regression tests for bug fixes and focused unit tests for new command, provider, tool, or widget behavior.

## Commit & Pull Request Guidelines

Git history uses Conventional Commit-style messages, for example `config: remove DEFAULT_MAX_STEPS limit` and `refactor: extract CLI entrypoint`. Use `type(scope): description` when a scope helps, such as `fix(tools): handle empty command output`. Pull requests should include a concise summary, tests run, linked issues when relevant, and screenshots or terminal output for user-visible UI changes.

## Security & Configuration Tips

Do not commit local secrets, API keys, or generated environment files. Keep provider configuration and credentials outside source control, and prefer documented environment variables or local config files ignored by Git.
