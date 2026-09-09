from typing import Any, List, Tuple


def has_queued_messages(agent: Any) -> bool:
    """True if the queue has a message for the current session/agent."""
    session = getattr(agent, "session", None)
    if session is not None and getattr(session, "pending_messages", None):
        return True
    if getattr(agent, "pending_messages", None):
        return True
    if getattr(agent, "is_subagent", False):
        return False
    host = getattr(agent, "host", None) or getattr(agent, "app", None)
    if host is None:
        return False
    mq = getattr(host, "message_queue", None)
    if not isinstance(mq, (list, tuple)) or not mq:
        return False
    sid = getattr(host, "current_session_id", None)
    for item in mq:
        item_sid = item[3] if len(item) > 3 else None
        if item_sid is None or sid is None or item_sid == sid:
            return True
    return False


def drain_queued_messages(agent: Any) -> List[Tuple[str, Any, bool, Any]]:
    """Drain queued user messages for this agent across session, self, or app queue."""
    drained: List[Tuple[str, Any, bool, Any]] = []
    session = getattr(agent, "session", None)
    pending_list = None
    if session is not None and getattr(session, "pending_messages", None):
        pending_list = session.pending_messages
    elif getattr(agent, "pending_messages", None):
        pending_list = agent.pending_messages

    if pending_list:
        while pending_list:
            item = pending_list.pop(0)
            if isinstance(item, str):
                drained.append((item, None, True, None))
            elif isinstance(item, (list, tuple)):
                msg = item[0]
                show = item[1] if len(item) > 1 else True
                atts = item[2] if len(item) > 2 else None
                disp = item[4] if len(item) > 4 else None
                drained.append((msg, atts, show, disp))
        return drained

    if getattr(agent, "is_subagent", False):
        return drained

    host = getattr(agent, "host", None) or getattr(agent, "app", None)
    if host is not None:
        mq = getattr(host, "message_queue", None)
        if isinstance(mq, list) and mq:
            sid = getattr(host, "current_session_id", None)
            kept = []
            for item in mq:
                item_sid = item[3] if len(item) > 3 else None
                if item_sid is not None and sid is not None and item_sid != sid:
                    kept.append(item)
                    continue
                drained.append(
                    (
                        item[0],
                        item[2] if len(item) > 2 else None,
                        item[1] if len(item) > 1 else True,
                        item[4] if len(item) > 4 else None,
                    )
                )
            mq[:] = kept
    return drained
