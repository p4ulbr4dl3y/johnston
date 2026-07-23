from typing import Any, Callable, Dict, List, Optional


class SubagentSessionData:
    def __init__(self, task_id: str, description: str, prompt: str, subagent_type: str, background: bool):
        self.task_id = task_id
        self.description = description
        self.prompt = prompt
        self.subagent_type = subagent_type
        self.background = background
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

    def add_listener(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_listener(self, cb: Callable[[Dict[str, Any]], None]) -> None:
        if cb in self.listeners:
            self.listeners.remove(cb)

    def finish(self, status: str = "completed", error_msg: str = "") -> None:
        self.status = status
        self.add_event({"type": "status_change", "status": status, "error": error_msg})


class SubagentTracker:
    _instance: Optional["SubagentTracker"] = None

    def __init__(self):
        self.sessions: Dict[str, SubagentSessionData] = {}

    @classmethod
    def get_instance(cls) -> "SubagentTracker":
        if cls._instance is None:
            cls._instance = SubagentTracker()
        return cls._instance

    def create_session(
        self, task_id: str, description: str, prompt: str, subagent_type: str, background: bool
    ) -> SubagentSessionData:
        sess = SubagentSessionData(task_id, description, prompt, subagent_type, background)
        self.sessions[task_id] = sess
        return sess

    def get_session(self, task_id: str) -> Optional[SubagentSessionData]:
        return self.sessions.get(task_id)

    def find_session_by_description_or_id(self, identifier: str) -> Optional[SubagentSessionData]:
        if not identifier:
            return list(self.sessions.values())[-1] if self.sessions else None

        if identifier in self.sessions:
            return self.sessions[identifier]

        clean_id = identifier.strip('"\' `')
        for sess in self.sessions.values():
            if sess.task_id == identifier or sess.task_id == clean_id:
                return sess
            clean_desc = sess.description.strip('"\' `')
            if clean_desc == clean_id or clean_id in clean_desc or clean_desc in clean_id:
                return sess
            clean_prompt = sess.prompt.strip('"\' `')
            if clean_prompt == clean_id or clean_id in clean_prompt or clean_prompt in clean_id:
                return sess

        if self.sessions:
            return list(self.sessions.values())[-1]
        return None
