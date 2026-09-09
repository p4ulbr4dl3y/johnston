# Repository Guidelines

Johnston: Python terminal AI assistant, Textual UI. Entry: `src/johnston/cli/main.py` (CLI, `johnston.cli.main:main` script), `src/johnston/tui/app.py` (app). Logic and tools in `src/johnston/core/`, TUI in `src/johnston/tui/`. Styling `src/johnston/tui/app.tcss`; install `install.sh`/`install.ps1`.

## Build & Test

`uv` for all Python/deps.

- `uv run johnston` (or `uv run python -m johnston.cli.main`) — CLI entry.
- `uv run python -m johnston.tui.app` — app during UI work.
- `uv run pytest -n auto -m "not slow"` — test suite, parallel (all cores). `slow` (timing-sensitive UI/latency) tests are excluded; run them serially as a separate stage: `uv run pytest -m slow`.
- `uv run coverage run -m pytest && uv run coverage report -m` — coverage (fail_under=90). Note: this runs the full suite serially, including `slow` tests (takes longer); coverage threshold assumes all tests run.
- `uv run ruff check .` — lint.
- `uv build` — build artifacts.

Prefix shell commands with `rtk` where practical (`rtk git status`). Prefer `rg` over `grep` and `fd` over `find`.

## Architecture

Layered core (`src/johnston/core/`): DDD-style. High-level vs low-level — keep deps pointing inward.

- `src/johnston/core/domain/` — business rules: `entities/` (session), `policies/` (catalog, models_catalog, permission, role), `defaults/` (config, prompts, providers, linters, skills).
- `src/johnston/core/application/` — use-cases: `generation/`, `permission/`, `provider/`, `session/`, `rules/`, `skills/`, `linters/`.
- `src/johnston/core/infrastructure/` — implementation: `adapters/`, `mcp/`, `platform/`, `runtime/` (circuit_breaker, frontmatter, token_util, thinking_effort), `storage/`, `tasks/`.
- `src/johnston/core/adapters/` — external LLM providers (anthropic, gemini, openai). `src/johnston/core/base_provider/` holds provider internals (agent, compaction, errors, tools).
- `src/johnston/core/roles/` — assistant role registry/apply/resolve/prompt/provider/tools.

TUI layering (`src/johnston/tui/`):

- `src/johnston/tui/app/` — app controllers/state (app, ai_controller, dispatch, role_service, session/status_state).
- `src/johnston/tui/presentation/screens/` — user-facing screens. Reusable sub-widgets live in `src/johnston/tui/presentation/widgets/`.
- `src/johnston/tui/mixins/` — shared view behavior (actions, lifecycle, message_flow, session_persistence).
- `src/johnston/tui/` root — core chat widgets (chat_input, chat_toolcall, status_footer, command_suggestions).
- Utils in `src/johnston/tui/utils/` (file_reader, lexer).

## Testing

Pytest + `pytest-asyncio` (auto). Tests are FLAT in `tests/`, named `test_*.py`; area is encoded in the filename prefix (`test_edge_core.py`, `test_edge_ui_*`, or tool/manager name), not only a mirrored dir. Top-level test suites per area (adapters, tools, ui) also exist. Discover via `-k`.

Add regression tests for bug fixes, focused unit tests for new behavior.

## Style

Python 3.10+ (`<3.14`). Ruff: 120-char line, `py310`, checks `E,F,W,I` (E501 ignored). snake_case modules/funcs, PascalCase classes. Keep helpers typed, near subsystem. Avoid broad refactors in UI widgets/core managers/tools; scope changes, keep testable.

## Config & Providers

Provider config/API keys stay OUT of source control — env vars or git-ignored local config (see `core/infrastructure/config`, `core/domain/defaults/providers.py`). No secrets in git.

## Commits & PRs

Conventional Commits: `type(scope): desc` (`fix(tools): handle empty command output`). PRs: concise summary, tests run, linked issues, screenshots/terminal output for UI changes.

## Refactoring

No backward compatibility for refactors/cleanups — break freely, update callers/tests.

## Reuse Before New Code

Before implementing/refactoring/changing a feature, check existing project code to reuse — avoid duplication.
