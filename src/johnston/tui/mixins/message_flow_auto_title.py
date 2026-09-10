import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


def schedule_auto_title(app: Any, session: Any) -> None:
    """Schedule background auto-titling for a session without blocking UI."""
    if (
        not getattr(app, "is_app_active", True)
        or getattr(app, "_exit", False)
        or getattr(app, "_closing", False)
        or getattr(app, "_closed", False)
    ):
        return
    if not session or getattr(session, "auto_titled", False):
        return
    if getattr(session, "_title", None) and not getattr(session, "parent_id", None):
        return

    async def _run() -> None:
        if (
            not getattr(app, "is_app_active", True)
            or getattr(app, "_exit", False)
            or getattr(app, "_closing", False)
            or getattr(app, "_closed", False)
        ):
            return
        try:
            from johnston.tui.adapters import core_bridge

            agent = getattr(app, "agent", None)
            title = await core_bridge.auto_title_session(agent, session)
            if title:
                if hasattr(app, "sm"):
                    app.sm.save(session)
                if getattr(app, "is_app_active", True) and getattr(app, "current_session_id", None) == getattr(
                    session, "id", None
                ):
                    if hasattr(app, "refresh_status_footer"):
                        app.refresh_status_footer()
        except Exception as e:
            logger.debug("Background auto-titling failed: %s", e)

    asyncio.create_task(_run())
