"""Pure-core session actions — NO widget/Textual imports.

Functions: new_session, compact_session, rewind_session.
Callers (commands.py) handle UI orchestration (push_screen, callback, focus, notify).
"""
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from core.domain.policies.messages import (
    count_history_user_turns,
    drop_stale_system_notes,
    find_visible_user_cutoff,
)
from core.session_manager import SessionStore

logger = logging.getLogger(__name__)


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
    sm: SessionStore,
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
    await kill_all_tasks()
    cancel_subagents()

    new_id = sm.generate_session_id()
    sm.create_main(new_id)

    agent.clear_history()
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
            title = "Session Compacted"
            if tokens.after is not None:
                title = f"Session Compacted ({msg[msg.find('(') + 1: msg.rfind(')')]})"
            outcome = CompactionOutcome(
                status=CompactionStatus.COMPLETED, message=msg, title=title, tokens=tokens
            )
            on_divider_update(title)
            refresh_footer_cb()
        else:
            outcome = CompactionOutcome(status=CompactionStatus.FAILED, message=msg)
            on_divider_update("Compaction Failed")
        return outcome
    except asyncio.CancelledError:
        on_divider_update("Compaction Cancelled")
        raise
    finally:
        save_session_cb()


# ---------------------------------------------------------------------------
# get_rewind_git_stats
# ---------------------------------------------------------------------------

@dataclass
class RewindEntry:
    """A single rollback candidate: index, user message text, git stat and changed files."""

    index: int
    text: str
    git_stats: str = ""
    changed_files: list[str] = field(default_factory=list)


async def get_rewind_git_stats(
    current_session_id: str | None,
    user_msgs: list[tuple[int, str]],
    project_path: str | None,
    checkpoint_manager: Optional[Any] = None,
) -> list[RewindEntry]:
    """Fetch git-checkpoint stats for each user message in the rewind list.

    Returns a list of :class:`RewindEntry` where ``git_stats`` is a formatted
    string like '+12 / -4', 'no changes', or ''.
    """
    from core.domain.ports.checkpoint import get_checkpoint_manager

    cm = checkpoint_manager or get_checkpoint_manager()
    msgs_with_stats: list[RewindEntry] = []
    checkpoints_enabled = False

    try:
        checkpoints_enabled = await asyncio.to_thread(cm.is_valid_checkpoint_target, project_path)
    except Exception:
        checkpoints_enabled = False

    if current_session_id and checkpoints_enabled:
        seq_indices = list(range(len(user_msgs)))
        try:
            details_map = await asyncio.wait_for(
                asyncio.to_thread(
                    cm.get_diff_details_batch,
                    current_session_id,
                    seq_indices,
                    project_path=project_path,
                ),
                timeout=3.0,
            )
        except Exception:
            details_map = {idx: ("diff unavailable", []) for idx in seq_indices}
        for seq_idx, (child_idx, text) in enumerate(user_msgs):
            item = details_map.get(seq_idx)
            stat = item[0] if item else ""
            files = item[1] if item else []
            msgs_with_stats.append(RewindEntry(index=child_idx, text=text, git_stats=stat, changed_files=files))
    else:
        msgs_with_stats = [RewindEntry(index=child_idx, text=text) for child_idx, text in user_msgs]

    return msgs_with_stats


# ---------------------------------------------------------------------------
# get_session_diff
# ---------------------------------------------------------------------------

async def get_session_diff(
    current_session_id: str | None,
    message_index: Optional[int] = None,
    project_path: str | None = None,
    checkpoint_manager: Optional[Any] = None,
) -> list[tuple[str, str, int, int]]:
    """Fetch git-checkpoint full diff between checkpoint and current workspace.

    Returns a list of tuples: (file_path, diff_text, added_lines, deleted_lines).
    """
    from core.domain.ports.checkpoint import get_checkpoint_manager

    if not current_session_id:
        return []

    cm = checkpoint_manager or get_checkpoint_manager()

    try:
        checkpoints_enabled = await asyncio.to_thread(cm.is_valid_checkpoint_target, project_path)
    except Exception:
        checkpoints_enabled = False

    if not checkpoints_enabled:
        return []

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                cm.get_checkpoint_diff,
                current_session_id,
                message_index,
                project_path=project_path,
            ),
            timeout=5.0,
        )
    except Exception as e:
        logger.warning("Failed to fetch session diff: %s", e)
        return []


# ---------------------------------------------------------------------------
# rewind helpers (_reset_token_counters, _truncate_transcript)
# ---------------------------------------------------------------------------

def _reset_token_counters(agent: Any, *, reset_context: bool = True) -> None:
    """Reset cumulative token/cost metrics after a rollback.

    ``reset_context=False`` keeps the freshly recomputed
    ``last_context_tokens`` (callers that truncate history recompute it first).
    """
    for attr, value in (
        ("tokens_input", 0),
        ("tokens_output", 0),
        ("tokens_cache_read", 0),
        ("last_context_tokens", 0),
        ("total_tokens", 0),
        ("cost_usd", 0.0),
    ):
        if attr == "last_context_tokens" and not reset_context:
            continue
        if hasattr(agent, attr):
            setattr(agent, attr, value)


def _truncate_transcript(session: Any, seq_idx: int) -> None:
    """Drop stored transcript events from the selected UI-visible user turn onward.

    ``seq_idx`` is the UI position of the selected user message (0-indexed over
    visible user widgets). Which events count as a visible turn is defined by
    the shared policy in ``core.domain.policies.messages``, keeping this index
    space aligned with fork, checkpoints and the chat UI. A selection beyond
    the last turn is a no-op.
    """
    if session is None or not getattr(session, "messages", None):
        return
    if seq_idx == 0:
        session.messages = []
        return
    cutoff = find_visible_user_cutoff(session.messages, seq_idx)
    if cutoff is not None:
        session.messages = drop_stale_system_notes(session.messages[:cutoff])


# ---------------------------------------------------------------------------
# rewind_session
# ---------------------------------------------------------------------------

def rewind_session(
    agent: Any,
    curr_sid: str | None,
    project_path: str | None,
    user_msgs: list[tuple[int, str]],
    selected_child_idx: int,
    *,
    restore_git: bool = True,
    session: Any = None,
    rollback_ui: Callable[[int], None],
    load_text_into_input: Callable[[str], None],
    save_session_cb: Callable[[], None],
    refresh_footer_cb: Callable[[], None],
    checkpoint_manager: Optional[Any] = None,
) -> None:
    """Execute a rewind/rollback for a selected user message.

    Does NOT import Textual widgets.  UI callbacks handle ChatView operations:
    * ``rollback_ui(target_idx)`` — calls ``chat_view.rollback_to(target_idx)``.
    * ``load_text_into_input(text)`` — loads msg text into input, moves cursor.
    * ``save_session_cb()`` — saves session (async or sync) after rollback.
    * ``refresh_footer_cb()`` — refreshes the status footer after rollback.

    Core logic performed:
    * Walk user_msgs to find the text and sequence index of the message.
    * Compute target_idx = selected_child_idx - 1 (the position to rollback to).
    * Clear or truncate agent history depending on seq_idx.
    * Truncate the store transcript (``session.messages``) at the same turn.
    * Reset token counters.
    * Restore Git checkpoints in background if ``restore_git=True``.
    """
    found = False
    msg_text = ""
    seq_idx = 0
    for i, (child_idx, text) in enumerate(user_msgs):
        if child_idx == selected_child_idx:
            msg_text = text
            seq_idx = i
            found = True
            break

    if not found and user_msgs:
        logger.warning("Selected child index %s not in user messages", selected_child_idx)
        return

    target_idx = selected_child_idx - 1
    rollback_ui(target_idx)

    # Agent history: full clear or truncate
    if seq_idx == 0:
        if hasattr(agent, "clear_history"):
            agent.clear_history()
        elif hasattr(agent, "history"):
            agent.history = []
        _reset_token_counters(agent)
    else:
        # Map UI sequence index to a history index: the last ``real_tail``
        # visible user turns map 1:1 to real (non-checkpoint, non-note) user
        # messages in history, so only the tail can be truncated by index.
        # A selection inside the compacted region cannot be restored from
        # history and is rolled back to a clean slate.
        real_tail = count_history_user_turns(agent.history)
        tail_start = len(user_msgs) - real_tail
        if seq_idx >= tail_start:
            truncate_idx = max(0, seq_idx - tail_start)
            if hasattr(agent, "truncate_history_to_user_message"):
                agent.truncate_history_to_user_message(truncate_idx)
            elif hasattr(agent, "history"):
                agent.history = []
        else:
            if hasattr(agent, "clear_history"):
                agent.clear_history()
            elif hasattr(agent, "history"):
                agent.history = []
        _reset_token_counters(agent, reset_context=False)

    # Store transcript: drop events from the selected turn onward so a later
    # /resume does not resurrect rolled-back turns.
    _truncate_transcript(session, seq_idx)

    # Restore Git checkpoints in background
    if curr_sid:
        # Capture BEFORE creating the new task so the chain never awaits itself.
        pending_restore = getattr(agent, "rewind_git_restore_task", None)

        async def _restore_git_bg():
            # Chain after any still-running restore from a previous rewind: two
            # restores racing for the worktree lock could apply in reverse order
            # and resurrect stale state over newer files. Note that cancelling
            # the previous task would NOT stop its in-flight to_thread git calls,
            # so awaiting it is the only safe serialization.
            if pending_restore is not None and not pending_restore.done():
                try:
                    await pending_restore
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.warning("Previous git checkpoint restore failed: %s", e)
            try:
                from core.domain.ports.checkpoint import get_checkpoint_manager

                cm = checkpoint_manager or get_checkpoint_manager()
                if restore_git:
                    await asyncio.to_thread(
                        cm.restore_checkpoint, curr_sid, seq_idx, project_path=project_path
                    )
                await asyncio.to_thread(
                    cm.purge_checkpoints_after, curr_sid, seq_idx, project_path=project_path
                )
            except Exception as e:
                logger.warning("Git checkpoint restore failed: %s", e)

        git_restore_task = asyncio.create_task(_restore_git_bg())
        # Kept on the agent so a follow-up rewind can chain onto it and app
        # shutdown can cancel/await it.
        agent.rewind_git_restore_task = git_restore_task

    refresh_footer_cb()
    save_session_cb()

    # Load text into input
    load_text_into_input(msg_text)
