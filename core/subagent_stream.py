"""Backwards-compatible re-export. Canonical location: core.application.session.stream"""
from core.application.session.stream import (  # noqa: F401
    _apply_provider_config,
    _run_single_subagent_message,
    _safe_save,
    apply_subagent_role,
    cancel_running_subagents,
    configure_subagent_agent,
    merge_subagent_metrics,
    record_subagent_step,
    run_subagent_stream_bg,
)

__all__ = [
    "apply_subagent_role",
    "cancel_running_subagents",
    "configure_subagent_agent",
    "merge_subagent_metrics",
    "record_subagent_step",
    "run_subagent_stream_bg",
]
