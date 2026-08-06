"""
Linters Manager for Johnston.
Handles global (~/.johnston/linters.json) and project (.johnston/linters.json) linter configs.
Provides a preset registry of syntax-only linters for popular languages, with
enable/disable and availability scanning.
"""
import asyncio
import functools
import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR
from core.platform_utils import is_windows

GLOBAL_LINTERS_FILE = os.path.join(CONFIG_DIR, "linters.json")


# Preset linters: syntax-only checks per language. cmd placeholders:
#   {file}  -> path to file being checked
#   {tmp}   -> writable scratch dir for tools that need output location
PRESET_LINTERS: Dict[str, Dict[str, Any]] = {
    "python": {
        "name": "python",
        "label": "Python",
        "extensions": [".py"],
        "cmd": ["uvx", "ruff", "check", "-q", "--select", "E9,F", "{file}"],
        "install": "uvx",
        "package": "ruff",
        "check": ["uvx", "ruff", "--version"],
    },
    "js": {
        "name": "js",
        "label": "JavaScript",
        "extensions": [".js", ".mjs", ".cjs", ".jsx"],
        "cmd": ["npx", "--yes", "eslint@9", "--no-config-lookup", "{file}"],
        "install": "npx",
        "package": "eslint",
        "check": ["npx", "--yes", "eslint@9", "--version"],
    },
    "ts": {
        "name": "ts",
        "label": "TypeScript",
        "extensions": [".ts", ".tsx"],
        "cmd": ["npx", "--yes", "eslint@9", "--no-config-lookup", "{file}"],
        "install": "npx",
        "package": "eslint",
        "check": ["npx", "--yes", "eslint@9", "--version"],
    },
    "js_biome": {
        "name": "js_biome",
        "label": "JS/TS/CSS (Biome)",
        "extensions": [".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".css"],
        "cmd": ["biome", "lint", "--only=correctness", "{file}"],
        "install": "npx",
        "package": "@biomejs/biome",
        "check": ["biome", "--version"],
    },
    "rust": {
        "name": "rust",
        "label": "Rust",
        "extensions": [".rs"],
        "cmd": ["rustc", "--edition", "2021", "--emit=metadata", "-o", "{tmp}/check.rmeta", "{file}"],
        "install": "system",
        "package": "Rust toolchain (rustc)",
        "check": ["rustc", "--version"],
    },
    "c": {
        "name": "c",
        "label": "C",
        "extensions": [".c", ".h"],
        "cmd": ["gcc", "-fsyntax-only", "{file}"],
        "install": "system",
        "package": "GCC/Clang",
        "check": ["gcc", "--version"],
    },
    "cpp": {
        "name": "cpp",
        "label": "C++",
        "extensions": [".cc", ".cpp", ".cxx", ".hpp", ".hh"],
        "cmd": ["gcc", "-x", "c++", "-fsyntax-only", "{file}"],
        "install": "system",
        "package": "GCC/Clang (C++)",
        "check": ["gcc", "--version"],
    },
    "ruby": {
        "name": "ruby",
        "label": "Ruby",
        "extensions": [".rb"],
        "cmd": ["ruby", "-c", "{file}"],
        "install": "system",
        "package": "Ruby",
        "check": ["ruby", "--version"],
    },
    "php": {
        "name": "php",
        "label": "PHP",
        "extensions": [".php"],
        "cmd": ["php", "-l", "{file}"],
        "install": "brew",
        "package": "php",
        "check": ["php", "--version"],
    },
    "json": {
        "name": "json",
        "label": "JSON",
        "extensions": [".json"],
        "cmd": ["jq", "empty", "{file}"],
        "install": "system",
        "package": "jq",
        "check": ["jq", "--version"],
    },
    "yaml": {
        "name": "yaml",
        "label": "YAML",
        "extensions": [".yaml", ".yml"],
        "cmd": ["uvx", "yamllint", "--no-warnings", "{file}"],
        "install": "uvx",
        "package": "yamllint",
        "check": ["uvx", "yamllint", "--version"],
    },
    "toml": {
        "name": "toml",
        "label": "TOML",
        "extensions": [".toml"],
        "cmd": ["uvx", "taplo", "check", "{file}"],
        "install": "uvx",
        "package": "taplo",
        "check": ["uvx", "taplo", "--version"],
    },
}

# Output noise prefixes that should never reach the chat (progress lines etc.)
NOISE_PREFIXES = (
    "Building ", "Downloading ", "× Failed", "└─>", "Call to ",
    "[stderr]", "Audited ", "Checked ", "No fixes applied",
)

_linters_manager_instance: Optional["LintersManager"] = None


def get_linters_manager() -> "LintersManager":
    global _linters_manager_instance
    if _linters_manager_instance is None:
        _linters_manager_instance = LintersManager()
    return _linters_manager_instance


class LintersManager:
    """Manages linter presets, enabled state, install/uninstall, and availability."""

    def __init__(self, config_file: Optional[str] = None):
        self.config_file = os.path.realpath(config_file or GLOBAL_LINTERS_FILE)
        self._availability: Dict[str, bool] = {}
        self.ensure_default_configs()

    def ensure_default_configs(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        if not os.path.exists(self.config_file):
            from tools.base import atomic_write_json
            atomic_write_json(self.config_file, {"linters": {}}, indent=2)

    # ------------------------------------------------------------------ load

    def load_linters(self) -> List[Dict[str, Any]]:
        """
        Loads the linter config; every preset appears with its effective enabled
        state; custom linters (defined in config) are appended.
        """
        merged: Dict[str, Dict[str, Any]] = {}
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
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
            entry["enabled"] = True
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
        """
        self._availability = {}
        for name, preset in PRESET_LINTERS.items():
            inst = preset.get("install")
            # System-style binary on PATH always wins (covers global installs of
            # otherwise npx-managed tools, e.g. global biome).
            cmd_bin = (preset.get("cmd") or [""])[0] or (preset.get("check") or [""])[0]
            if cmd_bin and _cached_which(cmd_bin):
                self._availability[name] = True
                continue
            if inst == "system":
                base = preset["check"][0] if preset.get("check") else preset["cmd"][0]
                self._availability[name] = _cached_which(base) is not None
            else:
                # uvx/npx: prefer cached offline resolution; probing network is
                # slow, so trust the package cache instead of executing.
                self._availability[name] = _cache_has_tool(inst, preset.get("package", ""))
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
                with open(file_to_update, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            if not isinstance(cfg.get("linters"), dict):
                cfg["linters"] = {}

            entry = cfg["linters"].get(name, {})
            if isinstance(entry, dict):
                entry["enabled"] = enabled
            else:
                entry = {"enabled": enabled}
            cfg["linters"][name] = entry

            from tools.base import atomic_write_json
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
        if not os.path.exists(path):
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
            cache = os.path.join(
                os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
                "uv",
            ) if is_windows() else os.path.join(os.path.expanduser("~"), ".cache", "uv")
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

