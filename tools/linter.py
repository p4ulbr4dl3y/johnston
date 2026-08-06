import asyncio
import functools
import os
import shutil
from typing import Optional

from core.linters_manager import NOISE_PREFIXES, get_linters_manager


@functools.lru_cache(maxsize=16)
def _cached_which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


async def run_linter(path: str) -> str:
    """Run enabled & available linters for the file extension; return warning string if errors found."""
    if not os.path.exists(path):
        return ""

    ext = os.path.splitext(path)[1].lower()
    linter_mgr = get_linters_manager()
    lint_list = linter_mgr.get_for_extension(ext)
    if not lint_list:
        return ""

    errors = []
    for lint in lint_list:
        output = await _run_one(lint, path)
        if output:
            errors.append(output)

    if not errors:
        return ""

    combined = "\n".join(errors).strip()
    combined = _clean_output(combined)
    if not combined:
        return ""

    lines = combined.splitlines()
    if len(lines) > 10:
        combined = "\n".join(lines[:10]) + f"\n... ({len(lines) - 10} more lines)"

    return f"\n\nERR: {combined}"


async def _run_one(lint, path: str) -> Optional[str]:
    """Runs a single linter entry; returns captured stderr/stdout on non-zero exit."""
    try:
        cmd = linter_mgr_render_cmd(lint, path)
        if not cmd or not cmd[0]:
            return None
        output = await _exec_cmd(cmd)
        return output
    except Exception:
        return None


_linter_mgr_cache = None


def linter_mgr_render_cmd(lint, path: str) -> list[str]:
    """Expands {file}/{tmp} placeholders using the linter manager's renderer."""
    global _linter_mgr_cache
    if _linter_mgr_cache is None:
        _linter_mgr_cache = get_linters_manager()
    return _linter_mgr_cache.render_cmd(lint, path)


async def _exec_cmd(cmd: list[str]) -> Optional[str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode != 0 and stdout:
                return stdout.decode("utf-8", errors="replace").strip()
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return None
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
    except asyncio.CancelledError:
        raise
    except Exception:
        return None
    return None


def _clean_output(text: str) -> str:
    clean_lines = [
        line for line in text.splitlines()
        if not any(line.strip().startswith(prefix) for prefix in NOISE_PREFIXES)
    ]
    return "\n".join(clean_lines).strip()
