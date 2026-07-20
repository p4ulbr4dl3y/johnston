import os
import json
import time
import uuid
from typing import List, Dict, Any, Optional

CONFIG_DIR = os.path.expanduser("~/.tui")
SESSIONS_DIR = os.path.join(CONFIG_DIR, "sessions")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

class SessionManager:
    def __init__(self):
        self.ensure_dirs()

    def ensure_dirs(self):
        os.makedirs(SESSIONS_DIR, exist_ok=True)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Возвращает список всех сохраненных сессий, отсортированный по времени обновления"""
        sessions = []
        if not os.path.exists(SESSIONS_DIR):
            return sessions

        for filename in os.listdir(SESSIONS_DIR):
            if filename.endswith(".json"):
                filepath = os.path.join(SESSIONS_DIR, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        sessions.append({
                            "id": data.get("id", filename[:-5]),
                            "title": data.get("title", "Без названия"),
                            "created_at": data.get("created_at", 0),
                            "updated_at": data.get("updated_at", 0),
                            "message_count": len(data.get("messages", []))
                        })
                except Exception as e:
                    print(f"Ошибка чтения сессии {filename}: {e}")

        sessions.sort(key=lambda s: s["updated_at"], reverse=True)
        return sessions

    def create_session(self, title: str = "Новый диалог") -> str:
        session_id = f"session_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        data = {
            "id": session_id,
            "title": title,
            "created_at": time.time(),
            "updated_at": time.time(),
            "messages": [],
            "agent_history": []
        }
        self.save_session(session_id, data)
        self.set_active_session_id(session_id)
        return session_id

    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        filepath = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Ошибка загрузки сессии {session_id}: {e}")
        return None

    def save_session(self, session_id: str, data: Dict[str, Any]):
        filepath = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        data["updated_at"] = time.time()
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def delete_session(self, session_id: str):
        filepath = os.path.join(SESSIONS_DIR, f"{session_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)

    def get_active_session_id(self) -> str:
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    sid = cfg.get("active_session_id")
                    if sid and os.path.exists(os.path.join(SESSIONS_DIR, f"{sid}.json")):
                        return sid
            except Exception:
                pass
        
        # Если нет активной сессии, смотрим список или создаем новую
        sessions = self.list_sessions()
        if sessions:
            sid = sessions[0]["id"]
            self.set_active_session_id(sid)
            return sid
        else:
            return self.create_session("Главный диалог")

    def set_active_session_id(self, session_id: str):
        cfg = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                cfg = {}
        
        cfg["active_session_id"] = session_id
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
