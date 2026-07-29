#!/usr/bin/env bash
set -e

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
    echo "-> Installing johnston from PyPI..."
    uv tool install --force johnston
fi

echo ""
echo "=== Installation complete! ==="
echo "Run 'johnston' to start Johnston."
