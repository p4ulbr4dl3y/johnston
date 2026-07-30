import hashlib
import json
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR, PROJECTS_DIR  # noqa: F401


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

        Pure reader: does NOT delete empty session files. Empty files are purged
        explicitly via purge_empty_sessions() (called from save_session when a session
        becomes empty). A read-only getter must not mutate the filesystem as a side
        effect — that makes list_sessions unsafe to call from UI/status code.
        """
        sessions = []
        if not os.path.exists(self.sessions_dir):
            return sessions

        for filename in os.listdir(self.sessions_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(self.sessions_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
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

    def purge_empty_sessions(self) -> int:
        """Removes session files that contain no messages. Returns count removed.

        Explicit cleanup operation kept separate from the read-only list_sessions so
        that reading the session list never has destructive filesystem side effects.
        """
        removed = 0
        if not os.path.exists(self.sessions_dir):
            return removed
        for filename in os.listdir(self.sessions_dir):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(self.sessions_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                ui_msgs = data.get("ui_messages") or data.get("messages") or []
                agent_history = data.get("agent_history") or []
                if not ui_msgs and not agent_history:
                    os.remove(filepath)
                    removed += 1
            except Exception:
                pass
        return removed

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        if not session_id:
            return None
        filepath = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading session {session_id}: {e}")
        return None

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

        temp_filepath = f"{filepath}.tmp.{uuid.uuid4().hex[:6]}"
        try:
            with open(temp_filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_filepath, filepath)
        except Exception:
            if os.path.exists(temp_filepath):
                try:
                    os.remove(temp_filepath)
                except Exception:
                    pass
            raise

        self.set_active_session_id(session_id)

    def delete_session(self, session_id: str):
        filepath = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
        try:
            from core.git_checkpoint import GitCheckpointManager
            GitCheckpointManager.delete_session_checkpoints(session_id, project_path=self.project_path)
        except Exception:
            pass

    def get_active_session_id(self) -> Optional[str]:
        """Returns ID of last active session or None if none exist"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    sid = cfg.get("active_session_id")
                    if sid and os.path.exists(os.path.join(self.sessions_dir, f"{sid}.json")):
                        return sid
            except Exception:
                pass

        sessions = self.list_sessions()
        if sessions:
            sid = sessions[0]["id"]
            self.set_active_session_id(sid)
            return sid

        return None

    def set_active_session_id(self, session_id: str):
        cfg = {}
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}

        cfg["active_session_id"] = session_id
        with open(self.config_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
