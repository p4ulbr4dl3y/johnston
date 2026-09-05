import fnmatch
import logging
import os
import shutil
import subprocess
import threading
from typing import List, Optional, Tuple

from tools.search.common import (
    DEFAULT_EXCLUDE_DIRS,
    _GitignoreMatcher,
    _match_glob,
    _safe_relpath,
    _walk_filtered,
)

logger = logging.getLogger(__name__)


def _search_filename_ripgrep(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Tuple[List[str], int]]:
    """Use rg --files for fast filename listing with streaming output."""
    if cancel_event and cancel_event.is_set():
        return [], 0

    rg_bin = shutil.which("rg")
    if not rg_bin:
        return None

    cmd = [rg_bin, "--files", "--null", "--color=never"]

    if include_hidden:
        cmd.append("--hidden")

    if glob_pattern:
        for g in glob_pattern.split(","):
            g = g.strip()
            if g:
                cmd.extend(["-g", g])

    for exc in DEFAULT_EXCLUDE_DIRS:
        cmd.extend(["-g", f"!**/{exc}/**"])

    cmd.extend(["--", target_path])

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=8192,
        )
    except Exception as e:
        logger.debug("rg --files invocation failed: %s", e)
        return None

    matched_paths: List[str] = []
    q = query.strip() if query else ""
    q_is_wild = not q or q == "*"

    buffer = b""
    try:
        if proc.stdout is not None:
            while True:
                if cancel_event and cancel_event.is_set():
                    break
                chunk = proc.stdout.read(8192)
                if not chunk:
                    break
                buffer += chunk
                while b"\x00" in buffer:
                    raw_path, buffer = buffer.split(b"\x00", 1)
                    if not raw_path:
                        continue
                    fpath = raw_path.decode("utf-8", errors="replace")
                    rel = _safe_relpath(fpath, cwd) if os.path.isabs(fpath) else fpath
                    fname = os.path.basename(rel)

                    if not q_is_wild:
                        if not (fnmatch.fnmatch(fname, q) or fnmatch.fnmatch(rel, q)):
                            if q.lower() not in fname.lower() and q.lower() not in rel.lower():
                                continue

                    if glob_pattern and not _match_glob(rel, fname, glob_pattern):
                        continue

                    matched_paths.append(rel)
                    if len(matched_paths) >= max_results:
                        break
                if len(matched_paths) >= max_results:
                    break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except Exception:
                proc.kill()
        try:
            proc.communicate()
        except Exception:
            pass

    if cancel_event and cancel_event.is_set():
        return [], 0

    if proc.returncode not in (0, 1, -15, -9) and not matched_paths:
        return None

    return matched_paths, len(matched_paths)


def _search_filename_python(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[str], int]:
    """Find files/directories matching query/glob pattern in pure Python."""
    matched_paths: List[str] = []
    q = query.strip() if query else ""
    q_is_wild = not q or q == "*"

    def _matches_query(rel: str, fname: str) -> bool:
        if q_is_wild:
            return True
        if fnmatch.fnmatch(fname, q) or fnmatch.fnmatch(rel, q):
            return True
        return q.lower() in fname.lower() or q.lower() in rel.lower()

    if cancel_event and cancel_event.is_set():
        return [], 0

    if os.path.isfile(target_path):
        rel = _safe_relpath(target_path, cwd)
        fname = os.path.basename(target_path)
        if _matches_query(rel, fname) and _match_glob(rel, fname, glob_pattern):
            matched_paths.append(rel)
        return matched_paths, len(matched_paths)

    for abs_p in _walk_filtered(target_path, include_hidden, gitignore_matcher, cancel_event):
        if cancel_event and cancel_event.is_set():
            break
        if len(matched_paths) >= max_results:
            break
        rel = _safe_relpath(abs_p, cwd)
        fname = os.path.basename(rel)
        if _matches_query(rel, fname) and _match_glob(rel, fname, glob_pattern):
            matched_paths.append(rel)

    if cancel_event and cancel_event.is_set():
        return [], 0

    return matched_paths, len(matched_paths)


def _search_filename(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[str], int, int]:
    rg_result = _search_filename_ripgrep(
        target_path=target_path,
        query=query,
        cwd=cwd,
        glob_pattern=glob_pattern,
        max_results=max_results,
        include_hidden=include_hidden,
        cancel_event=cancel_event,
    )
    if rg_result is not None:
        paths, count = rg_result
        return paths, count, count

    paths, count = _search_filename_python(
        target_path=target_path,
        query=query,
        cwd=cwd,
        glob_pattern=glob_pattern,
        max_results=max_results,
        include_hidden=include_hidden,
        gitignore_matcher=gitignore_matcher,
        cancel_event=cancel_event,
    )
    return paths, count, count
