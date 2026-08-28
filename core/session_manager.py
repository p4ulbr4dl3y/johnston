"""Session manager facade re-exporting the underlying storage implementation.

Maintains module interface for callers referencing core.session_manager.
The canonical infrastructure implementation lives in
``core.infrastructure.storage.session_store``.
"""
from core.infrastructure.platform.paths import PROJECTS_DIR
from core.infrastructure.storage.session_store import (
    SessionStore,
    get_session_store,
)

__all__ = ["PROJECTS_DIR", "SessionStore", "get_session_store"]


