import ast
import fnmatch
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, Generator, List, Optional, Set, Tuple

from core.domain.defaults.errors import ToolResult
from core.domain.defaults.git_excludes import DEFAULT_BINARY_EXTENSIONS, DEFAULT_IGNORE_DIRS
from tools.base import (
    ERROR_KIND_NOT_FOUND,
    ERROR_KIND_PARAMS,
    ERROR_KIND_PERMISSION,
    BaseTool,
    done,
    fail,
    resolve_path,
    truncate_output,
    try_int,
)
from tools.cancel import run_cancellable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LRU Cache with mtime invalidation
# ---------------------------------------------------------------------------

class _OutlineCache:
    """Thread-safe LRU cache for outline results with mtime-based invalidation."""

    def __init__(self, max_size: int = 100):
        self._cache: "OrderedDict[str, Tuple[float, List[str]]]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key: str, file_mtime: float) -> Optional[List[str]]:
        """Get cached outline if mtime matches."""
        with self._lock:
            if key in self._cache:
                cached_mtime, result = self._cache[key]
                if cached_mtime == file_mtime:
                    # Move to end (most recently used)
                    self._cache.move_to_end(key)
                    return result
                else:
                    # Mtime changed, invalidate
                    del self._cache[key]
            return None

    def put(self, key: str, file_mtime: float, result: List[str]) -> None:
        """Store outline in cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            self._cache[key] = (file_mtime, result)
            # Evict oldest if over capacity
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()


# Global outline cache (100 entries max)
_OUTLINE_CACHE = _OutlineCache(max_size=100)

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

MAX_SEARCH_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_OUTLINE_FILE_BYTES = 5 * 1024 * 1024  # 5 MB (outline is CPU-heavy)
OUTLINE_WORKERS = 4  # Thread pool size for parallel outline


def _safe_relpath(path: str, cwd: str) -> str:
    """Compute relative path safely; on Windows cross-drive ValueError returns path as-is."""
    try:
        return os.path.relpath(path, cwd)
    except (ValueError, Exception):
        return path


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


# ---------------------------------------------------------------------------
# .gitignore awareness
# ---------------------------------------------------------------------------

def _load_gitignore_spec(root: str) -> Optional[Any]:
    """Load and compile all .gitignore files in the tree into a pathspec matcher.

    Returns None if no .gitignore files found or parsing fails.
    Uses a lightweight custom parser instead of requiring the `pathspec` package.
    """
    patterns: List[Tuple[str, str]] = []  # (directory_prefix, pattern_line)

    for dirpath, dirnames, filenames in os.walk(root):
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


class _GitignoreMatcher:
    """Lightweight .gitignore matcher supporting *, **, ?, and ! negation."""

    def __init__(self, patterns: List[Tuple[str, str]], root: str):
        self._root = root
        self._compiled: List[Tuple[bool, str, "re.Pattern"]] = []  # (negated, prefix, regex)

        for prefix, raw_pat in patterns:
            negated = raw_pat.startswith("!")
            pat = raw_pat.lstrip("!")

            # Leading slash means anchored to the gitignore directory
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
        """Load and compile all .gitignore files in the tree."""
        return _load_gitignore_spec(root)

    @staticmethod
    def _gitignore_to_regex(pattern: str, anchored: bool) -> str:
        """Convert a gitignore pattern to a regex string."""
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
                    bracket_content = bracket_content.replace("!", "^", 1) if bracket_content.startswith("!") else bracket_content
                    result += f"[{bracket_content}]"
                    i = j
                else:
                    result += re.escape(c)
            elif c in r"\.^$+{}|()":
                result += "\\" + c
            else:
                result += c
            i += 1

        # Trailing slash means directory only — we match dirs and files under them
        if result.endswith("/"):
            result = result.rstrip("/") + "(?:/.*)?"
        elif anchored:
            result = result + "(?:/.*)?"
        else:
            # Unanchored: can match at any level
            result = "(?:^|.*/)" + result + "(?:/.*)?"

        if anchored:
            result = "^" + result
        result += "$"
        return result

    def is_ignored(self, rel_path: str) -> bool:
        """Check if a relative path is ignored by any .gitignore rule."""
        norm = rel_path.replace("\\", "/")
        ignored = False

        for negated, prefix, compiled_re in self._compiled:
            # Check against path with and without prefix
            test_paths = [norm]
            if prefix and norm.startswith(prefix):
                test_paths.append(norm[len(prefix):])

            for test_path in test_paths:
                if compiled_re.search(test_path):
                    ignored = not negated
                    break

        return ignored


def _build_gitignore_matcher(cwd: str) -> Optional[_GitignoreMatcher]:
    """Build gitignore matcher for the project, cached per-thread via thread-local."""
    return _load_gitignore_spec(cwd)


# ---------------------------------------------------------------------------
# git check-ignore integration for 100% compatibility
# ---------------------------------------------------------------------------

def _git_check_ignore_batch(
    paths: List[str],
    cwd: str,
    cancel_event: Optional[threading.Event] = None,
) -> Set[str]:
    """Use git check-ignore to filter paths. Returns set of ignored paths.

    Falls back gracefully if git is not available or not in a git repo.
    """
    if not paths:
        return set()

    git_bin = shutil.which("git")
    if not git_bin:
        return set()

    ignored_paths: Set[str] = set()

    # Process in batches to avoid command line length limits
    batch_size = 1000
    for i in range(0, len(paths), batch_size):
        if cancel_event and cancel_event.is_set():
            break

        batch = paths[i:i + batch_size]
        try:
            result = subprocess.run(
                [git_bin, "check-ignore", "--stdin", "--no-index"],
                cwd=cwd,
                input="\n".join(batch),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10.0,
            )
            # git check-ignore returns 0 if any path is ignored, 1 if none
            # Output contains the ignored paths, one per line
            for line in result.stdout.strip().split("\n"):
                if line:
                    ignored_paths.add(line)
        except Exception as e:
            logger.debug("git check-ignore failed: %s", e)
            # If git check-ignore fails, assume no paths are ignored
            break

    return ignored_paths


def _is_git_repo(path: str) -> bool:
    """Check if path is inside a git repository."""
    git_dir = os.path.join(path, ".git")
    if os.path.isdir(git_dir):
        return True
    # Check if we're in a git repo by walking up
    current = os.path.abspath(path)
    while current != os.path.dirname(current):
        if os.path.isdir(os.path.join(current, ".git")):
            return True
        current = os.path.dirname(current)
    return False


# ---------------------------------------------------------------------------
# Python AST outline
# ---------------------------------------------------------------------------

def _format_ast_args(args: ast.arguments) -> str:
    """Format AST arguments into a concise signature representation."""
    parts = []
    if getattr(args, "posonlyargs", None):
        for a in args.posonlyargs:
            parts.append(a.arg)
        parts.append("/")
    for a in args.args:
        parts.append(a.arg)
    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    elif args.kwonlyargs:
        parts.append("*")
    for a in args.kwonlyargs:
        parts.append(a.arg)
    if args.kwarg:
        parts.append(f"**{args.kwarg.arg}")
    return ", ".join(parts)


def _outline_python_content(code: str, file_rel_path: str, query: Optional[str] = None) -> List[str]:
    """Parse Python AST and extract classes, methods, and functions matching query."""
    try:
        tree = ast.parse(code, filename=file_rel_path)
    except Exception:
        return []

    lines: List[str] = []
    q = query.lower().strip() if query and query.strip() and query.strip() != "*" else None

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            methods: List[Tuple[str, int, str]] = []
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)

            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async def " if isinstance(item, ast.AsyncFunctionDef) else "def "
                    args_s = _format_ast_args(item.args)
                    methods.append((f"{prefix}{item.name}({args_s})", item.lineno, item.name))

            class_matches = (q is None) or (q in class_name.lower())
            matching_methods = [m for m in methods if (q is None) or (q in m[2].lower())]

            if class_matches or matching_methods:
                bases_str = f"({', '.join(bases)})" if bases else ""
                lines.append(f"  class {class_name}{bases_str}: (line {node.lineno})")
                shown_methods = methods if class_matches else matching_methods
                for m_sig, m_line, _ in shown_methods:
                    lines.append(f"    {m_sig} (line {m_line})")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name
            if (q is None) or (q in fn_name.lower()):
                prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
                args_s = _format_ast_args(node.args)
                lines.append(f"  {prefix}{fn_name}({args_s}) (line {node.lineno})")

    return lines


# ---------------------------------------------------------------------------
# Generic (regex-based) outline for TS/JS/Go/Rust/Kotlin/Swift/Scala etc.
# ---------------------------------------------------------------------------

RE_GENERIC_DEF = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?"
    r"(?:"
    # JS/TS/Lua/PHP: function declarations (also supports Lua's obj.method syntax)
    r"(?P<async>async\s+)?function\s+(?P<fn>[A-Za-z0-9_$.:]+)\s*\((?P<fn_args>[^)]*)\)"
    r"|"
    # JS/TS: arrow functions assigned to const/let/var
    r"(?:const|let|var)\s+(?P<arrowfn>[A-Za-z0-9_$]+)\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::\s*[^=]+)?\s*=>"
    r"|"
    # JS/TS: class declarations
    r"class\s+(?P<cls>[A-Za-z0-9_$]+)"
    r"|"
    # JS/TS: interface
    r"interface\s+(?P<iface>[A-Za-z0-9_$]+)"
    r"|"
    # JS/TS: type alias
    r"type\s+(?P<typ>[A-Za-z0-9_$]+)\s*="
    r"|"
    # JS/TS: enum
    r"enum\s+(?P<enum>[A-Za-z0-9_$]+)"
    r"|"
    # Go: func
    r"func\s+(?:\([^)]+\)\s+)?(?P<gofn>[A-Za-z0-9_]+)\s*\((?P<gofn_args>[^)]*)\)"
    r"|"
    # Go: type struct/interface
    r"type\s+(?P<gotype>[A-Za-z0-9_]+)\s+(?:struct|interface)"
    r"|"
    # Rust: pub/private fn, struct, enum, trait, impl, mod
    r"(?:pub(?:\([^)]*\))?\s+)?fn\s+(?P<rsfn>[A-Za-z0-9_]+)"
    r"|"
    r"(?:pub(?:\([^)]*\))?\s+)?struct\s+(?P<rsstruct>[A-Za-z0-9_]+)"
    r"|"
    r"(?:pub(?:\([^)]*\))?\s+)?enum\s+(?P<rsenum>[A-Za-z0-9_]+)"
    r"|"
    r"(?:pub(?:\([^)]*\))?\s+)?trait\s+(?P<rstrait>[A-Za-z0-9_]+)"
    r"|"
    r"impl(?:<[^>]*>)?\s+(?P<rsimpl>[A-Za-z0-9_]+)"
    r"|"
    r"mod\s+(?P<rsmod>[A-Za-z0-9_]+)"
    r"|"
    # Kotlin: fun, class, object, interface, val, var (top-level)
    r"(?:(?:public|private|protected|internal|override|suspend|inline)\s+)*fun\s+(?:<[^>]+>\s+)?(?P<ktfun>[A-Za-z0-9_]+)"
    r"|"
    r"(?:(?:public|private|protected|internal|data|sealed|abstract|open|inner)\s+)*class\s+(?P<ktclass>[A-Za-z0-9_]+)"
    r"|"
    r"(?:(?:public|private|protected|internal)\s+)?object\s+(?P<ktobject>[A-Za-z0-9_]+)"
    r"|"
    r"(?:(?:public|private|protected|internal)\s+)?interface\s+(?P<ktiface>[A-Za-z0-9_]+)"
    r"|"
    # Swift: func, class, struct, enum, protocol, extension
    r"(?:(?:public|private|internal|open|fileprivate|static|class|final|override|mutating)\s+)*func\s+(?P<swfn>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|internal|open|fileprivate|final)\s+)?class\s+(?P<swclass>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|internal)\s+)?struct\s+(?P<swstruct>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|internal)\s+)?enum\s+(?P<swenum>[A-Za-z0-9_$]+)"
    r"|"
    r"protocol\s+(?P<swproto>[A-Za-z0-9_$]+)"
    r"|"
    r"extension\s+(?P<swext>[A-Za-z0-9_$]+)"
    r"|"
    # Scala: def, class, object, trait, val, var
    r"(?:(?:public|private|protected|override|abstract|final|lazy|implicit)\s+)*def\s+(?P<scfn>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected|abstract|final|sealed|case)\s+)?class\s+(?P<scclass>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected)\s+)?object\s+(?P<scobject>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected)\s+)?trait\s+(?P<sctrait>[A-Za-z0-9_$]+)"
    r"|"
    # Java: class, interface, enum, method
    r"(?:(?:public|private|protected|static|final|abstract|synchronized|native)\s+)*(?:class|interface|enum)\s+(?P<jvcls>[A-Za-z0-9_$]+)"
    r"|"
    # C#: class, interface, struct, enum, record, namespace
    r"(?:(?:public|private|protected|internal|static|abstract|sealed|virtual|override|async|partial|readonly)\s+)*(?:class|interface|struct|enum|record)\s+(?P<cscls>[A-Za-z0-9_]+)"
    r"|"
    # Ruby: class, module, def
    r"class\s+(?P<rbcls>[A-Z][A-Za-z0-9_:]*)"
    r"|"
    r"module\s+(?P<rbmod>[A-Z][A-Za-z0-9_:]*)"
    r"|"
    r"def\s+(?:self\.)?(?P<rbdef>[a-z_][A-Za-z0-9_]*[?!]?)"
    r"|"
    # PHP: class, interface, trait
    r"(?:abstract\s+)?class\s+(?P<phpcls>[A-Za-z0-9_]+)"
    r"|"
    r"interface\s+(?P<phpiface>[A-Za-z0-9_]+)"
    r"|"
    r"trait\s+(?P<phptrait>[A-Za-z0-9_]+)"
    r"|"
    # Dart: class, mixin, extension, abstract
    r"(?:abstract\s+)?class\s+(?P<dartcls>[A-Za-z0-9_]+)"
    r"|"
    r"mixin\s+(?P<dartmix>[A-Za-z0-9_]+)"
    r"|"
    # Elixir: defmodule, def, defmacro, defp
    r"defmodule\s+(?P<exmod>[A-Za-z0-9_.]+)"
    r"|"
    r"def(?:macro|p)?\s+(?P<exfn>[a-z_][a-z0-9_]*[?!]?)"
    r"|"
    # Haskell: data, type, class, newtype, module
    r"(?:data|type|newtype)\s+(?P<hsdata>[A-Z][A-Za-z0-9_]*)"
    r"|"
    r"class\s+(?P<hsclass>[A-Z][A-Za-z0-9_]*)"
    r"|"
    # Protocol Buffers: message, service, enum
    r"message\s+(?P<pbmsg>[A-Za-z0-9_]+)"
    r"|"
    r"service\s+(?P<pbsvc>[A-Za-z0-9_]+)"
    r")",
    re.MULTILINE,
)


def _outline_generic_content(code: str, query: Optional[str] = None) -> List[str]:
    """Regex-based outline extractor for TS/JS/Go/Rust/Kotlin/Swift/Scala and other languages."""
    lines: List[str] = []
    q = query.lower().strip() if query and query.strip() and query.strip() != "*" else None

    for m in RE_GENERIC_DEF.finditer(code):
        matched_text = m.group(0).strip()
        # Resolve the matched symbol name from all possible named groups
        name = ""
        for group_name in (
            "fn", "arrowfn", "cls", "iface", "typ", "enum",
            "gofn", "gotype",
            "rsfn", "rsstruct", "rsenum", "rstrait", "rsimpl", "rsmod",
            "ktfun", "ktclass", "ktobject", "ktiface",
            "swfn", "swclass", "swstruct", "swenum", "swproto", "swext",
            "scfn", "scclass", "scobject", "sctrait",
            "jvcls", "cscls",
            "rbcls", "rbmod", "rbdef",
            "phpcls", "phpiface", "phptrait", "phpfn",
            "dartcls", "dartmix",
            "exmod", "exfn",
            "hsdata", "hsclass",
            "pbmsg", "pbsvc",
        ):
            group_name_clean = group_name.strip()
            try:
                val = m.group(group_name_clean)
                if val:
                    name = val
                    break
            except (IndexError, re.error):
                continue

        if not name:
            continue
        if q is not None and q not in name.lower():
            continue

        lineno = code[: m.start()].count("\n") + 1
        # Clean up matched text for display
        display = matched_text.split("\n")[0].strip()
        if len(display) > 120:
            display = display[:117] + "..."
        lines.append(f"  {display} (line {lineno})")

    return lines


# ---------------------------------------------------------------------------
# Glob matching with ** support
# ---------------------------------------------------------------------------

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
                    # **/ matches zero or more directories
                    result += "(?:.*/)?"
                    i += 3
                    continue
                else:
                    # ** at end matches everything
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
                bracket_content = bracket_content.replace("!", "^", 1) if bracket_content.startswith("!") else bracket_content
                result += f"[{bracket_content}]"
                i = j
            else:
                result += re.escape(c)
        elif c in r"\.^$+{}|()":
            result += "\\" + c
        else:
            result += c
        i += 1

    return re.compile(result)


def _match_glob(rel_path: str, filename: str, glob_pattern: Optional[str]) -> bool:
    """Evaluate whether a path matches the optional glob filter (supports ! negation and **)."""
    if not glob_pattern:
        return True

    norm_rel = rel_path.replace("\\", "/")
    patterns = [p.strip() for p in glob_pattern.split(",") if p.strip()]
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


# ---------------------------------------------------------------------------
# Directory walker with gitignore support (generator-based)
# ---------------------------------------------------------------------------

def _walk_filtered(
    target_path: str,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Generator[str, None, None]:
    """Walk a directory tree yielding absolute file paths, respecting exclusions and gitignore.

    This is a generator to reduce memory footprint for large repositories.
    """
    for root, dirs, filenames in os.walk(target_path, topdown=True):
        if cancel_event and cancel_event.is_set():
            return

        # Filter excluded directories
        filtered_dirs = []
        for d in dirs:
            if d in DEFAULT_EXCLUDE_DIRS or d.endswith(".egg-info") or d.startswith(".git"):
                continue
            if not include_hidden and d.startswith(".") and d != ".":
                continue
            # Check gitignore
            if gitignore_matcher:
                rel = _safe_relpath(os.path.join(root, d), os.path.dirname(target_path)) if os.path.isabs(target_path) else _safe_relpath(os.path.join(root, d), target_path)
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
            # Check gitignore for files
            if gitignore_matcher:
                base = target_path if os.path.isdir(target_path) else os.path.dirname(target_path)
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
    """Walk a directory tree returning a list of absolute file paths.

    Convenience wrapper around _walk_filtered for cases where we need random access or length.
    """
    return list(_walk_filtered(target_path, include_hidden, gitignore_matcher, cancel_event))


# ---------------------------------------------------------------------------
# Content search: ripgrep (fast path)
# ---------------------------------------------------------------------------

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

    # Context lines: use before/after if specified, otherwise use symmetric
    if before_lines > 0:
        cmd.extend(["--before", str(before_lines)])
    if after_lines > 0:
        cmd.extend(["--after", str(after_lines)])
    if before_lines == 0 and after_lines == 0:
        pass  # no context

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
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except Exception as e:
        logger.debug("ripgrep invocation failed: %s", e)
        return None

    output_lines: List[str] = []
    matched_files: Set[str] = set()
    match_count = 0

    try:
        if proc.stdout is not None:
            for raw_line in proc.stdout:
                if cancel_event and cancel_event.is_set():
                    break
                line = raw_line.rstrip("\r\n")
                if not line or line == "--":
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
                            match_count += 1
                        output_lines.append(f"{rel}{sep}{lineno}{sep}{text}")
                    else:
                        output_lines.append(line)
                else:
                    output_lines.append(line)

                if match_count >= max_results:
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
        return [], 0, 0

    if proc.returncode not in (0, 1, -15, -9) and match_count == 0:
        logger.debug("ripgrep exited with code %s", proc.returncode)
        return None

    return output_lines, match_count, len(matched_files)


# ---------------------------------------------------------------------------
# Content search: pure Python fallback
# ---------------------------------------------------------------------------

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
            if os.path.getsize(abs_fpath) > MAX_SEARCH_FILE_BYTES:
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
                    local_output.append(f"{rel_path}{sep}{lineno}{sep} {raw_line}")

        file_matches: Set[str] = {rel_path}
        return local_output, file_matches, local_count

    # Collect files to process
    if os.path.isfile(target_path):
        files_to_process = [target_path]
    elif os.path.isdir(target_path):
        files_to_process = _walk_filtered_list(target_path, include_hidden, gitignore_matcher, cancel_event)
    else:
        files_to_process = []

    # Process with thread pool for large directories
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
                                # Trim to max
                                remaining = max_results - match_count
                                output_lines.extend(file_output[:remaining])
                            else:
                                output_lines.extend(file_output)
                            matched_files.update(file_set)
                            match_count += min(file_count, max_results - match_count)
                            if match_count >= max_results:
                                # Cancel remaining futures
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


# ---------------------------------------------------------------------------
# Filename search: ripgrep --files (fast path)
# ---------------------------------------------------------------------------

def _search_filename_ripgrep(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    cancel_event: Optional[threading.Event] = None,
) -> Optional[Tuple[List[str], int]]:
    """Use rg --files for fast filename listing, then filter in Python."""
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

    cmd.append(target_path)

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10.0,
        )
    except Exception:
        return None

    if result.returncode not in (0, 1):
        return None

    matched_paths: List[str] = []
    q = query.strip() if query else ""
    q_is_wild = not q or q == "*"

    for fpath in result.stdout.split("\x00"):
        if cancel_event and cancel_event.is_set():
            break
        if not fpath:
            continue
        if len(matched_paths) >= max_results:
            break

        rel = _safe_relpath(fpath, cwd) if os.path.isabs(fpath) else fpath
        fname = os.path.basename(rel)

        # Apply query filter
        if not q_is_wild:
            if not (fnmatch.fnmatch(fname, q) or fnmatch.fnmatch(rel, q)):
                if q.lower() not in fname.lower() and q.lower() not in rel.lower():
                    continue

        # Apply glob filter (only if not already applied by rg -g)
        if glob_pattern and not _match_glob(rel, fname, glob_pattern):
            continue

        matched_paths.append(rel)

    return matched_paths, len(matched_paths)


# ---------------------------------------------------------------------------
# Filename search: pure Python fallback
# ---------------------------------------------------------------------------

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
    """Find files/directories matching query/glob pattern."""
    matched_paths: List[str] = []
    q = query.strip() if query else ""
    q_is_wild = not q or q == "*"

    def _matches_query(rel: str, fname: str) -> bool:
        if q_is_wild:
            return True
        if fnmatch.fnmatch(fname, q) or fnmatch.fnmatch(rel, q):
            return True
        return q.lower() in fname.lower() or q.lower() in rel.lower()

    if os.path.isfile(target_path):
        rel = _safe_relpath(target_path, cwd)
        fname = os.path.basename(target_path)
        if _matches_query(rel, fname) and _match_glob(rel, fname, glob_pattern):
            matched_paths.append(rel)
        return matched_paths, len(matched_paths)

    # Use generator for streaming file enumeration
    for abs_p in _walk_filtered(target_path, include_hidden, gitignore_matcher, cancel_event):
        if cancel_event and cancel_event.is_set():
            break
        if len(matched_paths) >= max_results:
            break
        rel = _safe_relpath(abs_p, cwd)
        fname = os.path.basename(rel)
        if _matches_query(rel, fname) and _match_glob(rel, fname, glob_pattern):
            matched_paths.append(rel)

    return matched_paths, len(matched_paths)


# ---------------------------------------------------------------------------
# Filename search: combined
# ---------------------------------------------------------------------------

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
    """Find files matching query. Tries rg --files first, falls back to Python."""
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


# ---------------------------------------------------------------------------
# Outline search: parallel with AST + regex
# ---------------------------------------------------------------------------

def _outline_file(
    abs_fpath: str,
    cwd: str,
    query: Optional[str],
    glob_pattern: Optional[str],
    use_cache: bool = True,
) -> Optional[Tuple[str, List[str], int]]:
    """Process a single file for outline extraction with optional caching.

    Returns (rel_path, symbols, count) or None.
    Uses LRU cache with mtime invalidation for repeated calls.
    """
    try:
        if os.path.getsize(abs_fpath) > MAX_OUTLINE_FILE_BYTES:
            return None
    except Exception:
        return None

    rel = _safe_relpath(abs_fpath, cwd)
    fname = os.path.basename(abs_fpath)
    ext = os.path.splitext(fname)[1].lower()

    if not _match_glob(rel, fname, glob_pattern):
        return None
    if not glob_pattern and ext not in CODE_EXTENSIONS:
        return None

    # Check cache first
    if use_cache:
        try:
            file_mtime = os.path.getmtime(abs_fpath)
            cache_key = f"{abs_fpath}:{query}:{glob_pattern}"
            cached = _OUTLINE_CACHE.get(cache_key, file_mtime)
            if cached is not None:
                return rel, cached, len(cached)
        except Exception:
            pass

    try:
        with open(abs_fpath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None

    if ext == ".py":
        file_symbols = _outline_python_content(content, rel, query)
    else:
        file_symbols = _outline_generic_content(content, query)

    if file_symbols:
        # Store in cache
        if use_cache:
            try:
                file_mtime = os.path.getmtime(abs_fpath)
                cache_key = f"{abs_fpath}:{query}:{glob_pattern}"
                _OUTLINE_CACHE.put(cache_key, file_mtime, file_symbols)
            except Exception:
                pass
        return rel, file_symbols, len(file_symbols)
    return None


def _search_outline(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    include_hidden: bool = False,
    gitignore_matcher: Optional[_GitignoreMatcher] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[str], int, int]:
    """Extract AST/regex outline symbols from files matching path and optional query.

    Uses parallel processing for directories with many files.
    """
    output_lines: List[str] = []
    total_symbols = 0
    matched_files: Set[str] = set()

    # Collect files to process
    if os.path.isfile(target_path):
        files_to_process = [target_path]
    elif os.path.isdir(target_path):
        files_to_process = _walk_filtered_list(target_path, include_hidden, gitignore_matcher, cancel_event)
    else:
        return [], 0, 0

    if len(files_to_process) > 20:
        # Parallel processing for large directories
        results: List[Tuple[str, List[str], int]] = []
        total_files = len(files_to_process)
        processed_files = 0

        if progress_callback:
            progress_callback({"stage": "outline_parallel", "total_files": total_files})

        with ThreadPoolExecutor(max_workers=OUTLINE_WORKERS) as executor:
            futures = {}
            for f in files_to_process:
                if cancel_event and cancel_event.is_set():
                    break
                futures[executor.submit(_outline_file, f, cwd, query, glob_pattern)] = f

            for future in as_completed(futures):
                if cancel_event and cancel_event.is_set():
                    break
                try:
                    result = future.result(timeout=5.0)
                    if result:
                        results.append(result)
                    processed_files += 1
                    # Report progress every 10% or every 50 files
                    if progress_callback and (processed_files % max(1, total_files // 10) == 0 or processed_files % 50 == 0):
                        progress_callback({
                            "stage": "outline_progress",
                            "processed": processed_files,
                            "total": total_files,
                        })
                except Exception:
                    continue

        if progress_callback:
            progress_callback({"stage": "outline_complete", "results": len(results)})

        # Sort results by path for deterministic output
        results.sort(key=lambda x: x[0])
    else:
        # Sequential processing for small sets
        results = []
        for abs_fpath in files_to_process:
            if cancel_event and cancel_event.is_set():
                break
            result = _outline_file(abs_fpath, cwd, query, glob_pattern)
            if result:
                results.append(result)

    # Render results with symbol capping
    for rel, symbols, count in results:
        if total_symbols >= max_results:
            break
        matched_files.add(rel)
        output_lines.append(f"{rel}:")
        for sym_line in symbols:
            if total_symbols >= max_results:
                break
            output_lines.append(sym_line)
            total_symbols += 1
        output_lines.append("")

    return output_lines, total_symbols, len(matched_files)


# ---------------------------------------------------------------------------
# Main search_sync dispatcher
# ---------------------------------------------------------------------------

def search_sync(
    query: str,
    path: str,
    cwd: str,
    mode: str = "content",
    glob_pattern: Optional[str] = None,
    case_sensitive: bool = False,
    max_results: int = 50,
    before_lines: int = 0,
    after_lines: int = 0,
    context_lines: int = 1,
    include_hidden: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[threading.Event] = None,
) -> ToolResult:
    """Synchronous CPU/IO worker executed in a worker thread via run_cancellable."""
    t0 = time.monotonic()

    if cancel_event and cancel_event.is_set():
        header_kv = {"search": (mode or "content").strip().lower()}
        if query and query.strip():
            header_kv["query"] = query
        header_kv["status"] = "0 matches found"
        return done(content="", **header_kv)

    if not os.path.exists(path):
        return fail(ERROR_KIND_NOT_FOUND, f"path '{path}' not found", name=path)

    mode = (mode or "content").strip().lower()
    if mode not in ("content", "filename", "outline"):
        return fail(
            ERROR_KIND_PARAMS,
            f"invalid mode '{mode}'; must be 'content', 'filename', or 'outline'",
            name="mode",
        )

    if mode == "content" and not query.strip():
        return fail(ERROR_KIND_PARAMS, "query parameter is required for content search", name="query")

    # Resolve before/after from context_lines if not explicitly set
    if before_lines == 0 and after_lines == 0 and context_lines > 0:
        before_lines = context_lines
        after_lines = context_lines

    # Report start
    if progress_callback:
        progress_callback({"stage": "start", "mode": mode})

    # Build gitignore matcher for Python fallbacks
    gitignore_matcher = None
    if os.path.isdir(path):
        try:
            gitignore_matcher = _build_gitignore_matcher(path)
            if progress_callback and gitignore_matcher:
                progress_callback({"stage": "gitignore_loaded"})
        except Exception:
            pass

    if mode == "content":
        rg_res = _search_content_ripgrep(
            target_path=path,
            query=query,
            cwd=cwd,
            case_sensitive=case_sensitive,
            before_lines=before_lines,
            after_lines=after_lines,
            glob_pattern=glob_pattern,
            max_results=max_results,
            include_hidden=include_hidden,
            cancel_event=cancel_event,
        )
        if rg_res is not None:
            raw_lines, match_count, file_count = rg_res
        else:
            raw_lines, match_count, file_count = _search_content_python(
                target_path=path,
                query=query,
                cwd=cwd,
                case_sensitive=case_sensitive,
                before_lines=before_lines,
                after_lines=after_lines,
                glob_pattern=glob_pattern,
                max_results=max_results,
                include_hidden=include_hidden,
                gitignore_matcher=gitignore_matcher,
                cancel_event=cancel_event,
            )
    elif mode == "filename":
        raw_lines, match_count, file_count = _search_filename(
            target_path=path,
            query=query,
            cwd=cwd,
            glob_pattern=glob_pattern,
            max_results=max_results,
            include_hidden=include_hidden,
            gitignore_matcher=gitignore_matcher,
            cancel_event=cancel_event,
        )
    else:  # outline
        raw_lines, match_count, file_count = _search_outline(
            target_path=path,
            query=query,
            cwd=cwd,
            glob_pattern=glob_pattern,
            max_results=max_results,
            include_hidden=include_hidden,
            gitignore_matcher=gitignore_matcher,
            progress_callback=progress_callback,
            cancel_event=cancel_event,
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # Report completion
    if progress_callback:
        progress_callback({"stage": "done", "elapsed_ms": elapsed_ms, "matches": match_count})

    header_kv: Dict[str, Any] = {"search": mode}
    rel_p = _safe_relpath(path, cwd)
    if rel_p not in (".", ""):
        header_kv["path"] = rel_p
    if query.strip():
        header_kv["query"] = query
    if glob_pattern:
        header_kv["glob"] = glob_pattern

    if match_count == 0:
        header_kv["status"] = "0 matches found"
        header_kv["elapsed_ms"] = str(elapsed_ms)
        return done(content="", **header_kv)

    header_kv["matches"] = str(match_count)
    header_kv["files"] = str(file_count)
    header_kv["elapsed_ms"] = str(elapsed_ms)

    body = "\n".join(raw_lines).strip()
    full_output = truncate_output(body, tool_name="search")
    return done(content=full_output, **header_kv)


# ---------------------------------------------------------------------------
# SearchTool class
# ---------------------------------------------------------------------------

class SearchTool(BaseTool):
    name = "search"
    description = (
        "Fast codebase search. Modes: 'content' (regex/text grep across files), "
        "'filename' (find files/directories by pattern), or 'outline' (AST symbol definitions: classes, functions, methods). "
        "Uses ripgrep when available for maximum speed, with automatic Python fallback."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Fast codebase search. Modes: 'content' (regex/text grep across files), "
                "'filename' (find files/directories by pattern), or 'outline' (AST symbol definitions: classes, functions, methods). "
                "Uses ripgrep when available for maximum speed, with automatic Python fallback."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query: regex or text for 'content', filename/path pattern for 'filename', "
                            "or symbol name for 'outline' (empty/omitted in outline/filename matches all)."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": "Path to directory or file to search within (default: current workspace root).",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["content", "filename", "outline"],
                        "description": "Search mode: 'content' (default), 'filename', or 'outline'.",
                    },
                    "glob": {
                        "type": "string",
                        "description": (
                            "Glob pattern to filter files. Supports comma-separated patterns, "
                            "! negation, and ** for recursive matching (e.g. '*.py', '!*test*', '**/*.ts')."
                        ),
                    },
                    "case_sensitive": {
                        "type": "boolean",
                        "description": "Whether search is case-sensitive (default: false).",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 500,
                        "description": "Maximum number of results to return (default: 50).",
                    },
                    "context_lines": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 10,
                        "description": "Symmetric context lines before and after matches (for mode='content', default: 1). Overridden by before/after if set.",
                    },
                    "before": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 20,
                        "description": "Context lines before each match (for mode='content'). Overrides context_lines.",
                    },
                    "after": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 20,
                        "description": "Context lines after each match (for mode='content'). Overrides context_lines.",
                    },
                    "include_hidden": {
                        "type": "boolean",
                        "description": "Include hidden files/directories (starting with '.') in search (default: false).",
                    },
                },
                "required": [],
            },
        },
    }

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return True

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)

        query = str(args.get("query") or "")
        raw_path = str(args.get("path") or ".").strip() or "."
        resolved_path = resolve_path(raw_path, cwd=ctx.cwd)

        if getattr(ctx, "sandbox_enabled", False):
            from core.infrastructure.platform.sandbox import is_path_readable_in_sandbox

            if not is_path_readable_in_sandbox(resolved_path, cwd=ctx.cwd):
                return fail(
                    ERROR_KIND_PERMISSION,
                    f"sandbox restriction: read not permitted for sensitive path '{resolved_path}'",
                    name=resolved_path,
                )

        mode = str(args.get("mode") or "content").strip()
        glob_pattern = str(args.get("glob") or "").strip() or None
        case_sensitive = bool(args.get("case_sensitive", False))
        max_results = try_int(args.get("max_results"), 50)
        max_results = max(1, min(max_results, 500))
        context_lines = try_int(args.get("context_lines"), 1)
        context_lines = max(0, min(context_lines, 10))

        before_lines = try_int(args.get("before"), 0)
        before_lines = max(0, min(before_lines, 20))
        after_lines = try_int(args.get("after"), 0)
        after_lines = max(0, min(after_lines, 20))

        include_hidden = bool(args.get("include_hidden", False))

        cwd = ctx.cwd or os.getcwd()

        return await run_cancellable(
            search_sync,
            query=query,
            path=resolved_path,
            cwd=cwd,
            mode=mode,
            glob_pattern=glob_pattern,
            case_sensitive=case_sensitive,
            max_results=max_results,
            before_lines=before_lines,
            after_lines=after_lines,
            context_lines=context_lines,
            include_hidden=include_hidden,
        )
