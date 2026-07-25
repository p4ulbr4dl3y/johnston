#!/usr/bin/env bash
set -e

REPO_URL="https://github.com/p4ulbr4dl3y/johnston.git"

echo "=== Installing Johnston ==="

# 1. Check or install uv
if ! command -v uv >/dev/null 2>&1; then
    echo "-> 'uv' not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv >/dev/null 2>&1; then
    echo "[ERROR] Failed to find 'uv'. Please restart shell or add ~/.local/bin to PATH."
    exit 1
fi

# 2. Install johnston as a tool via uv
if [ -f "pyproject.toml" ] && grep -q 'name = "johnston"' pyproject.toml 2>/dev/null; then
    echo "-> Installing johnston from local directory..."
    uv tool install --force .
else
    echo "-> Installing johnston from GitHub repository..."
    uv tool install --force "git+${REPO_URL}"
fi

# 3. Optional dependency notice (rtk)
if ! command -v rtk >/dev/null 2>&1; then
    echo ""
    echo "[INFO] Optional tool 'rtk' not found."
    echo "       Johnston works without it, but rtk enables CLI output token compression."
    echo "       To install rtk: cargo install rtk (or see https://github.com/rtk-org/rtk)"
fi

echo ""
echo "=== Installation complete! ==="
echo "Run 'johnston' to start Johnston."
