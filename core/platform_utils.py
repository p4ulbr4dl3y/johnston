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
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    return env


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".heic", ".svg"}


def is_image_file(path_str: str) -> bool:
    ext = os.path.splitext(path_str)[1].lower()
    return ext in IMAGE_EXTENSIONS


def get_clipboard_image_or_file() -> tuple[str | None, Any | None]:
    """
    Cross-platform retrieval of image or image file path from OS clipboard.
    Returns (file_path, image_obj) where image_obj is a PIL.Image.Image instance.
    """
    import io

    # 1. Try PIL ImageGrab (works on Windows, macOS, and supported Linux setups)
    try:
        from PIL import Image, ImageGrab

        res = ImageGrab.grabclipboard()
        if isinstance(res, Image.Image):
            return (None, res)
        elif isinstance(res, list) and res:
            first = str(res[0])
            if is_image_file(first) and os.path.exists(first):
                return (first, None)
        elif isinstance(res, str) and is_image_file(res) and os.path.exists(res):
            return (res, None)
    except Exception:
        pass

    # 2. macOS JXA fallback (AppKit / NSPasteboard)
    if not is_windows() and shutil.which("osascript"):
        try:
            from PIL import Image

            from core.config import TEMP_IMAGES_DIR

            out_dir = TEMP_IMAGES_DIR
            os.makedirs(out_dir, exist_ok=True)
            tmp_path = os.path.join(out_dir, f"raw_clip_{os.getpid()}.tmp")

            jxa_script = f"""
ObjC.import("AppKit");
var pb = $.NSPasteboard.generalPasteboard;

var files = pb.propertyListForType("NSFilenamesPboardType");
if (!files.isNil() && files.count > 0) {{
    var filePath = files.objectAtIndex(0).js;
    var low = filePath.toLowerCase();
    if (low.endsWith(".png") || low.endsWith(".jpg") || low.endsWith(".jpeg") ||
        low.endsWith(".webp") || low.endsWith(".gif") || low.endsWith(".bmp") ||
        low.endsWith(".tiff") || low.endsWith(".heic") || low.endsWith(".svg")) {{
        "FILE:" + filePath;
    }}
}}

var imgData = pb.dataForType($.NSPasteboardTypePNG);
if (imgData.isNil()) {{
    imgData = pb.dataForType($.NSPasteboardTypeTIFF);
}}
if (imgData.isNil()) {{
    imgData = pb.dataForType($.NSPasteboardTypeJPEG);
}}

if (!imgData.isNil()) {{
    imgData.writeToFileAtomically("{tmp_path}", true);
    "DATA";
}} else {{
    "";
}}
"""
            res = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", jxa_script],
                capture_output=True,
                text=True,
                timeout=3,
            )
            out_str = res.stdout.strip()
            if out_str.startswith("FILE:"):
                target_file = out_str[5:]
                return (target_file, None)

            if out_str == "DATA" and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
                img = Image.open(tmp_path)
                img.load()
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
                return (None, img)
        except Exception:
            pass

    # 3. Linux CLI fallback (wl-paste for Wayland, xclip for X11)
    if not is_windows():
        try:
            from PIL import Image

            if shutil.which("wl-paste"):
                res = subprocess.run(
                    ["wl-paste", "-t", "image/png"],
                    capture_output=True,
                    timeout=2,
                )
                if res.returncode == 0 and res.stdout:
                    img = Image.open(io.BytesIO(res.stdout))
                    img.load()
                    return (None, img)
            elif shutil.which("xclip"):
                res = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                    capture_output=True,
                    timeout=2,
                )
                if res.returncode == 0 and res.stdout:
                    img = Image.open(io.BytesIO(res.stdout))
                    img.load()
                    return (None, img)
        except Exception:
            pass

    return (None, None)


async def terminate_process(process: Any, timeout: float = 1.0) -> None:
    if not process:
        return

    try:
        if is_windows():
            process.terminate()
        else:
            try:
                pid = getattr(process, "pid", None)
                if isinstance(pid, int) and pid > 0:
                    os.killpg(pid, signal.SIGTERM)
                else:
                    process.terminate()
            except Exception:
                process.terminate()
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass

