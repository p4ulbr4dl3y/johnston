import os


def read_file_content(file_path: str) -> str | None:
    """Read a file from disk for display purposes.

    Returns the file content (utf-8, errors='replace') or *None* when the
    path does not exist or read fails.  Widget callers should handle the
    *None* case gracefully (e.g. fall back to ``result_text``).
    """
    if not file_path:
        return None
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None
