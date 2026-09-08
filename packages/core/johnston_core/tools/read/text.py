import itertools
import os

from johnston_core.tools.read.cache import _get_file_line_count, get_read_line_window


def _read_file_lines(
    file_path: str, offset: int | None, s_line: int | None, e_line: int | None
) -> tuple[list[str], int]:
    """Read file lines, optionally bounded to a requested line window.

    When a start/end line is given, reads only the requested range
    (inclusive, 1-based) instead of the whole file, avoiding a full
    buffered read + copy. Trailing newlines are stripped in place.
    Returns (window_lines, total_line_count) so pagination headers
    stay accurate even for partial reads.
    """
    try:
        st = os.stat(file_path)
        mtime, size = st.st_mtime, st.st_size
    except OSError:
        mtime, size = 0.0, 0
    total = _get_file_line_count(file_path, mtime, size)

    with open(file_path, "rb") as f:
        if offset:
            f.seek(offset)
        if s_line is not None and s_line > 1:
            # Skip to the requested first line without buffering the whole file.
            for _ in itertools.islice(f, s_line - 1):
                pass
        window = get_read_line_window()
        if e_line is not None:
            # Read only up to the requested end line.
            remaining = max(1, e_line - max(1, s_line or 1) + 1)
        else:
            remaining = window
        raw_lines = []
        for _ in range(remaining):
            ln = f.readline()
            if not ln:
                break
            raw_lines.append(ln)
        lines = [ln.rstrip(b"\r\n").decode("utf-8", errors="replace") for ln in raw_lines]
        return lines, total
