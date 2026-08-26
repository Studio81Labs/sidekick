#!/usr/bin/env bash
set -euo pipefail

# A production tag is the public version. Keep it identical to the root package
# version so deploys and Sentry releases cannot acquire a second identity.
PACKAGE_JSON="${1:-package.json}"

if [ "${GITHUB_REF_TYPE:-}" != "tag" ] || [[ "${GITHUB_REF_NAME:-}" != v* ]]; then
  echo "Not a v* tag; release version gate passes."
  exit 0
fi

if [ ! -f "$PACKAGE_JSON" ]; then
  echo "::error::Cannot verify ${GITHUB_REF_NAME}: ${PACKAGE_JSON} is missing"
  exit 1
fi

EXPECTED="$(node -e '
  const fs = require("node:fs");
  const value = JSON.parse(fs.readFileSync(process.argv[1], "utf8")).version;
  if (typeof value !== "string" || !value.trim()) process.exit(1);
  process.stdout.write(value.trim());
' "$PACKAGE_JSON")" || {
  echo "::error::Cannot read a non-empty version from ${PACKAGE_JSON}"
  exit 1
}

ACTUAL="${GITHUB_REF_NAME#v}"
if [ "$ACTUAL" = "$EXPECTED" ]; then
  echo "Release tag ${GITHUB_REF_NAME} matches ${PACKAGE_JSON} (${EXPECTED})."
  exit 0
fi

echo "::error::Release tag ${GITHUB_REF_NAME} does not match ${PACKAGE_JSON} (${EXPECTED})"
echo "Cut v${EXPECTED} from the commit that declares that version."
exit 1
