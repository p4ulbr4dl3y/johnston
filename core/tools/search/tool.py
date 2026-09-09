import os
import shutil
import time
from typing import Any, Callable, Dict, Optional

from core.domain.defaults.errors import ToolResult
from core.tools.base import (
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
from core.tools.cancel import run_cancellable
from core.tools.search.common import (
    _build_gitignore_matcher,
    _safe_relpath,
)
from core.tools.search.content import (
    _search_content_python,
    _search_content_ripgrep,
)
from core.tools.search.files import _search_filename
from core.tools.search.outline import _search_outline


def search_sync(
    query: str,
    path: str,
    cwd: str,
    mode: str = "content",
    glob_pattern: Optional[str] = None,
    case_sensitive: bool = False,
    max_results: int = 50,
    context_lines: int = 0,
    include_hidden: bool = False,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_event: Optional[Any] = None,
) -> ToolResult:
    """Synchronous worker executed in a background thread via run_cancellable."""
    t0 = time.monotonic()

    if cancel_event and cancel_event.is_set():
        header_kv = {"search": (mode or "content").strip().lower()}
        rel_p = _safe_relpath(path, cwd)
        if rel_p not in (".", ""):
            header_kv["path"] = rel_p
        if glob_pattern:
            header_kv["glob"] = glob_pattern
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
            context_lines=context_lines,
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
                context_lines=context_lines,
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
            case_sensitive=case_sensitive,
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
            case_sensitive=case_sensitive,
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
    if rel_p not in (".", "") and (os.path.isdir(path) or match_count == 0):
        header_kv["path"] = rel_p
    if glob_pattern:
        header_kv["glob"] = glob_pattern

    if match_count == 0:
        header_kv["status"] = "0 matches found"
        return done(content="", **header_kv)

    header_kv["matches"] = str(match_count)
    if file_count > 1 or os.path.isdir(path):
        header_kv["files"] = str(file_count)

    body = "\n".join(raw_lines).strip()
    full_output = truncate_output(body, tool_name="search")
    return done(content=full_output, **header_kv)


class SearchTool(BaseTool):
    name = "search"
    description = (
        "Fast codebase search across files by content (regex/text grep), "
        "filename (glob), or symbol outline (AST classes/functions)."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "Fast codebase search across files by content (regex/text grep), "
                "filename (glob), or symbol outline (AST classes/functions)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query: required for 'content' (regex or text); "
                            "optional for 'filename' (filepath pattern) and 'outline' (symbol name, empty matches all)."
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
                        "description": "Whether search is case-sensitive across all modes (default: false).",
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
                        "maximum": 20,
                        "description": "Number of context lines before and after matches (mode='content' only, default: 0).",
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

        raw_mode = args.get("mode")
        glob_pattern = str(args.get("glob") or "").strip() or None
        if not raw_mode and not query.strip() and glob_pattern:
            mode = "filename"
        else:
            mode = str(raw_mode or "content").strip()
        case_sensitive = bool(args.get("case_sensitive", False))
        max_results = try_int(args.get("max_results"), 50)
        max_results = max(1, min(max_results, 500))
        context_lines = try_int(args.get("context_lines"), 0)
        context_lines = max(0, min(context_lines, 20))

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
            context_lines=context_lines,
            include_hidden=include_hidden,
        )
