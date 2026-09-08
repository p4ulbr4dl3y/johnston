import os
import tempfile
import time

from johnston_core.domain.entities.session import AgentSession, SessionKind
from johnston_core.infrastructure.storage.session_index_db import SessionIndexDb
from johnston_core.infrastructure.storage.session_store import SessionStore


def test_session_index_db_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_index.db")
        index = SessionIndexDb(db_path)

        sess = AgentSession("s1", kind=SessionKind.MAIN, project_key="proj_1", title="Title 1")
        sess.messages = [{"type": "user", "text": "hello"}]
        sess.created_at = sess.updated_at = time.time()
        index.upsert_session(sess)

        rows = index.query_main_sessions("proj_1")
        assert len(rows) == 1
        assert rows[0]["id"] == "s1"
        assert rows[0]["title"] == "Title 1"

        # Update title
        sess.title = "New Title"
        index.upsert_session(sess)
        rows2 = index.query_main_sessions("proj_1")
        assert len(rows2) == 1
        assert rows2[0]["title"] == "New Title"

        # Delete
        index.delete_session("s1")
        assert len(index.query_main_sessions("proj_1")) == 0


def test_session_store_with_sqlite_reindex():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SessionStore(project_path=tmpdir)
        s1 = store.create_main("s1")
        s1.messages = [{"type": "user", "text": "foo"}]
        s1.updated_at = 100.0
        store.save(s1)

        s2 = store.create_main("s2")
        s2.messages = [{"type": "user", "text": "bar"}]
        s2.updated_at = 200.0
        store.save(s2)

        # Clear in-memory state
        store._sessions.clear()
        store._invalidate_disk_cache()

        # Should query SQLite and sort by updated_at desc
        sessions = store.list_main_sessions()
        assert [s["id"] for s in sessions] == ["s2", "s1"]

        # Delete from store also deletes from SQLite
        store.delete("s2")
        sessions_after_delete = store.list_main_sessions()
        assert [s["id"] for s in sessions_after_delete] == ["s1"]


def test_empty_sessions_and_signature_sync():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SessionStore(project_path=tmpdir)
        # 1. Empty session (no messages)
        s_empty = store.create_main("empty1")
        store.save(s_empty)

        store._sessions.clear()
        store._invalidate_disk_cache()

        # list_main_sessions should return empty without endless reindex
        sessions = store.list_main_sessions()
        assert sessions == []

        # 2. Add message to session externally
        s_empty.messages = [{"type": "user", "text": "not empty"}]
        store.save(s_empty)
        store._sessions.clear()
        store._invalidate_disk_cache()

        sessions2 = store.list_main_sessions()
        assert len(sessions2) == 1
        assert sessions2[0]["id"] == "empty1"
