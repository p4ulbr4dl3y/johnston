import ast
import fnmatch
import logging
import os
import re
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional, Set, Tuple

from core.domain.defaults.errors import ToolResult
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

DEFAULT_EXCLUDE_DIRS: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
    "target",
    ".next",
    ".nuxt",
    ".cache",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".coverage",
    ".idea",
    ".vscode",
    "coverage",
    "htmlcov",
}

BINARY_EXTENSIONS: Set[str] = {
    ".pyc",
    ".pyo",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".o",
    ".a",
    ".class",
    ".jar",
    ".war",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".wasm",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".bz2",
    ".xz",
    ".7z",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".svg",
    ".mp3",
    ".mp4",
    ".mov",
    ".avi",
    ".flac",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".iso",
    ".bin",
}

CODE_EXTENSIONS: Set[str] = {
    ".py",
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
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".sh",
    ".bash",
    ".zsh",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".vue",
    ".svelte",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".mdx",
}


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
    except SyntaxError:
        return []

    lines: List[str] = []
    q = query.lower().strip() if query and query.strip() and query.strip() != "*" else None

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            methods: List[Tuple[str, int, str]] = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    prefix = "async def " if isinstance(item, ast.AsyncFunctionDef) else "def "
                    args_s = _format_ast_args(item.args)
                    methods.append((f"{prefix}{item.name}({args_s})", item.lineno, item.name))

            class_matches = (q is None) or (q in class_name.lower())
            matching_methods = [m for m in methods if (q is None) or (q in m[2].lower())]

            if class_matches or matching_methods:
                lines.append(f"  class {class_name}: (line {node.lineno})")
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


RE_GENERIC_DEF = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?"
    r"(?:(?P<async>async\s+)?function\s+(?P<fn>[A-Za-z0-9_$]+)\s*\((?P<fn_args>[^)]*)\)|"
    r"class\s+(?P<cls>[A-Za-z0-9_$]+)|"
    r"interface\s+(?P<iface>[A-Za-z0-9_$]+)|"
    r"type\s+(?P<typ>[A-Za-z0-9_$]+)\s*=|"
    r"enum\s+(?P<enum>[A-Za-z0-9_$]+)|"
    r"func\s+(?:\([^)]+\)\s+)?(?P<gofn>[A-Za-z0-9_]+)\s*\((?P<gofn_args>[^)]*)\)|"
    r"(?:pub\s+)?(?:fn\s+(?P<rsfn>[A-Za-z0-9_]+)|struct\s+(?P<rsstruct>[A-Za-z0-9_]+)|enum\s+(?P<rsenum>[A-Za-z0-9_]+)|trait\s+(?P<rstrait>[A-Za-z0-9_]+)))",
    re.MULTILINE,
)


def _outline_generic_content(code: str, query: Optional[str] = None) -> List[str]:
    """Regex-based outline extractor for TS/JS/Go/Rust and other languages."""
    lines: List[str] = []
    q = query.lower().strip() if query and query.strip() and query.strip() != "*" else None

    for m in RE_GENERIC_DEF.finditer(code):
        matched_text = m.group(0).strip()
        name = (
            m.group("fn")
            or m.group("cls")
            or m.group("iface")
            or m.group("typ")
            or m.group("enum")
            or m.group("gofn")
            or m.group("rsfn")
            or m.group("rsstruct")
            or m.group("rsenum")
            or m.group("rstrait")
            or ""
        )
        if not name:
            continue
        if q is not None and q not in name.lower():
            continue

        lineno = code[: m.start()].count("\n") + 1
        lines.append(f"  {matched_text} (line {lineno})")

    return lines


def _match_glob(rel_path: str, filename: str, glob_pattern: Optional[str]) -> bool:
    """Evaluate whether a path matches the optional glob filter (supports ! negation)."""
    if not glob_pattern:
        return True

    patterns = [p.strip() for p in glob_pattern.split(",") if p.strip()]
    positive_pats = [p for p in patterns if not p.startswith("!")]
    negative_pats = [p[1:] for p in patterns if p.startswith("!")]

    for neg in negative_pats:
        if fnmatch.fnmatch(filename, neg) or fnmatch.fnmatch(rel_path, neg):
            return False

    if not positive_pats:
        return True

    for pos in positive_pats:
        if fnmatch.fnmatch(filename, pos) or fnmatch.fnmatch(rel_path, pos):
            return True

    return False


def _search_content_ripgrep(
    target_path: str,
    query: str,
    cwd: str,
    case_sensitive: bool = False,
    context_lines: int = 1,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
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
        "--with-filename",
        "--line-number",
        "--no-heading",
        "--max-columns=300",
        "--max-columns-preview",
    ]

    if not case_sensitive:
        cmd.append("-i")

    if context_lines > 0:
        cmd.extend(["-C", str(context_lines)])

    if glob_pattern:
        for g in glob_pattern.split(","):
            g = g.strip()
            if g:
                cmd.extend(["-g", g])

    for exc in DEFAULT_EXCLUDE_DIRS:
        cmd.extend(["-g", f"!**/{exc}/**"])

    cmd.extend(["--", query, target_path])

    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30.0,
            check=False,
        )
    except Exception as e:
        logger.debug("ripgrep invocation failed: %s", e)
        return None

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    # Returncode 0: matches; returncode 1: no matches
    if proc.returncode == 1:
        return [], 0, 0

    if proc.returncode != 0:
        logger.debug("ripgrep exited with code %s: %s", proc.returncode, proc.stderr)
        return None

    output_lines: List[str] = []
    matched_files: Set[str] = set()
    match_count = 0

    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line or line == "--":
            continue

        colon_split = line.split(":", 2)
        dash_split = line.split("-", 2)
        fpath = ""

        if len(colon_split) >= 3 and colon_split[1].isdigit():
            fpath = colon_split[0]
            match_count += 1
            rel = os.path.relpath(fpath, cwd) if os.path.isabs(fpath) else fpath
            matched_files.add(rel)
            output_lines.append(f"{rel}:{colon_split[1]}:{colon_split[2]}")
        elif len(dash_split) >= 3 and dash_split[1].isdigit():
            fpath = dash_split[0]
            rel = os.path.relpath(fpath, cwd) if os.path.isabs(fpath) else fpath
            matched_files.add(rel)
            output_lines.append(f"{rel}-{dash_split[1]}-{dash_split[2]}")
        else:
            output_lines.append(line)

        if match_count >= max_results:
            break

    return output_lines, match_count, len(matched_files)


def _search_content_python(
    target_path: str,
    query: str,
    cwd: str,
    case_sensitive: bool = False,
    context_lines: int = 1,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
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

    def _process_file(abs_fpath: str) -> None:
        nonlocal match_count
        if match_count >= max_results:
            return
        if cancel_event and cancel_event.is_set():
            return
        if is_binary_file(abs_fpath):
            return

        rel_path = os.path.relpath(abs_fpath, cwd)
        filename = os.path.basename(abs_fpath)
        if not _match_glob(rel_path, filename, glob_pattern):
            return

        try:
            with open(abs_fpath, "r", encoding="utf-8", errors="replace") as f:
                file_lines = f.readlines()
        except Exception:
            return

        file_has_match = False
        total_file_lines = len(file_lines)

        match_indices: List[int] = []
        for idx, l_text in enumerate(file_lines):
            if pattern.search(l_text):
                match_indices.append(idx)

        if not match_indices:
            return

        rendered_indices: Set[int] = set()
        for idx in match_indices:
            if match_count >= max_results:
                break
            match_count += 1
            file_has_match = True

            start_ctx = max(0, idx - context_lines)
            end_ctx = min(total_file_lines, idx + context_lines + 1)
            for ctx_idx in range(start_ctx, end_ctx):
                if ctx_idx not in rendered_indices:
                    rendered_indices.add(ctx_idx)
                    lineno = ctx_idx + 1
                    raw_line = file_lines[ctx_idx].rstrip("\r\n")
                    sep = ":" if ctx_idx == idx else "-"
                    output_lines.append(f"{rel_path}{sep}{lineno}{sep} {raw_line}")

        if file_has_match:
            matched_files.add(rel_path)

    if os.path.isfile(target_path):
        _process_file(target_path)
    elif os.path.isdir(target_path):
        for root, dirs, files in os.walk(target_path, topdown=True):
            if cancel_event and cancel_event.is_set():
                break
            dirs[:] = [
                d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS and not d.endswith(".egg-info") and not d.startswith(".git")
            ]
            for fname in sorted(files):
                if match_count >= max_results:
                    break
                _process_file(os.path.join(root, fname))

    return output_lines, match_count, len(matched_files)


def _search_filename(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[str], int, int]:
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
        rel = os.path.relpath(target_path, cwd)
        fname = os.path.basename(target_path)
        if _matches_query(rel, fname) and _match_glob(rel, fname, glob_pattern):
            matched_paths.append(rel)
        return matched_paths, len(matched_paths), 1 if matched_paths else 0

    for root, dirs, files in os.walk(target_path, topdown=True):
        if cancel_event and cancel_event.is_set():
            break
        dirs[:] = [
            d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS and not d.endswith(".egg-info") and not d.startswith(".git")
        ]

        for fname in sorted(files):
            if len(matched_paths) >= max_results:
                break
            abs_p = os.path.join(root, fname)
            rel = os.path.relpath(abs_p, cwd)
            if _matches_query(rel, fname) and _match_glob(rel, fname, glob_pattern):
                matched_paths.append(rel)

        if len(matched_paths) >= max_results:
            break

    return matched_paths, len(matched_paths), len(matched_paths)


def _search_outline(
    target_path: str,
    query: str,
    cwd: str,
    glob_pattern: Optional[str] = None,
    max_results: int = 50,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[List[str], int, int]:
    """Extract AST/regex outline symbols from files matching path and optional query."""
    output_lines: List[str] = []
    total_symbols = 0
    matched_files: Set[str] = set()

    def _process_file(abs_fpath: str) -> None:
        nonlocal total_symbols
        if total_symbols >= max_results:
            return
        if cancel_event and cancel_event.is_set():
            return

        rel = os.path.relpath(abs_fpath, cwd)
        fname = os.path.basename(abs_fpath)
        ext = os.path.splitext(fname)[1].lower()

        if ext not in CODE_EXTENSIONS and not _match_glob(rel, fname, glob_pattern):
            return
        if not _match_glob(rel, fname, glob_pattern):
            return

        try:
            with open(abs_fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return

        file_symbols: List[str] = []
        if ext == ".py":
            file_symbols = _outline_python_content(content, rel, query)
        else:
            file_symbols = _outline_generic_content(content, query)

        if file_symbols:
            matched_files.add(rel)
            output_lines.append(f"{rel}:")
            for sym_line in file_symbols:
                if total_symbols >= max_results:
                    break
                output_lines.append(sym_line)
                total_symbols += 1
            output_lines.append("")

    if os.path.isfile(target_path):
        _process_file(target_path)
    elif os.path.isdir(target_path):
        for root, dirs, files in os.walk(target_path, topdown=True):
            if cancel_event and cancel_event.is_set():
                break
            dirs[:] = [
                d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS and not d.endswith(".egg-info") and not d.startswith(".git")
            ]
            for fname in sorted(files):
                if total_symbols >= max_results:
                    break
                abs_p = os.path.join(root, fname)
                _process_file(abs_p)

    return output_lines, total_symbols, len(matched_files)


def search_sync(
    query: str,
    path: str,
    cwd: str,
    mode: str = "content",
    glob_pattern: Optional[str] = None,
    case_sensitive: bool = False,
    max_results: int = 50,
    context_lines: int = 1,
    cancel_event: Optional[threading.Event] = None,
) -> ToolResult:
    """Synchronous CPU/IO worker executed in a worker thread via run_cancellable."""
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

    if mode == "content":
        rg_res = _search_content_ripgrep(
            target_path=path,
            query=query,
            cwd=cwd,
            case_sensitive=case_sensitive,
            context_lines=context_lines,
            glob_pattern=glob_pattern,
            max_results=max_results,
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
                context_lines=context_lines,
                glob_pattern=glob_pattern,
                max_results=max_results,
                cancel_event=cancel_event,
            )
    elif mode == "filename":
        raw_lines, match_count, file_count = _search_filename(
            target_path=path,
            query=query,
            cwd=cwd,
            glob_pattern=glob_pattern,
            max_results=max_results,
            cancel_event=cancel_event,
        )
    else:  # outline
        raw_lines, match_count, file_count = _search_outline(
            target_path=path,
            query=query,
            cwd=cwd,
            glob_pattern=glob_pattern,
            max_results=max_results,
            cancel_event=cancel_event,
        )

    header_kv: Dict[str, Any] = {"search": mode}
    if query.strip():
        header_kv["query"] = query
    if glob_pattern:
        header_kv["glob"] = glob_pattern

    if match_count == 0:
        header_kv["status"] = "0 matches found"
        return done(content="", **header_kv)

    header_kv["matches"] = str(match_count)
    header_kv["files"] = str(file_count)

    body = "\n".join(raw_lines).strip()
    full_output = truncate_output(body, tool_name="search")
    return done(content=full_output, **header_kv)


class SearchTool(BaseTool):
    name = "search"
    description = (
        "Fast codebase search. Modes: 'content' (regex/text grep across files), "
        "'filename' (find files/directories by pattern), or 'outline' (AST symbol definitions: classes, functions, methods)."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Fast codebase search. Modes: 'content' (regex/text grep across files), "
                "'filename' (find files/directories by pattern), or 'outline' (AST symbol definitions: classes, functions, methods)."
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
                        "description": "Optional glob pattern to filter files (e.g. '*.py', '!*test*').",
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
                        "description": "Context lines before and after matches (for mode='content', default: 1).",
                    },
                },
                "required": ["query"],
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
            context_lines=context_lines,
        )
