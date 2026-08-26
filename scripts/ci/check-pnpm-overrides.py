#!/usr/bin/env python3
# ported from Studio81Labs/nexcue@2658bd07ff90dde85042ba66ba4bbd57ec340817
"""Assert the pnpm overrides in pnpm-workspace.yaml still mean what they say.

An override wins silently. pnpm applies it, rewrites the lockfile's `specifier`
field to the override's own value, and exits 0 — so neither the install output
nor the lockfile shows that a declared range was overruled. Both failures below
were observed in this repo, and both looked like clean installs.

CHECK 1 -- a selectored override must resolve inside the selector's major.

  The selector is what scopes the override to one consumer line. brace-expansion
  exists here as 1.x, 2.x and 5.x simultaneously, and each line gets its own
  entry so a parent expecting 1.x keeps getting 1.x. Point the `@1` entry at a
  5.x range and pnpm collapses every 1.x consumer onto 5.x:

      "brace-expansion@1": ">=5.0.9 <6"   ->  brace-expansion@1.1.18 disappears
                                              from the lockfile entirely

  Install still exits 0. A forced major on a transitive dependency breaks at
  runtime, not at install, which is what makes it worth a gate. #546 fixed
  exactly this once already, having hit it via an unbounded `>=1.1.18`.

  Renovate is the live way back in: it extracts every override as a dependency
  of type `pnpm-workspace.overrides` and will offer to bump the VALUE past its
  selector -- `renovate/brace-expansion1-5.x` is that PR. It reads as a routine
  version bump. renovate.json disables those majors; this check is what holds if
  that rule is ever removed or the edit arrives by hand.

CHECK 2 -- an override must not be disjoint from a declared range.

  When a package.json declares a range the override cannot satisfy, the override
  wins and the declaration becomes decoration:

      packages/openapi/package.json   "js-yaml": "^5.0.0"
      pnpm-workspace.yaml             js-yaml: ">=4.3.1 <5"
      -> installs 4.3.1, lockfile unchanged, exit 0

  That is the shape a Renovate major bump takes against a capped package. The
  PR looks like an upgrade and delivers nothing.

  Only un-selectored overrides are checked here. A `name@N` entry is scoped to
  one resolution line and is not a claim about what any package.json declares,
  so comparing the two would report conflicts that are not conflicts.

WHY NO SEMVER LIBRARY: `semver` is not a dependency of this repo and is not
hoisted, and adding one for a guard means the guard's own supply chain. The
range forms actually present are few, so they are parsed directly -- and
anything unrecognised is a hard FAILURE, never a skip. A guard that quietly
passes on input it does not understand is the thing it exists to prevent.

Usage:  check-pnpm-overrides.py [--self-test]
"""

from __future__ import annotations

import ast
import glob
import json
import re
import sys
from pathlib import Path

# A half-open version interval [lo, hi). Versions are (major, minor, patch).
Version = tuple[int, int, int]
Interval = tuple[Version, Version]

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MAJOR_RE = re.compile(r"^(\d+)$")
GTE_LT_RE = re.compile(r"^>=\s*(\S+)\s+<\s*(\S+)$")

# Specifiers that name no version at all, so no range can conflict with them.
NON_VERSION_PREFIXES = ("workspace:", "catalog:", "link:", "file:", "npm:", "git:")


class Unparseable(ValueError):
    """A form the parser does not model. Always fatal -- never skipped."""


def _mapping_separator(line: str) -> int:
    """Index of the first YAML mapping colon outside quotes, or -1."""
    quote = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote == '"':
            escaped = True
            continue
        if quote:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == ":":
            return index
    return -1


def _yaml_string(raw: str) -> str:
    """Parse the string scalar forms override keys and values are allowed to use."""
    value = raw.strip()
    if not value:
        raise Unparseable("empty YAML scalar")
    if value[0] in "\"'":
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError) as exc:
            raise Unparseable(f"invalid quoted YAML scalar: {value!r}") from exc
        if not isinstance(parsed, str):
            raise Unparseable(f"override scalar is not a string: {value!r}")
        return parsed
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def parse_overrides(raw: str) -> dict[str, str]:
    """Read only the root ``overrides:`` mapping, without a YAML dependency.

    Package-manager override keys and values are strings, so loading an entire
    general-purpose YAML implementation for this one block adds a developer
    prerequisite without buying useful syntax. Unsupported shapes fail loudly;
    they never turn into an unchecked override.
    """
    lines = raw.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line == "overrides:")
    except StopIteration as exc:
        raise Unparseable("pnpm-workspace.yaml has no root overrides block") from exc

    overrides: dict[str, str] = {}
    for line in lines[start + 1 :]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        if not line.startswith("  ") or line.startswith("    "):
            raise Unparseable(f"unsupported nested overrides syntax: {line.strip()!r}")
        entry = line[2:]
        separator = _mapping_separator(entry)
        if separator < 0:
            raise Unparseable(f"cannot parse override entry: {entry!r}")
        key = _yaml_string(entry[:separator])
        value = _yaml_string(entry[separator + 1 :])
        if key in overrides:
            raise Unparseable(f"duplicate override key: {key!r}")
        overrides[key] = value
    return overrides


def parse_version(text: str) -> Version:
    m = VERSION_RE.match(text.strip())
    if not m:
        # Deliberately includes prereleases: "1.2.3-rc.1" orders by rules this
        # parser does not implement, so it must not be guessed at.
        raise Unparseable(f"not a plain x.y.z version: {text!r}")
    return (int(m[1]), int(m[2]), int(m[3]))


def next_patch(v: Version) -> Version:
    return (v[0], v[1], v[2] + 1)


def parse_range(text: str) -> Interval:
    """Parse the range forms this repo uses into [lo, hi)."""
    text = text.strip()

    if m := GTE_LT_RE.match(text):
        lo_raw, hi_raw = m[1], m[2]
        lo = parse_version(lo_raw)
        # The upper bound is written as a bare major in every current entry
        # (">=4.3.1 <5"), which means "<5.0.0".
        if mm := MAJOR_RE.match(hi_raw):
            hi = (int(mm[1]), 0, 0)
        else:
            hi = parse_version(hi_raw)
        return (lo, hi)

    if text.startswith("^"):
        v = parse_version(text[1:])
        # Caret narrows below 1.0.0: ^0.2.3 allows 0.2.x, ^0.0.3 allows only 0.0.3.
        if v[0] > 0:
            return (v, (v[0] + 1, 0, 0))
        if v[1] > 0:
            return (v, (0, v[1] + 1, 0))
        return (v, next_patch(v))

    if text.startswith("~"):
        v = parse_version(text[1:])
        return (v, (v[0], v[1] + 1, 0))

    if VERSION_RE.match(text):
        v = parse_version(text)
        return (v, next_patch(v))

    raise Unparseable(f"unsupported range form: {text!r}")


def parse_selector(key: str) -> tuple[str, Interval | None, str | None]:
    """Split an override key into (package name, permitted interval or None).

    Scoped names start with '@', so the selector separator is the LAST '@' that
    is not index 0: '@hono/node-server' has no selector, 'brace-expansion@1'
    does, and '@scope/pkg@2' has both.

    The interval returned is the selector's MAJOR, not the selector itself, even
    when the selector names an exact version. `chokidar@4.0.3: "4.0.1"` is a
    deliberate entry here -- it routes the consumers that ask for 4.0.3 to the
    last attested release in the same line. Requiring the value to sit inside
    4.0.3 itself would reject that, and the only way to satisfy such a rule is a
    no-op override. Same major is the constraint that actually matters: it is the
    boundary an API contract lives inside, and the one whose violation collapsed
    the brace-expansion lines.
    """
    at = key.rfind("@")
    if at <= 0:
        return key, None, None
    name, sel = key[:at], key[at + 1 :]
    if m := MAJOR_RE.match(sel):
        major = int(m[1])
    else:
        major = parse_version(sel)[0]
    return name, ((major, 0, 0), (major + 1, 0, 0)), sel


ADVISORY_RE = re.compile(r"\b(GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}|CVE-\d{4}-\d+)\b", re.I)


def is_exact(text: str) -> bool:
    """Whether an override value names one specific release."""
    return bool(VERSION_RE.match(text.strip()))


def advisory_for(raw: str, key: str) -> str | None:
    """The advisory id in the comment block directly above `key`, if any.

    Read from the raw file rather than the parsed YAML because comments are the
    only place intent is recorded, and intent is what separates a deliberate
    forced upgrade from the accident this check exists to catch. Scans upward
    from the entry through contiguous `#` lines, so a blank line ends the block
    and an unrelated comment further up is not borrowed.
    """
    lines = raw.splitlines()
    try:
        start = next(index for index, line in enumerate(lines) if line == "overrides:")
    except StopIteration:
        return None
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            break
        if not line.startswith("  ") or line.startswith("    "):
            continue
        entry = line[2:]
        separator = _mapping_separator(entry)
        if separator < 0:
            continue
        try:
            candidate = _yaml_string(entry[:separator])
        except Unparseable:
            continue
        if candidate != key:
            continue
        for j in range(i - 1, -1, -1):
            probe = lines[j].strip()
            if not probe.startswith("#"):
                break
            if m := ADVISORY_RE.search(probe):
                return m[1]
        return None
    return None


def intersects(a: Interval, b: Interval) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


def contains(outer: Interval, inner: Interval) -> bool:
    return outer[0] <= inner[0] and inner[1] <= outer[1]


def fmt(iv: Interval) -> str:
    return f"[{'.'.join(map(str, iv[0]))}, {'.'.join(map(str, iv[1]))})"


def workspace_package_jsons(root: Path) -> list[Path]:
    return [
        Path(p)
        for p in glob.glob(str(root / "**" / "package.json"), recursive=True)
        if "node_modules" not in p
    ]


def declared_ranges(root: Path) -> dict[str, list[tuple[str, str]]]:
    """Every direct dependency declaration, by package name.

    Paths are returned repo-relative: a `::error file=` annotation only attaches
    to the file in the GitHub UI if the path is relative to the repository root.

    peerDependencies are excluded: they state what a consumer must supply, not
    what this tree installs, so an override does not overrule them.
    """
    out: dict[str, list[tuple[str, str]]] = {}
    for pj in workspace_package_jsons(root):
        data = json.loads(pj.read_text())
        rel = pj.relative_to(root).as_posix()
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            for name, spec in (data.get(section) or {}).items():
                out.setdefault(name, []).append((rel, spec))
    return out


def check(root: Path) -> list[str]:
    errors: list[str] = []
    raw = (root / "pnpm-workspace.yaml").read_text()
    try:
        overrides = parse_overrides(raw)
    except Unparseable as exc:
        return [f"::error file=pnpm-workspace.yaml::{exc}"]
    declared = declared_ranges(root)

    for key, value in overrides.items():
        try:
            name, selector, selector_raw = parse_selector(key)
            value_iv = parse_range(str(value))
        except Unparseable as exc:
            errors.append(
                f"::error file=pnpm-workspace.yaml::override {key!r}: {exc}. "
                f"Extend the parser in scripts/ci/check-pnpm-overrides.py rather "
                f"than skipping it -- an unchecked override is how both of the "
                f"failures this guard exists for reached main."
            )
            continue

        # CHECK 1 -- the value must stay inside the selector's line, UNLESS the
        # entry is a deliberate forced upgrade past an advisory.
        #
        # The exception is not a softening. A cross-major override is sometimes
        # the only fix available: an advisory whose patched release exists only
        # in a later major, forced onto a tree that has not adopted it. The
        # sibling repo carries two (`uuid@9.0.1: 11.1.1`,
        # `@hono/node-server@1.19.17: 2.0.10`), and this check rejected both
        # before #563 — with advice that would have REINSTATED the vulnerable
        # version.
        #
        # Two conditions separate that from the accident:
        #
        #   exact value   a range crossing a major is the dangerous shape, and
        #                 the one that collapsed brace-expansion. It keeps
        #                 resolving to whatever is newest, so it drifts; one
        #                 named release cannot.
        #   an advisory   the reason has to be written down. Neither condition
        #                 proves intent on its own — together they mean someone
        #                 chose a specific release and said why.
        if selector is not None and not contains(selector, value_iv):
            exact = is_exact(str(value))
            advisory = advisory_for(raw, key) if exact else None
            if not exact:
                errors.append(
                    f"::error file=pnpm-workspace.yaml::override {key!r} is scoped "
                    f"to {fmt(selector)} but its value {value!r} is a RANGE "
                    f"allowing {fmt(value_iv)}. A range that crosses a major keeps "
                    f"resolving to whatever is newest, so every consumer of {name} "
                    f"in that line is collapsed onto the other major and pnpm does "
                    f"it silently (exit 0, no warning) — that is how "
                    f"brace-expansion@1.1.18 vanished from this repo's lockfile. "
                    f"If a later major is genuinely required, pin ONE release "
                    f"exactly and name the advisory above it; if {name} no longer "
                    f"needs this line, delete the entry."
                )
                continue
            if advisory is None:
                errors.append(
                    f"::error file=pnpm-workspace.yaml::override {key!r} forces "
                    f"{name} across a major ({fmt(selector)} -> {value!r}) with no "
                    f"advisory named in the comment above it. That is allowed when "
                    f"it is the only fix available — an advisory patched solely in "
                    f"a later major — but it has to say so: add the GHSA or CVE id "
                    f"directly above the entry, as every other entry here does. "
                    f"Without it, the next reader cannot tell a deliberate forced "
                    f"upgrade from the accident this check exists to catch."
                )
                continue
            # Deliberate and documented — allowed, and deliberately not warned
            # about. A gate that grumbles on a correct tree gets muted.
            continue

        # CHECK 3 -- an override that redirects a version to itself does nothing.
        if selector_raw is not None and str(value).strip() == selector_raw:
            errors.append(
                f"::error file=pnpm-workspace.yaml::override {key!r} redirects "
                f"{name}@{selector_raw} to itself, which is a no-op — the entry "
                f"reads as though it were pinning something and pins nothing. "
                f"This is what a Renovate bump of the override VALUE looks like "
                f"when the entry was a deliberate downgrade: "
                f"`chokidar@4.0.3: 4.0.1` became `4.0.3` on 2026-08-17 and pnpm "
                f"refused the install with ERR_PNPM_TRUST_DOWNGRADE, because "
                f"4.0.2 and 4.0.3 lost the provenance attestation 4.0.0 and 4.0.1 "
                f"carry. Restore the version you meant to route to, or delete the "
                f"entry if the redirect is no longer needed."
            )
            continue

        # CHECK 2 -- an un-selectored override must be reachable from what the
        # workspace actually declares.
        if selector is not None:
            continue
        for pj, spec in declared.get(name, []):
            if spec.startswith(NON_VERSION_PREFIXES):
                continue
            try:
                spec_iv = parse_range(spec)
            except Unparseable as exc:
                errors.append(
                    f"::error file={pj}::{name} declares {spec!r}: {exc}. "
                    f"An override exists for this package, so the declaration "
                    f"cannot be left unchecked."
                )
                continue
            if not intersects(spec_iv, value_iv):
                errors.append(
                    f"::error file={pj}::{name} declares {spec!r} {fmt(spec_iv)} but "
                    f"pnpm-workspace.yaml overrides it to {value!r} {fmt(value_iv)}. "
                    f"These do not overlap, so the override wins and the "
                    f"declaration does nothing -- pnpm installs the overridden "
                    f"version and exits 0 without touching the lockfile. Either "
                    f"move the override to match, or drop it if the advisory it "
                    f"pins past is fixed in the version being declared."
                )
    return errors


# --------------------------------------------------------------------------
# Self-test. A guard with no negative cases is indistinguishable from one that
# never fires, which is the failure mode of the thing it is guarding.
# --------------------------------------------------------------------------

SELF_TESTS = [
    # (description, overrides, package.json deps, expect_failure)
    (
        "selector honoured",
        {"brace-expansion@1": ">=1.1.18 <2"},
        {},
        False,
    ),
    (
        "REAL REGRESSION: @1 selector pointed at 5.x collapses the 1.x line",
        {"brace-expansion@1": ">=5.0.9 <6"},
        {},
        True,
    ),
    (
        "exact-version selector may point elsewhere in the SAME major -- the real "
        "chokidar@4.0.3 -> 4.0.1 entry, a deliberate downgrade to the last "
        "attested release",
        {"chokidar@4.0.3": "4.0.1"},
        {},
        False,
    ),
    (
        "an undocumented cross-major exact pin fails — since #563 the reason is "
        "the missing advisory, not the crossing itself",
        {"chokidar@4.0.3": "5.0.0"},
        {},
        True,
    ),
    (
        "REAL CASE from nexcue: a cross-major forced upgrade, pinned exactly and "
        "carrying its advisory, is the only fix for an advisory patched solely in "
        "a later major",
        {"uuid@9.0.1": ("11.1.1", "GHSA-w5hq-g745-h8pq (7.5). Pulled by gaxios.")},
        {},
        False,
    ),
    (
        "cross-major exact pin with NO advisory named — indistinguishable from an "
        "accident, so it must fail",
        {"uuid@9.0.1": "11.1.1"},
        {},
        True,
    ),
    (
        "cross-major RANGE stays fatal however it is documented — a range keeps "
        "drifting to whatever is newest",
        {"brace-expansion@1": (">=5.0.9 <6", "GHSA-v6h2-p8h4-qcjw (7.5).")},
        {},
        True,
    ),
    (
        "REAL REGRESSION: Renovate bumped the chokidar downgrade to itself, "
        "making it a no-op and reinstating the unattested version",
        {"chokidar@4.0.3": "4.0.3"},
        {},
        True,
    ),
    (
        "scoped name without a selector is not mis-split",
        {"@hono/node-server": ">=1.19.15 <2"},
        {},
        False,
    ),
    (
        "override overlaps the declared caret range",
        {"js-yaml": ">=4.3.1 <5"},
        {"js-yaml": "^4.3.1"},
        False,
    ),
    (
        "REAL REGRESSION: declared ^5.0.0 capped to 4.x by the override",
        {"js-yaml": ">=4.3.1 <5"},
        {"js-yaml": "^5.0.0"},
        True,
    ),
    (
        "workspace: protocol carries no version and must not be flagged",
        {"js-yaml": ">=4.3.1 <5"},
        {"js-yaml": "workspace:*"},
        False,
    ),
    (
        "unparseable override value fails rather than passing quietly",
        {"js-yaml": "next"},
        {},
        True,
    ),
    (
        "tilde range overlapping",
        {"prettier": ">=3.8.0 <4"},
        {"prettier": "~3.8.1"},
        False,
    ),
    (
        "tilde range disjoint",
        {"prettier": ">=3.9.0 <4"},
        {"prettier": "~3.8.1"},
        True,
    ),
    (
        "caret below 1.0.0 stays inside its minor",
        {"tiny": ">=0.3.0 <1"},
        {"tiny": "^0.2.3"},
        True,
    ),
]


def _write_workspace(path: Path, overrides: dict) -> None:
    """Emit an overrides block by hand so fixtures can carry COMMENTS.

    A generic YAML dumper drops them, and the advisory rule reads exactly those — a
    fixture without comments could not exercise it at all.
    """
    lines = ["overrides:"]
    for key, value in overrides.items():
        comment = None
        if isinstance(value, tuple):
            value, comment = value
        if comment:
            lines.append(f"  # {comment}")
        lines.append(f'  "{key}": "{value}"')
    path.write_text("\n".join(lines) + "\n")


def self_test(tmp: Path) -> int:
    failures = 0
    for desc, overrides, deps, expect_failure in SELF_TESTS:
        _write_workspace(tmp / "pnpm-workspace.yaml", overrides)
        (tmp / "package.json").write_text(json.dumps({"dependencies": deps}))
        errs = check(tmp)
        got = bool(errs)
        status = "ok " if got == expect_failure else "FAIL"
        if got != expect_failure:
            failures += 1
        print(f"  [{status}] {desc}")
        if got != expect_failure:
            print(f"         expected failure={expect_failure}, got={got}")
            for e in errs:
                print(f"         {e[:160]}")
    desc = "single-quoted cross-major key retains its adjacent advisory"
    (tmp / "pnpm-workspace.yaml").write_text(
        "overrides:\n"
        "  # GHSA-w5hq-g745-h8pq (7.5). Pulled by gaxios.\n"
        "  'uuid@9.0.1': '11.1.1'\n"
    )
    (tmp / "package.json").write_text(json.dumps({"dependencies": {}}))
    errs = check(tmp)
    status = "ok " if not errs else "FAIL"
    print(f"  [{status}] {desc}")
    if errs:
        failures += 1
        for e in errs:
            print(f"         {e[:160]}")
    print()
    if failures:
        print(f"::error::self-test: {failures}/{len(SELF_TESTS) + 1} cases behaved wrongly")
        return 1
    print(f"Self-test OK: {len(SELF_TESTS) + 1} cases, both real regressions caught.")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            return self_test(Path(td))

    root = Path(__file__).resolve().parents[2]
    errors = check(root)
    if errors:
        for e in errors:
            print(e)
        print(f"::error::{len(errors)} pnpm override problem(s) found")
        return 1
    overrides = parse_overrides((root / "pnpm-workspace.yaml").read_text())
    print(f"pnpm overrides OK: {len(overrides)} entries checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
