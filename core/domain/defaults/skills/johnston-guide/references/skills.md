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
- `description`: Summary text displayed in system prompt `<available_skills>` catalog and CLI/UI listings.
- `hidden`: (Optional boolean, default `false`). If `true`, excluded from the system prompt catalog unless explicitly requested or viewed.

## Execution & Discovery
- **System Prompt Catalog**: All non-hidden skills are cataloged in the system prompt with their `name` and `description`.
- **On-Demand Inspection**: Agent inspects `SKILL.md` via `read` tool only when relevant to the user request.
- **CLI Listing**: Run `johnston --skills` to list available skills and scopes.
- **Interactive UI**: Use `/skills` slash command in the TUI to browse and inspect installed skills.
