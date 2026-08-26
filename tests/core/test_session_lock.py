import atexit
import json
import os
import platform
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.infrastructure.platform.session_lock import SessionLock
from core.session_manager import SessionStore
from tools.context import ToolContext


class TestSessionLock(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.lock_path = os.path.join(self.tmp_dir.name, "test_sess.lock")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_acquire_and_release(self):
        lock1 = SessionLock(self.lock_path)
        self.assertTrue(lock1.acquire())
        self.assertTrue(os.path.exists(self.lock_path))

        # Re-acquiring with same instance returns True
        self.assertTrue(lock1.acquire())

        # Second instance cannot acquire while lock1 is holding it
        lock2 = SessionLock(self.lock_path)
        self.assertFalse(lock2.acquire())

        # Probe shows locked
        is_locked, meta = SessionLock.probe(self.lock_path)
        self.assertTrue(is_locked)
        self.assertIsNotNone(meta)
        self.assertEqual(meta.get("pid"), os.getpid())

        # Release lock1
        lock1.release()
        # Lockfile is retained on release (prevents POSIX flock race)
        self.assertTrue(os.path.exists(self.lock_path))

        # Now lock2 can acquire
        self.assertTrue(lock2.acquire())
        lock2.release()

    def test_no_atexit_leak_on_probes(self):
        lock = SessionLock(self.lock_path)
        self.assertTrue(lock.acquire())

        # Run 20 probes on locked file
        initial_callbacks = len(getattr(atexit, "_exithandlers", []))
        for _ in range(20):
            is_locked, _ = SessionLock.probe(self.lock_path)
            self.assertTrue(is_locked)

        current_callbacks = len(getattr(atexit, "_exithandlers", []))
        self.assertEqual(initial_callbacks, current_callbacks)

        lock.release()

    def test_probe_non_existent(self):
        is_locked, meta = SessionLock.probe(os.path.join(self.tmp_dir.name, "none.lock"))
        self.assertFalse(is_locked)
        self.assertIsNone(meta)

    def test_probe_stale_lockfile(self):
        # Write lockfile without flock
        with open(self.lock_path, "w") as f:
            json.dump({"pid": 999999, "hostname": "local"}, f)

        is_locked, meta = SessionLock.probe(self.lock_path)
        self.assertFalse(is_locked)
        self.assertIsNone(meta)

    def test_steal_lock(self):
        # Mock probe and kill to test stealing
        with patch.object(SessionLock, "probe", return_value=(True, {"pid": 12345, "hostname": platform.node()})):
            with patch("os.kill") as mock_kill:
                stolen = SessionLock.steal(self.lock_path)
                self.assertIsNotNone(stolen)
                self.assertTrue(stolen._is_owner)
                mock_kill.assert_called()
                stolen.release()


class TestSessionStoreLockingAndFork(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.store = SessionStore(project_path=self.tmp_dir.name)

    def tearDown(self):
        self.store.release_all_locks()
        self.tmp_dir.cleanup()

    def test_store_lock_lifecycle(self):
        sess = self.store.create_main()
        sid = sess.id

        self.assertFalse(self.store.is_session_locked(sid))

        # Acquire lock
        self.assertTrue(self.store.acquire_session_lock(sid))
        # Held by self -> is_session_locked returns False for own store
        self.assertFalse(self.store.is_session_locked(sid))

        # Another store instance on same project sees it as locked
        other_store = SessionStore(project_path=self.tmp_dir.name)
        self.assertTrue(other_store.is_session_locked(sid))

        # Release
        self.store.release_session_lock(sid)
        self.assertFalse(other_store.is_session_locked(sid))

    def test_store_steal_session_lock(self):
        sess = self.store.create_main()
        sid = sess.id

        # External store locks it
        other_store = SessionStore(project_path=self.tmp_dir.name)
        self.assertTrue(other_store.acquire_session_lock(sid))
        self.assertTrue(self.store.is_session_locked(sid))

        # We steal it with mock
        mock_acquired = SessionLock(self.store._lock_path(sid))
        with patch.object(SessionLock, "steal", return_value=mock_acquired):
            self.assertTrue(self.store.steal_session_lock(sid))
            self.assertFalse(self.store.is_session_locked(sid))

    def test_store_fork_session(self):
        sess = self.store.create_main()
        sess.description = "Initial task"
        sess.messages = [{"type": "user", "text": "hello"}]
        sess.tokens_input = 100
        self.store.save(sess)

        forked = self.store.fork_session(sess.id)
        self.assertIsNotNone(forked)
        self.assertNotEqual(forked.id, sess.id)
        self.assertEqual(len(forked.messages), 1)
        self.assertEqual(forked.messages[0]["text"], "hello")
        self.assertEqual(forked.tokens_input, 100)
        self.assertIn("(fork)", forked.description)

        # Forking invalid session returns None
        self.assertIsNone(self.store.fork_session("non_existent"))

    def test_list_main_sessions_annotates_locked(self):
        sess1 = self.store.create_main()
        sess1.messages = [{"type": "user", "text": "Task 1"}]
        self.store.save(sess1)

        sess2 = self.store.create_main()
        sess2.messages = [{"type": "user", "text": "Task 2"}]
        self.store.save(sess2)

        # Lock sess2 via external lock
        lock_path = self.store._lock_path(sess2.id)
        ext_lock = SessionLock(lock_path)
        self.assertTrue(ext_lock.acquire())

        sessions = self.store.list_main_sessions()
        s2_entry = next((s for s in sessions if s["id"] == sess2.id), None)
        self.assertIsNotNone(s2_entry)
        self.assertTrue(s2_entry["is_locked"])

        s1_entry = next((s for s in sessions if s["id"] == sess1.id), None)
        self.assertIsNotNone(s1_entry)
        self.assertFalse(s1_entry["is_locked"])

        ext_lock.release()

    def test_tool_context_is_read_only(self):
        host = MagicMock()
        host.is_read_only = True
        host.role = "worker"
        ctx = ToolContext(app=host)
        self.assertTrue(ctx.is_read_only)

        host.is_read_only = False
        self.assertFalse(ctx.is_read_only)
