import os


def read_file_content(file_path: str, max_bytes: int = 2 * 1024 * 1024) -> str | None:
    """Read a file from disk for display purposes.

    Returns the file content (utf-8, errors='replace') or *None* when the
    path does not exist or read fails.  Widget callers should handle the
    *None* case gracefully (e.g. fall back to ``result_text``).
    """
    if not file_path:
        return None
    expanded = os.path.expanduser(file_path)
    if not os.path.isfile(expanded):
        return None
    try:
        with open(expanded, "r", encoding="utf-8", errors="replace") as f:
            return f.read(max_bytes)
    except Exception:
        return None
