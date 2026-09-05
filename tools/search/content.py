import logging
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Set, Tuple

from tools.search.common import (
    DEFAULT_EXCLUDE_DIRS,
    OUTLINE_WORKERS,
    _GitignoreMatcher,
    _match_glob,
    _safe_relpath,
    _walk_filtered_list,
    get_max_search_bytes,
    is_binary_file,
)

logger = logging.getLogger(__name__)


def _search_content_ripgrep(
    target_path: str,
    query: str,
    cwd: str,
    case_sensitive: bool = False,
    before_lines: int = 0,
    after_lines: int = 0,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Tuple[List[str], int, int]]:
    """Run ripgrep subprocess for fast content search. Returns None on failure or if rg missing."""
    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    rg_bin = shutil.which("rg")
    if not rg_bin:
        return None

    if os.path.isfile(target_path):
        rel_target = _safe_relpath(target_path, cwd)
        fname = os.path.basename(target_path)
        if not _match_glob(rel_target, fname, glob_pattern):
            return [], 0, 0

    cmd = [
        rg_bin,
        "--color=never",
        "--null",
        "-H",
        "--line-number",
        "--no-heading",
        "--max-columns=300",
        "--max-columns-preview",
    ]

    if not case_sensitive:
        cmd.append("-i")

    if before_lines > 0:
        cmd.extend(["-B", str(before_lines)])
    if after_lines > 0:
        cmd.extend(["-A", str(after_lines)])

    if include_hidden:
        cmd.append("--hidden")

    if glob_pattern:
        for g in glob_pattern.split(","):
            g = g.strip()
            if g:
                cmd.extend(["-g", g])

    for exc in DEFAULT_EXCLUDE_DIRS:
        cmd.extend(["-g", f"!**/{exc}/**"])

    cmd.extend(["--", query, target_path])

    rg_rest_re = re.compile(r"^(\d+)([:-])(.*)$")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        logger.debug("ripgrep invocation failed: %s", e)
        return None

    output_lines: List[str] = []
    matched_files: Set[str] = set()
    match_count = 0
    stopping = False

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    break
                line = raw_line.rstrip("\r\n")
                if not line or line == "--":
                    if stopping:
                        break
                    continue

                if "\x00" in line:
                    fpath, rest = line.split("\x00", 1)
                    m = rg_rest_re.match(rest)
                    if m:
                        lineno = m.group(1)
                        sep = m.group(2)
                        text = m.group(3)
                        rel = _safe_relpath(fpath, cwd) if os.path.isabs(fpath) else fpath
                        matched_files.add(rel)
                        if sep == ":":
                            if stopping:
                                break
                            match_count += 1
                            if match_count >= max_results:
                                stopping = True
                        output_lines.append(f"{rel}{sep}{lineno}{sep}{text}")
                    else:
                        output_lines.append(line)
                else:
                    output_lines.append(line)
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
        return [], 0, 0

    if proc.returncode not in (0, 1, -15, -9) and match_count == 0:
        logger.debug("ripgrep exited with code %s", proc.returncode)
        return None

    return output_lines, match_count, len(matched_files)


def _search_content_python(
    target_path: str,
    query: str,
    cwd: str,
    case_sensitive: bool = False,
    before_lines: int = 0,
    after_lines: int = 0,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[str], int, int]:
    """Pure Python fallback for content regex/literal search."""
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        pattern = re.compile(query, flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)

    matched_files: Set[str] = set()
    output_lines: List[str] = []
    match_count = 0
    lock = threading.Lock()

    def _process_file(abs_fpath: str) -> Optional[Tuple[List[str], Set[str], int]]:
        if cancel_event and cancel_event.is_set():
            return None
        if is_binary_file(abs_fpath):
            return None

        try:
            if os.path.getsize(abs_fpath) > get_max_search_bytes():
                return None
        except Exception:
            return None

        rel_path = _safe_relpath(abs_fpath, cwd)
        filename = os.path.basename(abs_fpath)
        if not _match_glob(rel_path, filename, glob_pattern):
            return None

        try:
            with open(abs_fpath, "r", encoding="utf-8", errors="replace") as f:
                file_lines = f.readlines()
        except Exception:
            return None

        local_matches: List[int] = []
        for idx, l_text in enumerate(file_lines):
            if pattern.search(l_text):
                local_matches.append(idx)

        if not local_matches:
            return None

        local_output: List[str] = []
        rendered_indices: Set[int] = set()
        local_count = 0

        for idx in local_matches:
            local_count += 1
            start_ctx = max(0, idx - before_lines)
            end_ctx = min(len(file_lines), idx + after_lines + 1)
            for ctx_idx in range(start_ctx, end_ctx):
                if ctx_idx not in rendered_indices:
                    rendered_indices.add(ctx_idx)
                    lineno = ctx_idx + 1
                    raw_line = file_lines[ctx_idx].rstrip("\r\n")
                    sep = ":" if ctx_idx == idx else "-"
                    local_output.append(f"{rel_path}{sep}{lineno}{sep}{raw_line}")

        return local_output, {rel_path}, local_count

    if os.path.isfile(target_path):
        files_to_process = [target_path]
    elif os.path.isdir(target_path):
        files_to_process = _walk_filtered_list(target_path, include_hidden, gitignore_matcher, cancel_event)
    else:
        files_to_process = []

    if len(files_to_process) > 20:
        with ThreadPoolExecutor(max_workers=OUTLINE_WORKERS) as executor:
            futures = {executor.submit(_process_file, f): f for f in files_to_process}
            for future in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    break
                if match_count >= max_results:
                    break
                try:
                    result = future.result(timeout=5.0)
                    if result:
                        file_output, file_set, file_count = result
                        with lock:
                            if match_count + file_count > max_results:
                                remaining = max_results - match_count
                                output_lines.extend(file_output[:remaining])
                            else:
                                output_lines.extend(file_output)
                            matched_files.update(file_set)
                            match_count += min(file_count, max_results - match_count)
                            if match_count >= max_results:
                                for f in futures:
                                    f.cancel()
                                break
                except Exception:
                    continue
    else:
        for abs_fpath in files_to_process:
            if cancel_event and cancel_event.is_set():
                break
            if match_count >= max_results:
                break
            result = _process_file(abs_fpath)
            if result:
                file_output, file_set, file_count = result
                if match_count + file_count > max_results:
                    remaining = max_results - match_count
                    output_lines.extend(file_output[:remaining])
                else:
                    output_lines.extend(file_output)
                matched_files.update(file_set)
                match_count += min(file_count, max_results - match_count)

    return output_lines, match_count, len(matched_files)
