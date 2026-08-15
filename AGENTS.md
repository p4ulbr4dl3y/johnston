# Repository Guidelines

Johnston: Python terminal AI assistant, Textual UI. Entry: `app.py` (app), `cli.py` (CLI, `cli:main` script). Logic in `core/`, tools in `tools/`, widgets in `widgets/`. Styling `app.tcss`; install `install.sh`/`install.ps1`.

## Build & Test

`uv` for all Python/deps.

- `uv run python cli.py` — CLI entry.
- `uv run python app.py` — app during UI work.
- `uv run pytest -n auto` — test suite, parallel (all cores).
- `uv run coverage run -m pytest && uv run coverage report -m` — coverage (fail_under=90).
- `uv run ruff check .` — lint.
- `uv build` — build artifacts.

Prefix shell commands with `rtk` where practical (`rtk git status`).

## Architecture

Layered core (`core/`): DDD-style. High-level vs low-level — keep deps pointing inward.

- `core/domain/` — business rules: `entities/` (session), `policies/` (catalog, permission, role), `defaults/` (config, prompts, providers, linters, skills).
- `core/application/` — use-cases: `generation/`, `provider/`, `session/`, `rules/`, `skills/`, `linters/`.
- `core/infrastructure/` — implementation: `adapters/`, `mcp/`, `platform/`, `runtime/` (circuit_breaker, frontmatter, token_util, thinking_effort), `storage/`, `tasks/`.
- `core/adapters/` — external LLM providers (anthropic, gemini, ollama, openai). `core/base_provider/` holds provider internals (agent, compaction, errors, tools).
- `core/roles/` — assistant role apply/resolve/prompt/provider/tools.
- `core/` root — managers/config hitting multiple layers (role_registry, provider_manager, session_manager, permission_manager, models_catalog).

Widgets layering (`widgets/`):

- `widgets/app/` — app controllers/state (app, ai_controller, dispatch, role_service, session/status_state).
- `widgets/screens/` — user-facing screens. Reusable sub-widgets live in `widgets/presentation/{screens,widgets}`.
- `widgets/mixins/` — shared view behavior (actions, lifecycle, message_flow, session_persistence).
- `widgets/` root — core chat widgets (chat_input, chat_toolcall, status_footer, commands, chat_view).
- Utils in `widgets/utils/` (file_reader, lexer).

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
