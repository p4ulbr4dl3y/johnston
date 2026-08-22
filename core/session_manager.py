import hashlib
import json
import logging
import os
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from core.domain.entities.session import (
    SessionStatus,
    _coerce_float,
    _coerce_int,
)
from core.infrastructure.platform.paths import PROJECTS_DIR
from core.infrastructure.platform.platform_utils import atomic_write_json, atomic_write_jsonl, read_json
from core.infrastructure.runtime.fs_signature import compute_dir_signature_hash

logger = logging.getLogger(__name__)


class SessionKind(str, Enum):
    """Type of an AgentSession record: a main chat session or a subagent task."""

    MAIN = "main"
    SUBAGENT = "subagent"


class MessageType(str, Enum):
    """Canonical event/message types stored in session.messages.

    Persisted as plain strings (``.value``) so on-disk JSON stays compatible.
    Raw inbound events are dicts with a ``"type"`` field; enum values are used
    at construction/coalescing boundaries.
    """

    BOT = "bot"
    BOT_RESET = "bot_reset"
    THINKING = "thinking"
    TOOL = "tool"
    STATUS_CHANGE = "status_change"
    USER = "user"



def _now() -> float:
    return time.time()



class AgentSession:
    """Unified session model for main chat sessions and subagent task sessions.

    Hierarchy: project -> main session -> subagent sessions (parent_id).
    Messages use a single renderable format shared with the chat UI.
    """

    def __init__(
        self,
        session_id: str,
        kind: SessionKind = SessionKind.MAIN,
        parent_id: Optional[str] = None,
        role: str = "worker",
        status: str = SessionStatus.ACTIVE,
        project_key: str = "",
        description: str = "",
        prompt: str = "",
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
    ):
        self.id = session_id
        self.kind = kind
        self.parent_id = parent_id
        self.role = role
        self.status = status
        self.project_key = project_key
        self.description = description
        self.prompt = prompt
        self.messages: List[Dict[str, Any]] = []
        self.agent_history: List[Dict[str, Any]] = []
        self.tokens_input: int = 0
        self.tokens_output: int = 0
        self.total_tokens: int = 0
        self.cost_usd: float = 0.0
        self.last_context_tokens: int = 0
        self.tokens_cache_read: int = 0
        self.created_at = created_at or _now()
        self.updated_at = updated_at or self.created_at

        # Live-state only (never persisted): streaming agent, listeners, async task.
        self.agent: Any = None
        self.listeners: List[Any] = []
        self.async_task: Any = None
        self.pending_messages: List[Any] = []  # follow-up queue (live, not persisted)
        self.project_dir: str = ""
        self.branch_name: str = ""
        self.background: bool = True

    # -- live event streaming (subagents) ---------------------------------

    def add_event(self, event: Dict[str, Any]) -> None:
        """Append a stream event, coalescing consecutive chunks into canonical messages.

        Canonical message types (shared with main session snapshots):
        - "bot": text of a reply, coalesced (replace) across stream chunks
        - "thinking": text + optional duration, coalesced until thinking finishes
        - "tool": tool call, with "result_text" merged into the same message
        """
        etype = event.get("type", "")
        last = self.messages[-1] if self.messages else None

        if etype == MessageType.BOT and last and last.get("type") == MessageType.BOT:
            last["text"] = event.get("text", "")
            if event.get("final"):
                last["final"] = True
        elif etype == MessageType.BOT_RESET and last and last.get("type") == MessageType.BOT:
            last["text"] = ""
            last.pop("final", None)
        elif etype == MessageType.THINKING and last and last.get("type") == MessageType.THINKING and "duration" not in last:
            last["text"] = event.get("text", "")
            if event.get("duration") is not None:
                last["duration"] = event["duration"]
        elif (
            etype == MessageType.TOOL
            and "result_text" in event
            and last
            and last.get("type") == MessageType.TOOL
            and "result_text" not in last
        ):
            last["result_text"] = event["result_text"]
            for key in ("status", "is_error", "returncode"):
                if key in event:
                    last[key] = event[key]
        else:
            if etype == MessageType.TOOL and last and last.get("type") == MessageType.BOT and not last.get("text", "").strip():
                self.messages.pop()
            self.messages.append(event)
            self.updated_at = _now()

        if not self.listeners:
            return
        for cb in list(self.listeners):
            try:
                cb(event)
            except Exception:
                logger.warning("Session listener callback failed", exc_info=True)

    def add_listener(self, cb: Any) -> None:
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_listener(self, cb: Any) -> None:
        if cb in self.listeners:
            self.listeners.remove(cb)

    def touch(self) -> None:
        self.updated_at = _now()

    def finish(self, status: str, error_msg: str = "") -> None:
        self.status = status
        self.add_event({"type": MessageType.STATUS_CHANGE.value, "status": status, "error": error_msg})

    # -- persistence -------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        history = getattr(self.agent, "history", None)
        if history is None:
            history = self.agent_history
        return {
            "id": self.id,
            "kind": self.kind.value,
            "parent_id": self.parent_id,
            "role": self.role,
            "status": self.status,
            "project_key": self.project_key,
            "description": self.description,
            "prompt": self.prompt,
            "messages": self.messages,
            "agent_history": history,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "last_context_tokens": self.last_context_tokens,
            "tokens_cache_read": self.tokens_cache_read,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_dir": self.project_dir,
            "branch_name": self.branch_name,
        }

    def to_jsonl_lines(self) -> List[Dict[str, Any]]:
        history = getattr(self.agent, "history", None)
        if history is None:
            history = self.agent_history
        meta = {
            "_type": "meta",
            "id": self.id,
            "kind": self.kind.value,
            "parent_id": self.parent_id,
            "role": self.role,
            "status": self.status,
            "project_key": self.project_key,
            "description": self.description,
            "prompt": self.prompt,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "last_context_tokens": self.last_context_tokens,
            "tokens_cache_read": self.tokens_cache_read,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_dir": self.project_dir,
            "branch_name": self.branch_name,
        }
        lines: List[Dict[str, Any]] = [meta]
        for m in self.messages:
            lines.append({"_type": "msg", "data": m})
        for h in history:
            lines.append({"_type": "history", "data": h})
        return lines

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSession":
        raw_kind = data.get("kind", SessionKind.MAIN.value)
        try:
            kind = SessionKind(raw_kind)
        except ValueError:
            kind = SessionKind.MAIN
        sess = cls(
            session_id=data.get("id", ""),
            kind=kind,
            parent_id=data.get("parent_id"),
            role=data.get("role", "worker"),
            status=data.get("status", SessionStatus.ACTIVE),
            project_key=data.get("project_key", ""),
            description=data.get("description") or "",
            prompt=data.get("prompt") or "",
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
        sess.messages = data.get("messages", [])
        sess.agent_history = data.get("agent_history", [])
        sess.tokens_input = _coerce_int(data.get("tokens_input"))
        sess.tokens_output = _coerce_int(data.get("tokens_output"))
        sess.total_tokens = _coerce_int(data.get("total_tokens"))
        sess.cost_usd = _coerce_float(data.get("cost_usd"))
        sess.last_context_tokens = _coerce_int(data.get("last_context_tokens"))
        sess.tokens_cache_read = _coerce_int(data.get("tokens_cache_read"))
        sess.project_dir = data.get("project_dir", "")
        sess.branch_name = data.get("branch_name", "")
        return sess

    @classmethod
    def from_file(cls, fpath: str) -> Optional["AgentSession"]:
        if not fpath or not os.path.exists(fpath):
            return None
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if not first_line:
                    return None
                try:
                    first = json.loads(first_line)
                except Exception:
                    return None

                if not isinstance(first, dict) or first.get("_type") != "meta":
                    return None

                sess = cls.from_dict(first)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    etype = entry.get("_type")
                    if etype == "msg":
                        data = entry.get("data")
                        sess.messages.append(data if data is not None else {})
                    elif etype == "history":
                        data = entry.get("data")
                        sess.agent_history.append(data if data is not None else {})
                return sess
        except Exception:
            return None


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
        # In-memory cache of the parsed disk session tree, keyed by a signature
        # of (relpath, mtime_ns, size) across all session JSONL files. Avoids
        # re-reading/parsing every file on each list()/children() call.
        self._disk_cache_signature: Optional[int] = None
        self._disk_cache: Optional[Dict[str, AgentSession]] = None
        self.ensure_dirs()

    @classmethod
    def get_instance(cls, project_path: Optional[str] = None) -> "SessionStore":
        if cls._instance is None or project_path is not None:
            cls._instance = SessionStore(project_path=project_path)
        return cls._instance

    def ensure_dirs(self) -> None:
        os.makedirs(self.sessions_dir, exist_ok=True)

    def generate_session_id(self) -> str:
        return f"session_{int(time.time())}_{uuid.uuid4().hex[:4]}"

    def generate_subagent_id(self) -> str:
        return f"subagent-{uuid.uuid4().hex[:6]}"

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
        description: str = "",
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
            description=description,
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
                sessions.setdefault(sid, sess)
        result = list(sessions.values())
        if kind:
            result = [s for s in result if s.kind == SessionKind(kind)]
        return result

    def _load_disk_sessions(self) -> Dict[str, AgentSession]:
        signature = self._disk_signature()
        if signature is not None and signature == self._disk_cache_signature and self._disk_cache is not None:
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

    def _load_file(self, sessions: Dict[str, AgentSession], fpath: str) -> None:
        try:
            sess = AgentSession.from_file(fpath)
            if sess:
                sessions[sess.id] = sess
        except Exception:
            logger.warning("Failed to load session file: %s", fpath, exc_info=True)

    def list_main_sessions(self) -> List[Dict[str, Any]]:
        """Return NON-EMPTY main sessions sorted by updated time (for /resume UI)."""
        sessions = []
        for sess in self.list(kind="main"):
            if not sess.messages and not sess.agent_history:
                continue
            title = self._title_from_messages(sess)
            if title == "Untitled" and sess.description:
                desc = " ".join(str(sess.description).split())
                title = desc[:55] + "..." if len(desc) > 55 else desc
            sessions.append(
                {
                    "id": sess.id,
                    "title": title,
                    "created_at": sess.created_at,
                    "updated_at": sess.updated_at,
                    "message_count": self._message_count(sess),
                }
            )
        sessions.sort(key=lambda s: (s["updated_at"], s["created_at"], s["id"]), reverse=True)
        return sessions

    @staticmethod
    def _title_from_messages(sess: AgentSession) -> str:
        for m in sess.messages:
            if isinstance(m, dict) and m.get("type") == "user":
                text = str(m.get("display_text") or m.get("text", "")).strip()
                if text:
                    clean = " ".join(text.split())
                    return clean[:55] + "..." if len(clean) > 55 else clean
        return "Untitled"

    @staticmethod
    def _message_count(sess: AgentSession) -> int:
        """Count agent loop iterations: assistant messages in history.

        Each assistant message = one LLM call in the agent loop (user request,
        tool executions, then final answer).
        """
        if sess.agent_history:
            assistant_msgs = [m for m in sess.agent_history if isinstance(m, dict) and m.get("role") == "assistant"]
            if assistant_msgs:
                return len(assistant_msgs)
        return 0

    def children(self, parent_id: str) -> List[AgentSession]:
        return [s for s in self.list() if s.parent_id == parent_id]

    # -- save/delete -------------------------------------------------------

    def save(self, sess: AgentSession) -> None:
        try:
            if sess.kind == SessionKind.SUBAGENT:
                os.makedirs(self._subagent_dir(sess.parent_id), exist_ok=True)
                fpath = self._subagent_path(sess.parent_id, sess.id)
            else:
                fpath = self._main_path(sess.id)
            atomic_write_jsonl(fpath, sess.to_jsonl_lines())
            self._sessions[sess.id] = sess
            if self._disk_cache is not None:
                self._disk_cache[sess.id] = sess
                self._disk_cache_signature = self._disk_signature()
        except Exception:
            logger.exception("Failed to save session %s", sess.id)

    def delete(self, session_id: str) -> None:
        sess = self.get(session_id)
        if sess and sess.kind == SessionKind.MAIN:
            import shutil

            shutil.rmtree(self._subagent_dir(session_id), ignore_errors=True)
            try:
                os.remove(self._main_path(session_id))
            except OSError:
                pass
        elif sess:
            try:
                os.remove(self._subagent_path(sess.parent_id, session_id))
            except OSError:
                pass
        else:
            try:
                os.remove(self._main_path(session_id))
            except OSError:
                pass
        self._sessions.pop(session_id, None)
        self._invalidate_disk_cache()

    def set_active_session_id(self, session_id: str) -> None:
        cfg = read_json(self.config_file, {})
        cfg["active_session_id"] = session_id
        atomic_write_json(self.config_file, cfg)

    # -- search ---------------------------------------------------------------

    def find_session_by_description_or_id(
        self, identifier: str, parent_id: Optional[str] = None
    ) -> Optional[AgentSession]:
        if not identifier:
            return None
        clean_id = identifier.strip("\"' `")

        candidates = self.children(parent_id) if parent_id else self.list()
        res = self._search_in_list(candidates, identifier, clean_id)
        if res:
            return res

        # Fallback: full project-wide search
        if parent_id:
            res = self._search_in_list(self.list(), identifier, clean_id)
            if res:
                return res
        return None

    def _search_in_list(self, candidates: List[AgentSession], identifier: str, clean_id: str) -> Optional[AgentSession]:
        for sess in candidates:
            if sess.id == identifier or sess.id == clean_id:
                return sess
            clean_desc = sess.description.strip("\"' `")
            if clean_desc == clean_id:
                return sess
            clean_prompt = sess.prompt.strip("\"' `")
            if clean_prompt == clean_id:
                return sess

        if "..." in clean_id:
            parts = [p.strip() for p in clean_id.split("...") if p.strip()]
            for sess in candidates:
                clean_desc = sess.description.strip("\"' `")
                if parts and all(p in clean_desc for p in parts):
                    return sess
                clean_prompt = sess.prompt.strip("\"' `")
                if parts and all(p in clean_prompt for p in parts):
                    return sess

        clean_id_lower = clean_id.lower()
        if len(clean_id_lower) >= 3:
            for sess in candidates:
                c_desc = sess.description.strip("\"' `").lower()
                c_prompt = sess.prompt.strip("\"' `").lower()
                if c_desc and (clean_id_lower in c_desc or c_desc in clean_id_lower):
                    return sess
                if c_prompt and (clean_id_lower in c_prompt or c_prompt in clean_id_lower):
                    return sess

        return None


