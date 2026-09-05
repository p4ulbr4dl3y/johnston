import logging
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set, Tuple

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
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as e:
        logger.debug("ripgrep invocation failed: %s", e)
        return None

    output_lines: List[str] = []
    grouped_results: Dict[str, List[Tuple[str, str, str]]] = {}
    matched_files: Set[str] = set()
    match_count = 0
    stopping = False
    after_remaining = 0
    last_matched_rel: Optional[str] = None

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
                        if os.path.isabs(fpath):
                            rel = _safe_relpath(fpath, cwd)
                        else:
                            rel = fpath.replace("\\", "/")
                            if rel.startswith("./"):
                                rel = rel[2:]
                        if sep == ":":
                            if stopping:
                                break
                            matched_files.add(rel)
                            match_count += 1
                            last_matched_rel = rel
                            grouped_results.setdefault(rel, []).append((lineno, sep, text))
                            if match_count >= max_results:
                                stopping = True
                                after_remaining = after_lines
                                if after_remaining <= 0:
                                    break
                        elif stopping:
                            if after_remaining <= 0 or rel != last_matched_rel:
                                break
                            after_remaining -= 1
                            grouped_results.setdefault(rel, []).append((lineno, sep, text))
                        else:
                            grouped_results.setdefault(rel, []).append((lineno, sep, text))
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

    for rel, entries in grouped_results.items():
        if output_lines:
            output_lines.append("")
        output_lines.append(f"{rel}:")
        prev_empty = False
        for lineno, sep, text in entries:
            is_empty = (sep == "-" and not text.strip())
            if is_empty and prev_empty:
                continue
            prev_empty = is_empty
            output_lines.append(f"  {lineno}{sep} {text}" if text else f"  {lineno}{sep}")

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

    def _process_file(
        abs_fpath: str,
    ) -> Optional[Tuple[List[Tuple[int, str, str]], str, int, List[str], List[int]]]:
        if cancel_event and cancel_event.is_set():
            return None
        if is_binary_file(abs_fpath):
            return None

        # Guard against symlinks pointing to inaccessible/special files
        if os.path.islink(abs_fpath):
            try:
                real_p = os.path.realpath(abs_fpath)
                if not os.path.isfile(real_p):
                    return None
            except OSError:
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

        entries = _build_entries(file_lines, local_matches)
        return entries, rel_path, len(local_matches), file_lines, local_matches

    def _build_entries(file_lines: List[str], matches: List[int]) -> List[Tuple[int, str, str]]:
        entries: List[Tuple[int, str, str]] = []
        ctx_set: Set[int] = set()
        for idx in matches:
            start_ctx = max(0, idx - before_lines)
            end_ctx = min(len(file_lines), idx + after_lines + 1)
            for c in range(start_ctx, end_ctx):
                ctx_set.add(c)

        for ctx_idx in sorted(ctx_set):
            lineno = ctx_idx + 1
            raw_line = file_lines[ctx_idx].rstrip("\r\n")
            sep = ":" if ctx_idx in matches else "-"
            entries.append((lineno, sep, raw_line))
        return entries

    def _append_file_results(rel_p: str, entries: List[Tuple[int, str, str]]) -> None:
        if output_lines:
            output_lines.append("")
        output_lines.append(f"{rel_p}:")
        prev_empty = False
        for lineno, sep, raw_line in entries:
            is_empty = (sep == "-" and not raw_line.strip())
            if is_empty and prev_empty:
                continue
            prev_empty = is_empty
            output_lines.append(f"  {lineno}{sep} {raw_line}" if raw_line else f"  {lineno}{sep}")

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    if os.path.isfile(target_path):
        files_to_process = [target_path]
    elif os.path.isdir(target_path):
        files_to_process = _walk_filtered_list(target_path, include_hidden, gitignore_matcher, cancel_event)
        files_to_process.sort()
    else:
        files_to_process = []

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    if len(files_to_process) > 20:
        batch_size = 50
        with ThreadPoolExecutor(max_workers=OUTLINE_WORKERS) as executor:
            for i in range(0, len(files_to_process), batch_size):
                if cancel_event and cancel_event.is_set():
                    break
                if match_count >= max_results:
                    break
                batch = files_to_process[i : i + batch_size]
                futures = {executor.submit(_process_file, f): f for f in batch}
                batch_results: Dict[str, Tuple[List[Tuple[int, str, str]], int, List[str], List[int]]] = {}
                for future in as_completed(futures):
                    if cancel_event and cancel_event.is_set():
                        for fut in futures:
                            fut.cancel()
                        break
                    try:
                        res = future.result(timeout=5.0)
                        if res:
                            entries, rel_p, n_matches, flines, lmatches = res
                            batch_results[rel_p] = (entries, n_matches, flines, lmatches)
                    except Exception:
                        continue

                # Deterministic accumulation in sorted file order for this batch
                for rel_p in sorted(batch_results.keys()):
                    if match_count >= max_results:
                        break
                    entries, n_matches, flines, lmatches = batch_results[rel_p]
                    avail = max_results - match_count
                    if n_matches > avail:
                        entries = _build_entries(flines, lmatches[:avail])
                        n_matches = avail
                    _append_file_results(rel_p, entries)
                    matched_files.add(rel_p)
                    match_count += n_matches
    else:
        for abs_fpath in files_to_process:
            if cancel_event and cancel_event.is_set():
                break
            if match_count >= max_results:
                break
            res = _process_file(abs_fpath)
            if res:
                entries, rel_p, n_matches, flines, lmatches = res
                avail = max_results - match_count
                if n_matches > avail:
                    entries = _build_entries(flines, lmatches[:avail])
                    n_matches = avail
                _append_file_results(rel_p, entries)
                matched_files.add(rel_p)
                match_count += n_matches

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    return output_lines, match_count, len(matched_files)
