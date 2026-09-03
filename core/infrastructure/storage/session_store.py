import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from core.domain.entities.session import (
    AgentSession,
    SessionKind,
    SessionStatus,
)
from core.domain.policies.messages import (
    history_before_turn,
    transcript_before_turn,
)
from core.domain.policies.session_naming import build_fork_title
from core.infrastructure.config.settings import get_settings
from core.infrastructure.platform.paths import PROJECTS_DIR
from core.infrastructure.platform.platform_utils import atomic_write_text, update_json_config
from core.infrastructure.platform.session_lock import SessionLock
from core.infrastructure.runtime.fs_signature import compute_dir_signature_hash

logger = logging.getLogger(__name__)


def _session_change_signature(sess: AgentSession) -> tuple:
    """O(1) signature of a session's persistent state (save-optimization).

    Saves are debounced and coalesced, so the same session is frequently
    re-saved with NO persistent change; this signature detects that without
    re-serializing the whole session. It covers:

    - ``len(messages)`` / ``len(history)`` — appends, truncations, rewinds;
    - the JSONL last message/history entries — in-place coalescing of the
      trailing message (bot text, thinking duration, tool result merge);
    - every scalar in ``_persistent_fields()`` (tokens, cost, title, role,
      status, timestamps...), so new fields are covered automatically.

    The last entries are serialized exactly like ``atomic_write_jsonl`` does
    (``json.dumps(..., ensure_ascii=False)``), so a value that could not be
    persisted raises here too and ``save`` keeps today's failure semantics.
    """
    msgs = sess.messages
    hist = sess._history()
    last_msg = json.dumps(msgs[-1], ensure_ascii=False) if msgs else None
    last_hist = json.dumps(hist[-1], ensure_ascii=False) if hist else None
    meta = tuple(sorted(sess._persistent_fields().items()))
    return (len(msgs), len(hist), last_msg, last_hist, meta)


def _serialize_session_jsonl(sess: AgentSession) -> str:
    """Serialize a session to the exact JSONL bytes ``atomic_write_jsonl`` writes.

    One line per entry: meta first, then one ``{"_type": "msg", ...}`` per
    message and one ``{"_type": "history", ...}`` per agent-history entry.
    """
    return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in sess.to_jsonl_lines())


def get_session_store(ctx_or_app: Any) -> "SessionStore":
    """Resolve the session store from a ctx/app that may carry ``.sm``.

    Falls back to the process-wide singleton when the object has no store
    attached (or is None). Single source of truth for the store resolution
    previously duplicated across task_collection, tools and widgets.
    """
    store = getattr(ctx_or_app, "sm", None) if ctx_or_app else None
    if store is None:
        store = SessionStore.get_instance()
    return store


class SessionStore:
    """Unified store for main and subagent sessions, organized by project.

    Disk layout:
        ~/.johnston/projects/<project_key>/
            config.json
            sessions/<main_id>.jsonl
            sessions/<main_id>.subagents/<subagent_id>.jsonl
    """

    _instance: Optional["SessionStore"] = None

    @property
    def DISK_CACHE_TTL(self) -> float:
        """Seconds between filesystem rescans (storage.disk_cache_ttl)."""
        if hasattr(self, "_disk_cache_ttl") and self._disk_cache_ttl is not None:
            return self._disk_cache_ttl
        return get_settings().storage.disk_cache_ttl

    @DISK_CACHE_TTL.setter
    def DISK_CACHE_TTL(self, value: float) -> None:
        self._disk_cache_ttl = value

    def __init__(self, project_path: Optional[str] = None):
        if not project_path:
            project_path = os.getcwd()
        self.project_path = os.path.realpath(os.path.abspath(project_path))

        path_hash = hashlib.md5(self.project_path.encode("utf-8")).hexdigest()[:8]
        folder_name = os.path.basename(self.project_path) or "root"
        self.project_key = f"{folder_name}_{path_hash}"
        self.project_dir = os.path.join(PROJECTS_DIR, self.project_key)
        self.sessions_dir = os.path.join(self.project_dir, "sessions")
        self.config_file = os.path.join(self.project_dir, "config.json")

        self._sessions: Dict[str, AgentSession] = {}
        self._active_locks: Dict[str, SessionLock] = {}
        self._written_active_session_id: Optional[str] = None
        # In-memory cache of the parsed disk session tree, keyed by a signature
        # of (relpath, mtime_ns, size) across all session JSONL files. Avoids
        # re-reading/parsing every file on each list()/children() call.
        self._disk_cache_signature: Optional[int] = None
        self._disk_cache: Optional[Dict[str, AgentSession]] = None
        self._disk_cache_ts: float = 0.0
        # Last-written state per session file (``{fpath: {"sig": ..., "content_hash":
        # ...}}``), used to skip no-op re-serializations/rewrites in save().
        self._session_write_state: Dict[str, Dict[str, Any]] = {}
        self.ensure_dirs()

    @classmethod
    def get_instance(cls, project_path: Optional[str] = None) -> "SessionStore":
        if cls._instance is None or project_path is not None:
            cls._instance = SessionStore(project_path=project_path)
        return cls._instance

    def ensure_dirs(self) -> None:
        os.makedirs(self.sessions_dir, exist_ok=True)

    def generate_session_id(self) -> str:
        while True:
            sid = uuid.uuid4().hex[:8]
            if not os.path.exists(self._main_path(sid)):
                return sid

    def generate_subagent_id(self) -> str:
        return uuid.uuid4().hex[:8]

    # -- paths -------------------------------------------------------------

    def _main_path(self, session_id: str) -> str:
        safe_id = os.path.basename(session_id or "")
        return os.path.join(self.sessions_dir, f"{safe_id}.jsonl")

    def _subagent_dir(self, parent_id: str) -> str:
        safe_parent = os.path.basename(parent_id or "")
        return os.path.join(self.sessions_dir, f"{safe_parent}.subagents")

    def _subagent_path(self, parent_id: str, subagent_id: str) -> str:
        safe_sub = os.path.basename(subagent_id or "")
        return os.path.join(self._subagent_dir(parent_id), f"{safe_sub}.jsonl")

    # -- CRUD --------------------------------------------------------------

    def create_main(self, session_id: Optional[str] = None, role: str = "worker") -> AgentSession:
        sess = AgentSession(
            session_id=session_id or self.generate_session_id(),
            kind=SessionKind.MAIN,
            role=role,
            status=SessionStatus.ACTIVE,
            project_key=self.project_key,
        )
        self._sessions[sess.id] = sess
        return sess

    def create_subagent(
        self,
        parent_id: str,
        subagent_id: Optional[str] = None,
        role: str = "worker",
        title: str = "",
        prompt: str = "",
        status: str = SessionStatus.RUNNING,
        project_dir: str = "",
        branch_name: str = "",
        background: bool = True,
    ) -> AgentSession:
        sess = AgentSession(
            session_id=subagent_id or self.generate_subagent_id(),
            kind=SessionKind.SUBAGENT,
            parent_id=parent_id,
            role=role,
            status=status,
            project_key=self.project_key,
            title=title,
            prompt=prompt,
        )
        sess.project_dir = project_dir
        sess.branch_name = branch_name
        sess.background = background
        self._sessions[sess.id] = sess
        return sess

    def get(self, session_id: str, reload: bool = True) -> Optional[AgentSession]:
        if not session_id:
            return None
        if session_id in self._sessions:
            return self._sessions[session_id]
        if reload:
            return self._load_from_disk(session_id)
        return None

    def _load_from_disk(self, session_id: str) -> Optional[AgentSession]:
        for fpath in (self._main_path(session_id), self._subagent_path_from_scan(session_id)):
            if not fpath or not os.path.exists(fpath):
                continue
            try:
                sess = AgentSession.from_file(fpath)
                if sess:
                    self._sessions[sess.id] = sess
                    return sess
            except Exception:
                logger.warning("Failed to load session from disk: %s", fpath, exc_info=True)
        return None

    def _subagent_path_from_scan(self, subagent_id: str) -> Optional[str]:
        if not os.path.isdir(self.sessions_dir):
            return None
        for fname in os.listdir(self.sessions_dir):
            if not fname.endswith(".subagents"):
                continue
            sdir = os.path.join(self.sessions_dir, fname)
            fpath = os.path.join(sdir, f"{subagent_id}.jsonl")
            if os.path.exists(fpath):
                return fpath
        return None

    def list(self, kind: Optional[str] = None) -> List[AgentSession]:
        """Load all sessions (main + subagents) for the current project from disk.

        Results are cached in-memory and invalidated when the on-disk session tree
        changes (new/moved/deleted files or content edits) via a cheap directory
        signature, or explicitly on any local write (save/delete).
        """
        sessions = self._load_disk_sessions()
        for sid, sess in self._sessions.items():
            if sess.project_key == self.project_key:
                sessions[sid] = sess
        result = list(sessions.values())
        if kind:
            result = [s for s in result if s.kind == SessionKind(kind)]
        return result

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
            sess = AgentSession.from_file(fpath)
            if sess:
                sessions[sess.id] = sess
        except Exception:
            logger.warning("Failed to load session file: %s", fpath, exc_info=True)
    def list_main_sessions(self) -> List[Dict[str, Any]]:
        """Return NON-EMPTY main sessions sorted by updated time (for /resume UI).

        Reads through the shared disk cache (signature-invalidated) instead of
        re-parsing every JSONL file on each call; live in-memory sessions win
        over their disk copies.
        """
        merged: Dict[str, AgentSession] = dict(self._load_disk_sessions())
        for sid, sess in self._sessions.items():
            if sess.project_key == self.project_key:
                merged[sid] = sess

        sessions = []
        for sess in merged.values():
            if sess.kind != SessionKind.MAIN:
                continue
            if not sess.messages and not sess.agent_history:
                continue
            summary = sess.to_summary_dict()
            sid = summary.get("id")
            summary["is_locked"] = self.is_session_locked(sid) if sid else False
            sessions.append(summary)

        sessions.sort(key=lambda s: (s["updated_at"], s["created_at"], s["id"]), reverse=True)
        return sessions

    def children(self, parent_id: str) -> List[AgentSession]:
        if not parent_id:
            return []
        if self._disk_cache is not None:
            return [s for s in self.list() if s.parent_id == parent_id]

        s_dir = self._subagent_dir(parent_id)
        sessions: Dict[str, AgentSession] = {}
        if os.path.isdir(s_dir):
            for fname in sorted(os.listdir(s_dir)):
                if fname.endswith(".jsonl"):
                    self._load_file(sessions, os.path.join(s_dir, fname))
        for sid, sess in self._sessions.items():
            if sess.parent_id == parent_id and sess.project_key == self.project_key:
                sessions[sid] = sess
        return list(sessions.values())

    # -- save/delete -------------------------------------------------------

    def save(self, sess: AgentSession) -> None:
        try:
            if sess.kind == SessionKind.SUBAGENT:
                os.makedirs(self._subagent_dir(sess.parent_id), exist_ok=True)
                fpath = self._subagent_path(sess.parent_id, sess.id)
            else:
                fpath = self._main_path(sess.id)

            # Perf (M3): saves are debounced (~1.5s + per-turn coalescing), so the
            # same session is frequently re-saved with NO persistent change. The
            # cheap signature (lengths + metadata + last entries) detects common
            # changes (appends, truncations, touches, coalescing) in O(1); when it
            # matches, the full serialized content is compared against the last
            # written bytes — this catches in-place mutation of an EARLIER message
            # (e.g. tool result_text/status merged by the widget layer). When both
            # match, the atomic rewrite is skipped entirely; the file on disk is
            # byte-identical to what the rewrite would have produced, so readers
            # (AgentSession.from_file) observe the exact same state as before.
            state = self._session_write_state.get(fpath)
            sig = _session_change_signature(sess)
            content: Optional[str] = None
            if state is not None and state["sig"] == sig:
                content = _serialize_session_jsonl(sess)
                if state["content_hash"] == hashlib.md5(content.encode("utf-8")).hexdigest():
                    self._sessions[sess.id] = sess
                    return

            if content is None:
                content = _serialize_session_jsonl(sess)
            atomic_write_text(fpath, content)
            self._sessions[sess.id] = sess
            self._session_write_state[fpath] = {
                "sig": sig,
                "content_hash": hashlib.md5(content.encode("utf-8")).hexdigest(),
            }
            if self._disk_cache is not None:
                self._disk_cache[sess.id] = sess
                self._disk_cache_signature = self._disk_signature()
                self._disk_cache_ts = time.time()
        except Exception:
            logger.exception("Failed to save session %s", sess.id)

    async def save_async(self, sess: AgentSession) -> None:
        """Asynchronously save session off the event loop thread."""
        await asyncio.to_thread(self.save, sess)

    def delete(self, session_id: str) -> None:
        sess = self.get(session_id)
        if sess and sess.kind == SessionKind.MAIN:
            import shutil

            shutil.rmtree(self._subagent_dir(session_id), ignore_errors=True)
            try:
                os.remove(self._main_path(session_id))
            except OSError:
                pass
            # Drop saved-state for the removed file and any cascaded subagents so
            # a future save with identical content still (re)creates the file.
            self._session_write_state.pop(self._main_path(session_id), None)
            subdir_prefix = self._subagent_dir(session_id) + os.sep
            for fpath in [p for p in self._session_write_state if p.startswith(subdir_prefix)]:
                del self._session_write_state[fpath]
        elif sess:
            fpath = self._subagent_path(sess.parent_id, session_id)
            try:
                os.remove(fpath)
            except OSError:
                pass
            self._session_write_state.pop(fpath, None)
        else:
            fpath = self._main_path(session_id)
            try:
                os.remove(fpath)
            except OSError:
                pass
            self._session_write_state.pop(fpath, None)
        self._sessions.pop(session_id, None)
        self._invalidate_disk_cache()

    def set_active_session_id(self, session_id: str) -> None:
        # Skip the config rewrite when unchanged: saves call this on every write.
        if session_id == self._written_active_session_id:
            return
        update_json_config(self.config_file, lambda cfg: cfg.__setitem__("active_session_id", session_id))
        self._written_active_session_id = session_id

    # -- search ---------------------------------------------------------------

    def find_session_by_title_or_id(
        self, identifier: str, parent_id: Optional[str] = None
    ) -> Optional[AgentSession]:
        if not identifier:
            return None
        clean_id = identifier.strip("\"' `")

        if clean_id in self._sessions:
            sess = self._sessions[clean_id]
            if not parent_id or sess.parent_id == parent_id:
                return sess

        candidates = self.children(parent_id) if parent_id else self.list()
        res = self._search_in_list(candidates, identifier, clean_id)
        if res:
            self._sessions[res.id] = res
            return res

        # Fallback: full project-wide search
        if parent_id:
            res = self._search_in_list(self.list(), identifier, clean_id)
            if res:
                self._sessions[res.id] = res
                return res
        return None

    def _search_in_list(self, candidates: List[AgentSession], identifier: str, clean_id: str) -> Optional[AgentSession]:
        for sess in candidates:
            if sess.id == identifier or sess.id == clean_id:
                return sess
            clean_title = (sess._title or sess.title).strip("\"' `")
            if clean_title == clean_id:
                return sess
            clean_prompt = sess.prompt.strip("\"' `")
            if clean_prompt == clean_id:
                return sess

        if "..." in clean_id:
            parts = [p.strip() for p in clean_id.split("...") if p.strip()]
            for sess in candidates:
                clean_title = (sess._title or sess.title).strip("\"' `")
                if parts and all(p in clean_title for p in parts):
                    return sess
                clean_prompt = sess.prompt.strip("\"' `")
                if parts and all(p in clean_prompt for p in parts):
                    return sess

        clean_id_lower = clean_id.lower()
        if len(clean_id_lower) >= 3:
            for sess in candidates:
                c_title = (sess._title or sess.title).strip("\"' `").lower()
                c_prompt = sess.prompt.strip("\"' `").lower()
                if c_title and (clean_id_lower in c_title or c_title in clean_id_lower):
                    return sess
                if c_prompt and (clean_id_lower in c_prompt or c_prompt in clean_id_lower):
                    return sess

        return None

    # -- locking & forking ----------------------------------------------------

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

    def fork_session(
        self,
        session_id: str,
        new_title: Optional[str] = None,
        up_to_msg_index: Optional[int] = None,
    ) -> Optional[AgentSession]:
        """Create a user-facing fork of a MAIN session under a fresh session ID.

        ``new_title`` is a base hint, not a verbatim title: it is normalized,
        capped and numbered among the parent's existing fork siblings, which
        get the ``(fork N)`` marker appended. Subagent sessions are not
        forkable — forking is a user action on main sessions only.
        """
        import copy

        source = self.get(session_id)
        if not source or source.kind != SessionKind.MAIN:
            return None
        new_id = self.generate_session_id()
        parent_id = source.id
        siblings = sum(1 for s in self.list() if s.parent_id == parent_id and s.kind == source.kind)
        fork_title = build_fork_title(new_title or source.title, siblings + 1)
        new_sess = AgentSession(
            session_id=new_id,
            kind=source.kind,
            parent_id=parent_id,
            role=source.role,
            status=SessionStatus.ACTIVE,
            project_key=self.project_key,
            title=fork_title,
            prompt=source.prompt,
        )
        if up_to_msg_index is None:
            new_sess.messages = copy.deepcopy(source.messages)
            new_sess.agent_history = copy.deepcopy(source.agent_history)
            new_sess.tokens_input = source.tokens_input
            new_sess.tokens_output = source.tokens_output
            new_sess.total_tokens = source.total_tokens
            new_sess.cost_usd = source.cost_usd
            new_sess.last_context_tokens = source.last_context_tokens
            new_sess.tokens_cache_read = source.tokens_cache_read
        else:
            seq_idx = up_to_msg_index
            if seq_idx <= 0:
                new_sess.messages = []
                new_sess.agent_history = []
            else:
                # Turn positions are defined by the shared user-turn policy so a
                # fork's cutoff always matches rewind and checkpoint indexing.
                new_sess.messages = copy.deepcopy(transcript_before_turn(source.messages, seq_idx))
                new_sess.agent_history = copy.deepcopy(history_before_turn(source.agent_history, seq_idx))
        new_sess.project_dir = source.project_dir
        new_sess.branch_name = source.branch_name
        new_sess.fork_msg_count = len(new_sess.messages)
        new_sess.auto_titled = False
        self.save(new_sess)
        return new_sess


