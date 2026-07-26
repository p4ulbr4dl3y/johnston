import asyncio
import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Any


def is_windows() -> bool:
    return os.name == "nt"


def supports_pty() -> bool:
    return not is_windows()


def new_task_id(prefix: str, counter: int, timestamp_ns: int) -> str:
    return f"{prefix}_{timestamp_ns}_{counter}"


def johnston_config_dir() -> Path:
    if is_windows():
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "johnston"
    return Path.home() / ".johnston"


def shell_executable() -> str | None:
    if is_windows():
        for candidate in ("pwsh", "powershell", "cmd"):
            path = shutil.which(candidate)
            if path:
                return path
        return None
    return os.environ.get("SHELL") or shutil.which("sh") or "/bin/sh"


def shell_subprocess_kwargs() -> dict[str, Any]:
    if is_windows():
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return {"creationflags": creationflags} if creationflags else {}
    return {"start_new_session": True}


def shell_env() -> dict[str, str]:
    env = os.environ.copy()
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


async def terminate_process(process: Any, timeout: float = 1.0) -> None:
    if not process:
        return

    try:
        if is_windows():
            process.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except Exception:
                process.terminate()
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
