#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

VERSION=$(uv run python -c "from alexandria.version import __version__; print(__version__)")
echo "==> Publishing alexandria-wiki v${VERSION}"

# Build
echo "==> Running tests"
uv run pytest tests/ -q --tb=short

echo "==> Building"
rm -rf dist/
uv run python -m build

echo "==> Checking distribution"
uv run twine check dist/*

# Upload
echo "==> Uploading to PyPI"
uv run twine upload dist/*

echo ""
echo "Published: https://pypi.org/project/alexandria-wiki/${VERSION}/"

# Tag
echo "==> Tagging v${VERSION}"
git tag -a "v${VERSION}" -m "Release v${VERSION}"
git push github "v${VERSION}"

echo "Done."
