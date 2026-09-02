import asyncio
import locale
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Set, Union

_FSYNC_EXECUTOR = None
_FSYNC_EXECUTOR_LOCK = threading.Lock()


def _fsync_executor():
    """Shared single-thread daemon executor for background fsync calls."""
    global _FSYNC_EXECUTOR
    if _FSYNC_EXECUTOR is None:
        with _FSYNC_EXECUTOR_LOCK:
            if _FSYNC_EXECUTOR is None:
                from concurrent.futures import ThreadPoolExecutor

                _FSYNC_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="johnston-fsync")
    return _FSYNC_EXECUTOR


def _fsync_path_async(path: str) -> None:
    """Open the file and fsync it on a background thread.

    Runs after os.replace so the visible path is already updated; the fsync only
    hardens durability (survives a crash/power-loss) without blocking the event
    loop. A failure is swallowed — the write already succeeded.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        _fsync_executor().submit(_do_fsync, fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass


def _do_fsync(fd: int) -> None:
    try:
        os.fsync(fd)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def is_windows() -> bool:
    return os.name == "nt"


def johnston_config_dir() -> Path:
    override = os.environ.get("JOHNSTON_CONFIG_DIR")
    if override:
        return Path(override)
    return Path.home() / ".johnston"


def atomic_write_text(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    # Refuse to clobber a symlink (would replace the link, silently corrupting the
    # target) or a read-only file. os.replace would bypass both protections.
    if os.path.islink(path):
        raise PermissionError(f"refusing to overwrite symbolic link: {path}")
    if os.path.exists(path) and not os.access(path, os.W_OK):
        raise PermissionError(f"destination is not writable: {path}")
    import tempfile

    fd, tmp_path = tempfile.mkstemp(prefix=".johnston-", suffix=".tmp", dir=directory, text=True)
    try:
        # newline="" keeps \r\n line endings verbatim: default text mode would
        # translate each \n to \r\n on Windows, corrupting CRLF content to \r\r\n.
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
            f.flush()
        os.replace(tmp_path, path)
        # fsync moved out-of-band (background thread) so session saves do not
        # stall the event loop on every write. Atomicity (mkstemp + os.replace)
        # is preserved; only durability is hardened asynchronously.
        _fsync_path_async(path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        raise


def atomic_write_json(path: str, data: Any, indent: int = 2) -> None:
    import json

    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write_text(path, content)


def atomic_write_jsonl(path: str, data: Any) -> None:
    """Writes JSONL content atomically. Accepts list of dicts/lines or str."""
    if isinstance(data, str):
        content = data if data.endswith("\n") else data + "\n"
    else:
        import json

        content = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in data)
    atomic_write_text(path, content)


async def atomic_write_jsonl_async(path: str, data: Any) -> None:
    """Writes JSONL content atomically in a background thread."""
    await asyncio.to_thread(atomic_write_jsonl, path, data)


def read_json(path: str, default: Any = None) -> Any:
    """Reads JSON file safely, returning default if missing, empty, or invalid."""
    if not path or not os.path.exists(path):
        return default
    try:
        import json

        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if not content:
                return default
            return json.loads(content)
    except Exception:
        return default


_json_read_cache: Dict[str, tuple] = {}


def invalidate_json_read_cache(path: Optional[str] = None) -> None:
    """Invalidate cached JSON file entries."""
    if path is None:
        _json_read_cache.clear()
    else:
        _json_read_cache.pop(path, None)


def update_json_config(
    path: str,
    mutator: Callable[[Dict[str, Any]], None],
    indent: int = 2,
) -> Dict[str, Any]:
    """Read a JSON dict, apply ``mutator``, and atomically write it back.

    Missing, invalid, or non-dict content is treated as an empty dict. Writes via
    ``atomic_write_json`` and invalidates the shared read cache. Returns the
    updated dict so callers can use the result without re-reading.
    """
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    mutator(data)
    atomic_write_json(path, data, indent=indent)
    invalidate_json_read_cache(path)
    return data


def cached_json_read(path: str, default: Any = None) -> Any:
    """Reads a JSON file, returning a cache value when the file mtime is unchanged."""
    if not os.path.exists(path):
        _json_read_cache.pop(path, None)
        return default
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    cached = _json_read_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    data = read_json(path, default)
    _json_read_cache[path] = (mtime, data)
    return data


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


def decode_output(data: bytes) -> str:
    """Best-effort decode of subprocess output bytes.

    Tries UTF-8 first (modern CLI tools). When the bytes are clearly not
    UTF-8 — e.g. OEM/ANSI console output from cmd.exe or Windows PowerShell
    on a non-UTF-8 locale — falls back to the Windows OEM code page and the
    OS locale encoding. Never raises.
    """
    if not data:
        return ""
    text = data.decode("utf-8", errors="replace")
    # A couple of U+FFFD are normal (multi-byte char split at a chunk
    # boundary); a high ratio means the stream is genuinely not UTF-8.
    if "\ufffd" not in text or text.count("\ufffd") / max(len(text), 1) < 0.05:
        return text
    for enc in _output_fallback_encodings():
        try:
            return data.decode(enc, errors="replace")
        except LookupError:
            continue
    return text


def _output_fallback_encodings() -> list[str]:
    encodings: list[str] = []
    if is_windows():
        try:
            import ctypes

            oem_cp = ctypes.windll.kernel32.GetOEMCP()
            if oem_cp:
                encodings.append(f"cp{oem_cp}")
        except Exception:
            pass
    try:
        pref = locale.getpreferredencoding(False)
        if pref:
            encodings.append(pref)
    except Exception:
        pass
    encodings.append("utf-8")
    return encodings


def shell_env() -> dict[str, str]:
    env = os.environ.copy()
    env["TERM"] = "dumb"
    env["NO_COLOR"] = "1"
    env["FORCE_COLOR"] = "0"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PAGER"] = "cat"
    env["GIT_PAGER"] = "cat"
    env["CI"] = "1"
    env["DEBIAN_FRONTEND"] = "noninteractive"
    env["CLI_AUTO_PROMPT"] = "0"
    return env


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg", ".heic"}


def is_image_file(path_str: str) -> bool:
    ext = os.path.splitext(path_str)[1].lower()
    return ext in IMAGE_EXTENSIONS


def cleanup_dir_by_age(
    dir_path: str,
    max_age_days: float = 7.0,
    extensions: Optional[Union[Sequence[str], Set[str]]] = None,
    exclude_prefixes: Sequence[str] = (),
) -> int:
    """Remove files under ``dir_path`` whose mtime is older than ``max_age_days``.

    Returns the number of removed files. Never raises; individual failures are swallowed.
    """
    if not dir_path or not os.path.isdir(dir_path):
        return 0
    cutoff = time.time() - max_age_days * 24 * 3600
    removed = 0
    ext_tuple = tuple(extensions) if extensions is not None else None
    for name in os.listdir(dir_path):
        if exclude_prefixes and any(name.startswith(p) for p in exclude_prefixes):
            continue
        if ext_tuple is not None and not name.endswith(ext_tuple):
            continue
        path = os.path.join(dir_path, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            continue
    return removed


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

            from core.infrastructure.platform.paths import TEMP_IMAGES_DIR

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


def copy_to_os_clipboard(text: str) -> None:
    if not text:
        return
    try:
        if is_windows():
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=text)
        elif shutil.which("pbcopy"):
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=text)
        elif shutil.which("wl-copy"):
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=text)
        elif shutil.which("xclip"):
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE, text=True)
            p.communicate(input=text)
    except Exception:
        pass


async def copy_to_os_clipboard_async(text: str) -> None:
    """Copy text to the OS clipboard off the event loop.

    Wraps the blocking ``copy_to_os_clipboard`` (subprocess spawn + communicate)
    in a thread so Textual's async event loop is never stalled.
    """
    await asyncio.to_thread(copy_to_os_clipboard, text)
