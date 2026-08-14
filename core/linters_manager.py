"""
Linters Manager for Johnston.
Handles global (~/.johnston/linters.json) and project (.johnston/linters.json) linter configs.
Provides a preset registry of syntax-only linters for popular languages, with
enable/disable and availability scanning.
"""

import asyncio
import functools
import os
import shutil
import tempfile
import time
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR
from core.domain.defaults.linters import NOISE_PREFIXES, PRESET_LINTERS
from core.platform_utils import decode_output, is_windows, read_json

GLOBAL_LINTERS_FILE = os.path.join(CONFIG_DIR, "linters.json")


_linters_manager_instance: Optional["LintersManager"] = None


def get_linters_manager() -> "LintersManager":
    """:func:`LintersManager.get_instance`; kept as an alias for existing callers."""
    return LintersManager.get_instance()


class LintersManager:
    """Manages linter presets, enabled state, install/uninstall, and availability."""

    _instance: Optional["LintersManager"] = None

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = os.path.realpath(config_file or GLOBAL_LINTERS_FILE)
        self._availability: Dict[str, bool] = {}
        self._availability_ts: float = 0.0
        self._availability_ttl = 60.0  # seconds
        self.ensure_default_configs()

    @classmethod
    def get_instance(cls) -> "LintersManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def ensure_default_configs(self):
        from core.config_helpers import ensure_json_config

        ensure_json_config(self.config_file, {"linters": {}})

    # ------------------------------------------------------------------ load

    def load_linters(self) -> List[Dict[str, Any]]:
        """
        Loads the linter config; every preset appears with its effective enabled
        state; custom linters (defined in config) are appended.
        """
        merged: Dict[str, Dict[str, Any]] = {}
        try:
            cfg = read_json(self.config_file, {})
            if isinstance(cfg, dict):
                section = cfg.get("linters", {})
                if isinstance(section, dict):
                    for name, entry in section.items():
                        base = dict(entry or {})
                        base["name"] = name
                        merged[name] = base
        except Exception:
            pass

        result: List[Dict[str, Any]] = []
        for p_name, preset in PRESET_LINTERS.items():
            entry = dict(preset)
            entry["name"] = p_name
            entry["scope"] = "preset"
            entry["enabled"] = False  # opt-in: presets stay off until explicitly enabled
            entry["custom"] = False
            if p_name in merged:
                entry.update(merged[p_name])
            result.append(entry)

        for name, entry in merged.items():
            if name in PRESET_LINTERS:
                continue
            if not entry.get("custom", True):
                continue
            entry = dict(entry)
            entry.setdefault("extensions", [])
            entry.setdefault("enabled", True)
            entry.setdefault("custom", True)
            result.append(entry)

        return result

    # ------------------------------------------------------------ availability

    def scan_available(self) -> Dict[str, bool]:
        """
        Returns {linter_name: available} for presets, using which() for system
        tools and a fast `--version` probe for uvx/npx-managed tools. Offline-safe.

        Results are cached in-memory for TTL seconds so the expensive os.walk of
        the uv/npm cache runs at most once per window.
        """
        now = time.time()
        if self._availability and (now - self._availability_ts) < self._availability_ttl:
            return self._availability

        self._availability = {}
        for name, preset in PRESET_LINTERS.items():
            inst = preset.get("install")
            # System-style binary on PATH always wins (covers global installs of
            # otherwise npx-managed tools, e.g. global biome).
            cmd_bin = (preset.get("cmd") or [""])[0] or (preset.get("check") or [""])[0]
            which = _cached_which(cmd_bin) if cmd_bin else None
            if which:
                self._availability[name] = True
                continue
            if inst == "system":
                base = preset["check"][0] if preset.get("check") else preset["cmd"][0]
                self._availability[name] = _cached_which(base) is not None
            else:
                # uvx/npx: prefer cached offline resolution; probing network is
                # slow, so trust the package cache instead of executing.
                self._availability[name] = _cache_has_tool(inst, preset.get("package", ""))
        self._availability_ts = now
        return self._availability

    def is_available(self, name: str) -> bool:
        if not self._availability:
            self.scan_available()
        return self._availability.get(name, False)

    # --------------------------------------------------------------- state ops

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """Persists enabled state for a linter (preset or custom) to the config file."""
        linters = self.load_linters()
        target = next((lint for lint in linters if lint.get("name") == name), None)
        if target is None:
            return False

        file_to_update = self.config_file
        try:
            cfg: Dict[str, Any] = {"linters": {}}
            if os.path.exists(file_to_update):
                cfg = read_json(file_to_update, {})
                if not isinstance(cfg, dict):
                    cfg = {"linters": {}}
            if not isinstance(cfg.get("linters"), dict):
                cfg["linters"] = {}

            entry = cfg["linters"].get(name, {})
            if isinstance(entry, dict):
                entry["enabled"] = enabled
            else:
                entry = {"enabled": enabled}
            cfg["linters"][name] = entry

            from core.platform_utils import atomic_write_json

            atomic_write_json(file_to_update, cfg, indent=2)
            return True
        except Exception:
            return False

    # ---------------------------------------------------------------- helpers

    def get_for_extension(self, ext: str) -> List[Dict[str, Any]]:
        """Returns enabled, available linters matching a file extension."""
        ext = ext.lower()
        matches = []
        for lint in self.load_linters():
            if not lint.get("enabled"):
                continue
            exts = [str(e).lower() for e in lint.get("extensions", [])]
            if ext not in exts:
                continue
            if not self.is_available(lint.get("name", "")):
                continue
            matches.append(lint)
        return matches

    @staticmethod
    def render_cmd(lint: Dict[str, Any], path: str, tmp_dir: Optional[str] = None) -> List[str]:
        """Expands {file} / {tmp} placeholders in a linter cmd template."""
        tmp_dir = tmp_dir or os.path.join(tempfile.gettempdir(), "johnston-lints")
        os.makedirs(tmp_dir, exist_ok=True)
        return [c.replace("{file}", path).replace("{tmp}", tmp_dir) for c in lint.get("cmd", [])]

    # ---------------------------------------------------------------- execution

    async def run_for(self, path: str) -> str:
        """Runs enabled & available linters for the file extension; returns warning string if errors found."""
        if not isinstance(path, (str, os.PathLike)) or not os.path.exists(path):
            return ""

        lint_list = self.get_for_extension(os.path.splitext(path)[1].lower())
        if not lint_list:
            return ""

        errors = []
        for lint in lint_list:
            output = await self._run_one(lint, path)
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

    async def _run_one(self, lint, path: str) -> Optional[str]:
        """Runs a single linter entry; returns captured output on non-zero exit."""
        try:
            cmd = self.render_cmd(lint, path)
            if not cmd or not cmd[0]:
                return None
            return await _exec_cmd(cmd)
        except Exception:
            return None


# --------------------------------------------------------------------- utils


@functools.lru_cache(maxsize=64)
def _cached_which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _cache_has_tool(manager: str, package: str) -> bool:
    """
    Checks local caches for uvx/npx-managed tools without hitting the network.
    Cache roots are platform-aware and respect common env overrides:
      uvx: UV_CACHE_DIR else ~/.cache/uv (posix) / %LOCALAPPDATA%\\uv (windows)
      npx: npm_config_cache else ~/.npm/_npx (posix) / %LOCALAPPDATA%\\npm-cache\\_npx (windows)
    """
    if manager == "uvx":
        cache = os.environ.get("UV_CACHE_DIR")
        if not cache:
            cache = (
                os.path.join(
                    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                    "uv",
                )
                if is_windows()
                else os.path.join(os.path.expanduser("~"), ".cache", "uv")
            )
        if not os.path.isdir(cache):
            return False
        # ruff/yamllint/taplo install via uvx tool or ephemeral env; look for
        # package name inside archive/cache dirs (best effort, offline-safe).
        for root, dirs, files in os.walk(cache):
            if any(package in d for d in dirs):
                return True
            if any(package in f for f in files):
                return True
        return False
    elif manager == "npx":
        cache = os.environ.get("npm_config_cache")
        if cache:
            npx_dir = os.path.join(cache, "_npx")
        elif is_windows():
            npx_dir = os.path.join(
                os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                "npm-cache",
                "_npx",
            )
        else:
            npx_dir = os.path.join(os.path.expanduser("~"), ".npm", "_npx")
        if not os.path.isdir(npx_dir):
            return False
        pkg_key = package.replace("@", "").split("/")[-1]
        for root, dirs, files in os.walk(npx_dir):
            if any(pkg_key in d for d in dirs):
                return True
            if any(pkg_key in f for f in files):
                return True
        return False
    return False


async def _exec_cmd(cmd: List[str]) -> Optional[str]:
    """Runs a command; returns captured output on non-zero exit, None otherwise."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            if proc.returncode != 0 and stdout:
                return decode_output(stdout).strip()
            if proc.returncode != 0:
                return f"[linter exited with code {proc.returncode}]"
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
        line for line in text.splitlines() if not any(line.strip().startswith(prefix) for prefix in NOISE_PREFIXES)
    ]
    return "\n".join(clean_lines).strip()
