"""Session persistence mixin for JohnstonApp.

Delegates session UI loading, state writing, saving, and resume hints to
SessionPersistenceService.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from johnston.tui.app.session_service import SessionPersistenceService, _global_session_write_lock

logger = logging.getLogger(__name__)

__all__ = ["SessionPersistenceMixin", "_global_session_write_lock"]


class SessionPersistenceMixin:
    """Session UI loading and persistence for JohnstonApp."""

    @classmethod
    def _resolve_session_service(cls, host: Any) -> SessionPersistenceService:
        service = getattr(host, "session_service", None)
        if service is None or getattr(service, "app", None) is not host:
            service = SessionPersistenceService(host)
            try:
                host.session_service = service
            except Exception:
                pass
        return service

    def _get_session_service(self) -> SessionPersistenceService:
        """Get or lazily create SessionPersistenceService for this app."""
        return SessionPersistenceMixin._resolve_session_service(self)

    def load_session_ui(self, session_id: str, read_only: bool = False) -> None:
        """Load session state into UI and agent history."""
        SessionPersistenceMixin._resolve_session_service(self).load_session_ui(
            session_id, read_only=read_only
        )

    def _get_current_session_data(self) -> Optional[dict]:
        """Collect session data from the transcript session store (source of truth)."""
        return SessionPersistenceMixin._resolve_session_service(self).get_current_session_data()

    def save_current_session(self) -> None:
        """Save complete UI element state to ~/.johnston/projects/<project>/sessions."""
        SessionPersistenceMixin._resolve_session_service(self).save_current_session()

    def _write_session_data(self, session_data: dict) -> bool:
        """Write collected session data into the store (no UI access — safe for threads)."""
        return SessionPersistenceMixin._resolve_session_service(self).write_session_data(session_data)

    async def save_current_session_async(self, force: bool = False) -> None:
        """Collect session data on main UI thread, then save to disk in background thread."""
        await SessionPersistenceMixin._resolve_session_service(self).save_current_session_async(
            force=force
        )

    def get_resume_hint(self) -> Optional[str]:
        """Return CLI command string to resume active session if it contains messages."""
        return SessionPersistenceMixin._resolve_session_service(self).get_resume_hint()
