---
name: review-loop
description: Autonomous defect-first review-fix loop. Spawns stateless reviewer subagents to audit uncommitted changes or target modules until approval or max iterations. Use when user asks for a review loop, self-healing code review, audit of a subsystem, or iterative fixes.
---

# Review Loop

Execute an automated Actor-Critic cycle: Main agent coordinates and fixes code directly (or delegates large refactors to worker subagents), while isolated, stateless `reviewer` subagents independently audit changes until approval.

## The Heuristic
> **"Never let the author approve their own code. The reviewer must be completely blind to previous iterations, author rationales, and excuses. Code and tests must speak for themselves."**

## Execution Workflow

```
1. Target Scope & Baseline -> 2. Review-Fix Loop (max 3) -> 3. Final Report
```

### Step 1: Pre-flight & Scope Resolution

1. **Resolve Review Scope**:
   - **User argument provided** (e.g. `/review-loop <path/module>`): Target specified files/modules directly.
   - **Uncommitted changes exist**: Use working tree (`git status -s` and `git diff`).
   - **Branch diff exists**: Use branch changes (`git diff origin/main...HEAD`).
   - **Clean working tree & no argument**: Ask user for target scope via `ask_user`. **DO NOT** scan `git log` or speculate.
2. **Baseline Health**: Run project tests and linters via `shell`. If existing tests fail, fix them before starting the review cycle.

### Step 2: The Review-Fix Loop (max 3 iterations)

```
Iteration N (1..3):
  [1. Run Tests via shell] ──(fail)──> [Fix Baseline]
          │ (pass)
          ▼
  [2. invoke_subagent(role="reviewer")] ──> Yield turn & wait for runtime notification
          │
          ▼
  [3. Parse Reviewer Output]
          ├── VERDICT: APPROVE ──────────> [BREAK LOOP -> Step 3]
          └── VERDICT: REJECT ───────────> [Extract P0/P1/P2 Blockers (Ignore P3)]
                                                 │
                                                 ▼
                                     [4. Apply Surgical Fixes]
                                        ├── Small: edit directly
                                        └── Large: invoke_subagent(role="worker") -> git merge
                                                 │
                                                 ▼
                                     [5. Address False Positives via Code/Tests]
                                                 │
                                                 ▼
                                         (Next Iteration)
```

#### 1. Launching the Reviewer Subagent
Use the builtin `reviewer` role via `invoke_subagent`:

```python
invoke_subagent(
    title="Review & Verification - Iteration N",
    task="Audit changes in <scope> via git diff/files and execute adversarial verification via shell (probe edge cases, boundary inputs, failure paths). Return findings with severity P0-P3 and final VERDICT.",
    role="reviewer",
)
```
*Yield turn immediately after launch. Await runtime `<notification>` before continuing.*

#### 2. Handling Findings & False Positives
- **Filter findings**: Ignore `[P3]` nits. Focus exclusively on `[P0]`, `[P1]`, and `[P2]` defects.
- **False Positives (No Excuses in Prompt)**:
  - **NEVER** pass author explanations or previous review disputes to the next reviewer.
  - If a finding is invalid, make the code self-evident: add an explicit unit test, assertion, or type hint. Clean reviewer will run tests and self-clear.

#### 3. Applying Fixes (Context Preservation)
- **Small fixes**: Main agent edits directly using `edit` / `create`.
- **Large fixes / multi-file refactors**: Prevent main context exhaustion by delegating to `invoke_subagent(role="worker")`. Worker executes in an isolated git worktree; apply with `git merge <subagent-branch>` upon completion.
- Verify fixes locally with test suite runs via `shell` before next iteration.

### Step 3: Terminal States

1. **If `VERDICT: APPROVE`**:
   - Run full test suite one final time via `shell`.
   - Present concise summary of changes and review verification to the user.
2. **If Iteration 3 finishes with `VERDICT: REJECT`**:
   - Break loop immediately (hard cap reached).
   - Present remaining blockers to the user for manual review and decision.

## Loop Invariants

- **Stateless Reviewer**: Never pass previous review transcripts or author rationales to new reviewers. Each reviewer sees only code and tests with fresh eyes.
- **Adversarial Verification**: Reading code is not verification. Reviewer must actively run tests and probe edge cases via `shell` before approving.
- **Fail-Fast Scope**: If working tree is clean and no scope is specified, halt and prompt user. No blind `git log` crawling.
- **Context Economy**: Delegate heavy code rewrites to worker subagents.
- **Hard Cap**: Exactly 3 iterations maximum.
