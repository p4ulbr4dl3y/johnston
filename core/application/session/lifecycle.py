"""Pure-core session lifecycle actions — NO widget/Textual imports.

Functions: new_session, compact_session.
Callers (commands.py) handle UI orchestration (push_screen, callback, focus, notify).
"""
import asyncio
import inspect
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from core.base_provider.compaction import format_compaction_title
from core.domain.ports.storage import SessionStorePort

logger = logging.getLogger("core.application.session.actions")


class CompactionStatus(Enum):
    """Terminal outcome of a compaction attempt."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CompactionTokens:
    """Structured token counts reported by the compactor summary."""

    before: Optional[int] = None
    after: Optional[int] = None


@dataclass
class CompactionOutcome:
    """Structured result of a session compaction, parsed once from the compactor."""

    status: CompactionStatus
    message: str = ""
    title: str = ""
    tokens: Optional[CompactionTokens] = None

    @property
    def success(self) -> bool:
        return self.status == CompactionStatus.COMPLETED


def _parse_compaction_tokens(msg: str) -> CompactionTokens:
    """Parse the ``(X → Y tokens)`` section of a compaction message exactly once.

    The compactor currently reports tokens inside a parenthesised tail
    (e.g. ``... (12,345 → 6,789 tokens)``). Called in a single place so the
    string-parse is not duplicated across the application layer.
    """
    import re

    if "(" not in msg or ")" not in msg:
        return CompactionTokens()
    tokens_info = msg[msg.find("(") + 1: msg.rfind(")")]
    # Match standalone token quantities like 1,234 / 12k / 3M (not the word "tokens").
    nums = []
    for part in tokens_info.split("→"):
        text = part.strip()
        mult = 1
        m = re.search(r"[\d.,]+\s*[kKmM]?", text)
        if m:
            raw = m.group(0)
            num = "".join(ch for ch in raw if ch.isdigit())
            if not num:
                continue
            if raw.lower().rstrip().endswith("m"):
                mult = 1_000_000
            elif raw.lower().rstrip().endswith("k"):
                mult = 1_000
            nums.append(int(num) * mult)
    if len(nums) >= 2:
        return CompactionTokens(before=nums[0], after=nums[1])
    return CompactionTokens()


# ---------------------------------------------------------------------------
# new_session
# ---------------------------------------------------------------------------

async def new_session(
    sm: SessionStorePort,
    agent: Any,
    *,
    cancel_workers: Callable[[], None],
    kill_all_tasks: Callable[[], None],
    cancel_subagents: Callable[[], None],
) -> str:
    """Create a new main session — pure logic, no UI.

    * Cancels pending UI workers (callers passes cancel_workers).
    * Kills all app task-manager tasks.
    * Cancels running subagents for current session.
    * Generates a fresh session id, creates it in the store.
    * Clears agent history.

    Returns the new session id.  The UI caller is responsible for
    setting ``is_generating``, clearing ``message_queue``, updating
    ``current_session_id``, removing chat_view children, showing
    welcome, and refreshing the status footer.

    This function does NOT import Textual or any widget module.
    """
    cancel_workers()
    kill_res = kill_all_tasks()
    if inspect.isawaitable(kill_res):
        await kill_res
    cancel_subagents()

    new_id = sm.generate_session_id()
    sm.create_main(new_id)

    if agent is not None:
        if hasattr(agent, "clear_history"):
            agent.clear_history()
        elif hasattr(agent, "history"):
            agent.history = []
        if hasattr(agent, "role"):
            agent.role = "worker"
    return new_id


# ---------------------------------------------------------------------------
# compact_session
# ---------------------------------------------------------------------------

async def compact_session(
    agent: Any,
    *,
    save_session_cb: Callable[[], None],
    on_begin: Callable[[], None],
    on_divider_update: Callable[[str], None],
    refresh_footer_cb: Callable[[], None],
    session: Optional[Any] = None,
) -> CompactionOutcome:
    """Compact agent history.

    Calls ``agent.compact_history()`` and returns a structured
    :class:`CompactionOutcome` (status/message/title/tokens).
    UI side-effects (divider creation, save, is_generating flag) are left
    to the caller via callbacks so this stays pure-core.

    * ``save_session_cb`` — called after compaction (success or failure).
    * ``on_begin`` — called before compaction (e.g. set is_generating=True,
      create divider widget).
    * ``on_divider_update(title)`` — called after compaction to update the
      divider title in the UI.
    * ``refresh_footer_cb`` — called after successful compaction to refresh
      the status footer.
    * ``session`` — optional session entity to record the compaction event divider before saving.
    """
    if not agent:
        return CompactionOutcome(status=CompactionStatus.FAILED, message="No active agent found")

    if not hasattr(agent, "compact_history"):
        return CompactionOutcome(
            status=CompactionStatus.FAILED, message="Active agent does not support context compaction"
        )

    on_begin()

    try:
        success, msg = await agent.compact_history()
        if success:
            tokens = _parse_compaction_tokens(msg)
            title = format_compaction_title(msg)
            outcome = CompactionOutcome(
                status=CompactionStatus.COMPLETED, message=msg, title=title, tokens=tokens
            )
            if session is not None:
                from core.domain.entities.session import record_session_compaction

                record_session_compaction(session, title)
            on_divider_update(title)
            refresh_footer_cb()
        else:
            outcome = CompactionOutcome(status=CompactionStatus.FAILED, message=msg)
            if session is not None:
                from core.domain.entities.session import record_session_compaction

                record_session_compaction(session, "Compaction Failed")
            on_divider_update("Compaction Failed")
        return outcome
    except asyncio.CancelledError:
        if session is not None:
            from core.domain.entities.session import record_session_compaction

            record_session_compaction(session, "Compaction Cancelled")
        on_divider_update("Compaction Cancelled")
        raise
    finally:
        save_session_cb()
