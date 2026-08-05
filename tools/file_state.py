import os
import time
from typing import Dict, Tuple

_FILE_READ_STATE: Dict[str, float] = {}


def record_file_read(path: str) -> None:
    path = os.path.abspath(os.path.expanduser(path))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = time.time()
    _FILE_READ_STATE[path] = mtime


def record_file_write(path: str) -> None:
    path = os.path.abspath(os.path.expanduser(path))
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = time.time()
    _FILE_READ_STATE[path] = mtime


def verify_file_read(path: str) -> Tuple[bool, str]:
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        return True, ""

    if path not in _FILE_READ_STATE:
        return (
            False,
            f"ERR: file '{path}' has not been read yet. Use the 'read' tool first before modifying it.",
        )

    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        return True, ""

    last_read_mtime = _FILE_READ_STATE[path]
    if current_mtime > last_read_mtime + 0.01:
        return (
            False,
            f"ERR: file '{path}' has been modified since it was last read. "
            "Read it again before attempting to modify it.",
        )

    return True, ""


def clear_file_state() -> None:
    _FILE_READ_STATE.clear()
