import os
import json
import time
import uuid
import hashlib
from typing import List, Dict, Any, Optional
from core.config import CONFIG_DIR, PROJECTS_DIR

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
        """Возвращает список только НЕПУСТЫХ сессий текущего проекта, отсортированный по времени обновления"""
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
                        
                        # Если сессия пустая — удаляем мусорный файл
                        if not ui_msgs:
                            os.remove(filepath)
                            continue
                            
                        sessions.append({
                            "id": data.get("id", filename[:-5]),
                            "title": data.get("title", "Untitled"),
                            "created_at": data.get("created_at", 0),
                            "updated_at": data.get("updated_at", 0),
                            "message_count": len(ui_msgs)
                        })
                except Exception as e:
                    print(f"Error reading session {filename}: {e}")

        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return sessions

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
        """Сохраняет сессию ТОЛЬКО если в ней есть хотя бы одно сообщение"""
        if not session_id:
            return

        filepath = os.path.join(self.sessions_dir, f"{session_id}.json")
        ui_msgs = data.get("ui_messages") or data.get("messages") or []

        # Не сохраняем пустые сессии, а если файл существовал — удаляем
        if not ui_msgs:
            if os.path.exists(filepath):
                os.remove(filepath)
            return

        data["updated_at"] = time.time()
        if "created_at" not in data:
            data["created_at"] = time.time()

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        self.set_active_session_id(session_id)

    def delete_session(self, session_id: str):
        filepath = os.path.join(self.sessions_dir, f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)

    def get_active_session_id(self) -> Optional[str]:
        """Возвращает ID последней активной сессии проекта или None если сохраненных нет"""
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
