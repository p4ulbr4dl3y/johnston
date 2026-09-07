"""Subagent streaming helpers operating on the unified AgentSession model.

Subagent sessions are AgentSession records (kind="subagent") stored per-project
under sessions/<parent_id>.subagents/ via SessionStore.
"""

# Public facade: re-exports from the child modules so existing imports and
# ``unittest.mock.patch`` by full path keep working unchanged.
from core.application.session.stream_agent import (  # noqa: F401
    _sync_subagent_metrics,
    configure_agent,
    configure_subagent_agent,
    merge_subagent_metrics,
    sync_session_metrics,
)
from core.application.session.stream_followup import send_subagent_followup  # noqa: F401
from core.application.session.stream_runner import (  # noqa: F401
    _is_real_cancellation,
    _run_single_subagent_message,
    _safe_save,
    cancel_running_subagents,
    execute_session_turn,
    run_subagent_stream_bg,
)
from core.application.session.stream_steps import (  # noqa: F401
    record_session_step,
    record_subagent_step,
    stream_step_to_session_event,
)
