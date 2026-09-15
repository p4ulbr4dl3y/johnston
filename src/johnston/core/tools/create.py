import os
import time
from dataclasses import dataclass
from typing import Any, Dict

from johnston.core.domain.defaults.errors import ToolResult
from johnston.core.tools.base import BaseTool, read_file_text, write_file_text
from johnston.core.tools.cancel import run_cancellable
from johnston.core.tools.utils import format_file_diff, get_max_tool_payload_bytes, resolve_writable_path


def _as_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes")
    return bool(val)


def _compute_line_delta(old_text: str, new_text: str) -> tuple[int, int]:
    """Compute (added_lines, deleted_lines) between old and new text."""
    import difflib

    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added = sum(b2 - b1 for tag, _a1, _a2, b1, b2 in matcher.get_opcodes() if tag in ("replace", "insert"))
    deleted = sum(a2 - a1 for tag, a1, a2, _b1, _b2 in matcher.get_opcodes() if tag in ("replace", "delete"))
    return added, deleted


def _format_backup_path(path: str) -> str:
    """Format an absolute backup path with ~ if within user home."""
    home = os.path.expanduser("~")
    if path.startswith(home):
        return f"~{path[len(home):]}"
    return path


def _prune_old_backups(backups_dir: str, ttl_days: int = 7) -> None:
    """Prune .bak files older than ttl_days."""
    try:
        cutoff = time.time() - (ttl_days * 86400)
        for entry in os.scandir(backups_dir):
            if entry.is_file() and entry.name.endswith(".bak"):
                try:
                    if entry.stat().st_mtime < cutoff:
                        os.remove(entry.path)
                except OSError:
                    pass
    except Exception:
        pass


def _save_backup(file_path: str, old_content: str) -> str | None:
    """Save existing file content to ~/.johnston/backups/{timestamp}_{filename}.bak."""
    try:
        from johnston.core.infrastructure.platform.paths import BACKUPS_DIR

        os.makedirs(BACKUPS_DIR, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        basename = os.path.basename(file_path)
        backup_name = f"{ts}_{basename}.bak"
        backup_path = os.path.join(BACKUPS_DIR, backup_name)
        if os.path.exists(backup_path):
            import uuid

            backup_name = f"{ts}_{uuid.uuid4().hex[:6]}_{basename}.bak"
            backup_path = os.path.join(BACKUPS_DIR, backup_name)

        with open(backup_path, "w", encoding="utf-8", errors="replace") as f:
            f.write(old_content)

        _prune_old_backups(BACKUPS_DIR, ttl_days=7)
        return backup_path
    except Exception:
        return None


@dataclass(frozen=True)
class _ProbeResult:
    is_dir: bool
    existed: bool
    is_binary: bool = False
    old_content: str = ""


class CreateTool(BaseTool):
    name = "create"
    description = (
        "Create a new file or overwrite an existing file. "
        "For localized/partial modifications, use 'edit' instead. Parent directories created automatically."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": (
                    "File path to create or overwrite. Use relative path for workspace files, "
                    "or absolute for external files."
                ),
            },
            "content": {
                "type": "string",
                "description": "Full file content (empty string creates an empty file).",
            },
            "overwrite": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Set true to overwrite existing file (default: false). "
                    "Use ONLY if you have already read/inspected the file and intentionally want a full rewrite."
                ),
            },
        },
        "required": ["path", "content"],
    }

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        path_arg = args.get("path")
        path, err = resolve_writable_path(ctx, path_arg)
        if err is not None:
            return err

        overwrite = _as_bool(args.get("overwrite", False))

        def _probe() -> _ProbeResult:
            """Run sync filesystem checks off the event loop."""
            if os.path.isdir(path):
                return _ProbeResult(is_dir=True, existed=False)
            if not os.path.isfile(path):
                return _ProbeResult(is_dir=False, existed=False)

            from johnston.core.tools.search.common import is_binary_file

            if is_binary_file(path):
                return _ProbeResult(is_dir=False, existed=True, is_binary=True)

            try:
                if os.path.getsize(path) > get_max_tool_payload_bytes():
                    return _ProbeResult(is_dir=False, existed=True)
            except OSError:
                pass

            old_text = ""
            try:
                old_text = read_file_text(path)
            except Exception:
                old_text = ""

            return _ProbeResult(is_dir=False, existed=True, old_content=old_text)

        probe = await run_cancellable(_probe)
        if probe.is_dir:
            return ToolResult.error("is_directory", name=path, detail="path is an existing directory")
        if probe.existed and not overwrite:
            return ToolResult.error(
                "file_exists",
                name=str(path_arg or path),
                detail=(
                    f"File '{path_arg}' already exists. DO NOT overwrite blindly. "
                    f"If you have not read this file yet, call 'read' first. "
                    f"Use 'edit' for partial changes, or set overwrite=true ONLY if you have inspected the file and intend a complete rewrite."
                ),
            )
        if probe.is_binary:
            return ToolResult.error("binary_file", name=str(path_arg or path), detail="cannot overwrite binary file")

        raw_content = args.get("content")
        if raw_content is None:
            content = ""
        elif isinstance(raw_content, bytes):
            content = raw_content.decode("utf-8", errors="replace")
        elif not isinstance(raw_content, str):
            content = str(raw_content)
        else:
            content = raw_content
        content = content.rstrip("\r\n")

        def _write() -> None:
            write_file_text(path, content)

        try:
            await run_cancellable(_write)
        except Exception as e:
            return ToolResult.error("execute", detail=f"write failed: {e}", name=path_arg or path)

        new_lines = content.splitlines()
        cnt = len(new_lines) if content else 0

        if not probe.existed:
            result_str = f"[created {path_arg} | {cnt} lines]"
            return ToolResult.done(content=result_str, display=result_str)

        added, deleted = _compute_line_delta(probe.old_content, content)
        backup_path = _save_backup(path, probe.old_content)
        if backup_path:
            disp_backup = _format_backup_path(backup_path)
            result_str = f"[overwritten {path_arg} | +{added}/-{deleted} lines | backup: {disp_backup}]"
        else:
            result_str = f"[overwritten {path_arg} | +{added}/-{deleted} lines]"

        display_str = result_str
        if probe.old_content:
            try:
                diff_text = format_file_diff(probe.old_content, content, str(path_arg))
                if diff_text:
                    display_str = diff_text
            except Exception:
                pass

        return ToolResult.done(content=result_str, display=display_str)
