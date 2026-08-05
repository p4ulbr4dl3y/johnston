# Johnston System Configuration & Architecture Guide

Johnston is configured via global settings in `~/.johnston/` and project-level overrides in `<project_root>/.johnston/`. Project-level configurations override global configurations with the same name.

---

## 1. Directory Structure & Precedence

```
~/.johnston/                        # Global configuration
├── config.json                     # Active provider, default model, settings
├── providers.json                  # Custom and configured LLM provider definitions
├── mcp.json                        # Global MCP server configurations
├── subagents/definitions/*.md      # Custom subagent definitions
├── rules/*.md                      # Global system prompt rules
├── skills/<skill_name>/SKILL.md    # Global skills
└── modes/*.md                      # Custom execution modes

<project_root>/
├── .johnston/                      # Project-specific overrides
│   ├── mcp.json
│   ├── subagents/*.md
│   ├── rules/*.md
│   ├── skills/<skill_name>/SKILL.md
│   └── modes/*.md
```

---

## 2. MCP Server Configuration (`mcp.json`)

Configure Model Context Protocol (MCP) servers to extend Johnston's toolset.

- **Global location:** `~/.johnston/mcp.json`
- **Project location:** `.johnston/mcp.json`
- **CLI Management:** `johnston --mcp`

### Tool Loading Modes: `eager` vs `lazy`

Each MCP server operates in one of two tool loading modes:

1. **`eager` (Default):**
   - Tools are registered as native LLM functions (e.g. `mcp_<server_name>_<tool_name>`).
   - Complete JSON schemas are passed in every prompt.
   - Ideal for frequently used, lightweight servers.

2. **`lazy`:**
   - Tools are **not** loaded as full JSON schemas into context.
   - Johnston injects a lightweight summary block (`<mcp_servers>`) listing available servers and tools.
   - The LLM invokes tools on demand using the universal `call_mcp` wrapper.
   - Ideal for large MCP servers (e.g. documentation, search toolkits) to minimize token consumption.

### File Format Example
```json
{
  "mcpServers": {
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git"],
      "mode": "eager"
    },
    "big-toolkit": {
      "command": "node",
      "args": ["/path/to/server.js"],
      "mode": "lazy",
      "env": {
        "API_KEY": "secret_key_here"
      },
      "disabled": false
    }
  }
}
```

---

## 3. Custom Subagent Definitions (`subagents/`)

Subagents run autonomous sub-tasks in isolated conversation contexts.

- **Global location:** `~/.johnston/subagents/definitions/<name>.md`
- **Project location:** `.johnston/subagents/<name>.md`
- **CLI Management:** `johnston --subagents`

### Built-in Subagents
- `explore`: Read-only, fast codebase research subagent.
- `general`: Multi-step execution subagent.

### Markdown Format Example (`reviewer.md`)
```markdown
---
name: reviewer
description: Code reviewer subagent
tools: read, grep, glob
model: deepseek-v4-flash
---

## Subagent Mode: REVIEWER

Inspect git diffs and code changes. Focus on potential bugs, security issues, and style violations.
```

### Supported Frontmatter Fields
- `name`: Subagent identifier (defaults to filename).
- `description`: Summary of purpose.
- `tools`: Comma-separated list of permitted tool names.
- `model`: Specific LLM model override for this subagent.

---

## 4. Rules & System Instructions (`rules/`)

Inject system prompt rules globally or per-project. Rules can be conditionally triggered by current execution mode or modified file globs.

- **Global location:** `~/.johnston/rules/<name>.md`
- **Project location:** `.johnston/rules/<name>.md`
- **CLI Management:** `johnston --rules`

### Markdown Format Example (`python_style.md`)
```markdown
---
name: python_style
modes: [action, explore]
globs: ["*.py", "src/**/*.py"]
description: Python PEP 8 & Ruff guidelines
---

- Target Python 3.10+.
- Keep line length under 120 characters.
- Run `uv run ruff check .` to verify changes.
```

### Frontmatter Filtering Rules
- `modes` / `mode`: List of execution modes (`action`, `explore`, or custom modes) where rule applies. If omitted, applies to all modes.
- `globs` / `glob`: File pattern matchers (e.g. `["*.py"]`). Rule activates when user edits or touches matching files.

---

## 5. LLM Provider Setup (`providers.json`)

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

## 6. Skills Management (`skills/`)

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
- **Multi-file Skills:** Johnston scans subdirectories inside the skill directory and injects a `<skill_files>` file tree index into the prompt so the agent can discover auxiliary reference files.

---

## 7. Custom Execution Modes (`modes/`)

Define isolated execution modes to restrict or customize agent behavior (e.g. read-only exploration, architect planning mode).

- **Global location:** `~/.johnston/modes/<name>.md`
- **Project location:** `.johnston/modes/<name>.md`
- **CLI Management:** `johnston --modes`

### Built-in Modes
- `action`: Full read, write, shell, and task execution permissions.
- `explore`: Read-only mode. File creation/edits are blocked; state-changing shell commands (e.g. `rm`, `git commit`, `>`) are strictly forbidden.

### Custom Mode Example (`architect.md`)
```markdown
---
key: architect
name: Architect
description: High-level design & architecture planning mode
read_only: true
disallowed_tools: [create, edit, multi_edit]
---

## Execution Mode: ARCHITECT

You are in high-level architecture planning mode. Analyze code structure, propose design patterns, and output plans. Do not execute file edits directly.
```

### Mode Parameters
- `key`: Unique mode key (e.g. `architect`).
- `name`: Display name.
- `read_only`: Boolean flag blocking state-changing operations.
- `disallowed_tools`: List of specific tool names disabled in this mode.
