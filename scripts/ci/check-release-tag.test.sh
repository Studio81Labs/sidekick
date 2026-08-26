#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT="$ROOT/scripts/ci/check-release-tag.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
printf '{"version":"1.2.3"}\n' > "$TMP/package.json"

GITHUB_REF_TYPE=branch GITHUB_REF_NAME=main bash "$SCRIPT" "$TMP/package.json" >/dev/null
GITHUB_REF_TYPE=tag GITHUB_REF_NAME=v1.2.3 bash "$SCRIPT" "$TMP/package.json" >/dev/null

if GITHUB_REF_TYPE=tag GITHUB_REF_NAME=v1.2.4 bash "$SCRIPT" "$TMP/package.json" >/dev/null 2>&1; then
  echo "mismatched tag unexpectedly passed" >&2
  exit 1
fi

if GITHUB_REF_TYPE=tag GITHUB_REF_NAME=v1.2.3 bash "$SCRIPT" "$TMP/missing.json" >/dev/null 2>&1; then
  echo "missing manifest unexpectedly passed" >&2
  exit 1
fi

echo "check-release-tag tests passed"
