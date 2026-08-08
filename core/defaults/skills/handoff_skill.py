"""Default handoff skill definition."""

DEFAULT_HANDOFF_SKILL_CONTENT = """---
name: handoff
description: Session Continuation Handoff Note. Summarizes current session state, modified files, completed steps, and next actions for seamless continuation.
---

# Session Continuation Handoff Note

Generate a clean handoff summary for continuing work in a future session.

## Summary Structure
1. **Goal / Objective**: Brief description of the task.
2. **Completed Actions**: Key changes made and tests run.
3. **Files Modified**: Bullet list of modified files.
4. **Current Status**: Pass/fail state, open issues.
5. **Next Steps**: Exact actions for the next agent session.
"""
