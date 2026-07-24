import json
import os
from typing import Any, Callable, Dict, List, Optional

from core.config import SUBAGENT_SESSIONS_DIR, SUBAGENTS_DIR


class SubagentSessionData:
    def __init__(
        self,
        task_id: str,
        description: str,
        prompt: str,
        subagent_type: str,
        background: bool,
        session_id: Optional[str] = None
    ):
        self.task_id = task_id
        self.description = description
        self.prompt = prompt
        self.subagent_type = subagent_type
        self.background = background
        self.session_id = session_id
        self.status = "running"
        self.events: List[Dict[str, Any]] = []
        self.listeners: List[Callable[[Dict[str, Any]], None]] = []
        self.agent: Any = None
        self.async_task: Any = None

    def add_event(self, event: Dict[str, Any]) -> None:
        self.events.append(event)
        for cb in list(self.listeners):
            try:
                cb(event)
            except Exception:
                pass
        etype = event.get("type", "")
        if etype not in ("bot_chunk", "bot_delta", "thinking_delta"):
            SubagentTracker.get_instance().save_session(self)

    def add_listener(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_listener(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        if cb in self.listeners:
            self.listeners.remove(cb)

    def finish(self, status: str = "completed", error_msg: str = "") -> None:
        self.status = status
        self.add_event({"type": "status_change", "status": status, "error": error_msg})
        SubagentTracker.get_instance().save_session(self)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "prompt": self.prompt,
            "subagent_type": self.subagent_type,
            "background": self.background,
            "session_id": self.session_id,
            "status": self.status,
            "events": self.events,
            "agent_history": getattr(self.agent, "history", []) if self.agent else []
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubagentSessionData":
        sess = cls(
            task_id=data.get("task_id", ""),
            description=data.get("description", ""),
            prompt=data.get("prompt", ""),
            subagent_type=data.get("subagent_type", "general"),
            background=bool(data.get("background", False)),
            session_id=data.get("session_id"),
        )
        sess.status = data.get("status", "completed")
        sess.events = data.get("events", [])
        return sess


class SubagentTracker:
    _instance: Optional["SubagentTracker"] = None

    def __init__(self):
        self.sessions: Dict[str, SubagentSessionData] = {}
        self.storage_dir = SUBAGENT_SESSIONS_DIR
        self._load_all_sessions()

    @classmethod
    def get_instance(cls) -> "SubagentTracker":
        if cls._instance is None:
            cls._instance = SubagentTracker()
        return cls._instance

    def _load_all_sessions(self) -> None:
        dirs_to_check = [self.storage_dir, SUBAGENTS_DIR]
        for dpath in dirs_to_check:
            if os.path.exists(dpath):
                for fname in os.listdir(dpath):
                    if fname.endswith(".json"):
                        fpath = os.path.join(dpath, fname)
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            sess = SubagentSessionData.from_dict(data)
                            if sess.task_id not in self.sessions:
                                self.sessions[sess.task_id] = sess
                        except Exception:
                            pass

    def save_session(self, sess: SubagentSessionData) -> None:
        try:
            os.makedirs(self.storage_dir, exist_ok=True)
            fpath = os.path.join(self.storage_dir, f"{sess.task_id}.json")
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(sess.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def create_session(
        self,
        task_id: str,
        description: str,
        prompt: str,
        subagent_type: str,
        background: bool,
        session_id: Optional[str] = None
    ) -> SubagentSessionData:
        sess = SubagentSessionData(task_id, description, prompt, subagent_type, background, session_id=session_id)
        self.sessions[task_id] = sess
        self.save_session(sess)
        return sess

    def get_session(self, task_id: str) -> Optional[SubagentSessionData]:
        return self.sessions.get(task_id)

    def get_sessions_for_session(self, session_id: Optional[str] = None) -> List[SubagentSessionData]:
        if not session_id:
            return list(self.sessions.values())
        return [s for s in self.sessions.values() if s.session_id == session_id]

    def find_session_by_description_or_id(
        self, identifier: str, session_id: Optional[str] = None
    ) -> Optional[SubagentSessionData]:
        candidates = self.get_sessions_for_session(session_id)
        if not identifier:
            return candidates[-1] if candidates else None

        if identifier in self.sessions:
            cand = self.sessions[identifier]
            if not session_id or not cand.session_id or cand.session_id == session_id:
                return cand

        clean_id = identifier.strip('"\' `')
        for sess in candidates:
            if sess.task_id == identifier or sess.task_id == clean_id:
                return sess
            clean_desc = sess.description.strip('"\' `')
            if clean_desc == clean_id or clean_id in clean_desc or clean_desc in clean_id:
                return sess
            clean_prompt = sess.prompt.strip('"\' `')
            if clean_prompt == clean_id or clean_id in clean_prompt or clean_prompt in clean_id:
                return sess

        if candidates:
            return candidates[-1]
        return None
