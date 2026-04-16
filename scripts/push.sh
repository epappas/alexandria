#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REMOTE="${1:-github}"
BRANCH="${2:-master}"

echo "==> Running tests"
uv run pytest tests/ -q --tb=short

echo "==> Pushing to ${REMOTE}/${BRANCH}"
git push "$REMOTE" "$BRANCH"

echo ""
echo "Pushed $(git rev-parse --short HEAD) to ${REMOTE}/${BRANCH}"
