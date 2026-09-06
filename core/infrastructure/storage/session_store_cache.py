import logging
import os
import sys
import time
from typing import Dict, Optional

from core.domain.entities.session import AgentSession
from core.infrastructure.config.settings import get_settings
from core.infrastructure.runtime.fs_signature import compute_dir_signature_hash
from core.infrastructure.storage.session_index_db import SessionIndexDb
from core.infrastructure.storage.session_serialization import from_file as _session_from_file

logger = logging.getLogger(__name__)


class SessionStoreCacheMixin:
    """Disk scanning, caching, and signature validation helpers for SessionStore."""

    sessions_dir: str
    index_db: SessionIndexDb
    _disk_cache: Optional[Dict[str, AgentSession]]
    _disk_cache_signature: Optional[int]
    _disk_cache_ts: float
    _disk_cache_ttl: Optional[float]

    @property
    def DISK_CACHE_TTL(self) -> float:
        """Seconds between filesystem rescans (storage.disk_cache_ttl)."""
        if hasattr(self, "_disk_cache_ttl") and self._disk_cache_ttl is not None:
            return self._disk_cache_ttl
        mod = sys.modules.get("core.infrastructure.storage.session_store")
        fn = getattr(mod, "get_settings", None) or get_settings
        return fn().storage.disk_cache_ttl

    @DISK_CACHE_TTL.setter
    def DISK_CACHE_TTL(self, value: float) -> None:
        self._disk_cache_ttl = value

    def _subagent_path_from_scan(self, subagent_id: str) -> Optional[str]:
        if not os.path.isdir(self.sessions_dir):
            return None
        # Fast SQLite check for parent_id
        try:
            with self.index_db._connection() as conn:
                cursor = conn.execute("SELECT parent_id FROM session_index WHERE id = ?", (subagent_id,))
                row = cursor.fetchone()
                if row and row["parent_id"]:
                    fpath = self._subagent_path(row["parent_id"], subagent_id)
                    if os.path.exists(fpath):
                        return fpath
        except Exception:
            pass

        # Fallback directory scan
        for fname in os.listdir(self.sessions_dir):
            if not fname.endswith(".subagents"):
                continue
            sdir = os.path.join(self.sessions_dir, fname)
            fpath = os.path.join(sdir, f"{subagent_id}.jsonl")
            if os.path.exists(fpath):
                return fpath
        return None

    def _load_disk_sessions(self) -> Dict[str, AgentSession]:
        now = time.time()
        if self._disk_cache is not None and (now - self._disk_cache_ts < self.DISK_CACHE_TTL):
            return dict(self._disk_cache)

        signature = self._disk_signature()
        if signature is not None and signature == self._disk_cache_signature and self._disk_cache is not None:
            self._disk_cache_ts = now
            return dict(self._disk_cache)

        sessions: Dict[str, AgentSession] = {}
        if os.path.isdir(self.sessions_dir):
            for fname in sorted(os.listdir(self.sessions_dir)):
                fpath = os.path.join(self.sessions_dir, fname)
                if os.path.isdir(fpath):
                    if fname.endswith(".subagents"):
                        for sub_name in sorted(os.listdir(fpath)):
                            if sub_name.endswith(".jsonl"):
                                self._load_file(sessions, os.path.join(fpath, sub_name))
                elif fname.endswith(".jsonl"):
                    self._load_file(sessions, fpath)
        self._disk_cache = sessions
        self._disk_cache_signature = signature
        self._disk_cache_ts = now
        return sessions

    def _disk_signature(self) -> Optional[int]:
        """Hash of (path, mtime_ns, size) for every session JSONL on disk,
        used to detect external changes without re-reading file contents."""
        if not os.path.isdir(self.sessions_dir):
            return None
        sub_dirs = []
        try:
            for fname in sorted(os.listdir(self.sessions_dir)):
                fpath = os.path.join(self.sessions_dir, fname)
                if os.path.isdir(fpath) and fname.endswith(".subagents"):
                    sub_dirs.append(fpath)
        except OSError:
            return None
        return compute_dir_signature_hash([self.sessions_dir, *sub_dirs], [".jsonl"]) or 0

    def _invalidate_disk_cache(self) -> None:
        self._disk_cache_signature = None
        self._disk_cache = None
        self._disk_cache_ts = 0.0

    def _load_file(self, sessions: Dict[str, AgentSession], fpath: str) -> None:
        try:
            sess = _session_from_file(fpath)
            if sess:
                sessions[sess.id] = sess
        except Exception:
            logger.warning("Failed to load session file: %s", fpath, exc_info=True)


__all__ = ["SessionStoreCacheMixin"]
