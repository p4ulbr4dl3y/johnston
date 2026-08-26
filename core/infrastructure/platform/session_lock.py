import atexit
import json
import logging
import os
import platform
import signal
import sys
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _is_windows() -> bool:
    return sys.platform == "win32" or os.name == "nt"


class SessionLock:
    """Cross-platform advisory file lock for AgentSession instances.

    Uses OS kernel locking (``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows)
    so locks are automatically released by the OS if a process terminates abruptly (crash/kill).
    Lock files are retained on release to prevent POSIX inode-deletion race conditions.
    """

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self._fd: Optional[int] = None
        self._is_owner = False

    @classmethod
    def for_session(cls, sessions_dir: str, session_id: str) -> "SessionLock":
        safe_id = os.path.basename(session_id or "default")
        lock_path = os.path.join(sessions_dir, f"{safe_id}.lock")
        return cls(lock_path)

    def acquire(self) -> bool:
        """Attempt non-blocking acquisition of the session lock.

        Returns True if acquired, False if already held by another live process.
        """
        if self._is_owner and self._fd is not None:
            return True

        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(self.lock_path, flags, 0o600)
        except OSError:
            return False

        try:
            if _is_windows():
                import msvcrt

                # Windows locking requires non-zero size or byte range
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            self._fd = fd
            self._is_owner = True
            try:
                atexit.register(self.release)
            except Exception:
                pass

            # Write lock metadata
            payload = {
                "pid": os.getpid(),
                "created_at": time.time(),
                "hostname": platform.node(),
            }
            try:
                os.ftruncate(fd, 0)
                os.lseek(fd, 0, os.SEEK_SET)
                os.write(fd, json.dumps(payload).encode("utf-8"))
                os.fsync(fd)
            except OSError:
                pass

            return True
        except (BlockingIOError, OSError, PermissionError):
            try:
                os.close(fd)
            except OSError:
                pass
            return False

    def release(self) -> None:
        """Release the held lock and close the file descriptor."""
        try:
            atexit.unregister(self.release)
        except Exception:
            pass

        if self._fd is None or not self._is_owner:
            return

        fd = self._fd
        self._fd = None
        self._is_owner = False

        try:
            if _is_windows():
                import msvcrt

                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    @classmethod
    def probe(cls, lock_path: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Check if lock is held by another process without permanently acquiring it.

        Returns (is_locked, metadata_dict). If lock is free or stale, returns (False, None).
        """
        if not os.path.exists(lock_path):
            return False, None

        # Attempt to acquire and immediately release to verify lock state
        test_lock = cls(lock_path)
        if test_lock.acquire():
            test_lock.release()
            return False, None

        # Lock is held — read metadata if possible
        meta: Optional[Dict[str, Any]] = None
        try:
            with open(lock_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    meta = json.loads(content)
        except Exception:
            pass

        return True, meta

    @classmethod
    def steal(cls, lock_path: str) -> Optional["SessionLock"]:
        """Forcefully take over a session lock, terminating previous holder if local.

        Returns the acquired SessionLock instance on success, or None on failure.
        """
        is_locked, meta = cls.probe(lock_path)
        if is_locked and meta:
            holder_pid = meta.get("pid")
            hostname = meta.get("hostname")
            current_host = platform.node()

            # Only kill if same machine and not our own process
            if holder_pid and holder_pid != os.getpid() and (not hostname or hostname == current_host):
                try:
                    if _is_windows():
                        import subprocess

                        subprocess.run(["taskkill", "/F", "/PID", str(holder_pid)], capture_output=True)
                        time.sleep(0.15)
                    else:
                        os.kill(holder_pid, signal.SIGTERM)
                        # Brief grace period for cleanup
                        time.sleep(0.15)
                        try:
                            # If still alive, force kill
                            os.kill(holder_pid, 0)
                            os.kill(holder_pid, signal.SIGKILL)
                        except OSError:
                            pass
                except OSError:
                    pass

        # Directly instantiate and acquire ownership
        lock = cls(lock_path)
        if lock.acquire():
            return lock
        return None
