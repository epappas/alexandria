#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "==> Cleaning previous builds"
rm -rf dist/ build/ *.egg-info

echo "==> Running tests"
uv run pytest tests/ -q --tb=short

echo "==> Building sdist + wheel"
uv run python -m build

echo "==> Verifying wheel contents"
uv run twine check dist/*

echo ""
echo "Build complete:"
ls -lh dist/
