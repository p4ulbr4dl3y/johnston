# Skills Reference

## Overview
Skills are modular packages of domain knowledge, specialized instructions, reference docs, and scripts that extend Johnston's capabilities.

## Locations
- Global skills: `~/.johnston/skills/<skill-name>/`
- Project skills: `.johnston/skills/<skill-name>/`
- Bundled default skills: provisioned into global directory on first launch.

Precedence: Project-level skills override global skills with the same name.

## Directory Structure
```
<skill-name>/
├── SKILL.md                 # Required: Entrypoint with YAML frontmatter & markdown instructions
├── references/              # Optional: Specialized on-demand reference documentation
│   ├── topic1.md
│   └── topic2.md
└── scripts/                 # Optional: Executable helper scripts
```

## Frontmatter Format (`SKILL.md`)
```markdown
---
name: skill-name
description: Clear, concise summary of what this skill does and when to activate it.
hidden: false
---

# Skill Instructions
Detailed guidelines and workflows...
```

### Frontmatter Fields
- `name`: Unique skill identifier (defaults to directory name).
- `description`: Summary text displayed in system prompt `<skills>` catalog and CLI/UI listings. If omitted, falls back to the first non-empty Markdown line without `#`.
- `hidden`: (Optional boolean, default `false`). If `true`, excluded from the system prompt catalog unless explicitly requested or viewed.

## Execution & Discovery
- **System Prompt Catalog**: All non-hidden skills are cataloged in the system prompt inside the `<skills>` block with priority ordering (project > global > bundled):
  ```
  <skills>
  Skills: read SKILL.md via read if relevant. Project overrides global overrides bundled.
  - skill-name (/absolute/path/to/SKILL.md): Clear summary of what this skill does.
  </skills>
  ```
- **On-Demand Inspection**: Agent inspects `SKILL.md` via `read` tool only when relevant to the user request.
- **CLI Listing & Execution**:
  - `johnston skills`: list available skills, locations, and scopes.
  - `johnston skills --json`: output structured JSON catalog.
  - `johnston run -s <skill-name> "<prompt>"`: run headless session with pre-loaded skill (supports multiple `-s`).
- **Interactive UI**:
  - Use `/skills` slash command in the TUI to open the visual skill browser.
  - Press `Tab` in the modal to toggle `hidden: true/false` on disk.
  - Press `Enter` on a skill to paste `/<skill-name> ` into the chat input.
- **Direct Invocation**:
  - Use `/<skill-name> <prompt>` in chat. Johnston injects the entire `SKILL.md` inside a `<skill name="..." path="...">` XML block into the current prompt turn, bypassing tier-2 discovery.
  - Chaining supported: `/<skill-1> /<skill-2> <prompt>` activates multiple skills simultaneously.

## Skill Design Methodology & Best Practices

### Progressive Disclosure
Skills use a 3-tier context loading architecture to optimize token usage:
1. **Tier 1 — Catalog Metadata** (`name` + `description`):
   - Injected into every turn's system prompt inside `<skills>` (~50–100 tokens per skill).
   - Serves as the agent's routing directory to decide if a skill is needed.
2. **Tier 2 — Main Instructions** (`SKILL.md` body):
   - Loaded on-demand via `read(path="...")` only when the agent determines relevance.
   - Recommended size: `< 500 lines`. Focus on core workflow, decision trees, and selection logic.
3. **Tier 3 — Deep References & Scripts** (`references/`, `scripts/`):
   - Sub-documents (`references/foo.md`) are read only when diving into specific frameworks or domains.
   - Reusable deterministic logic belongs in `scripts/` (executed via `shell` or imported, saving reasoning tokens).

### Writing Effective Descriptions
- `description` in YAML frontmatter is the primary triggering mechanism.
- Include both **what** the skill does AND **specific trigger contexts/phrases** (e.g. "Use when user asks to analyze Dockerfiles, configure container builds, or debug multi-stage images").
- Avoid generic descriptions like "Helps with python"; specify domains, libraries, and problems.

### Authoring Rules of Thumb
- **Explain the "Why"**: Give models the rationale and mental model rather than rigid `ALWAYS`/`NEVER` constraints.
- **Factor Large Docs**: When `SKILL.md` approaches 500 lines, extract domain variants or deep schemas into `references/<topic>.md`.
- **Crystallize Common Scripts**: If multiple prompts repeat similar helper scripts or complex pipelines, bundle the script into `scripts/` and reference it from `SKILL.md`.
- **Domain Organization**:
  ```
  cloud-deploy/
  ├── SKILL.md                 # Decision tree and workflow selection
  └── references/
      ├── aws.md               # Loaded only when deploying to AWS
      ├── gcp.md               # Loaded only when deploying to GCP
      └── azure.md             # Loaded only when deploying to Azure
  ```

