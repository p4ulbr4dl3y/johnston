import ast
import os
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from tools.search.common import (
    CODE_EXTENSIONS,
    MAX_OUTLINE_FILE_BYTES,
    OUTLINE_WORKERS,
    _GitignoreMatcher,
    _match_glob,
    _safe_relpath,
    _walk_filtered_list,
    compute_line_offsets,
    get_line_number,
    is_binary_file,
)
from tools.search.treesitter import GLOBAL_TREE_SITTER


class _OutlineCache:
    """Thread-safe LRU cache for extracted file symbols keyed by (abs_path, mtime)."""

    def __init__(self, max_size: int = 100):
        self._cache: "OrderedDict[str, Tuple[float, List[Tuple[str, int, str]]]]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_size = max_size

    def get(self, key: str, file_mtime: float) -> Optional[List[Tuple[str, int, str]]]:
        """Get cached full symbols list if mtime matches."""
        with self._lock:
            if key in self._cache:
                cached_mtime, symbols = self._cache[key]
                if cached_mtime == file_mtime:
                    self._cache.move_to_end(key)
                    return symbols
                else:
                    del self._cache[key]
            return None

    def put(self, key: str, file_mtime: float, symbols: List[Tuple[str, int, str]]) -> None:
        """Store extracted symbols in cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
            self._cache[key] = (file_mtime, symbols)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


_OUTLINE_CACHE = _OutlineCache(max_size=100)


def _format_ast_args(args: ast.arguments) -> str:
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


def _outline_python_content(
    code: str,
    file_rel_path: str = "",
    query: Optional[str] = None,
) -> List[Tuple[str, int, str]]:
    """Parse Python AST and extract classes, methods, and functions."""
    try:
        tree = ast.parse(code, filename=file_rel_path or "<string>")
    except Exception:
        return []

    symbols: List[Tuple[str, int, str]] = []
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
                symbols.append((f"  {node.lineno}: class {class_name}{bases_str}:", node.lineno, class_name))
                shown_methods = methods if class_matches else matching_methods
                for m_sig, m_line, m_name in shown_methods:
                    symbols.append((f"    {m_line}: {m_sig}", m_line, m_name))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name
            if (q is None) or (q in fn_name.lower()):
                prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
                args_s = _format_ast_args(node.args)
                symbols.append((f"  {node.lineno}: {prefix}{fn_name}({args_s})", node.lineno, fn_name))

    return symbols


RE_GENERIC_DEF = re.compile(
    r"^[ \t]*(?:export\s+(?:default\s+)?)?"
    r"(?:"
    r"(?P<async>async\s+)?function\s+(?P<fn>[A-Za-z0-9_$.:]+)\s*\((?P<fn_args>[^)]*)\)"
    r"|"
    r"(?:const|let|var)\s+(?P<arrowfn>[A-Za-z0-9_$]+)\s*=\s*(?:async\s+)?\([^)]*\)\s*(?::\s*[^=]+)?\s*=>"
    r"|"
    r"class\s+(?P<cls>[A-Za-z0-9_$]+)"
    r"|"
    r"interface\s+(?P<iface>[A-Za-z0-9_$]+)"
    r"|"
    r"type\s+(?P<typ>[A-Za-z0-9_$]+)\s*="
    r"|"
    r"enum\s+(?P<enum>[A-Za-z0-9_$]+)"
    r"|"
    r"func\s+(?:\([^)]+\)\s+)?(?P<gofn>[A-Za-z0-9_]+)\s*\((?P<gofn_args>[^)]*)\)"
    r"|"
    r"type\s+(?P<gotype>[A-Za-z0-9_]+)\s+(?:struct|interface)"
    r"|"
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
    r"(?:(?:public|private|protected|internal|override|suspend|inline)\s+)*fun\s+(?:<[^>]+>\s+)?(?P<ktfun>[A-Za-z0-9_]+)"
    r"|"
    r"(?:(?:public|private|protected|internal|data|sealed|abstract|open|inner)\s+)*class\s+(?P<ktclass>[A-Za-z0-9_]+)"
    r"|"
    r"(?:(?:public|private|protected|internal)\s+)?object\s+(?P<ktobject>[A-Za-z0-9_]+)"
    r"|"
    r"(?:(?:public|private|protected|internal)\s+)?interface\s+(?P<ktiface>[A-Za-z0-9_]+)"
    r"|"
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
    r"(?:(?:public|private|protected|override|abstract|final|lazy|implicit)\s+)*def\s+(?P<scfn>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected|abstract|final|sealed|case)\s+)?class\s+(?P<scclass>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected)\s+)?object\s+(?P<scobject>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected)\s+)?trait\s+(?P<sctrait>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected|static|final|abstract|synchronized|native)\s+)*(?:class|interface|enum)\s+(?P<jvcls>[A-Za-z0-9_$]+)"
    r"|"
    r"(?:(?:public|private|protected|internal|static|abstract|sealed|virtual|override|async|partial|readonly)\s+)*(?:class|interface|struct|enum|record)\s+(?P<cscls>[A-Za-z0-9_]+)"
    r"|"
    r"class\s+(?P<rbcls>[A-Z][A-Za-z0-9_:]*)"
    r"|"
    r"module\s+(?P<rbmod>[A-Z][A-Za-z0-9_:]*)"
    r"|"
    r"def\s+(?:self\.)?(?P<rbdef>[a-z_][A-Za-z0-9_]*[?!]?)"
    r"|"
    r"(?:abstract\s+)?class\s+(?P<phpcls>[A-Za-z0-9_]+)"
    r"|"
    r"interface\s+(?P<phpiface>[A-Za-z0-9_]+)"
    r"|"
    r"trait\s+(?P<phptrait>[A-Za-z0-9_]+)"
    r"|"
    r"(?:abstract\s+)?class\s+(?P<dartcls>[A-Za-z0-9_]+)"
    r"|"
    r"mixin\s+(?P<dartmix>[A-Za-z0-9_]+)"
    r"|"
    r"defmodule\s+(?P<exmod>[A-Za-z0-9_.]+)"
    r"|"
    r"def(?:macro|p)?\s+(?P<exfn>[a-z_][a-z0-9_]*[?!]?)"
    r"|"
    r"(?:data|type|newtype)\s+(?P<hsdata>[A-Z][A-Za-z0-9_]*)"
    r"|"
    r"class\s+(?P<hsclass>[A-Z][A-Za-z0-9_]*)"
    r"|"
    r"message\s+(?P<pbmsg>[A-Za-z0-9_]+)"
    r"|"
    r"service\s+(?P<pbsvc>[A-Za-z0-9_]+)"
    r"|"
    # C/C++ functions and structs
    r"|"
    r"(?:(?:inline|static|virtual|extern|constexpr)\s+)*(?:[A-Za-z0-9_:<>&*]+\s+)+(?P<cfn>[A-Za-z_][A-Za-z0-9_]*)\s*\([^)]*\)\s*(?:const)?\s*[{;]"
    r"|"
    r"struct\s+(?P<cstruct>[A-Za-z_][A-Za-z0-9_]*)\s*[{;]"
    r")",
    re.MULTILINE,
)

GENERIC_GROUP_NAMES = (
    "fn", "arrowfn", "cls", "iface", "typ", "enum",
    "gofn", "gotype",
    "rsfn", "rsstruct", "rsenum", "rstrait", "rsimpl", "rsmod",
    "ktfun", "ktclass", "ktobject", "ktiface",
    "swfn", "swclass", "swstruct", "swenum", "swproto", "swext",
    "scfn", "scclass", "scobject", "sctrait",
    "jvcls", "cscls",
    "rbcls", "rbmod", "rbdef",
    "phpcls", "phpiface", "phptrait",
    "dartcls", "dartmix",
    "exmod", "exfn",
    "hsdata", "hsclass",
    "pbmsg", "pbsvc",
    "cfn", "cstruct",
)


def _outline_generic_symbols(code: str) -> List[Tuple[str, int, str]]:
    """Extract (display, lineno, name) tuples for languages without Tree-sitter."""
    symbols: List[Tuple[str, int, str]] = []
    line_offsets = compute_line_offsets(code)

    for m in RE_GENERIC_DEF.finditer(code):
        name = ""
        for group_name in GENERIC_GROUP_NAMES:
            try:
                val = m.group(group_name)
                if val:
                    name = val
                    break
            except (IndexError, re.error):
                continue

        if not name:
            continue

        lineno = get_line_number(line_offsets, m.start())
        display = m.group(0).strip().split("\n")[0].strip()
        if len(display) > 120:
            display = display[:117] + "..."
        symbols.append((f"  {lineno}: {display}", lineno, name))

    return symbols


def _outline_generic_content(code: str, query: Optional[str] = None) -> List[str]:
    """Regex-based outline extractor for languages without Tree-sitter."""
    symbols = _outline_generic_symbols(code)
    q = query.lower().strip() if query and query.strip() and query.strip() != "*" else None
    if q is None:
        return [s[0] for s in symbols]
    return [s[0] for s in symbols if q in s[2].lower()]


def _outline_file(
    abs_fpath: str,
    cwd: str,
    query: Optional[str],
    glob_pattern: Optional[str],
    use_cache: bool = True,
) -> Optional[Tuple[str, List[str], int]]:
    """Process a single file for outline extraction with LRU caching."""
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
    if is_binary_file(abs_fpath):
        return None

    all_symbols: Optional[List[Tuple[str, int, str]]] = None

    # Check cache first
    file_mtime = 0.0
    if use_cache:
        try:
            file_mtime = os.path.getmtime(abs_fpath)
            all_symbols = _OUTLINE_CACHE.get(abs_fpath, file_mtime)
        except Exception:
            pass

    if all_symbols is None:
        try:
            with open(abs_fpath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception:
            return None

        # 1. Tree-sitter first
        if GLOBAL_TREE_SITTER and GLOBAL_TREE_SITTER.is_available(ext):
            all_symbols = GLOBAL_TREE_SITTER.extract_symbols(content, ext)

        # 2. Python AST fallback
        if not all_symbols and ext in (".py", ".pyi"):
            all_symbols = _outline_python_content(content, rel)

        # 3. Regex fallback (non-Python files only)
        if not all_symbols and ext not in (".py", ".pyi"):
            all_symbols = _outline_generic_symbols(content)

        if use_cache and all_symbols is not None:
            try:
                _OUTLINE_CACHE.put(abs_fpath, file_mtime, all_symbols)
            except Exception:
                pass

    if not all_symbols:
        return None

    q_clean = query.lower().strip() if query and query.strip() and query.strip() != "*" else None

    # Filter symbols by query in memory
    filtered_lines: List[str] = []
    for display, _, name in all_symbols:
        if q_clean is None or (name and q_clean in name.lower()) or (not name and q_clean in display.lower()):
            filtered_lines.append(display)

    if filtered_lines:
        return rel, filtered_lines, len(filtered_lines)
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
    output_lines: List[str] = []
    total_symbols = 0
    matched_files: Set[str] = set()

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    if os.path.isfile(target_path):
        files_to_process = [target_path]
    elif os.path.isdir(target_path):
        files_to_process = _walk_filtered_list(target_path, include_hidden, gitignore_matcher, cancel_event)
    else:
        return [], 0, 0

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    if len(files_to_process) > 20:
        results: List[Tuple[str, List[str], int]] = []
        total_files = len(files_to_process)
        processed_files = 0
        batch_size = 50

        if progress_callback:
            progress_callback({"stage": "outline_parallel", "total_files": total_files})

        with ThreadPoolExecutor(max_workers=OUTLINE_WORKERS) as executor:
            for i in range(0, len(files_to_process), batch_size):
                if cancel_event and cancel_event.is_set():
                    break
                if total_symbols >= max_results:
                    break
                batch = files_to_process[i : i + batch_size]
                futures = {
                    executor.submit(_outline_file, f, cwd, query, glob_pattern): f
                    for f in batch
                }

                for future in as_completed(futures):
                    if cancel_event and cancel_event.is_set():
                        for fut in futures:
                            fut.cancel()
                        break
                    try:
                        res = future.result(timeout=5.0)
                        if res:
                            results.append(res)
                            total_symbols += res[2]
                        processed_files += 1
                        if progress_callback and (
                            processed_files % max(1, total_files // 10) == 0 or processed_files % 50 == 0
                        ):
                            progress_callback(
                                {
                                    "stage": "outline_progress",
                                    "processed": processed_files,
                                    "total": total_files,
                                }
                            )
                    except Exception:
                        continue

        if progress_callback:
            progress_callback({"stage": "outline_complete", "results": len(results)})

        results.sort(key=lambda x: x[0])
    else:
        results = []
        for abs_fpath in files_to_process:
            if cancel_event and cancel_event.is_set():
                break
            res = _outline_file(abs_fpath, cwd, query, glob_pattern)
            if res:
                results.append(res)

    if cancel_event and cancel_event.is_set():
        return [], 0, 0

    total_rendered = 0
    for rel, symbols, _ in results:
        if total_rendered >= max_results:
            break
        matched_files.add(rel)
        output_lines.append(f"{rel}:")
        for sym_line in symbols:
            if total_rendered >= max_results:
                break
            output_lines.append(sym_line)
            total_rendered += 1
        output_lines.append("")

    return output_lines, total_rendered, len(matched_files)
