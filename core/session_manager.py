import hashlib
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from core.config import PROJECTS_DIR
from core.platform_utils import read_json, write_json


class SessionManager:
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

        self.ensure_dirs()

    def ensure_dirs(self):
        os.makedirs(self.sessions_dir, exist_ok=True)

    def generate_session_id(self) -> str:
        return f"session_{int(time.time())}_{uuid.uuid4().hex[:4]}"

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Returns list of NON-EMPTY sessions for current project, sorted by updated time.

        Pure reader: does NOT delete empty session files. Empty files are removed
        on next save_session() when a session becomes empty. A read-only getter
        must not mutate the filesystem as a side effect — that makes list_sessions
        unsafe to call from UI/status code.
        """
        sessions = []
        if not os.path.exists(self.sessions_dir):
            return sessions

        for filename in os.listdir(self.sessions_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.sessions_dir, filename)
                try:
                    data = read_json(filepath)
                    if not data or not isinstance(data, dict):
                        continue
                    ui_msgs = data.get("ui_messages") or data.get("messages") or []
                    agent_history = data.get("agent_history") or []

                    if not ui_msgs and not agent_history:
                        continue

                    sessions.append({
                        "id": data.get("id", filename[:-5]),
                        "title": data.get("title", "Untitled"),
                        "created_at": data.get("created_at", 0),
                        "updated_at": data.get("updated_at", 0),
                        "message_count": len(ui_msgs) if ui_msgs else len(agent_history)
                    })
                except Exception as e:
                    print(f"Error reading session {filename}: {e}")

        sessions.sort(key=lambda s: (s["updated_at"], s["created_at"], s["id"]), reverse=True)
        return sessions

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        filepath = os.path.join(self.sessions_dir, f"{session_id}.json")
        return read_json(filepath, default=None)

    def save_session(self, session_id: str, data: Dict[str, Any]):
        """Saves session ONLY if it contains at least one message"""
        if not session_id:
            return

        filepath = os.path.join(self.sessions_dir, f"{session_id}.json")
        ui_msgs = data.get("ui_messages") or data.get("messages") or []
        agent_history = data.get("agent_history") or []

        # Do not save empty sessions; if file existed - remove it
        if not ui_msgs and not agent_history:
            if os.path.exists(filepath):
                os.remove(filepath)
            return

        data["updated_at"] = time.time()
        if "created_at" not in data:
            data["created_at"] = time.time()

        write_json(filepath, data)
        self.set_active_session_id(session_id)

    def set_active_session_id(self, session_id: str):
        cfg = read_json(self.config_file, {})
        cfg["active_session_id"] = session_id
        write_json(self.config_file, cfg)
