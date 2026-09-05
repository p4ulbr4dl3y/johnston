import fnmatch
import os
import re
import threading
from bisect import bisect_right
from typing import Generator, List, Optional, Set, Tuple

from core.domain.defaults.git_excludes import DEFAULT_BINARY_EXTENSIONS, DEFAULT_IGNORE_DIRS
from tools.utils import get_max_tool_payload_bytes

DEFAULT_EXCLUDE_DIRS: Set[str] = set(DEFAULT_IGNORE_DIRS) | {
    ".hg",
    ".svn",
    ".cache",
    ".idea",
    ".vscode",
    "coverage",
    "htmlcov",
}

BINARY_EXTENSIONS: Set[str] = set(DEFAULT_BINARY_EXTENSIONS) | {
    ".pyc",
    ".pyo",
    ".pyd",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
}

CODE_EXTENSIONS: Set[str] = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".hxx",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".kts",
    ".scala",
    ".sc",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".psm1",
    ".psd1",
    ".sql",
    ".html",
    ".htm",
    ".css",
    ".scss",
    ".sass",
    ".less",
    ".vue",
    ".svelte",
    ".json",
    ".jsonc",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".md",
    ".mdx",
    ".rst",
    ".tex",
    ".lua",
    ".r",
    ".R",
    ".jl",
    ".ex",
    ".exs",
    ".erl",
    ".hrl",
    ".clj",
    ".cljs",
    ".hs",
    ".ml",
    ".mli",
    ".d",
    ".nim",
    ".zig",
    ".v",
    ".dart",
    ".groovy",
    ".gradle",
    ".tf",
    ".hcl",
    ".proto",
    ".sol",
    ".vhd",
    ".vhdl",
    ".el",
    ".lisp",
    ".cl",
    ".rkt",
    ".cmake",
    ".make",
    ".mk",
    ".dockerfile",
    ".docker",
    ".lock",
}

MAX_SEARCH_FILE_BYTES = 10 * 1024 * 1024  # 10 MB fallback constant
MAX_OUTLINE_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
OUTLINE_WORKERS = 4


def get_max_search_bytes() -> int:
    try:
        return get_max_tool_payload_bytes()
    except Exception:
        return MAX_SEARCH_FILE_BYTES


def _safe_relpath(path: str, cwd: str) -> str:
    """Compute relative path safely; on Windows cross-drive ValueError returns path as-is."""
    try:
        rel = os.path.relpath(path, cwd).replace("\\", "/")
        if rel.startswith("./"):
            rel = rel[2:]
        return rel
    except (ValueError, Exception):
        return path.replace("\\", "/")


def is_binary_file(filepath: str) -> bool:
    """Check if file is binary by extension or null-byte sampling."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext in BINARY_EXTENSIONS:
        return True
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            return b"\x00" in chunk
    except Exception:
        return True


def compute_line_offsets(text: str) -> List[int]:
    """Precompute byte/char offsets for all newlines in text for O(log N) line lookups."""
    offsets = [0]
    for idx, ch in enumerate(text):
        if ch == "\n":
            offsets.append(idx + 1)
    return offsets


def get_line_number(line_offsets: List[int], char_index: int) -> int:
    """Find 1-indexed line number using binary search over line offsets."""
    return bisect_right(line_offsets, char_index)


def _glob_to_regex(pattern: str) -> "re.Pattern":
    """Convert a glob pattern (with ** support) to a compiled regex."""
    result = ""
    i = 0
    n = len(pattern)

    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    result += "(?:.*/)?"
                    i += 3
                    continue
                else:
                    result += ".*"
                    i += 2
                    continue
            else:
                result += "[^/]*"
        elif c == "?":
            result += "[^/]"
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] == "!":
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j < n:
                bracket_content = pattern[i + 1 : j]
                bracket_content = (
                    bracket_content.replace("!", "^", 1)
                    if bracket_content.startswith("!")
                    else bracket_content
                )
                result += f"[{bracket_content}]"
                i = j
            else:
                result += re.escape(c)
        elif c in r"\.^$+{}|()":
            result += "\\" + c
        else:
            result += c
        i += 1

    return re.compile(f"^(?:{result})$")


def _match_glob(rel_path: str, filename: str, glob_pattern: Optional[str]) -> bool:
    """Evaluate whether a path matches the optional glob filter (supports ! negation and **)."""
    if not glob_pattern:
        return True

    norm_rel = rel_path.replace("\\", "/")
    if norm_rel.startswith("./"):
        norm_rel = norm_rel[2:]
    norm_glob = glob_pattern.replace("\\", "/")
    patterns = [p.strip() for p in norm_glob.split(",") if p.strip()]
    positive_pats = [p for p in patterns if not p.startswith("!")]
    negative_pats = [p[1:] for p in patterns if p.startswith("!")]

    for neg in negative_pats:
        try:
            neg_re = _glob_to_regex(neg)
            if neg_re.search(filename) or neg_re.search(norm_rel):
                return False
        except re.error:
            if fnmatch.fnmatch(filename, neg) or fnmatch.fnmatch(norm_rel, neg):
                return False

    if not positive_pats:
        return True

    for pos in positive_pats:
        try:
            pos_re = _glob_to_regex(pos)
            if pos_re.search(filename) or pos_re.search(norm_rel):
                return True
        except re.error:
            if fnmatch.fnmatch(filename, pos) or fnmatch.fnmatch(norm_rel, pos):
                return True

    return False


class _GitignoreMatcher:
    """Lightweight .gitignore matcher supporting *, **, ?, and ! negation."""

    def __init__(self, patterns: List[Tuple[str, str]], root: str):
        self._root = root
        self._compiled: List[Tuple[bool, str, "re.Pattern"]] = []

        for prefix, raw_pat in patterns:
            negated = raw_pat.startswith("!")
            pat = raw_pat.lstrip("!")

            if pat.startswith("/"):
                pat = pat[1:]
                anchored = True
            else:
                anchored = "/" in pat.rstrip("/")

            regex_str = self._gitignore_to_regex(pat, anchored)
            try:
                compiled_re = re.compile(regex_str)
                self._compiled.append((negated, prefix, compiled_re))
            except re.error:
                continue

    @classmethod
    def load_from_root(cls, root: str) -> Optional["_GitignoreMatcher"]:
        return _load_gitignore_spec(root)

    @staticmethod
    def _gitignore_to_regex(pattern: str, anchored: bool) -> str:
        result = ""
        i = 0
        n = len(pattern)

        while i < n:
            c = pattern[i]
            if c == "*":
                if i + 1 < n and pattern[i + 1] == "*":
                    if i + 2 < n and pattern[i + 2] == "/":
                        result += "(?:.*/)?"
                        i += 3
                        continue
                    else:
                        result += ".*"
                        i += 2
                        continue
                else:
                    result += "[^/]*"
            elif c == "?":
                result += "[^/]"
            elif c == "[":
                j = i + 1
                if j < n and pattern[j] == "!":
                    j += 1
                if j < n and pattern[j] == "]":
                    j += 1
                while j < n and pattern[j] != "]":
                    j += 1
                if j < n:
                    bracket_content = pattern[i + 1 : j]
                    bracket_content = (
                        bracket_content.replace("!", "^", 1)
                        if bracket_content.startswith("!")
                        else bracket_content
                    )
                    result += f"[{bracket_content}]"
                    i = j
                else:
                    result += re.escape(c)
            elif c in r"\.^$+{}|()":
                result += "\\" + c
            else:
                result += c
            i += 1

        dir_only = False
        if pattern.endswith("/"):
            dir_only = True
            result = result.rstrip("/")

        if anchored:
            prefix_re = "^"
        else:
            prefix_re = "(?:^|.*/)"

        if dir_only:
            result = prefix_re + result + "/(?:.*)?$"
        else:
            result = prefix_re + result + "(?:/.*)?$"
        return result

    def is_ignored(self, rel_path: str) -> bool:
        norm = rel_path.replace("\\", "/")
        if norm.startswith("./"):
            norm = norm[2:]
        ignored = False

        for negated, prefix, compiled_re in self._compiled:
            if prefix:
                if norm.startswith(prefix):
                    test_path = norm[len(prefix):]
                    if compiled_re.search(test_path):
                        ignored = not negated
            else:
                if compiled_re.search(norm):
                    ignored = not negated

        return ignored


def _load_gitignore_spec(root: str) -> Optional[_GitignoreMatcher]:
    patterns: List[Tuple[str, str]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in DEFAULT_EXCLUDE_DIRS and not d.startswith(".git")
        ]
        if ".gitignore" in filenames:
            gitignore_path = os.path.join(dirpath, ".gitignore")
            try:
                rel_prefix = os.path.relpath(dirpath, root).replace("\\", "/")
                if rel_prefix == ".":
                    rel_prefix = ""
                else:
                    rel_prefix += "/"

                with open(gitignore_path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.rstrip("\r\n")
                        stripped = line.strip()
                        if not stripped or stripped.startswith("#"):
                            continue
                        patterns.append((rel_prefix, stripped))
            except Exception:
                continue

    if not patterns:
        return None

    return _GitignoreMatcher(patterns, root)


def _build_gitignore_matcher(cwd: str) -> Optional[_GitignoreMatcher]:
    return _load_gitignore_spec(cwd)


def _walk_filtered(
    target_path: str,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Generator[str, None, None]:
    import stat

    base = (
        gitignore_matcher._root
        if gitignore_matcher
        else (target_path if os.path.isdir(target_path) else os.path.dirname(target_path))
    )
    for root, dirs, filenames in os.walk(target_path, topdown=True):
        if cancel_event and cancel_event.is_set():
            return

        filtered_dirs = []
        for d in dirs:
            if d in DEFAULT_EXCLUDE_DIRS or d.endswith(".egg-info") or d.startswith(".git"):
                continue
            if not include_hidden and d.startswith(".") and d != ".":
                continue
            if gitignore_matcher:
                rel = _safe_relpath(os.path.join(root, d), base)
                if gitignore_matcher.is_ignored(rel + "/"):
                    continue
            filtered_dirs.append(d)
        dirs[:] = sorted(filtered_dirs)

        for fname in sorted(filenames):
            if cancel_event and cancel_event.is_set():
                return
            if not include_hidden and fname.startswith("."):
                continue
            abs_p = os.path.join(root, fname)
            # Guard against special non-regular files (FIFOs, sockets, character devices)
            try:
                st = os.stat(abs_p, follow_symlinks=False)
                if not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
                    continue
            except OSError:
                continue
            if gitignore_matcher:
                rel = _safe_relpath(abs_p, base)
                if gitignore_matcher.is_ignored(rel):
                    continue
            yield abs_p


def _walk_filtered_list(
    target_path: str,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    cancel_event: Optional[threading.Event] = None,
) -> List[str]:
    return list(_walk_filtered(target_path, include_hidden, gitignore_matcher, cancel_event))
