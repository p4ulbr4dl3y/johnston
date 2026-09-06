"""Pure-core session actions — NO widget/Textual imports.

Functions: new_session, compact_session, rewind_session.
Callers (commands.py) handle UI orchestration (push_screen, callback, focus, notify).
"""
import logging

from core.application.session.lifecycle import (  # noqa: F401
    CompactionOutcome,
    CompactionStatus,
    CompactionTokens,
    _parse_compaction_tokens,
    compact_session,
    new_session,
)
from core.application.session.rewind import (  # noqa: F401
    RewindEntry,
    _cleanup_rewound_shell_tasks,
    _cleanup_rewound_subagents,
    _touched_files,
    _truncate_transcript,
    find_selected_user_message,
    get_rewind_git_stats,
    get_session_diff,
    reset_token_counters,
    restore_plan_from_messages,
    rewind_session,
    truncate_agent_history,
)

logger = logging.getLogger("core.application.session.actions")

__all__ = [
    "CompactionOutcome",
    "CompactionStatus",
    "CompactionTokens",
    "RewindEntry",
    "_cleanup_rewound_shell_tasks",
    "_cleanup_rewound_subagents",
    "_parse_compaction_tokens",
    "_touched_files",
    "_truncate_transcript",
    "compact_session",
    "find_selected_user_message",
    "get_rewind_git_stats",
    "get_session_diff",
    "new_session",
    "reset_token_counters",
    "restore_plan_from_messages",
    "rewind_session",
    "truncate_agent_history",
]
