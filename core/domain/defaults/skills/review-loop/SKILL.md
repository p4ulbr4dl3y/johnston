---
name: review-loop
description: Autonomous defect-first review-fix loop. Spawns stateless reviewer subagents to audit uncommitted changes until approval or max iterations reached. Use when user asks for a review loop, self-healing code review, or iterative fix until approval.
---

# Review Loop

Execute an automated Actor-Critic cycle: Main agent writes and fixes code directly in the workspace, while isolated, stateless `reviewer` subagents independently audit changes until approval.

## The Heuristic
> **"Never let the author approve their own code. The reviewer must be completely blind to previous iterations, author rationales, and excuses."**

## Execution Workflow

1. Pre-flight Baseline -> 2. Review-Fix Loop (max 3) -> 3. Final Report

### Step 1: Pre-flight Baseline
1. Identify target files and review scope via `shell`:
   - Working tree: `git status -s` and `git diff`
   - Branch diff: `git diff origin/main...HEAD`
2. Run project tests and linters via `shell` to confirm baseline health. If existing tests fail, fix them before starting the review cycle.

### Step 2: The Review-Fix Loop
Run maximum **3 iterations**:

```
Iteration N (1..3):
  [1. Run Tests via shell] ──(fail)──> [Main Agent Fixes] ──> retry
          │ (pass)
          ▼
  [2. invoke_subagent(type="reviewer")]
          │
          ▼
  [3. Parse Reviewer Output]
          ├── VERDICT: APPROVE ──────────> [BREAK LOOP -> Step 3]
          └── VERDICT: REJECT ───────────> [Extract P0/P1/P2 Blockers]
                                                 │
                                                 ▼
                                     [4. Main Agent Fixes Code]
                                                 │
                                                 ▼
                                         (Next Iteration)
```

#### Launching the Reviewer Subagent
Use the builtin `reviewer` role via `invoke_subagent`:

```python
invoke_subagent(
    title="Code Review - Iteration N",
    prompt="Audit current changes via git diff and relevant tests. Return findings with severity P0-P3 and final VERDICT.",
    type="reviewer",
)
```

*Note: The `reviewer` role is read-only (`read_only: true`), runs directly in the current workspace without worktree branching, and enforces defect-first rules (>80% confidence, ignore style nits, require provable impact).*

### Step 3: Handling Verdicts

1. **If `VERDICT: APPROVE`**:
   - Run full test suite one final time via `shell`.
   - Exit loop immediately.
   - Present a concise summary of changes and review confirmation to the user.

2. **If `VERDICT: REJECT`**:
   - Filter findings: ignore `[P3]` nits. Focus exclusively on `[P0]`, `[P1]`, and `[P2]` defects.
   - Main agent applies minimal surgical fixes using `edit` / `create`.
   - Verify fixes with test suite runs via `shell`.
   - Advance iteration counter and launch a fresh reviewer subagent.

3. **If Iteration 3 finishes with `VERDICT: REJECT`**:
   - Break loop to prevent token exhaustion and oscillation.
   - Present remaining blockers to the user with concrete recommendations for manual resolution.

## Loop Invariants
- **Stateless Reviewer**: Never pass previous review transcripts to new reviewer subagents. Each reviewer must evaluate the codebase with fresh eyes.
- **Diff Grounding**: Findings must strictly cite lines introduced by the reviewed change. Pre-existing issues outside the diff are out of scope.
- **Hard Cap**: Exactly 3 iterations maximum.
