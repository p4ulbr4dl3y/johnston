"""Public interface of the compaction package.

`from johnston.core.infrastructure.llm.base.compaction import X` resolves to
this module (a package directory wins over a same-named module file when both
exist), so all names are re-exported here to keep existing consumers working
unchanged. The stateful ``CompactionMixin`` lives in :mod:`compaction.mixin`.
"""
from johnston.core.infrastructure.llm.base.compaction.helpers import (
    _INSTRUCTION_PATTERNS,
    CHECKPOINT_CLOSE_TAG,
    CHECKPOINT_HEADER,
    CHECKPOINT_OPEN_TAG,
    CHECKPOINT_REDACTION_MARKER,
    DEFAULT_SUMMARY_TOKEN_BUDGET,
    REQUIRED_SUMMARY_SECTIONS,
    _clean_plan_items,
    _sanitize_summary_text,
    _strip_checkpoint,
    _summary_signature,
    _validate_summary_shape,
    _wrap_checkpoint,
    collect_user_messages,
    extract_plan_from_history,
    format_compaction_title,
    resolve_auto_compact_limit,
    should_compact,
)
from johnston.core.infrastructure.llm.base.compaction.mixin import CompactionMixin

__all__ = [
    "CHECKPOINT_CLOSE_TAG",
    "CHECKPOINT_HEADER",
    "CHECKPOINT_OPEN_TAG",
    "CHECKPOINT_REDACTION_MARKER",
    "DEFAULT_SUMMARY_TOKEN_BUDGET",
    "REQUIRED_SUMMARY_SECTIONS",
    "_INSTRUCTION_PATTERNS",
    "_clean_plan_items",
    "_sanitize_summary_text",
    "_strip_checkpoint",
    "_summary_signature",
    "_validate_summary_shape",
    "_wrap_checkpoint",
    "collect_user_messages",
    "extract_plan_from_history",
    "format_compaction_title",
    "resolve_auto_compact_limit",
    "should_compact",
    "CompactionMixin",
]
