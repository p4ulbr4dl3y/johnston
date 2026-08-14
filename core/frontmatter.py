"""
Frontmatter & Markdown Registry File Utilities.
Provides unified YAML frontmatter parsing, CSV/bracket list parsing, and directory iteration.
"""

import os
from typing import Any, Dict, Generator, List, Tuple


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    Parses YAML frontmatter delimited by `---`.
    Supports single-line and multi-line scalar values (including > and | block scalars).
    Returns (frontmatter_dict, body_content).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    fm_text, body = parts[1], parts[2]
    fm: Dict[str, Any] = {}

    def _flush(current_key, current_val_lines):
        if not current_key:
            return None
        joined = " ".join(line.strip() for line in current_val_lines if line.strip()).strip()
        if joined in (">", "|"):
            joined = ""
        elif joined.startswith("> ") or joined.startswith("| "):
            joined = joined[2:].strip()
        elif (joined.startswith(">") or joined.startswith("|")) and len(joined) > 1:
            joined = joined[1:].strip()
        return current_key, joined.strip('"').strip("'")

    current_key = None
    current_val_lines: List[str] = []
    for line in fm_text.splitlines():
        sline = line.strip()
        if not sline or sline.startswith("#"):
            continue

        if ":" in sline and not line.startswith(" ") and not line.startswith("\t"):
            if current_key:
                flushed = _flush(current_key, current_val_lines)
                fm[flushed[0]] = flushed[1]
            k, v = sline.split(":", 1)
            current_key = k.strip().lower()
            # Strip inline '#' comments from inline values (not block scalars).
            v_str = v.strip()
            if not v_str.startswith(">") and not v_str.startswith("|"):
                v_str = v_str.split("#", 1)[0]
            v_str = v_str.strip().strip('"').strip("'")
            current_val_lines = [v_str] if v_str else []
        elif current_key and (line.startswith(" ") or line.startswith("\t")):
            current_val_lines.append(sline)

    if current_key:
        fm[current_key] = _flush(current_key, current_val_lines)[1]
    return fm, body


def parse_csv_list(raw_val: Any) -> List[str]:
    """Parses bracketed or comma-separated string lists, e.g. '[foo, bar]' -> ['foo', 'bar']."""
    if not raw_val:
        return []
    if isinstance(raw_val, list):
        return [v.strip() for v in raw_val if v is not None and str(v).strip()]
    cleaned = str(raw_val).strip("[]")
    return [v.strip() for v in cleaned.split(",") if v.strip()]


def iter_md_files(dirs: List[Tuple[str, str]]) -> Generator[Tuple[str, str], None, None]:
    """
    Yields (file_path, source) pairs for .md/.markdown files across directory list,
    deduplicating paths using realpath.
    """
    scanned_paths = set()
    for dpath, source in dirs:
        if not os.path.isdir(dpath):
            continue
        rpath = os.path.realpath(dpath)
        if rpath in scanned_paths:
            continue
        scanned_paths.add(rpath)

        for fname in sorted(os.listdir(dpath)):
            if fname.endswith(".md") or fname.endswith(".markdown"):
                fpath = os.path.join(dpath, fname)
                if os.path.isfile(fpath):
                    yield fpath, source
