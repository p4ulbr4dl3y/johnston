---
name: skill-creator
description: Create new Johnston skills, iterate on existing skills, structure multi-tier references, and optimize triggering descriptions. Use when users want to create a skill from scratch, edit or optimize an existing skill, or design test cases for skills.
---

# Skill Creator

Guide the user through creating, refining, and testing high-quality skills for Johnston.

## Core Workflow

```
Capture Intent -> Structure & Draft -> Verification -> Optimize Description -> Install
```

## 1. Capture Intent & Scope

Identify what the skill should accomplish and where it should live:

1. **Target Capability**: What specific problem or workflow does this skill solve?
2. **Scope**:
   - **Project skill** (`.johnston/skills/<skill-name>/`): specific to this repository/workspace.
   - **Global skill** (`~/.johnston/skills/<skill-name>/`): available across all projects.
3. **Trigger Context**: What prompts, keywords, file types, or tasks should activate it?
4. **Output Expectations**: Fixed template, code snippet, report, or interactive guide?

Use `ask_user` if requirements are ambiguous or require design choices from the user.

## 2. Structure & Progressive Disclosure

Skills use a 3-tier loading architecture to minimize token overhead:

```
<skill-name>/
├── SKILL.md                 # Tier 2: Core instructions & workflow (<500 lines)
├── references/              # Tier 3: Specialized docs loaded on-demand
│   ├── framework-a.md
│   └── framework-b.md
└── scripts/                 # Tier 3: Deterministic helper scripts (Python/bash)
```

### Rules of Architecture:
- **Tier 1 (Frontmatter)**: `name` and `description` are loaded into every turn's system prompt inside `<skills>`. Keep description concise (~20–40 words), covering both capabilities and triggers.
- **Tier 2 (SKILL.md)**: Target under 500 lines. Focus on decision trees, main steps, and pointers to references.
- **Tier 3 (References & Scripts)**: Split by domain/variant. If a workflow has repetitive data extraction or boilerplate generation, bundle a Python script in `scripts/` instead of asking the LLM to write it every turn.

## 3. Authoring SKILL.md

### Frontmatter Template
```markdown
---
name: my-skill
description: Concise summary of purpose. Use when user wants to [trigger A], [trigger B], or works with [files/tech X].
hidden: false
---
```

### Instruction Guidelines
- **Explain the "Why"**: Models reason better with context and intent than dogmatic `MUST`/`NEVER` shouting.
- **Provide Concrete Examples**: Use realistic input/output pairs to ground expected behavior.
- **Imperative Voice**: Direct, actionable steps (`Parse input`, `Validate schema`, `Output report`).
- **File System Safety**: Respect Johnston permission modes (`review`, `edits`, `yolo`).

## 4. Verification & Testing

Verify skill effectiveness using test prompts:

1. **Define 2-3 realistic test prompts**: representative tasks a real user would execute.
2. **Test execution via subagents**:
   - Use `invoke_subagent(title="Test <name> workflow", prompt="Execute task using skill at <path>", type="worker")`.
   - For comparative testing, run one subagent with the skill instructions and one baseline without the skill.
3. **Inspect output**:
   - Check if the subagent followed instructions without redundant questions.
   - If the subagent wrote repetitive utility scripts, extract them into `scripts/`.
4. **Refine instructions**:
   - Fix ambiguities or failure modes discovered during test runs.

## 5. Description Optimization

The `description` field is the primary routing mechanism that decides whether Johnston invokes the skill.

### Trigger Checklist:
- Does it contain the domain keywords (e.g. `fastapi`, `docker`, `migrations`)?
- Does it include explicit trigger verbs/phrases (`Use when...`, `create...`, `debug...`)?
- Is it narrow enough to prevent false positives (over-triggering on unrelated tasks)?
- Is it broad enough to prevent undertriggering when user doesn't use the exact skill name?

## 6. Saving and Verification in Johnston

1. Write files using `create`:
   - Project: `.johnston/skills/<name>/SKILL.md`
   - Global: `~/.johnston/skills/<name>/SKILL.md`
2. Inspect discovery:
   - CLI: `johnston skills` or `johnston skills --json` via `shell`.
   - TUI: Open `/skills` screen to verify registration and toggle `hidden` status with `Tab`.
3. Inform the user how to test:
   - Natural invocation via chat matching the description triggers.
   - Direct invocation: `/<skill-name> <task>`.
   - Non-interactive / headless run: `johnston run -s <name> "<task>"`.
