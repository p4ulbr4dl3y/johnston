"""
Git Utilities for Johnston.
Provides unified git command execution with timeout handling and process safety.
"""

import subprocess
from typing import List, Optional


def run_git(
    args: List[str],
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> subprocess.CompletedProcess:
    """Executes a git command safely with optional timeout and environment overrides."""
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(args=["git"] + args, returncode=124, stdout="", stderr="timeout")
    except Exception as e:
        return subprocess.CompletedProcess(args=["git"] + args, returncode=1, stdout="", stderr=str(e))
