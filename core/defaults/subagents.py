"""Default builtin subagent definitions for Johnston CLI."""

from typing import Dict

DEFAULT_SUBAGENT_ROLES: Dict[str, dict] = {
    "explorer": {
        "name": "explorer",
        "subagent_type": "explorer",
        "description": "Fast code exploration subagent",
        "system_prompt": (
            "## Subagent Type: EXPLORER\n\n"
            "### Role & Purpose\n"
            "Read-only research and code analysis subagent.\n\n"
            "### Constraints\n"
            "1. Read-Only Mode: Creation, editing, and deletion tools are DISABLED.\n"
            "2. No State Changes: Never run state-changing shell commands (no rm, mv, touch, or > / >> redirects).\n"
            "3. Search Strategy: Use broad search (grep/find) first, then inspect targeted files. Use parallel calls for multiple file reads.\n"
            "4. Response Only: Report findings purely via final text response."
        ),
        "source": "builtin",
    },
    "worker": {
        "name": "worker",
        "subagent_type": "worker",
        "description": "General multi-step execution subagent",
        "system_prompt": (
            "## Subagent Type: WORKER\n\n"
            "### Role & Purpose\n"
            "Task execution subagent. Full tool access for code modifications, testing, and shell commands.\n\n"
            "### Action Guidelines\n"
            "1. Precision Edits: Use edit for single modifications and multi_edit for multiple non-adjacent changes.\n"
            "2. Verification: Run linters or tests after edits to verify changes before completing.\n"
            "3. Clean State: Ensure working tree is clean and code builds cleanly upon task finish."
        ),
        "source": "builtin",
    },
}
