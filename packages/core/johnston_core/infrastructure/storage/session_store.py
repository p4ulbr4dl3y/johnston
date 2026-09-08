import asyncio
import copy
import hashlib
import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional

from johnston_core.domain.entities.session import (
    AgentSession,
    SessionKind,
    SessionStatus,
)
from johnston_core.domain.policies.messages import (
    history_before_turn,
    transcript_before_turn,
)
from johnston_core.domain.policies.session_naming import build_fork_title
from johnston_core.infrastructure.config.settings import get_settings  # noqa: F401
from johnston_core.infrastructure.platform.paths import PROJECTS_DIR
from johnston_core.infrastructure.platform.platform_utils import atomic_write_text, update_json_config
from johnston_core.infrastructure.platform.session_lock import SessionLock
from johnston_core.infrastructure.storage.session_index_db import SessionIndexDb
from johnston_core.infrastructure.storage.session_serialization import (
    from_file as _session_from_file,
)
from johnston_core.infrastructure.storage.session_serialization import (
    persistent_fields as _session_persistent_fields,
)
from johnston_core.infrastructure.storage.session_serialization import (
    session_history as _session_history,
)
from johnston_core.infrastructure.storage.session_store_cache import SessionStoreCacheMixin
from johnston_core.infrastructure.storage.session_store_locks import SessionStoreLocksMixin
from johnston_core.infrastructure.storage.session_store_paths import SessionStorePathsMixin

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
    hist = _session_history(sess)
    last_msg = json.dumps(msgs[-1], ensure_ascii=False, default=str) if msgs else None
    last_hist = json.dumps(hist[-1], ensure_ascii=False, default=str) if hist else None
    meta = tuple(sorted(_session_persistent_fields(sess).items()))
    return (len(msgs), len(hist), last_msg, last_hist, meta)


def _serialize_session_jsonl(sess: AgentSession) -> str:
    """Serialize a session to the exact JSONL bytes ``atomic_write_jsonl`` writes.

    One line per entry: meta first, then one ``{"_type": "msg", ...}`` per
    message and one ``{"_type": "history", ...}`` per agent-history entry.
    Falls back per corrupted entry to guarantee the rest of the session is preserved.
    """
    lines: List[str] = []
    for item in sess.to_jsonl_lines():
        try:
            lines.append(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        except Exception:
            safe_type = item.get("_type", "msg") if isinstance(item, dict) else "msg"
            lines.append(
                json.dumps(
                    {"_type": safe_type, "corrupted": True, "repr": str(item)},
                    ensure_ascii=False,
                    default=str,
                )
                + "\n"
            )
    return "".join(lines)


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


class SessionStore(SessionStorePathsMixin, SessionStoreLocksMixin, SessionStoreCacheMixin):
    """Unified store for main and subagent sessions, organized by project.

    Disk layout:
        ~/.johnston/projects/<project_key>/
            config.json
            sessions/<main_id>.jsonl
            sessions/<main_id>.subagents/<subagent_id>.jsonl
    """

    _instance: Optional["SessionStore"] = None

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
        self.index_db_file = os.path.join(self.project_dir, "sessions_index.db")
        self.index_db = SessionIndexDb(self.index_db_file)

        self._sessions: Dict[str, AgentSession] = {}
        self._active_locks: Dict[str, SessionLock] = {}
        self._written_active_session_id: Optional[str] = None
        # In-memory cache of the parsed disk session tree, keyed by a signature
        # of (relpath, mtime_ns, size) across all session JSONL files. Avoids
        # re-reading/parsing every file on each list()/children() call.
        self._disk_cache_signature: Optional[int] = None
        self._disk_cache: Optional[Dict[str, AgentSession]] = None
        self._disk_cache_ts: float = 0.0
        self._disk_cache_ttl: Optional[float] = None
        # Last-written state per session file (``{fpath: {"sig": ..., "content_hash":
        # ...}}``), used to skip no-op re-serializations/rewrites in save().
        self._session_write_state: Dict[str, Dict[str, Any]] = {}
        self.ensure_dirs()

    @classmethod
    def get_instance(cls, project_path: Optional[str] = None) -> "SessionStore":
        if cls._instance is None or project_path is not None:
            cls._instance = SessionStore(project_path=project_path)
        return cls._instance

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
                sess = _session_from_file(fpath)
                if sess:
                    self._sessions[sess.id] = sess
                    return sess
            except Exception:
                logger.warning("Failed to load session from disk: %s", fpath, exc_info=True)
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

    def list_main_sessions(self) -> List[Dict[str, Any]]:
        """Return NON-EMPTY main sessions sorted by updated time (for /resume UI).

        Uses SQLite session_index for fast lookup (~1ms); falls back to disk scan
        and populates SQLite on cold start or when external JSONL files change.
        """
        current_sig = str(self._disk_signature() or 0)
        stored_sig = self.index_db.get_meta("signature")

        # Re-index if signature mismatch (external change) or never indexed
        if stored_sig != current_sig and os.path.isdir(self.sessions_dir):
            disk_sessions = list(self._load_disk_sessions().values())
            self.index_db.bulk_reindex(self.project_key, disk_sessions, signature=current_sig)

        rows = self.index_db.query_main_sessions(self.project_key)

        # Merge with live uncommitted/in-memory sessions
        index_sessions: Dict[str, Dict[str, Any]] = {r["id"]: r for r in rows}
        for sid, sess in self._sessions.items():
            if sess.project_key == self.project_key and sess.kind == SessionKind.MAIN:
                if not sess.messages and not sess.agent_history:
                    index_sessions.pop(sid, None)
                else:
                    index_sessions[sid] = sess.to_summary_dict()

        sessions = list(index_sessions.values())
        for summary in sessions:
            sid = summary.get("id")
            summary["is_locked"] = self.is_session_locked(sid) if sid else False

        sessions.sort(
            key=lambda s: (float(s.get("updated_at") or 0.0), float(s.get("created_at") or 0.0), str(s.get("id") or "")),
            reverse=True,
        )
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

    def save(self, sess: AgentSession) -> bool:
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
                    return True

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
            self.index_db.upsert_session(sess)
            return True
        except Exception:
            logger.exception("Failed to save session %s", sess.id)
            return False

    async def save_async(self, sess: AgentSession) -> bool:
        """Asynchronously save session off the event loop thread."""
        return await asyncio.to_thread(self.save, sess)

    def delete(self, session_id: str) -> None:
        sess = self.get(session_id)
        if sess and sess.kind == SessionKind.MAIN:
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
        self.index_db.delete_session(session_id)

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


__all__ = ["SessionStore", "get_session_store"]
