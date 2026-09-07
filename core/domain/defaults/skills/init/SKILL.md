---
name: init
description: Analyze repository and generate or update concise, high-signal AGENTS.md guidelines. Use when user says /init or asks to initialize project instructions.
hidden: true
---

# Project Initialization

Automate codebase discovery and generate a surgical, high-density `AGENTS.md` contributor guide for AI coding assistants.

## The Golden Heuristic
> **"Every line must answer: Would an agent get this wrong without help? If no, cut it."**
> 
> Exclude generic software advice ("write clean code", "handle errors gracefully", "do not commit API keys"), exhaustive file trees, and obvious language defaults. Target length: **200–400 words**.

## Execution Workflow

1. Pre-flight -> 2. Autonomous Survey -> 3. Command Verification -> 4. Gap-Fill -> 5. Generate

### Phase 1: Pre-flight Check
1. Check for existing instruction files:
   - Root `AGENTS.md`
   - Root `CLAUDE.md`
   - `.cursorrules`, `.cursor/rules/`, `.github/copilot-instructions.md`
2. **Strategy**:
   - If `AGENTS.md` (or `CLAUDE.md`) exists: update in place. Preserve verified repository-specific facts; strip fluff, stale claims, or overly verbose tutorials.
   - If absent: create fresh `AGENTS.md` at repository root.

### Phase 2: Autonomous Survey (Explorer Subagent)
Launch an autonomous explorer subagent using `invoke_subagent` to prevent main chat context bloat:
```python
invoke_subagent(
    title="Survey codebase for init",
    prompt="Analyze repo manifests, CI configs, entry points, linters, and git log. Return high-signal facts for AGENTS.md.",
    type="explorer"
)
```

The surveyor must inspect executable sources of truth first:
1. **CI Workflows**: `.github/workflows/`, GitLab CI, Makefile. These reveal the actual test, lint, and build commands executed in production.
2. **Package Manifests**: `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc. Note runtime versions and package managers (e.g. `uv`, `pnpm`, `cargo`).
3. **Formatters & Linters**: `ruff`, `eslint`, `biome`, `prettier`, `black`, `rustfmt`, `golangci-lint`. Look for non-standard line lengths, ignored rules, or strict type-check configs.
4. **Application Wiring**: Locate the real application entry points (e.g. `main.py`, `app.py`, `src/index.ts`) and major boundaries. Note how layers communicate.
5. **Git Conventions**: Run `git log -n 20 --oneline` via `shell` to determine commit message format (e.g. Conventional Commits, ticket prefixes).

### Phase 3: Command Verification
Before writing commands into `AGENTS.md`, verify them via `shell`:
- How to run the full test suite.
- **How to run a single test or focused file** (critical for AI agents to iterate fast).
- Lint and typecheck commands.
- Verify they exit with code 0 or return expected feedback. Trust verified commands over README claims.

### Phase 4: Gap-Fill (Ask User)
Only ask the user if the codebase cannot answer an essential operational detail:
- Undocumented deployment or PR branching conventions.
- Required external test services (Docker, local databases, mock servers).

Use `ask_user` for a single concise question batch. **Do NOT ask questions the code already answers.**

### Phase 5: Generate AGENTS.md

Use `create` (or `edit` if updating) to write `# Repository Guidelines` to `AGENTS.md`:

```markdown
# Repository Guidelines

[One paragraph: project purpose, language version, package manager, and entry points].

## Build & Test
- Build / run command.
- Test suite command (e.g. parallel flags, excluded suites).
- Focused single test command (e.g. `uv run pytest path/to/test.py -k test_name`).
- Linter / typecheck commands.

## Architecture
- Layer breakdown or package boundaries (3-5 bullet points).
- High-level data flow and entrypoint wiring.

## Style & Conventions
- Language version, package manager constraints (e.g. "use `uv` only").
- Code style, naming conventions, import ordering.
- Non-obvious gotchas or framework quirks.

## Testing Guidelines
- Testing frameworks and mocking libraries.
- Fast vs slow / timing-sensitive tests.

## Commits & PRs
- Commit message format (e.g. `type(scope): description` <= 72 chars).
- PR requirements (tests passing, linter passing).
```

## Completion Checklist
- [ ] Document is concise (200–400 words).
- [ ] Commands are verified and executable.
- [ ] Contains instructions for running a single test.
- [ ] Excludes obvious boilerplate and generic advice.
