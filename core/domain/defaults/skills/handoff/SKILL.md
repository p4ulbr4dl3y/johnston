---
name: handoff
description: Summarize session progress, uncommitted changes, architectural decisions, and next steps for context transfer to a new session or developer. Use when user says /handoff, asks to prepare a handoff, or wants a session checkpoint.
hidden: true
---

# Session Handoff

Produce a high-density, actionable session handoff to transfer context into a fresh session without information loss.

## The Heuristic
> **"Provide everything the next agent needs to resume instantly without reading the entire previous conversation history."**

## Execution Workflow

1. Workspace State Check -> 2. Review Trajectory -> 3. Synthesize Handoff -> 4. Deliver

### Step 1: Workspace State Check
Gather empirical workspace truth before writing the summary:
1. **Git State**: Run `git status -s` and `git diff --stat` via `shell` to identify modified, added, or deleted files.
2. **Verification State**: Run the test runner or linter to verify whether the workspace is currently clean or broken.

### Step 2: Review Session Trajectory
Analyze what happened during the session:
- What was the initial user request and intent?
- What dead-ends were explored and discarded (to prevent the next agent from repeating them)?
- What technical decisions were made and why?

### Step 3: Structure the Handoff Document

Output the handoff in this structured format matching Johnston's compaction schema:

```markdown
# Session Handoff

### Objective
[1-2 sentences: primary goal + user intent + success criteria if stated]

### User Decisions & Preferences
[Architecture/style choices, explicit do/don't, "(none)" if none]

### Constraints
[Hard limits, sandbox, read-only, "do not modify X", or "(none)"]

### State
- Completed: [finished tasks with verification evidence; cite test names/exit codes]
- Active: [in-flight work; current investigation state]
- Pending: [tasks user deferred for later; "(none)" if none]
- Blocked: [blockers + EXACT error strings, or "(none)"]
- Failed approaches: [what was tried, why rejected, or "(none)"]

### Tool Output Anchors
[CRITICAL — preserve verbatim: exit codes, file:line refs, error strings, URLs, test names]

### Next Steps
1. [Single immediate action — the very next tool call or test run]
2. [Subsequent action]

### Open Questions
[Unanswered ambiguities, decisions deferred to user, or "(none)"]

### Key Files
- `path/to/file.py#L10-L25`: [why it matters, current state, last edit]
- `tests/test_foo.py`: [relevant test suite]

### Quick Resume Command
```bash
[Exact command to run tests or resume work, e.g. uv run pytest tests/path/test_foo.py -k test_name]
```
```

## Rules
- DENSE, FACTUAL, CONCISE. No conversational filler or preamble.
- Preserve EXACT paths, line numbers, error strings, exit codes, and test names.
- If a section has no content, write `(none)` — never omit a mandatory section.
- Ground state in actual `git status -s` and tool outputs.

### Step 4: Deliver & Storage Location
1. **Default Delivery**: Present the handoff directly in the chat response (avoids cluttering Git status with unrequested files).
2. **File Storage (when persisting to disk)**:
   - **Default File Path**: Write to `.johnston/HANDOFF.md` using `create` (keeps the project workspace clean and git-isolated).
   - **Root Override**: Write to `./HANDOFF.md` only if the user explicitly asks to save it in the repository root.
