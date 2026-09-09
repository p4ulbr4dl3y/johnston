import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Dict, Generator, List, Optional

from johnston.core.domain.entities.session import AgentSession, SessionKind

logger = logging.getLogger(__name__)


class SessionIndexDb:
    """SQLite-backed metadata index for fast session listing without JSONL disk scans."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._ensure_schema()

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        try:
            yield conn
        finally:
            conn.close()

    def _ensure_schema(self) -> None:
        try:
            with self._connection() as conn:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS session_index (
                            id TEXT PRIMARY KEY,
                            project_key TEXT NOT NULL,
                            kind TEXT NOT NULL,
                            parent_id TEXT,
                            role TEXT,
                            status TEXT,
                            title TEXT,
                            created_at REAL,
                            updated_at REAL,
                            message_count INTEGER DEFAULT 0,
                            turn_count INTEGER DEFAULT 0,
                            is_empty INTEGER DEFAULT 0
                        );
                        """
                    )
                    conn.execute(
                        """
                        CREATE INDEX IF NOT EXISTS idx_session_project_updated
                        ON session_index(project_key, kind, updated_at DESC);
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS index_meta (
                            key TEXT PRIMARY KEY,
                            value TEXT
                        );
                        """
                    )
        except Exception:
            logger.warning("Failed to initialize session index sqlite db at %s", self.db_path, exc_info=True)

    def get_meta(self, key: str) -> Optional[str]:
        try:
            with self._connection() as conn:
                cursor = conn.execute("SELECT value FROM index_meta WHERE key = ?", (key,))
                row = cursor.fetchone()
                return str(row["value"]) if row else None
        except Exception:
            return None

    def set_meta(self, key: str, value: str) -> None:
        try:
            with self._connection() as conn:
                with conn:
                    conn.execute(
                        "INSERT INTO index_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, str(value)),
                    )
        except Exception:
            logger.warning("Failed to set meta key %s", key, exc_info=True)

    def upsert_session(self, sess: AgentSession) -> None:
        """Insert or update session metadata in SQLite index."""
        try:
            is_empty = 1 if (not sess.messages and not sess.agent_history) else 0
            with self._connection() as conn:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO session_index (
                            id, project_key, kind, parent_id, role, status, title,
                            created_at, updated_at, message_count, turn_count, is_empty
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            project_key = excluded.project_key,
                            kind = excluded.kind,
                            parent_id = excluded.parent_id,
                            role = excluded.role,
                            status = excluded.status,
                            title = excluded.title,
                            created_at = excluded.created_at,
                            updated_at = excluded.updated_at,
                            message_count = excluded.message_count,
                            turn_count = excluded.turn_count,
                            is_empty = excluded.is_empty;
                        """,
                        (
                            sess.id,
                            sess.project_key,
                            sess.kind.value if isinstance(sess.kind, SessionKind) else str(sess.kind),
                            sess.parent_id,
                            sess.role,
                            sess.status,
                            sess.title,
                            float(sess.created_at or 0.0),
                            float(sess.updated_at or 0.0),
                            int(sess.message_count or 0),
                            int(sess.turn_count or 0),
                            is_empty,
                        ),
                    )
        except Exception:
            logger.warning("Failed to upsert session %s into index db", sess.id, exc_info=True)

    def delete_session(self, session_id: str) -> None:
        """Remove a session (and any cascaded subagents) from SQLite index."""
        try:
            with self._connection() as conn:
                with conn:
                    conn.execute(
                        "DELETE FROM session_index WHERE id = ? OR parent_id = ?",
                        (session_id, session_id),
                    )
        except Exception:
            logger.warning("Failed to delete session %s from index db", session_id, exc_info=True)

    def query_main_sessions(self, project_key: str, limit: int = 500) -> List[Dict[str, Any]]:
        """Query non-empty main sessions for project sorted by updated_at DESC."""
        try:
            with self._connection() as conn:
                cursor = conn.execute(
                    """
                    SELECT id, parent_id, title, created_at, updated_at, message_count, turn_count
                    FROM session_index
                    WHERE project_key = ? AND kind = ? AND is_empty = 0
                    ORDER BY updated_at DESC, created_at DESC, id DESC
                    LIMIT ?;
                    """,
                    (project_key, SessionKind.MAIN.value, limit),
                )
                rows = cursor.fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.warning("Failed to query main sessions from index db for %s", project_key, exc_info=True)
            return []

    def query_subagent_ids(self, project_key: str, parent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Query subagent metadata for a project or specific parent."""
        try:
            with self._connection() as conn:
                if parent_id:
                    cursor = conn.execute(
                        """
                        SELECT id, parent_id, role, status, title, created_at, updated_at, message_count
                        FROM session_index
                        WHERE project_key = ? AND kind = ? AND parent_id = ?
                        ORDER BY updated_at DESC;
                        """,
                        (project_key, SessionKind.SUBAGENT.value, parent_id),
                    )
                else:
                    cursor = conn.execute(
                        """
                        SELECT id, parent_id, role, status, title, created_at, updated_at, message_count
                        FROM session_index
                        WHERE project_key = ? AND kind = ?
                        ORDER BY updated_at DESC;
                        """,
                        (project_key, SessionKind.SUBAGENT.value),
                    )
                return [dict(r) for r in cursor.fetchall()]
        except Exception:
            logger.warning("Failed to query subagents from index db for %s", project_key, exc_info=True)
            return []

    def bulk_reindex(self, project_key: str, sessions: List[AgentSession], signature: Optional[str] = None) -> None:
        """Atomically rebuild the index for a collection of sessions."""
        try:
            records = []
            for s in sessions:
                is_empty = 1 if (not s.messages and not s.agent_history) else 0
                records.append((
                    s.id,
                    project_key,
                    s.kind.value if isinstance(s.kind, SessionKind) else str(s.kind),
                    s.parent_id,
                    s.role,
                    s.status,
                    s.title,
                    float(s.created_at or 0.0),
                    float(s.updated_at or 0.0),
                    int(s.message_count or 0),
                    int(s.turn_count or 0),
                    is_empty,
                ))

            with self._connection() as conn:
                with conn:
                    conn.execute("DELETE FROM session_index WHERE project_key = ?", (project_key,))
                    if records:
                        conn.executemany(
                            """
                            INSERT OR REPLACE INTO session_index (
                                id, project_key, kind, parent_id, role, status, title,
                                created_at, updated_at, message_count, turn_count, is_empty
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            records,
                        )
                    if signature is not None:
                        conn.execute(
                            "INSERT INTO index_meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                            ("signature", str(signature)),
                        )
        except Exception:
            logger.warning("Failed to bulk reindex sessions in index db", exc_info=True)
