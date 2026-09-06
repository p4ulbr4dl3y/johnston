import os
from typing import Dict

from core.infrastructure.platform.session_lock import SessionLock


class SessionStoreLocksMixin:
    """Inter-process session locking management for SessionStore."""

    sessions_dir: str
    _active_locks: Dict[str, SessionLock]

    def _lock_path(self, session_id: str) -> str:
        safe_id = os.path.basename(session_id or "default")
        return os.path.join(self.sessions_dir, f"{safe_id}.lock")

    def is_session_locked(self, session_id: str) -> bool:
        """Check if session is currently locked by another active process."""
        if not session_id:
            return False
        if session_id in self._active_locks:
            return False
        is_locked, _ = SessionLock.probe(self._lock_path(session_id))
        return is_locked

    def acquire_session_lock(self, session_id: str) -> bool:
        """Acquire exclusive lock on session. Returns True on success."""
        if not session_id:
            return False
        if session_id in self._active_locks:
            return True
        lock = SessionLock(self._lock_path(session_id))
        if lock.acquire():
            self._active_locks[session_id] = lock
            return True
        return False

    def release_session_lock(self, session_id: str) -> None:
        """Release lock held by this process on session."""
        if not session_id:
            return
        lock = self._active_locks.pop(session_id, None)
        if lock:
            lock.release()

    def release_all_locks(self) -> None:
        """Release all locks held by this process."""
        for lock in list(self._active_locks.values()):
            lock.release()
        self._active_locks.clear()

    def steal_session_lock(self, session_id: str) -> bool:
        """Steal lock from other process and acquire it for this process."""
        if not session_id:
            return False
        self.release_session_lock(session_id)
        lock = SessionLock.steal(self._lock_path(session_id))
        if lock:
            self._active_locks[session_id] = lock
            return True
        return False


__all__ = ["SessionStoreLocksMixin"]
