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
        self.agent_history: List[Dict[str, Any]] = []
        self.async_task: Any = None

    def add_event(self, event: Dict[str, Any]) -> None:
        etype = event.get("type", "")
        if etype in ("bot_chunk", "bot_delta", "thinking_delta") and self.events and self.events[-1].get("type") == etype:
            new_text = event.get("text", "")
            if etype == "bot_delta":
                self.events[-1]["text"] = new_text
            else:
                last_text = self.events[-1].get("text", "")
                self.events[-1]["text"] = last_text + new_text
        else:
            self.events.append(event)

        for cb in list(self.listeners):
            try:
                cb(event)
            except Exception:
                pass

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
        history = getattr(self.agent, "history", None)
        if history is None:
            history = self.agent_history
        return {
            "task_id": self.task_id,
            "description": self.description,
            "prompt": self.prompt,
            "subagent_type": self.subagent_type,
            "background": self.background,
            "session_id": self.session_id,
            "status": self.status,
            "events": self.events,
            "agent_history": history
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
        sess.agent_history = data.get("agent_history", [])
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
            from tools.base import atomic_write_json
            os.makedirs(self.storage_dir, exist_ok=True)
            fpath = os.path.join(self.storage_dir, f"{sess.task_id}.json")
            atomic_write_json(fpath, sess.to_dict(), indent=2)
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

    def _search_in_list(
        self, candidates: List[SubagentSessionData], identifier: str, clean_id: str
    ) -> Optional[SubagentSessionData]:
        if identifier in self.sessions:
            return self.sessions[identifier]

        for sess in candidates:
            if sess.task_id == identifier or sess.task_id == clean_id:
                return sess
            clean_desc = sess.description.strip('"\' `')
            if clean_desc == clean_id:
                return sess
            clean_prompt = sess.prompt.strip('"\' `')
            if clean_prompt == clean_id:
                return sess

        # Ellipsis matching
        if "..." in clean_id:
            parts = [p.strip() for p in clean_id.split("...") if p.strip()]
            for sess in candidates:
                clean_desc = sess.description.strip('"\' `')
                if parts and all(p in clean_desc for p in parts):
                    return sess
                clean_prompt = sess.prompt.strip('"\' `')
                if parts and all(p in clean_prompt for p in parts):
                    return sess

        # Substring / prefix / case-insensitive matching fallback
        clean_id_lower = clean_id.lower()
        if len(clean_id_lower) >= 3:
            for sess in candidates:
                c_desc = sess.description.strip('"\' `').lower()
                c_prompt = sess.prompt.strip('"\' `').lower()
                if c_desc and (clean_id_lower in c_desc or c_desc in clean_id_lower):
                    return sess
                if c_prompt and (clean_id_lower in c_prompt or c_prompt in clean_id_lower):
                    return sess

        return None

    def find_session_by_description_or_id(
        self, identifier: str, session_id: Optional[str] = None
    ) -> Optional[SubagentSessionData]:
        candidates = self.get_sessions_for_session(session_id)
        if not identifier:
            return candidates[-1] if candidates else None

        clean_id = identifier.strip('"\' `')

        # 1. Search in session_id candidates
        res = self._search_in_list(candidates, identifier, clean_id)
        if res:
            return res

        # 2. If restricted by session_id, fallback to all in-memory sessions
        if session_id:
            res = self._search_in_list(list(self.sessions.values()), identifier, clean_id)
            if res:
                return res

        # 3. Fallback: reload disk sessions and search all sessions
        self._load_all_sessions()
        return self._search_in_list(list(self.sessions.values()), identifier, clean_id)


def record_subagent_step(step: tuple, session: SubagentSessionData, text_accumulator: list[str]) -> None:
    """Records a subagent execution step event into the session event history."""
    import math

    etype = step[0]
    val1 = step[1] if len(step) > 1 else ""
    val2 = step[2] if len(step) > 2 else ""
    val3 = step[3] if len(step) > 3 else None

    if etype == "thinking_start":
        session.add_event({"type": "thinking_start", "val1": val1})
    elif etype == "thinking_delta":
        session.add_event({"type": "thinking_delta", "val1": val1})
    elif etype == "thinking_end":
        try:
            dur = float(val1)
            if not math.isfinite(dur):
                dur = 0.0
        except (ValueError, TypeError):
            dur = 0.0
        session.add_event({"type": "thinking_end", "duration": dur, "content": val2})
    elif etype == "tool":
        targs = val3 if isinstance(val3, dict) else {}
        session.add_event({"type": "tool", "tool_type": val1, "target": val2, "args": targs})
    elif etype == "tool_result":
        session.add_event({"type": "tool_result", "result_text": val1})
    elif etype == "bot_chunk":
        session.add_event({"type": "bot_chunk", "text": val1})
        text_accumulator[0] += val1
    elif etype == "bot_delta":
        session.add_event({"type": "bot_delta", "text": val1})
        text_accumulator[0] = val1
    elif etype in ("bot_text", "outro"):
        session.add_event({"type": "bot_text", "text": val1})
        text_accumulator[0] = val1


def merge_subagent_metrics(subagent: Any, context: Any) -> None:
    """Merges token consumption and cost metrics from subagent into parent app agent."""
    def _val(obj: Any, attr: str, default: Any = 0) -> Any:
        v = getattr(obj, attr, default)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        return default

    if context.app and getattr(context.app, "agent", None):
        main_agent = context.app.agent
        last_in = _val(subagent, "_merged_tokens_input", 0)
        last_out = _val(subagent, "_merged_tokens_output", 0)
        last_tot = _val(subagent, "_merged_total_tokens", 0)
        last_cost = _val(subagent, "_merged_cost_usd", 0.0)

        cur_in = _val(subagent, "tokens_input", 0)
        cur_out = _val(subagent, "tokens_output", 0)
        cur_tot = _val(subagent, "total_tokens", 0)
        cur_cost = _val(subagent, "cost_usd", 0.0)

        delta_in = cur_in - last_in
        delta_out = cur_out - last_out
        delta_tot = cur_tot - last_tot
        delta_cost = cur_cost - last_cost

        if delta_in > 0:
            main_agent.tokens_input = _val(main_agent, "tokens_input", 0) + delta_in
        if delta_out > 0:
            main_agent.tokens_output = _val(main_agent, "tokens_output", 0) + delta_out
        if delta_tot > 0:
            main_agent.total_tokens = _val(main_agent, "total_tokens", 0) + delta_tot
        if delta_cost > 0:
            main_agent.cost_usd = _val(main_agent, "cost_usd", 0.0) + delta_cost

        subagent._merged_tokens_input = cur_in
        subagent._merged_tokens_output = cur_out
        subagent._merged_total_tokens = cur_tot
        subagent._merged_cost_usd = cur_cost
