import os
import uuid


class SessionStorePathsMixin:
    """Path resolution and ID generation helpers for SessionStore."""

    sessions_dir: str

    def ensure_dirs(self) -> None:
        os.makedirs(self.sessions_dir, exist_ok=True)

    def generate_session_id(self) -> str:
        while True:
            sid = uuid.uuid4().hex[:8]
            if not os.path.exists(self._main_path(sid)):
                return sid

    def generate_subagent_id(self) -> str:
        return f"subagent-{uuid.uuid4().hex[:8]}"

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


__all__ = ["SessionStorePathsMixin"]
