---
name: handoff
description: Summarize session progress, uncommitted changes, architectural decisions, and next steps for context transfer to a new session or developer. Use when user says /handoff, asks to prepare a handoff, or wants a session checkpoint.
hidden: true
---

# Session Handoff (/handoff)

Produce a high-density, actionable session handoff to transfer context into a fresh session without information loss.

## The Heuristic
> **"Provide everything the next agent needs to resume instantly without reading the entire previous conversation history."**

---

## Execution Workflow

```
1. Workspace State Check -> 2. Review Trajectory -> 3. Synthesize Handoff -> 4. Deliver
```

---

### Step 1: Workspace State Check
Gather empirical workspace truth before writing the summary:
1. **Git State**: Run `git status -s` and `git diff --stat` via `shell` to identify modified, added, or deleted files.
2. **Verification State**: Run the test runner or linter to verify whether the workspace is currently clean or broken.

---

### Step 2: Review Session Trajectory
Analyze what happened during the session:
- What was the initial user request and intent?
- What dead-ends were explored and discarded (to prevent the next agent from repeating them)?
- What technical decisions were made and why?

---

### Step 3: Structure the Handoff Document

Output the handoff in this structured format:

```markdown
# Session Handoff: [Brief Task Title]

## 1. Goal
[1-2 sentences: what we set out to accomplish].

## 2. Completed Work
- [Component / File modified]: [Specific change made].
- [Tests added or updated].

## 3. Current Workspace State
- **Branch / Worktree**: `[branch name]`
- **Uncommitted Changes**: `[list of modified files]`
- **Test Status**: `[Passing / Failing - quote specific failing test if any]`

## 4. Key Decisions & Rationales
- **Decision**: [What was chosen].
  **Why**: [Technical reason or constraint].
- **Discarded Approaches**: [What was tried and why it failed].

## 5. Next Steps (Prioritized)
1. [Immediate next action item].
2. [Subsequent task].
3. [Edge cases or verification remaining].

## 6. Quick Resume Command
```bash
[Exact command to run tests or start app, e.g. uv run pytest tests/path/test_foo.py]
```
```

---

### Step 4: Deliver
1. Present the handoff directly in the chat response.
2. If the user explicitly requested saving to disk or working in a headless flow, write to `HANDOFF.md` or `.johnston/HANDOFF.md` using `create`.
