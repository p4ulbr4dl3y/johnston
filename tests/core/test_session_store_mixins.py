import os
import tempfile

from johnston_core.domain.entities.session import SessionKind
from johnston_core.infrastructure.config.settings import JohnstonSettings, StorageSettings
from johnston_core.infrastructure.storage.session_index_db import SessionIndexDb
from johnston_core.infrastructure.storage.session_store import SessionStore
from johnston_core.infrastructure.storage.session_store_cache import SessionStoreCacheMixin
from johnston_core.infrastructure.storage.session_store_locks import SessionStoreLocksMixin
from johnston_core.infrastructure.storage.session_store_paths import SessionStorePathsMixin


def test_paths_mixin_standalone():
    class DummyPaths(SessionStorePathsMixin):
        def __init__(self, sdir: str):
            self.sessions_dir = sdir

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = DummyPaths(os.path.join(tmpdir, "sessions"))
        paths.ensure_dirs()
        assert os.path.isdir(paths.sessions_dir)

        sid = paths.generate_session_id()
        assert len(sid) == 8
        sub_id = paths.generate_subagent_id()
        assert sub_id.startswith("subagent-")
        assert len(sub_id) == len("subagent-") + 8

        m_path = paths._main_path(sid)
        assert m_path.endswith(f"{sid}.jsonl")

        s_dir = paths._subagent_dir(sid)
        assert s_dir.endswith(f"{sid}.subagents")

        s_path = paths._subagent_path(sid, sub_id)
        assert s_path == os.path.join(s_dir, f"{sub_id}.jsonl")

        # Empty session id handling
        assert paths._main_path("").endswith(".jsonl")


def test_locks_mixin_standalone():
    class DummyLocks(SessionStoreLocksMixin):
        def __init__(self, sdir: str):
            self.sessions_dir = sdir
            self._active_locks = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        locks = DummyLocks(tmpdir)

        # Empty id
        assert not locks.is_session_locked("")
        assert not locks.acquire_session_lock("")
        locks.release_session_lock("")
        assert not locks.steal_session_lock("")

        # Normal acquire and release
        assert locks.acquire_session_lock("sess1")
        assert locks.acquire_session_lock("sess1")  # idempotent when held
        assert not locks.is_session_locked("sess1")  # held by self

        locks.release_session_lock("sess1")
        assert not locks.is_session_locked("sess1")

        # Steal lock
        assert locks.steal_session_lock("sess2")
        assert "sess2" in locks._active_locks

        locks.release_all_locks()
        assert len(locks._active_locks) == 0


def test_cache_mixin_standalone(monkeypatch):
    class DummyCache(SessionStorePathsMixin, SessionStoreCacheMixin):
        def __init__(self, sdir: str, db_path: str):
            self.sessions_dir = sdir
            self.index_db = SessionIndexDb(db_path)
            self._disk_cache = None
            self._disk_cache_signature = None
            self._disk_cache_ts = 0.0
            self._disk_cache_ttl = None

    with tempfile.TemporaryDirectory() as tmpdir:
        sdir = os.path.join(tmpdir, "sessions")
        os.makedirs(sdir, exist_ok=True)
        db_path = os.path.join(tmpdir, "index.db")
        cache = DummyCache(sdir, db_path)

        # Default TTL from settings
        custom_settings = JohnstonSettings(storage=StorageSettings(disk_cache_ttl=12.5))
        monkeypatch.setattr("johnston_core.infrastructure.storage.session_store.get_settings", lambda: custom_settings)
        assert cache.DISK_CACHE_TTL == 12.5

        # Explicit TTL setter
        cache.DISK_CACHE_TTL = 5.0
        assert cache.DISK_CACHE_TTL == 5.0

        # Signature on non-existent dir
        cache.sessions_dir = os.path.join(tmpdir, "nonexistent")
        assert cache._disk_signature() is None
        assert cache._subagent_path_from_scan("sub1") is None

        # Reset sessions_dir
        cache.sessions_dir = sdir
        sig = cache._disk_signature()
        assert isinstance(sig, int)

        # Load sessions from empty dir
        res = cache._load_disk_sessions()
        assert res == {}

        # Invalidate cache
        cache._invalidate_disk_cache()
        assert cache._disk_cache is None
        assert cache._disk_cache_signature is None
        assert cache._disk_cache_ts == 0.0

        # Load corrupted file
        bad_file = os.path.join(sdir, "corrupt.jsonl")
        with open(bad_file, "w", encoding="utf-8") as f:
            f.write("invalid json content\n")
        dummy_dict = {}
        cache._load_file(dummy_dict, bad_file)
        assert dummy_dict == {}


def test_session_store_integration():
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SessionStore(project_path=tmpdir)
        sess = store.create_main("s_int")
        sess.messages = [{"type": "user", "text": "hello"}]
        store.save(sess)

        # Cache hit
        loaded = store.get("s_int")
        assert loaded is not None
        assert loaded.id == "s_int"

        # List
        mains = store.list(kind=SessionKind.MAIN)
        assert len(mains) == 1
        assert mains[0].id == "s_int"

        # Subagent
        sub = store.create_subagent(parent_id="s_int", title="SubTask")
        store.save(sub)

        subs = store.children("s_int")
        assert len(subs) == 1
        assert subs[0].id == sub.id

        # Scan for subagent
        scanned_path = store._subagent_path_from_scan(sub.id)
        assert scanned_path is not None
        assert os.path.exists(scanned_path)

        # Delete
        store.delete("s_int")
        assert store.get("s_int") is None
