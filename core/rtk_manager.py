import shutil
import subprocess
import sys


def rewrite_cmd(cmd: str) -> str:
    """
    Rewrite bash command using RTK CLI on Unix systems if rtk binary is installed.
    Returns original command if rtk is not available or if rewrite fails.
    """
    if sys.platform == "win32":
        return cmd

    rtk_path = shutil.which("rtk")
    if not rtk_path:
        return cmd

    cmd_trimmed = cmd.strip()
    if cmd_trimmed == "rtk" or cmd_trimmed.startswith("rtk "):
        return cmd

    try:
        res = subprocess.run(
            [rtk_path, "rewrite", cmd],
            capture_output=True,
            text=True,
            timeout=2.0
        )
        if res.returncode in (0, 3) and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass

    return cmd
