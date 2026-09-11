import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def queue_message_ui(
    app: Any,
    prompt: str,
    show_in_ui: bool = True,
    attachments: Optional[list] = None,
    display_text: Optional[str] = None,
) -> None:
    """Queue message to be executed after current generation finishes."""
    curr_sid = getattr(app, "current_session_id", None)
    if display_text:
        item = (prompt, show_in_ui, attachments, curr_sid, display_text)
    elif attachments:
        item = (prompt, show_in_ui, attachments, curr_sid)
    else:
        item = (prompt, show_in_ui, None, curr_sid)
    app.message_queue.append(item)
    if show_in_ui:
        try:
            app.notify("Message queued", severity="information")
        except Exception as e:
            logger.warning("Notify failed: %s", e)


def pop_queued_for_current_session(app: Any) -> Any:
    """Pop the first queued message bound to the current session, or None."""
    curr_sid = getattr(app, "current_session_id", None)
    queue = getattr(app, "message_queue", None)
    if queue is None:
        return None
    for idx, item in enumerate(queue):
        item_sid = item[3] if len(item) > 3 else None
        if item_sid is None or curr_sid is None or item_sid == curr_sid:
            return queue.pop(idx)
    return None


async def process_queued_message(
    app: Any,
    prompt: str,
    show_in_ui: bool = True,
    attachments: Optional[list] = None,
    **kwargs: Any,
) -> None:
    """Run a queued message on the next event-loop iteration after the @work task."""
    # Yield once so the Textual work task can finish its teardown before the
    # next generation starts; run_ai_generation is cooperative, so a single
    # yield is enough (no busy-wait spin needed).
    await asyncio.sleep(0)
    user_text = (prompt or "").strip()
    if user_text.startswith("!"):
        cmd = user_text[1:].strip()
        if cmd:
            asyncio.create_task(app._exec_shell_command(cmd, user_text=user_text))
            return
    if user_text.startswith("/"):
        await app._exec_slash_command(user_text, attachments=attachments)
        return
    app.trigger_ai_response(prompt, show_in_ui=show_in_ui, attachments=attachments, **kwargs)
