"""Pure-core session actions — NO widget/Textual imports.

Functions: new_session, resume_session, compact_session, rewind_session.
Callers (commands.py) handle UI orchestration (push_screen, callback, focus, notify).
"""
import asyncio
import logging
from typing import Any, Callable

from core.session_manager import SessionStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# new_session
# ---------------------------------------------------------------------------

async def new_session(
    app: Any,
    *,
    cancel_workers: Callable[[], None],
    kill_all_tasks: Callable[[], None],
    cancel_subagents: Callable[[], None],
) -> str:
    """Create a new main session — pure logic, no UI.

    * Cancels pending UI workers (callers passes cancel_workers which
      iterates ``app.workers``).
    * Kills all app task-manager tasks.
    * Cancels running subagents for current session.
    * Resets generation state, clears message queue.
    * Generates a fresh session id, creates it in the store.
    * Clears agent history.

    Returns the new session id.  The UI caller is responsible for
    ``chat_view.remove_children()``, ``chat_view.check_welcome()`` and
    ``app.refresh_status_footer()``.

    This function does NOT import Textual or any widget module.
    """
    cancel_workers()
    await kill_all_tasks()
    cancel_subagents()

    app.is_generating = False
    app.message_queue.clear()

    new_id = app.sm.generate_session_id()
    app.sm.create_main(new_id)
    app.current_session_id = new_id

    app.agent.clear_history()
    return new_id


# ---------------------------------------------------------------------------
# resume_session
# ---------------------------------------------------------------------------

def resume_session(
    sm: SessionStore,
    sid: str,
) -> str:
    """Resolve session id for resume.  Returns the sid to load.

    The UI caller calls ``app.load_session_ui(sid)`` afterwards.
    No validation on this layer — store presence is checked by the caller.
    """
    return sid


# ---------------------------------------------------------------------------
# compact_session
# ---------------------------------------------------------------------------

async def compact_session(
    app: Any,
    *,
    save_session_cb: Callable[[], None],
    on_begin: Callable[[], None],
    on_divider_update: Callable[[str], None],
) -> tuple[bool, str]:
    """Compact agent history.

    Calls ``app.agent.compact_history()`` and returns (success, message).
    UI side-effects (divider creation, save, is_generating flag) are left
    to the caller via callbacks so this stays pure-core.

    * ``save_session_cb`` — called after compaction (success or failure).
    * ``on_begin`` — called before compaction (e.g. set is_generating=True,
      create divider widget).
    * ``on_divider_update(title)`` — called after compaction to update the
      divider title in the UI.

    Returns (success, title_or_msg).
    """
    if not hasattr(app, "agent") or not app.agent:
        return False, "No active agent found"

    if not hasattr(app.agent, "compact_history"):
        return False, "Active agent does not support context compaction"

    on_begin()

    try:
        success, msg = await app.agent.compact_history()
        if success:
            title = "Session Compacted"
            if msg and "(" in msg and ")" in msg:
                tokens_info = msg[msg.find("(") + 1: msg.rfind(")")]
                title = f"Session Compacted ({tokens_info})"
            on_divider_update(title)
            app.refresh_status_footer()
        else:
            on_divider_update(f"Compaction Failed: {msg}")
        return success, msg
    except asyncio.CancelledError:
        on_divider_update("Compaction Cancelled")
        raise
    finally:
        save_session_cb()
        app.is_generating = False


# ---------------------------------------------------------------------------
# get_rewind_git_stats
# ---------------------------------------------------------------------------

async def get_rewind_git_stats(
    current_session_id: str | None,
    user_msgs: list[tuple[int, str]],
    project_path: str | None,
) -> list[tuple[int, str, str]]:
    """Fetch git-checkpoint stats for each user message in the rewind list.

    Returns list of (child_idx, text, git_stat) where git_stat is a formatted
    string like '+12 / -4', 'no changes', or ''.
    """
    from core.git_checkpoint import GitCheckpointManager

    msgs_with_stats: list[tuple[int, str, str]] = []
    checkpoints_enabled = False

    try:
        checkpoints_enabled = await asyncio.to_thread(GitCheckpointManager.is_valid_checkpoint_target, project_path)
    except Exception:
        checkpoints_enabled = False

    if current_session_id and checkpoints_enabled:
        seq_indices = list(range(len(user_msgs)))
        try:
            stats_map = await asyncio.wait_for(
                asyncio.to_thread(
                    GitCheckpointManager.get_diff_stats_batch,
                    current_session_id,
                    seq_indices,
                    project_path=project_path,
                ),
                timeout=2.0,
            )
        except (asyncio.TimeoutError, Exception):
            stats_map = {}
        for seq_idx, (child_idx, text) in enumerate(user_msgs):
            stat = stats_map.get(seq_idx) or ""
            msgs_with_stats.append((child_idx, text, stat))
    else:
        msgs_with_stats = [(child_idx, text, "") for child_idx, text in user_msgs]

    return msgs_with_stats


# ---------------------------------------------------------------------------
# rewind_session
# ---------------------------------------------------------------------------

def rewind_session(
    app: Any,
    user_msgs: list[tuple[int, str]],
    selected_child_idx: int,
    *,
    rollback_ui: Callable[[int], None],
    load_text_into_input: Callable[[str], None],
    save_cb: Callable[[], None],
) -> None:
    """Execute a rewind/rollback for a selected user message.

    Does NOT import Textual widgets.  UI callbacks handle ChatView operations:
    * ``rollback_ui(target_idx)`` — calls ``chat_view.rollback_to(target_idx)``.
    * ``load_text_into_input(text)`` — loads msg text into input, moves cursor.
    * ``save_cb()`` — saves session (async or sync).

    Core logic performed:
    * Walk user_msgs to find the text and sequence index of the message.
    * Compute target_idx = selected_child_idx - 1 (the position to rollback to).
    * Clear or truncate agent history depending on seq_idx.
    * Reset token counters when going to zero.
    * Restore Git checkpoints in background.
    """
    msg_text = ""
    seq_idx = 0
    for i, (child_idx, text) in enumerate(user_msgs):
        if child_idx == selected_child_idx:
            msg_text = text
            seq_idx = i
            break

    target_idx = selected_child_idx - 1
    rollback_ui(target_idx)

    # Agent history: full clear or truncate
    if seq_idx == 0:
        if hasattr(app.agent, "clear_history"):
            app.agent.clear_history()
        elif hasattr(app.agent, "history"):
            app.agent.history = []
        for attr, value in (
            ("tokens_input", 0),
            ("tokens_output", 0),
            ("tokens_cache_read", 0),
            ("last_context_tokens", 0),
            ("total_tokens", 0),
            ("cost_usd", 0.0),
        ):
            if hasattr(app.agent, attr):
                setattr(app.agent, attr, value)
    else:
        if hasattr(app.agent, "truncate_history_to_user_message"):
            app.agent.truncate_history_to_user_message(seq_idx)
        elif hasattr(app.agent, "history"):
            app.agent.history = []

    # Restore Git checkpoints in background
    curr_sid = getattr(app, "current_session_id", None)
    proj_path = getattr(app.sm, "project_path", None) if hasattr(app, "sm") else None

    if curr_sid:
        async def _restore_git_bg():
            try:
                from core.git_checkpoint import GitCheckpointManager
                await asyncio.to_thread(
                    GitCheckpointManager.restore_checkpoint, curr_sid, seq_idx, project_path=proj_path
                )
                await asyncio.to_thread(
                    GitCheckpointManager.purge_checkpoints_after, curr_sid, seq_idx, project_path=proj_path
                )
            except Exception as e:
                logger.warning("Git checkpoint restore failed: %s", e)
        asyncio.create_task(_restore_git_bg())

    app.refresh_status_footer()
    save_cb()

    # Load text into input
    load_text_into_input(msg_text)
