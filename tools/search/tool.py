import os
import shutil
import time
from typing import Any, Callable, Dict, Optional

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
from tools.search.common import (
    _build_gitignore_matcher,
    _safe_relpath,
)
from tools.search.content import (
    _search_content_python,
    _search_content_ripgrep,
)
from tools.search.files import _search_filename
from tools.search.outline import _search_outline


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
    cancel_event: Optional[Any] = None,
) -> ToolResult:
    """Synchronous worker executed in a background thread via run_cancellable."""
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

    if before_lines == 0 and after_lines == 0 and context_lines > 0:
        before_lines = context_lines
        after_lines = context_lines

    if progress_callback:
        progress_callback({"stage": "start", "mode": mode})

    gitignore_matcher = None
    if os.path.isdir(path) and (mode == "outline" or not shutil.which("rg")):
        try:
            gi_root = cwd if (cwd and os.path.isdir(cwd) and path.startswith(cwd)) else path
            gitignore_matcher = _build_gitignore_matcher(gi_root)
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


class SearchTool(BaseTool):
    name = "search"
    description = (
        "Fast codebase search. Modes: 'content' (regex/text grep across files), "
        "'filename' (find files/directories by pattern), or 'outline' (AST symbol definitions: classes, functions, methods). "
        "Uses Tree-sitter for perfect outline parsing (Python, TS/TSX, JS, Go, Rust), ripgrep for fast content search, "
        "with automatic regex fallback. Supports LRU caching and streaming progress."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Fast codebase search. Modes: 'content' (regex/text grep across files), "
                "'filename' (find files/directories by pattern), or 'outline' (AST symbol definitions: classes, functions, methods). "
                "Uses Tree-sitter for perfect outline parsing (Python, TS/TSX, JS, Go, Rust), ripgrep for fast content search, "
                "with automatic regex fallback. Supports LRU caching and streaming progress."
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
