---
name: goal
description: Relentless autonomous execution toward a complex objective. Drives execution without premature stopping, tracks milestones via update_plan, and verifies completion evidence. Use when user says /goal, assigns an overnight task, or requires an autonomous multi-step push.
hidden: true
---

# Goal Execution

Drive a multi-step objective with relentless autonomy. Do not yield or stop prematurely until the goal is fully achieved, provably verified by tests, or blocked by critical missing user input.

## The Heuristic
> **"Do not stop after completing a single step or narrating your intent. Execute continuously until the acceptance criteria are 100% met."**

## Execution Workflow

1. Acceptance Criteria & Plan -> 2. Autonomous Execution -> 3. Adversarial Verification -> 4. Completion Report

### Phase 1: Acceptance Criteria & Plan
1. Parse the user objective and extract concrete, testable criteria:
   - What functional behavior must work?
   - What tests or benchmarks must pass?
   - What constraints must be respected?
2. Initialize the task list using `update_plan`:
   - Break work into 3–7 discrete milestones.
   - Set the first milestone to `in_progress`.

### Phase 2: Autonomous Execution Loop
Iterate relentlessly through the plan:
1. Apply surgical changes using `edit` (or `create` for new files).
2. Use `invoke_subagent` for parallel research, isolated investigations, or heavy tasks.
3. Update `update_plan` after completing each milestone (`completed` status).
4. If a test fails or an error occurs:
   - Formulate a concrete hypothesis.
   - Apply a surgical fix and rerun immediately.
   - Do NOT stop to ask the user how to fix standard coding bugs — solve them autonomously.

### Phase 3: Adversarial Verification
Before declaring the goal achieved:
1. Run the project test suite and linter via `shell`.
2. Probe boundary conditions: edge inputs, nulls, empty states, concurrency.
3. Confirm that no regressions were introduced to existing codebase behavior.

### Phase 4: Completion Report
Output a factual, dense completion summary:
- **Objective**: Stated goal.
- **Evidence**: Executed commands, test results, and exit codes proving success.
- **Key Files Modified**: `path/to/file.ext#L10-L45`.
- **Residual Risks**: Any remaining limitations or follow-up items.

## Stopping Invariants

### When You MUST Keep Going:
- An edit completed successfully -> proceed directly to the next milestone.
- A test failed -> inspect error, fix, and rerun.
- A command exited 0 -> move to the next step without pausing for confirmation.
- You feel the urge to say "I have implemented X, let me know if you want me to do Y" -> **DO Y IMMEDIATELY**.

### When You MUST Stop:
1. All acceptance criteria are met and verified by commands.
2. A required architectural decision cannot be resolved from the codebase (use `ask_user`).
3. An unrecoverable external dependency blocker occurs (missing credentials, network outage).
