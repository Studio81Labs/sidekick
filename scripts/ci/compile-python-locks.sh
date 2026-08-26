#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND="$ROOT/apps/backend"
PIP_TOOLS_VERSION=7.6.1
PYTHON_IMAGE="python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17"
MODE="${1:---write}"

case "$MODE" in
  --write|--check) ;;
  *) echo "usage: $0 [--write|--check]" >&2; exit 2 ;;
esac

command -v docker >/dev/null 2>&1 || {
  echo "docker is required to generate Python 3.12 locks reproducibly" >&2
  exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
docker run --rm \
  -e PIP_TOOLS_VERSION="$PIP_TOOLS_VERSION" \
  -v "$ROOT:/workspace:ro" \
  -v "$TMP:/out" \
  -w /workspace \
  "$PYTHON_IMAGE" \
  sh -euc '
    python -m venv /tmp/lock-venv
    /tmp/lock-venv/bin/python -m pip install --quiet --disable-pip-version-check "pip-tools==$PIP_TOOLS_VERSION"
    compile() {
      output="$1"
      existing="$2"
      shift 2
      if [ -f "$existing" ]; then
        # A freshness check must not change merely because PyPI published a
        # newer compatible transitive dependency during review. The committed
        # lock remains the resolver constraint; incompatible manifest changes
        # still force pip-compile to update the affected graph.
        set -- --constraint "$existing" "$@"
      fi
      /tmp/lock-venv/bin/pip-compile \
        --quiet \
        --allow-unsafe \
        --generate-hashes \
        --no-annotate \
        --no-header \
        --resolver=backtracking \
        --strip-extras \
        --output-file "$output" \
        "$@" \
        apps/backend/pyproject.toml
    }
    compile /out/requirements-prod.txt \
      /workspace/apps/backend/requirements-prod.txt --extra lock
    compile /out/requirements-dev.txt \
      /workspace/apps/backend/requirements-dev.txt --extra lock --extra dev
  '

if [ "$MODE" = "--write" ]; then
  cp "$TMP/requirements-prod.txt" "$BACKEND/requirements-prod.txt"
  cp "$TMP/requirements-dev.txt" "$BACKEND/requirements-dev.txt"
  echo "Wrote Python locks with pip-tools $PIP_TOOLS_VERSION."
  exit 0
fi

for lock in requirements-prod.txt requirements-dev.txt; do
  if ! cmp -s "$TMP/$lock" "$BACKEND/$lock"; then
    echo "::error::apps/backend/$lock is stale; run scripts/ci/compile-python-locks.sh"
    diff -u "$BACKEND/$lock" "$TMP/$lock" || true
    exit 1
  fi
done
echo "Python locks are current (pip-tools $PIP_TOOLS_VERSION)."
