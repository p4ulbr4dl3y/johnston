import asyncio
import os
import shutil
from typing import Optional


async def run_linter(path: str) -> str:
    """Run fast CLI linter on saved file and return warning string if errors found."""
    if not os.path.exists(path):
        return ""

    ext = os.path.splitext(path)[1].lower()
    errors = []

    if ext == ".py":
        if shutil.which("ruff"):
            output = await _exec_cmd(["ruff", "check", "--select", "E9,F", "--no-fix", "--output-format=concise", path])
            if output:
                errors.append(output)

    elif ext in (".ts", ".tsx", ".js", ".jsx", ".json"):
        if shutil.which("biome"):
            output = await _exec_cmd(["biome", "lint", "--only=correctness", path])
            if output:
                errors.append(output)

    if not errors:
        return ""

    combined = "\n".join(errors).strip()
    if not combined:
        return ""

    lines = combined.splitlines()
    if len(lines) > 10:
        combined = "\n".join(lines[:10]) + f"\n... ({len(lines) - 10} more lines)"

    return f"\n\n[Linter Feedback]:\n{combined}"


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
            return None
    except Exception:
        return None
    return None
