"""
Linters Manager for Johnston.
Handles global (~/.johnston/linters.json) and project (.johnston/linters.json) linter configs.
Provides a preset registry of syntax-only linters for popular languages, with
enable/disable and availability scanning.
"""
import functools
import json
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

from core.config import CONFIG_DIR

GLOBAL_LINTERS_FILE = os.path.join(CONFIG_DIR, "linters.json")
PROJECT_LINTERS_FILE = os.path.join(".johnston", "linters.json")


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
    "go": {
        "name": "go",
        "label": "Go",
        "extensions": [".go"],
        "cmd": ["gofmt", "-e", "{file}"],
        "install": "system",
        "package": "Go toolchain (gofmt)",
        "check": ["gofmt", "-h"],
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
    "bash": {
        "name": "bash",
        "label": "Bash/Shell",
        "extensions": [".sh", ".bash"],
        "cmd": ["bash", "-n", "{file}"],
        "install": "system",
        "package": "Bash",
        "check": ["bash", "--version"],
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
    "html": {
        "name": "html",
        "label": "HTML",
        "extensions": [".html", ".htm"],
        "cmd": ["tidy", "-q", "-e", "{file}"],
        "install": "system",
        "package": "tidy",
        "check": ["tidy", "-v"],
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
_NOISE_PREFIXES = (
    "Building ", "Downloading ", "× Failed", "└─>", "Call to ",
    "[stderr]", "Audited ", "Checked ", "No fixes applied",
)

_linters_manager_instance: Optional["LintersManager"] = None


def get_linters_manager(project_dir: Optional[str] = None) -> "LintersManager":
    global _linters_manager_instance
    if _linters_manager_instance is None:
        _linters_manager_instance = LintersManager(project_dir=project_dir)
    elif project_dir:
        real_p = os.path.realpath(project_dir)
        if _linters_manager_instance.project_dir != real_p:
            _linters_manager_instance.project_dir = real_p
            _linters_manager_instance.project_file = os.path.join(real_p, PROJECT_LINTERS_FILE)
    return _linters_manager_instance


class LintersManager:
    """Manages linter presets, enabled state, install/uninstall, and availability."""

    def __init__(self, project_dir: Optional[str] = None):
        self.project_dir = os.path.realpath(project_dir or os.getcwd())
        self.global_file = GLOBAL_LINTERS_FILE
        self.project_file = os.path.join(self.project_dir, PROJECT_LINTERS_FILE)
        self._availability: Dict[str, bool] = {}
        self.ensure_default_configs()

    def ensure_default_configs(self):
        os.makedirs(os.path.dirname(self.global_file), exist_ok=True)
        if not os.path.exists(self.global_file):
            from tools.base import atomic_write_json
            atomic_write_json(self.global_file, {"linters": {}}, indent=2)

    # ------------------------------------------------------------------ load

    def load_linters(self) -> List[Dict[str, Any]]:
        """
        Loads global + project linter configs; project overrides global by key.
        Every preset appears with its effective enabled state; custom linters
        (defined in config) are appended.
        """
        curr_proj_dir = os.path.realpath(self.project_dir or os.getcwd())
        self.project_file = os.path.join(curr_proj_dir, PROJECT_LINTERS_FILE)

        merged: Dict[str, Dict[str, Any]] = {}
        for scope, path in (("global", self.global_file), ("project", self.project_file)):
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    section = cfg.get("linters", {})
                    if isinstance(section, dict):
                        for name, entry in section.items():
                            base = dict(entry or {})
                            base["name"] = name
                            base["scope"] = scope
                            merged[name] = base
            except Exception:
                continue

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

        file_to_update = (
            self.project_file
            if target.get("scope") == "project" and os.path.exists(self.project_file)
            else self.global_file
        )
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


# --------------------------------------------------------------------- utils


@functools.lru_cache(maxsize=64)
def _cached_which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


@functools.lru_cache(maxsize=64)
def _cache_has_tool(manager: str, package: str) -> bool:
    """
    Checks local caches for uvx/npx-managed tools without hitting the network.
    uvx: ~/.cache/uv (tools/ or archive-v0); npx: ~/.npm/_npx/*/node_modules.
    """
    if manager == "uvx":
        cache = os.path.join(os.path.expanduser("~"), ".cache", "uv")
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
        cache = os.path.join(os.path.expanduser("~"), ".npm", "_npx")
        if not os.path.isdir(cache):
            return False
        for root, dirs, files in os.walk(cache):
            for d in dirs:
                if package.replace("@", "").split("/")[-1] in d:
                    return True
        return False
    return False

