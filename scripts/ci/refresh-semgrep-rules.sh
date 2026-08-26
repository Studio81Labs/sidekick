#!/usr/bin/env bash
set -euo pipefail

RULESETS=(typescript owasp-top-ten)
OUT_DIR=.semgrep
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p "$OUT_DIR"

for ruleset in "${RULESETS[@]}"; do
  source_url="https://semgrep.dev/c/p/${ruleset}"
  input="$(mktemp)"
  trap 'rm -f "$input"' EXIT
  curl -fsSL "$source_url" -o "$input"
  python3 - "$input" "$ruleset" "$OUT_DIR" <<'PY'
import datetime
import hashlib
import pathlib
import sys

import yaml

source, name, output_dir = sys.argv[1:]
raw = pathlib.Path(source).read_bytes()
document = yaml.safe_load(raw)
rules = document.get("rules") or []
if not rules:
    raise SystemExit(f"p/{name} returned zero rules")

keep = {
    "javascript", "js", "jsx", "typescript", "ts", "tsx",
    "python", "py", "json", "yaml", "generic", "dockerfile",
    "bash", "sh",
}
selected = [
    rule
    for rule in rules
    if keep & {str(language).lower() for language in rule.get("languages", [])}
]
if not selected:
    raise SystemExit(f"p/{name} has no rules for Poker Hero languages")

header = (
    "# GENERATED — run scripts/ci/refresh-semgrep-rules.sh and review the diff.\n"
    f"# source: https://semgrep.dev/c/p/{name}\n"
    f"# fetched: {datetime.date.today().isoformat()}\n"
    f"# upstream sha256: {hashlib.sha256(raw).hexdigest()}\n"
    f"# vendored: {len(selected)}/{len(rules)} rules\n"
)
body = yaml.safe_dump({"rules": selected}, sort_keys=False, width=100, allow_unicode=True)
target = pathlib.Path(output_dir) / f"{name}.yaml"
target.write_text(header + body)
print(f"{target}: {len(selected)} rules")
PY
  rm -f "$input"
  trap - EXIT
done
