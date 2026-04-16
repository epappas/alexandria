#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REMOTE="${1:-github}"
BRANCH="${2:-master}"
GHCR_IMAGE="ghcr.io/epappas/alexandria"

echo "==> Running tests"
uv run pytest tests/ -q --tb=short

echo "==> Pushing git to ${REMOTE}/${BRANCH}"
git push "$REMOTE" "$BRANCH"

echo "==> Building Docker image"
docker build -t "${GHCR_IMAGE}:latest" .

echo "==> Pushing Docker image to GitHub Container Registry"
docker push "${GHCR_IMAGE}:latest"

# Tag with version if available
VERSION=$(uv run python -c "from alexandria.version import __version__; print(__version__)" 2>/dev/null || echo "")
if [ -n "$VERSION" ]; then
    docker tag "${GHCR_IMAGE}:latest" "${GHCR_IMAGE}:${VERSION}"
    docker push "${GHCR_IMAGE}:${VERSION}"
    echo "==> Pushed ${GHCR_IMAGE}:${VERSION}"
fi

echo ""
echo "Pushed $(git rev-parse --short HEAD) to ${REMOTE}/${BRANCH}"
echo "Docker: ${GHCR_IMAGE}:latest"
