"""Default linter presets and output noise prefixes for Johnston."""

from typing import Any, Dict

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
