# Johnston System Configuration & Architecture Guide

Johnston is configured via global settings in `~/.johnston/` and project-level overrides in `<project_root>/.johnston/`. Project-level configurations override global configurations with the same name.

---

## 1. Directory Structure & Precedence

```
~/.johnston/                        # Global configuration
├── config.json                     # Active provider, default model, settings
├── providers.json                  # Custom and configured LLM provider definitions
├── mcp.json                        # Global MCP server configurations
├── linters.json                    # Linter presets & enabled state
├── roles/*.md                      # Unified role definitions (modes + subagents)
├── rules/*.md                      # Global system prompt rules
├── skills/<skill_name>/SKILL.md    # Global skills
```

<project_root>/
├── .johnston/                      # Project-specific overrides
│   ├── mcp.json
│   ├── linters.json
│   ├── roles/*.md
│   ├── rules/*.md
│   └── skills/<skill_name>/SKILL.md
```

---

## 2. MCP Server Configuration (`mcp.json`)

Configure Model Context Protocol (MCP) servers to extend Johnston's toolset.

- **Global location:** `~/.johnston/mcp.json`
- **Project location:** `.johnston/mcp.json`
- **CLI Management:** `johnston --mcp`

### File Format Example
```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git"]
    },
    "big-toolkit": {
      "command": "node",
      "args": ["/path/to/server.js"],
      "env": {
        "API_KEY": "secret_key_here"
      },
      "disabled": false
    }
  }
}
```

---

## 3. Linter Configuration (`linters.json`)

Johnston can run fast, **syntax-only** linters after `create`/`edit` tool writes to catch broken code early. Presets are **disabled by default** (opt-in) so nothing is imposed on the user; enable them interactively with the `/linters` modal (or `/lint`) and they are stored in config.

- **Global location:** `~/.johnston/linters.json`
- **CLI Management:** `johnston --linters`

### Presets

| Linter | Languages / extensions | Install | Command |
|---|---|---|---|
| `python` | `.py` | uvx | `uvx ruff check -q --select E9,F` |
| `js` / `ts` | `.js .mjs .cjs .jsx` / `.ts .tsx` | npx | `npx --yes eslint@9 --no-config-lookup` |
| `js_biome` | JS/TS/JSX + `.css` | npx/global | `biome lint --only=correctness` |
| `rust` | `.rs` | system (rustc) | `rustc --edition 2021 --emit=metadata` |
| `c` / `cpp` | `.c .h` / `.cc .cpp .cxx .hpp .hh` | system (gcc) | `gcc -fsyntax-only` |
| `ruby` | `.rb` | system | `ruby -c` |
| `php` | `.php` | brew (heavy) | `php -l` |
| `json` | `.json` | system (jq) | `jq empty` |
| `yaml` | `.yaml .yml` | uvx | `uvx yamllint --no-warnings` |
| `toml` | `.toml` | uvx | `uvx taplo check` |

Presets are **syntax-only**: they detect parse errors and fatal issues, not style. System tools (rustc, gcc, ruby, php, jq) are detected via `which`; uvx/npx-managed tools are detected from the local tool cache. Only **enabled and available** linters run — missing ones are skipped silently. uvx/npx fetch the tool on first run, no manual install step needed.

### File Format Example

```json
{
  "linters": {
    "python": { "enabled": false },
    "custom-checker": {
      "cmd": ["my-lint", "--syntax", "{file}"],
      "extensions": [".myext"],
      "enabled": true
    }
  }
}
```

- `enabled: false` disables that linter.
- Custom entries accept `cmd` (with `{file}` / `{tmp}` placeholders, `{tmp}` expands to a writable scratch dir) and `extensions`. They are appended to the preset list.
- `{tmp}` — e.g. Rust's `--emit=metadata -o {tmp}/check.rmeta` needs a writable output path.

---

## 4. Roles: Execution Modes & Subagents (`roles/`)

Roles unify agent execution modes and subagent definitions into a single markdown format. The `scope` field controls where each role is usable.

- **Global location:** `~/.johnston/roles/<name>.md`
- **Project location:** `.johnston/roles/<name>.md`
- **CLI Management:** `johnston --roles` (all roles), `johnston --subagents` (subagent-scoped roles)

### Scope
- `any` (default): available as both execution mode and subagent type.
- `subagent_only`: usable only as `subagent_type` in `invoke_subagent`.
- `main_only`: usable only as main agent execution mode (not a subagent).

### Built-in Roles
- `worker`: Execution role — full write, edit, shell, and task tool access. Available as main-agent mode and `subagent_type` (`any`).
- `explorer`: Read-only Q&A, codebase research, and planning role. Available as main-agent mode and `subagent_type` (`any`).
- `orchestrator`: Orchestrator role that plans and delegates subtasks (`main_only`).

### Markdown Format Example (`reviewer.md`)
```markdown
---
name: reviewer
description: Code reviewer subagent
scope: subagent_only
tools: read, grep, glob
model: deepseek-v4-flash
---

Inspect git diffs and code changes. Focus on potential bugs, security issues, and style violations.
```

### Supported Frontmatter Fields
- `name` / `key` / `subagent_type`: Role identifier (defaults to filename).
- `description`: Summary of purpose.
- `scope`: `any`, `subagent_only`, or `main_only`.
- `tools` / `allowed_tools`: Comma-separated whitelist of permitted tool names.
- `disallowed_tools`: Comma-separated list of blocked tool names.
- `read_only`: Boolean flag blocking state-changing operations.
- `model`: Specific LLM model override for this role.
- `allowed_shell_commands`: Comma-separated list of permitted shell commands.
- `workspace_allowlist`: Comma-separated list of allowed workspace paths.

---

## 5. Rules & System Instructions (`rules/`)

Inject system prompt rules globally or per-project. Rules can be conditionally triggered by current execution mode or modified file globs.

- **Global location:** `~/.johnston/rules/<name>.md`
- **Project location:** `.johnston/rules/<name>.md`
- **CLI Management:** `johnston --rules`

### Markdown Format Example (`python_style.md`)
```markdown
---
name: python_style
modes: [worker, explorer]
globs: ["*.py", "src/**/*.py"]
description: Python PEP 8 & Ruff guidelines
---

- Target Python 3.10+.
- Keep line length under 120 characters.
- Run `uv run ruff check .` to verify changes.
```

### Frontmatter Filtering Rules
- `modes` / `mode`: List of execution modes (`worker`, `explorer`, or custom modes) where rule applies. If omitted, applies to all modes.
- `globs` / `glob`: File pattern matchers (e.g. `["*.py"]`). Rule activates when user edits or touches matching files.

---

## 6. LLM Provider Setup (`providers.json`)

Configure endpoints for LLM providers (OpenAI, Anthropic, Gemini, Ollama, OpenRouter, Groq, xAI, Mistral, Together AI, DeepInfra, Fireworks, Cerebras, Nvidia, GitHub Copilot, or custom OpenAI-compatible endpoints).

- **Global location:** `~/.johnston/providers.json`
- **CLI Management:** `johnston --models`

### File Format Example
```json
{
  "openai": {
    "key": "openai",
    "name": "OpenAI",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "api_type": "openai"
  },
  "custom_local": {
    "key": "custom_local",
    "name": "Local VLLM Server",
    "base_url": "http://localhost:8000/v1",
    "api_type": "openai",
    "model": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "models": ["Qwen/Qwen2.5-Coder-32B-Instruct"],
    "fetch_models": false
  }
}
```

### Supported API Types
- `openai`: Standard OpenAI Chat Completions API format.
- `anthropic`: Anthropic Claude Messages API format.
- `gemini`: Google Gemini REST API format.
- `ollama`: Local Ollama API endpoint.

---

## 7. Skills Management (`skills/`)

Skills bundle instruction sets and prompt templates into reusable markdown packages.

- **Global location:** `~/.johnston/skills/<name>/SKILL.md`
- **Project location:** `.johnston/skills/<name>/SKILL.md`
- **CLI Management:** `johnston --skills`

### Directory Layout
```
.johnston/skills/my-skill/
├── SKILL.md
├── scripts/
└── references/
```

### SKILL.md Example
```markdown
---
name: my-skill
description: Brief summary of skill capabilities
hidden: false
user_invocable: true
---

# Instructions for the agent
Detailed step-by-step guidance...
```

### Special Attributes & Multi-file Support
- `hidden` / `user_invocable`: Controls whether skill is visible in system prompt / list.
- **Multi-file Skills:** Auxiliary files (scripts/, references/) live inside the skill directory; the agent discovers them by reading the skill's `SKILL.md` and listing the directory contents.

---

## 8. Roles Overview (`roles/`)

Roles replace the legacy `modes/` and `subagents/` directories. See [Section 4](#4-roles-execution-modes--subagents-roles) for the unified format.
