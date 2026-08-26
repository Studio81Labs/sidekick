#!/usr/bin/env python3
# ported from Studio81Labs/nexcue@314cec89
"""Report infra drift between this repository and a sibling built from the same template.

Why this exists: drift between Nexcue and TableTap is currently found by someone
deciding to go looking. That happened once, produced 11 issues, and took a full
manual comparison of two working trees (Studio81Labs/tabletap#507). Between
audits the two diverge silently, and because both are production apps, the repo
that is behind carries the risk without anyone knowing which one that is.

WHAT IT DOES NOT DO is diff the two trees. That was tried first and is useless
here: of the 14 plausibly-shared files, 13 differ today, and most of those
differences are correct. TableTap has `apps/pwa`, `packages/core` and
`packages/ui-web`; this repo has none of them, so commit scopes, module
resolution and per-app workflows genuinely diverge and always will. A check that
reports 13 findings on every run is muted within two weeks, which is the failure
mode issue #745 is explicitly written against.

So the comparison is narrow and typed. Three kinds, each chosen because a
difference in it is actionable rather than merely true:

  IDENTICAL  files with no repo-local content at all, compared byte for byte
  KEYS       one shared posture extracted from a file whose surroundings differ
  ACTIONS    the pinned version of every GitHub Action both repos use

ACTIONS is the highest-signal of the three and the cheapest to keep honest: both
repos pin digests via `helpers:pinGitHubActionDigests`, the comparison is
independent of repo topology, and a stale pin is exactly the class that left the
Android release job broken for six weeks.

DIRECTION IS REPORTED, NOT JUDGED. "Differs" and "is behind" are not the same
thing: TableTap shipped the unified `v*` release tag before this repo did. The
report says which value each repo holds and lets the reader decide.

Usage:
    check-sibling-drift.py --out report.md    # writes markdown, exit 0
    check-sibling-drift.py --self-test

Requires SIBLING_REPO (the `owner/name` to compare against) and SIBLING_TOKEN
(a token that can read it) in the environment. Some siblings are private, so
there is no unauthenticated fallback. Neither has a default: a drift check
pointed at nothing reports no drift, which reads exactly like convergence.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    print(
        "check-sibling-drift: PyYAML is required. Workflow pins are parsed "
        "rather than grepped, because a regex cannot tell an active step from "
        "a commented-out one. Install the hash-locked dependency from "
        "scripts/ci/sibling-drift-requirements.txt.",
        file=sys.stderr,
    )
    raise SystemExit(1)

class Yaml12(yaml.SafeLoader):
    """SafeLoader without YAML 1.1's legacy boolean words.

    PyYAML implements YAML 1.1, where `off`, `on`, `yes` and `no` are booleans.
    That silently changes meaning here: pnpm accepts `trustPolicy: off`, and
    unquoted it parses as `False` while the quoted spelling parses as `"off"` --
    so a formatting-only difference between the repos fabricates supply-chain
    drift. A workflow's `on:` key has the same problem, arriving as `True`.

    Only the legacy words are dropped. `true` / `false` still resolve as
    booleans, which is correct under both versions.
    """


Yaml12.yaml_implicit_resolvers = {
    key: [
        (tag, regexp)
        for tag, regexp in resolvers
        if not (tag == "tag:yaml.org,2002:bool" and key in "oOyYnN")
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


# YAML 1.2 core integers. PyYAML's 1.1 rules are not only about booleans:
# `01440` is octal 800, `1_440` is 1440, and `12:00` is sexagesimal 720. pnpm
# reads a plain number, so any of those spellings against its plain equivalent
# fabricated supply-chain drift on the value most worth trusting here.
#
# The RESOLVER alone is not enough -- PyYAML's constructor re-parses the scalar
# with the same 1.1 rules, so a correctly-tagged `01440` would still arrive as
# 800. Both are replaced.
YAML12_INT = re.compile(r"^[-+]?(?:[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+)$")

Yaml12.yaml_implicit_resolvers = {
    key: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:int"
    ]
    for key, resolvers in Yaml12.yaml_implicit_resolvers.items()
}
Yaml12.add_implicit_resolver("tag:yaml.org,2002:int", YAML12_INT, "-+0123456789")


def _construct_int_12(loader, node):
    text = loader.construct_scalar(node)
    negative = text.startswith("-")
    digits = text.lstrip("+-")
    if digits.startswith(("0o", "0O")):
        value = int(digits[2:], 8)
    elif digits.startswith(("0x", "0X")):
        value = int(digits[2:], 16)
    else:
        value = int(digits, 10)
    return -value if negative else value


Yaml12.add_constructor("tag:yaml.org,2002:int", _construct_int_12)

# ...and the same for floats, for the same reason. PyYAML's 1.1 float grammar
# requires a decimal point and a signed exponent, so `1e3` is a STRING there
# while any 1.2 reader makes it 1000 -- one repo writing `1e3` against the
# other's `1000` compared string-to-number and reported drift.
YAML12_FLOAT = re.compile(
    r"^[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?$"
    r"|^[-+]?\.(?:inf|Inf|INF)$"
    r"|^\.(?:nan|NaN|NAN)$"
)

Yaml12.yaml_implicit_resolvers = {
    key: [
        (tag, regexp)
        for tag, regexp in resolvers
        if tag != "tag:yaml.org,2002:float"
    ]
    for key, resolvers in Yaml12.yaml_implicit_resolvers.items()
}
Yaml12.add_implicit_resolver("tag:yaml.org,2002:float", YAML12_FLOAT, "-+0123456789.")


def _construct_float_12(loader, node):
    text = loader.construct_scalar(node)
    lowered = text.lower()
    if lowered.endswith(".inf"):
        return float("-inf") if lowered.startswith("-") else float("inf")
    if lowered.endswith(".nan"):
        return float("nan")
    return float(text)


Yaml12.add_constructor("tag:yaml.org,2002:float", _construct_float_12)


def load_yaml(text: str):
    return yaml.load(text, Loader=Yaml12)


# WHICH SIBLING comes from the environment, not a constant, so this file is
# byte-identical in every repo that runs it. That matters more than it looks:
# the copies are compared to each other by the IDENTICAL manifest below, so a
# hardcoded repo name here would make the check report itself as drift, every
# week, forever -- the same trap strip_provenance() exists to avoid.
#
# It also makes the rollout to a third and fourth repo a workflow edit rather
# than a fork of 2000 lines.
SIBLING = os.environ.get("SIBLING_REPO", "").strip()
SIBLING_REF = os.environ.get("SIBLING_REF", "").strip() or "main"

# ---------------------------------------------------------------------------
# The manifest. Grounded in an actual file-by-file comparison of both repos, not
# in what ought to be shared -- issue #745 asks for the list to start narrow and
# widen only when a real divergence slips past. Every entry here is one whose
# difference would be worth someone's morning; the deliberate omissions are
# recorded at the bottom so the next reader does not re-derive them.
# ---------------------------------------------------------------------------

# Most workflow files stay out of here. Their realistic drift is a stale action
# pin, which ACTIONS compares precisely and reports readably; byte-comparing
# them as well reports the same fact twice and drags in prose rewrites, which is
# why every per-app workflow is excluded. The exception is a workflow with NO
# topology component -- a pure infra copy that exists to be the same file in
# every repo. For those, byte-identity is the whole point and the prose is part
# of the copy.
#
# Non-pin drift inside the per-app workflows was the gap this left. JOB_NAMES
# below now covers the part of it that a human actually reads -- the checks
# list -- which is where #745 said to widen once something real slipped past.
# Something did: an audit on 2026-08-18 found six job-name differences across
# the shared workflows, one of them a job whose name claimed a lint the repo
# was not running.
IDENTICAL = [
    ".nvmrc",
    ".editorconfig",
    # .prettierignore is deliberately NOT here — see the note at the bottom of
    # this manifest: it carries repo-local content (generated-file carve-outs,
    # .semgrep/) and byte comparison reported correct divergence as drift.
    "scripts/lib/resolve-flutter.sh",
    # Both repos run this guard over their own pnpm overrides. It encodes rules
    # (selector/value major agreement, no-op detection, the cross-major
    # exemption) that were each written in response to a specific incident, so a
    # repo running an older copy is a repo without that lesson.
    "scripts/ci/check-pnpm-overrides.py",
    # Pure infra, no topology: both are the same file doing the same job.
    ".github/workflows/cleanup-pr-caches.yml",
    ".github/workflows/format-check.yml",
    ".github/workflows/prune-stale-caches.yml",
    # Release-safety guards, converged 2026-08-18. check-release-tag.sh gates
    # every production tag; check-semgrep-fixture.py is the only thing proving
    # the hand-written Dart rules still fire; compare-marketing-version.py is
    # the version comparison the pre-tag floor depends on. A repo running an
    # older copy of any of them is a repo whose release gate is weaker than it
    # looks, which is not visible from the outside.
    "scripts/ci/check-release-tag.sh",
    "scripts/ci/check-semgrep-fixture.py",
    "scripts/ci/compare-marketing-version.py",
    # Guards the CocoaPods half of the iOS plugin split. Its prose was made
    # repo-neutral when the second repo adopted it, precisely so it could be
    # held here -- the SPM-awareness is the part worth keeping identical, since
    # a copy that predates it reports drift on a correctly-migrated tree.
    "scripts/ci/check-podfile-lock.py",
    # Cache deletion is destructive policy. Keep its implementation and
    # fixture suite identical wherever the shared workflow can invoke it.
    "scripts/ci/prune-stale-caches.py",
    "scripts/ci/prune-stale-caches.test.py",
    # The checker checks itself. Every repo runs the same file, so a fix made in
    # one and not carried to the others is precisely the drift this exists to
    # catch -- and it would otherwise be the one blind spot in the manifest.
    # Safe to compare byte-for-byte only because SIBLING now comes from the
    # environment and strip_provenance() removes the ported-from header.
    "scripts/ci/check-sibling-drift.py",
    "scripts/ci/sibling-drift-requirements.txt",
]

# Capability markers may excuse an ABSENT owned artifact, but never disable the
# comparison of two present artifacts. The markers are deliberately broad:
# Flutter and React Native both carry apps/mobile/.gitignore, for example.
TOPOLOGY_GATED = {
    "scripts/lib/resolve-flutter.sh": "capability:mobile",
    "scripts/ci/check-podfile-lock.py": "capability:mobile",
    "scripts/ci/check-release-tag.sh": "capability:mobile",
    "scripts/ci/check-semgrep-fixture.py": "capability:mobile",
    "scripts/ci/compare-marketing-version.py": "capability:mobile",
    ".github/workflows/flutter-pin-check.yml": "capability:mobile",
    ".github/workflows/mobile-ci.yml": "capability:mobile",
    ".github/workflows/mobile-release.yml": "capability:mobile",
    ".github/workflows/packages-ci.yml": "capability:independent-packages",
    ".github/workflows/_build-openapi.yml": "capability:openapi-artifact",
    ".github/workflows/_release-version-gate.yml": "capability:versioned-release",
    ".github/workflows/admin-ci.yml": "apps/admin/package.json",
    ".github/workflows/admin-deploy.yml": "apps/marketing/package.json",
    ".github/workflows/backend-deploy.yml": "capability:backend-deployment",
    ".github/workflows/marketing-ci.yml": "apps/marketing/package.json",
    ".github/workflows/marketing-deploy.yml": "apps/marketing/package.json",
    ".github/workflows/openapi-check.yml": "capability:openapi",
}

# A smaller set genuinely has different implementations between Flutter and
# React Native. pubspec.yaml is the stack manifest, not an incidental marker:
# when either side lacks it, the pair does not share the Flutter implementation.
# Whole-file contents and job layouts may differ across that boundary, while
# action pins remain comparable through ACTION_TOPOLOGY_GATED below.
STACK_TOPOLOGY_GATED = {
    "scripts/lib/resolve-flutter.sh": "apps/mobile/pubspec.yaml",
    "scripts/ci/check-podfile-lock.py": "apps/mobile/pubspec.yaml",
    "scripts/ci/check-release-tag.sh": "apps/mobile/pubspec.yaml",
    ".github/workflows/flutter-pin-check.yml": "apps/mobile/pubspec.yaml",
    ".github/workflows/mobile-ci.yml": "apps/mobile/pubspec.yaml",
    ".github/workflows/mobile-release.yml": "apps/mobile/pubspec.yaml",
}

# These artifacts have stack-specific implementations, but every repository
# with any mobile app must retain one. Across Flutter and React Native their
# contents and job layouts are not comparable; their presence still is.
CROSS_STACK_REQUIRED = {
    "scripts/ci/check-release-tag.sh",
    ".github/workflows/mobile-ci.yml",
    ".github/workflows/mobile-release.yml",
}

# Some capabilities have equivalent markers because sibling implementations
# use different package names. A repository owns independent package CI when it
# has either the shared/core package used by Tarmoto or the core package used by
# Taven and TableTap. Nexcue's generated clients have neither.
CAPABILITY_MARKER_PATHS = {
    "capability:backend-deployment": (
        "apps/marketing/package.json",
        "apps/backend/pyproject.toml",
    ),
    "capability:independent-packages": (
        "packages/core/package.json",
        "packages/shared/package.json",
    ),
    "capability:mobile": (
        "apps/mobile/package.json",
        "apps/mobile/pubspec.yaml",
    ),
    "capability:openapi": ("packages/openapi/package.json",),
    "capability:openapi-artifact": (
        "apps/marketing/package.json",
        "apps/backend/pyproject.toml",
    ),
    "capability:versioned-release": (
        "apps/mobile/package.json",
        "apps/mobile/pubspec.yaml",
        "apps/backend/pyproject.toml",
    ),
}

# A shared workflow is compared only when both repositories declare the
# capability that owns it. This keeps a backend/admin-only sibling in the loop
# without inventing empty mobile, marketing or deployment workflows merely to
# satisfy the drift checker.
ACTION_TOPOLOGY_GATED = {
    ".github/workflows/_build-openapi.yml": "capability:openapi-artifact",
    ".github/workflows/_release-version-gate.yml": "capability:versioned-release",
    ".github/workflows/admin-ci.yml": "apps/admin/package.json",
    ".github/workflows/admin-deploy.yml": "apps/marketing/package.json",
    ".github/workflows/backend-deploy.yml": "capability:backend-deployment",
    ".github/workflows/marketing-ci.yml": "apps/marketing/package.json",
    ".github/workflows/marketing-deploy.yml": "apps/marketing/package.json",
    ".github/workflows/flutter-pin-check.yml": "apps/mobile/pubspec.yaml",
    ".github/workflows/mobile-ci.yml": "capability:mobile",
    ".github/workflows/mobile-release.yml": "capability:mobile",
    ".github/workflows/openapi-check.yml": "capability:openapi",
    ".github/workflows/packages-ci.yml": "capability:independent-packages",
}

# Optional jobs can introduce actions inside an otherwise shared workflow.
# Each entry records the owning job id, its capability marker, and which marker
# state owns the action. This is an assertion, not merely an exemption: an
# action moved to another job no longer satisfies the topology contract.
ACTION_ENTRY_TOPOLOGY_GATED = {
    (".github/workflows/admin-ci.yml", "build", "actions/download-artifact"): (
        "apps/marketing/package.json",
        True,
    ),
    (".github/workflows/admin-ci.yml", "build", "actions/upload-artifact"): (
        "apps/marketing/package.json",
        True,
    ),
    (".github/workflows/ci-scripts.yml", "test", "actions/setup-node"): (
        "scripts/ci/check-workflow-coverage.mjs",
        True,
    ),
    (".github/workflows/packages-ci.yml", "build", "actions/download-artifact"): (
        "apps/ingest/package.json",
        True,
    ),
}

# Workflows whose JOB NAMES are compared, keyed by job id.
#
# Job names are the checks list -- the thing someone scans when a pull request
# goes red -- and AGENTS.md fixes their grammar (`<area>: <what it proves>`) in
# every sibling for exactly that reason: a habit should transfer between repos
# rather than being relearned. A name is also the cheapest place for a real
# divergence to hide, because it is prose that no test reads.
#
# Names, not bodies. Bodies differ for legitimate reasons constantly (path
# filters, matrix shapes, per-repo secrets) and comparing them would bury the
# signal; a name is a claim about what the job proves, and the two repos should
# make the same claims.
JOB_NAME_WORKFLOWS = [
    ".github/workflows/_build-openapi.yml",
    ".github/workflows/_release-version-gate.yml",
    ".github/workflows/admin-ci.yml",
    ".github/workflows/admin-deploy.yml",
    ".github/workflows/backend-ci.yml",
    ".github/workflows/backend-deploy.yml",
    ".github/workflows/ci-scripts.yml",
    ".github/workflows/cleanup-pr-caches.yml",
    ".github/workflows/flutter-pin-check.yml",
    ".github/workflows/format-check.yml",
    ".github/workflows/labeler.yml",
    ".github/workflows/marketing-ci.yml",
    ".github/workflows/marketing-deploy.yml",
    ".github/workflows/mobile-ci.yml",
    ".github/workflows/mobile-release.yml",
    ".github/workflows/openapi-check.yml",
    ".github/workflows/packages-ci.yml",
    ".github/workflows/security-scan.yml",
    ".github/workflows/sibling-drift.yml",
    ".github/workflows/prune-stale-caches.yml",
]

# Job-name differences that are EXPECTED, each with the reason. An entry here is
# a claim that the difference is forced by app topology -- the narrow exception
# AGENTS.md allows alongside the web surface -- not that it is tolerable.
#
# Every entry costs a line and buys the next reader the difference between a
# considered decision and something to re-derive. Deleting an entry whose reason
# no longer holds is how this list stays honest; an entry that outlives its
# reason silently suppresses real drift, the same failure mode as an override
# that matches nothing.
EXPECTED_JOB_DIFFS = {
    # The mobile flavors differ: one repo has per-flavor source sets and a
    # per-flavor google-services.json, the other's flavors differ only by
    # applicationIdSuffix. The android half of the format/analyze job therefore
    # proves a different set of artifacts -- one builds a staging debug APK
    # alongside the release bundle, the other only the bundle. Recorded in
    # AGENTS.md as topology-forced.
    #
    # The two iOS entries that used to sit here are gone. They described one
    # repo building a simulator debug binary and the other building unsigned
    # for device -- which was never flavor topology at all, just two different
    # choices, and the simulator one could not fail on anything AOT-only. Both
    # now build `--no-codesign`; the flavor flag still differs and is real
    # topology, but it lives in the step rather than the job name.
    (".github/workflows/mobile-ci.yml", "mobile"): "android flavor topology",
    # The gate compares the tag against each repo's actual version source:
    # pubspec.yaml for Flutter, apps/mobile/package.json for React Native.
    (".github/workflows/_release-version-gate.yml", "check"): "version-source topology (pubspec vs package.json)",
}

# Poker Hero's Python backend and always-emitted contract gate use different
# job layouts from the Node siblings. Encode both sides' exact claims instead
# of exempting their job IDs: deletion or arbitrary renaming is still drift.
POKER_JOB_LAYOUTS = {
    ".github/workflows/backend-ci.yml": {
        "python": {
            "prepare-openapi": "contract: openapi spec",
            "test": "backend: tests and solver",
            "image": "backend: immutable image",
        },
        "node": {"build": "backend: lint, typecheck, test & build"},
    },
    ".github/workflows/openapi-check.yml": {
        "python": {
            "changes": "contract: detect inputs",
            "prepare-openapi": "contract: openapi spec",
            "validate": "contract: generated artifacts",
            "gate": "contract: gate",
        },
        "node": {"validate": "contract: emit + validate"},
    },
}

# Actions that are deliberately one-sided at the same Python/Node boundary.
# This is an exact contract, not a workflow-wide exemption: every listed
# action must remain on its owning stack only, while any other one-sided action
# (including a removed shared checkout) is ordinary drift.
POKER_ACTION_LAYOUTS = {
    ".github/workflows/backend-ci.yml": {
        "python": frozenset({"actions/setup-python", "actions/download-artifact"}),
        "node": frozenset(),
    },
    ".github/workflows/openapi-check.yml": {
        "python": frozenset({"actions/download-artifact"}),
        "node": frozenset(),
    },
}

# Every expected difference has a marker that identifies the topology forcing
# it. An exception without a marker is global, which would hide drift between
# two repositories that share the same topology.
EXPECTED_JOB_DIFF_MARKERS = {
    (".github/workflows/mobile-ci.yml", "mobile"): "apps/mobile/android/app/src/staging/google-services.json",
    (".github/workflows/_release-version-gate.yml", "check"): "apps/mobile/package.json",
}

# Complementary jobs whose IDs differ by backend implementation. Validate the
# expected job and exact rendered name on EACH side before suppressing their
# one-sided IDs; otherwise deleting one half could make the pair disappear from
# the union and turn lost real-database coverage into false convergence.
EXPECTED_TOPOLOGY_JOB_PAIRS = {
    (".github/workflows/backend-ci.yml", "apps/backend/src/data-source.ts"): (
        ("schema", "backend: schema from zero (real postgres)"),
        ("test-e2e", "backend: e2e (real postgres)"),
    ),
}

# Jobs owned by exactly one side of a capability boundary. Unlike a permissible
# difference in a union, these encode WHO must retain the job and its exact
# rendered claim, so deleting it from the owning side cannot disappear from the
# comparison merely because the other topology never had that job.
EXPECTED_TOPOLOGY_OWNED_JOBS = {
    (".github/workflows/admin-ci.yml", "prepare-openapi"): (
        "apps/marketing/package.json",
        True,
        "contract: openapi spec",
    ),
    (".github/workflows/backend-deploy.yml", "version-gate"): (
        "apps/ingest/package.json",
        False,
        "release: version gate",
    ),
    (".github/workflows/admin-deploy.yml", "resolve"): (
        "apps/ingest/package.json",
        False,
        "admin: resolve environment",
    ),
    (".github/workflows/packages-ci.yml", "prepare-openapi"): (
        "apps/ingest/package.json",
        True,
        "contract: openapi spec",
    ),
}

# Some capability owners share a job ID but prove different work. Select the
# exact claim by the most specific topology marker, in order. The final core
# marker is deliberately after slicer-contracts because both Taven and TableTap
# own packages/core, while only Taven has the slicer contract package.
EXPECTED_TOPOLOGY_JOB_NAME_VARIANTS = {
    (".github/workflows/packages-ci.yml", "build"): (
        ("apps/ingest/package.json", "packages: build, test & typecheck"),
        (
            "packages/slicer-contracts/package.json",
            "packages: lint, typecheck, test & build",
        ),
        ("packages/core/package.json", "packages: build & test"),
    ),
}

# These two topology differences rename a job that exists on both sides. Encode
# the exact documented pair: an arbitrary third name is drift even when the
# repositories have different topology markers.
EXPECTED_PRESENT_JOB_NAME_PAIRS = {
    (".github/workflows/mobile-ci.yml", "mobile"): frozenset(
        {
            "mobile: format, analyze & test (+ android builds when mobile changes)",
            "mobile: format, analyze & test (+ android release when mobile changes)",
        }
    ),
    (".github/workflows/_release-version-gate.yml", "check"): frozenset(
        {"tag matches pubspec", "tag matches the mobile version"}
    ),
}

SHARED_PRESET = "github>Studio81Labs/.github:renovate-base"


def at(*keys):
    """Read a nested key path from a parsed document. Absent -> None."""

    def get(doc):
        current = doc
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    return get


def shared_preset(doc):
    """Whether renovate.json extends the shared preset.

    Not a whole-file comparison: the repo-local rules around it genuinely
    differ (scope vocabularies, ignoreDeps), and only the preset reference is
    shared posture.
    """
    extends = at("extends")(doc)
    if isinstance(extends, list) and SHARED_PRESET in extends:
        return SHARED_PRESET
    return None


# (path, label, format, getter). PARSED, never pattern-matched: tsconfig.base.json
# is JSONC and carries a long comment block that names these very flags, so a
# regex over the raw text can read a commented-out historical value instead of
# the live one -- inventing drift, or worse, hiding a real strictness regression
# behind two agreeing comments. The same reasoning that moved workflow pins off
# a regex applies here, and for the same reason: these are structured documents,
# so read them as documents.
KEYS = [
    ("pnpm-workspace.yaml", "minimumReleaseAge", "yaml", at("minimumReleaseAge")),
    ("pnpm-workspace.yaml", "blockExoticSubdeps", "yaml", at("blockExoticSubdeps")),
    ("pnpm-workspace.yaml", "trustPolicy", "yaml", at("trustPolicy")),
    ("tsconfig.base.json", "strict", "json", at("compilerOptions", "strict")),
    (
        "tsconfig.base.json",
        "noUncheckedIndexedAccess",
        "json",
        at("compilerOptions", "noUncheckedIndexedAccess"),
    ),
    (
        "tsconfig.base.json",
        "exactOptionalPropertyTypes",
        "json",
        at("compilerOptions", "exactOptionalPropertyTypes"),
    ),
    (
        "tsconfig.base.json",
        "noImplicitOverride",
        "json",
        at("compilerOptions", "noImplicitOverride"),
    ),
    ("renovate.json", "shared preset", "json", shared_preset),
]

# Workflows scanned for action pins. This includes shared workflows that
# currently use no actions so adding the first action on only one side is still
# visible. Capability gates above handle surfaces a sibling does not own.
ACTION_WORKFLOWS = [
    ".github/workflows/_build-openapi.yml",
    ".github/workflows/_release-version-gate.yml",
    ".github/workflows/openapi-check.yml",
    ".github/workflows/lint-pr.yml",
    ".github/workflows/labeler.yml",
    ".github/workflows/backend-ci.yml",
    ".github/workflows/backend-deploy.yml",
    ".github/workflows/admin-ci.yml",
    ".github/workflows/admin-deploy.yml",
    ".github/workflows/marketing-ci.yml",
    ".github/workflows/marketing-deploy.yml",
    ".github/workflows/mobile-ci.yml",
    ".github/workflows/mobile-release.yml",
    ".github/workflows/ci-scripts.yml",
    ".github/workflows/cleanup-pr-caches.yml",
    ".github/workflows/flutter-pin-check.yml",
    ".github/workflows/format-check.yml",
    ".github/workflows/packages-ci.yml",
    ".github/workflows/prune-stale-caches.yml",
    ".github/workflows/security-scan.yml",
    ".github/workflows/sibling-drift.yml",
]

# Deliberately NOT compared, with the reason. Kept in code because the useful
# question a year from now is not "what is compared" but "why is X not".
#
#   commitlint.config.js  scope-enum is repo-local by design (AGENTS.md: scope
#                         vocabularies genuinely differ). Only the scopes differ
#                         today, so the file is noise.
#   lint-pr.yml (body)    same scope list, same reason. Its ACTION pins are
#                         still compared above.
#   labeler.yml (body)    only its action pin has ever differed, and ACTIONS
#                         reports that precisely; see the note on IDENTICAL.
#   tsconfig.base.json    module/moduleResolution/lib are deliberately NOT
#     (beyond strictness) centralised here -- this monorepo spans nodenext and
#                         bundler resolution. Only strictness is shared posture.
#   pnpm-workspace.yaml   the package list and overrides are repo-local; only
#     (beyond the gate)   the supply-chain gate is shared posture.
#   bootstrap.sh          diverges by topology (different app set to bootstrap).
#   check-flutter-pin.py  the prose states each repo's ACTUAL pubspec: one
#                         declares no `flutter` key, the other an open-ended
#                         floor. Same code, different true facts.
#   check-ios-spm.sh      canary plugins differ because the dependency sets do,
#                         and the Podfile assertion differs because the SPM
#                         migrations are at different stages -- one asserts the
#                         lock holds ONLY Flutter, the other that one named pod
#                         is gone. Forcing these identical would assert a
#                         migration state that is not true in one repo.
#   mobile-run-*.sh       flavors and emulator setup differ by app topology.
#   refresh-semgrep-rules.sh
#                         functionally identical -- all 47 differing lines are
#                         comments, three of them naming each repo's own rule
#                         file, so byte-identity is unreachable by construction.
#   resolve-app-version.sh
#                         same code, and the headers describe each repo's own
#                         Sentry consumers, which genuinely differ.
#   highest-released-build.sh, list-main-push-workflows.py
#                         same code; the default REPO and the doc references
#                         point at each repo itself.
#   *.test.sh             the suites assert on their own repo's fixtures.
#   openapi-check.yml     same, plus prose rewrites.
#   smoke/smoke.sh        the harness is shared, the PROBES are not, because the
#                         APIs are not: different health paths (one sets no
#                         global prefix), different authenticated routes, and an
#                         MCP posture check only one backend has a surface for.
#                         Unifying these would mean probing routes that do not
#                         exist -- a smoke test that fails for the wrong reason
#                         is worse than one that differs.
#
# One-sided by topology, so they never reach a comparison at all, but a reader
# diffing the two inventories will ask:
#
#   sync-mobile-i18n.sh   copies the PWA's message catalogs into Flutter. No PWA
#                         upstream, so no script.
# NOTE on provenance headers. AGENTS.md asks ported files to carry
# `ported from Studio81Labs/<repo>@<sha>` in a comment -- `#` for shell, YAML,
# Python and TOML, `<!-- ... -->` for Markdown -- and this check asks the two
# copies to be byte-identical. Both are real requirements and they collide: a
# header carrying a sha breaks identity by construction.
#
# Resolved by NORMALISING rather than by dropping either one -- `strip_provenance`
# removes the header from both sides before comparing, so the file keeps its
# audit trail and the check keeps its meaning. Dropping the header was tried
# first and was the wrong trade: it discarded the source revision a future audit
# needs, to satisfy a comparison that could simply ignore it.
#
#   .prettierignore       REMOVED from the list after its first live run. It now
#                         carries repo-local content -- this repo ignores
#                         `.semgrep/`, and the sibling has no `.semgrep/` at
#                         all -- so byte comparison reported a permanent
#                         difference that is correct divergence, not drift.
#                         Exactly the noise this check is built to avoid, so it
#                         came off the list rather than being explained away
#                         every week. Put it back if both repos ever converge
#                         on the same tooling.
#   scripts/ci/resolve-app-version.sh
#                         near-identical logic, but the sibling's copy names its
#                         own apps in the docstring, so byte comparison is noise.
#                         Worth revisiting if the logic itself drifts.

# The ref is ANY non-whitespace, non-comment token. Matching only digests and
# `v*` tags silently DROPPED any other valid ref -- `@main`, `@release-1` -- and
# a dropped occurrence made the action look one-sided, which the intersection
# below then discards as topology. That hid the single worst case this check
# exists to catch: a shared action moved off a digest onto a floating branch in
# one repo only.
# Quotes are optional because `uses: "actions/checkout@sha"` is valid YAML.
# Requiring the owner immediately after the colon dropped that occurrence, and a
# dropped occurrence is indistinguishable from an action the sibling does not
# use -- so the intersection discarded it as topology and a real pin regression
# went unreported. The ref excludes quotes so it cannot swallow the closing one.
#
# Regex rather than a YAML parse: this is the only workflow here that installs
# nothing, and `uses:` is a fixed, well-understood shape. Revisit if the
# comparison ever needs structure (job names, `permissions:`) rather than a
# single token.


def is_blank(text: str) -> bool:
    """Whether a workflow runs nothing.

    The question is not whether the FILE has characters but whether the
    workflow has runnable jobs, because that is what makes its pins disappear.
    A file reduced to comments, to `{}`, or to `jobs: {}` contributes no pins,
    which makes the OTHER side's pins one-sided -- and the intersection
    discards those as topology. Losing a shared workflow any of those ways
    produced no finding at all and could close the standing issue.

    A workflow whose jobs contain only `run:` steps is NOT blank: it still
    runs, it simply pins nothing, and reporting it would be noise.

    A file that will not parse is NOT blank either: it has content and its own
    loud failure downstream, which a quieter finding here should not pre-empt.
    """
    if not text.strip():
        return True
    try:
        root = yaml.compose(text, Loader=Yaml12)
    except yaml.YAMLError:
        return False
    return not runnable_jobs(root)


def _map_get(node, key):
    """Value node for `key` in a mapping node, or None."""
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if getattr(key_node, "value", None) == key:
            return value_node
    return None


def github_number(text: str) -> float | None:
    """A GitHub expression numeric literal, or None if it is not one.

    Decimal and exponential go through `float`; hexadecimal does not, because
    `float("0x0")` raises -- which is how `0x0` slipped past a value-based
    check that looked value-based.
    """
    body = text[1:] if text[:1] in "+-" else text
    sign = -1.0 if text.startswith("-") else 1.0
    if body[:2].lower() == "0x":
        try:
            return sign * int(body[2:], 16)
        except ValueError:
            return None
    try:
        return sign * float(body)
    except ValueError:
        return None


def statically_disabled(node) -> bool:
    """Whether a job or step is turned off by a literal `if: false`.

    Only a LITERAL. `if: github.event_name == 'push'` is dynamic and stays in
    scope -- guessing at runtime conditions would hide pins that really do run.
    A stale step parked behind `if: false` is the opposite case: it never runs,
    so comparing its ref against the sibling's live one invents drift and keeps
    the standing issue open.
    """
    condition = _map_get(node, "if")
    if not isinstance(condition, yaml.ScalarNode):
        return False
    text = condition.value.strip()
    if text.startswith("${{") and text.endswith("}}"):
        text = text[3:-2].strip()
    # GitHub evaluates `if` as an expression, so every FALSY constant disables
    # the node, not just the word `false`: zero, the empty string and null all
    # do. Only constants -- anything else is dynamic and stays in scope.
    #
    # Numeric zero is tested by VALUE, across GitHub's whole numeric syntax --
    # decimal, exponential and hexadecimal. Enumerating spellings missed `0`,
    # then `-0`, then `0x0`; `0.0`, `+0`, `0e0` and `0X0` are the same falsy
    # constant and were the next findings waiting.
    number = github_number(text)
    if number is not None:
        return number == 0
    return text.lower() in {"false", "null", "", "''", '""'}


def enabled_steps(job) -> list:
    """Steps of a job that are not statically disabled."""
    steps = _map_get(job, "steps")
    if not isinstance(steps, yaml.SequenceNode):
        return []
    return [
        step
        for step in steps.value
        if isinstance(step, yaml.MappingNode) and not statically_disabled(step)
    ]


def runnable_job_entries(root) -> list[tuple[str, object]]:
    """Jobs that actually do something: enabled, and holding enabled work.

    ONE definition of "runs", because two of them drifted apart twice. Both
    `is_blank` and `uses_entries` are written against this, so they cannot
    disagree about whether a workflow is alive -- and it was exactly that
    disagreement, not either answer on its own, that reported convergence over
    a workflow doing no work.
    """
    jobs = _map_get(root, "jobs")
    if not isinstance(jobs, yaml.MappingNode):
        return []
    alive = []
    for key, job in jobs.value:
        if not (isinstance(job, yaml.MappingNode) and job.value):
            continue
        if statically_disabled(job):
            continue
        calls_workflow = isinstance(_map_get(job, "uses"), yaml.ScalarNode)
        if calls_workflow or enabled_steps(job):
            alive.append((str(key.value), job))
    return alive


def runnable_jobs(root) -> list:
    """Runnable job nodes, retained as the shared definition used by is_blank()."""
    return [job for _, job in runnable_job_entries(root)]


def job_uses_entries(text: str, path: str) -> list[tuple[str, str, int]]:
    """Every executed `uses:` as (job id, value, source line).

    Composed rather than loaded so each value keeps its line number, which is
    what binds a `# vX.Y.Z` annotation to the pin it actually annotates. Labels
    used to be recovered by scanning the raw text, and that inherited the whole
    raw-grep problem at the presentation layer: a commented-out or embedded
    `uses:` for the same `action@ref` could overwrite the live one's label, so
    the report showed a stale or invented version beside a correctly compared
    ref. Wrong evidence points the reader at the wrong pin.

    Executable nodes only -- job-level reusable calls and enabled steps. An
    action input legitimately named `uses` under `with:` is never reached, so a
    deliberate input cannot be mistaken for an executed action.
    """
    try:
        root = yaml.compose(text, Loader=Yaml12)
    except yaml.YAMLError as error:
        raise SystemExit(f"::error::{path}: cannot parse as YAML: {error}")

    entries: list[tuple[str, str, int]] = []
    for job_id, job in runnable_job_entries(root):
        called = _map_get(job, "uses")  # a reusable workflow call
        if isinstance(called, yaml.ScalarNode):
            entries.append((job_id, called.value, called.start_mark.line))
        for step in enabled_steps(job):
            step_uses = _map_get(step, "uses")
            if isinstance(step_uses, yaml.ScalarNode):
                entries.append((job_id, step_uses.value, step_uses.start_mark.line))
    return entries


def uses_entries(text: str, path: str) -> list[tuple[str, int]]:
    """Every executed `uses:` as (value, source line), across runnable jobs."""
    return [(value, line) for _, value, line in job_uses_entries(text, path)]


def job_actions(text: str, path: str) -> set[tuple[str, str]]:
    """Remote action names keyed by their owning job id."""
    actions = set()
    for job_id, value, _ in job_uses_entries(text, path):
        parts = split_ref(value)
        if parts is not None:
            actions.add((job_id, parts[0]))
    return actions


TRAILING_COMMENT = re.compile(r"#\s*(?P<comment>v?\d+(?:\.\d+)*(?:[-+][\w.]+)?)\s*$")


def label_on_line(lines: list[str], index: int) -> str | None:
    """The `# vX.Y.Z` a human wrote on this exact line, if any.

    Presentation only, and now bound to the line the parser reported, so it
    cannot be taken from a different occurrence.
    """
    if 0 <= index < len(lines):
        found = TRAILING_COMMENT.search(lines[index])
        if found:
            return found.group("comment")
    return None


# Not pinned remote actions, and never in scope: a local composite action and a
# container image are not things the two repos pin against each other.
LOCAL_REF = re.compile(r"^(\./|\.github/|docker://)")

ACTION_NAME = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w.-]+)*$")


def split_ref(value: str) -> tuple[str, str] | None:
    """`owner/repo@ref` -> (action, ref). None if it is not a pinned remote action.

    Validated rather than merely split: `actions/checkout @ aaaaaaa` contains a
    `/` and an `@` and would otherwise yield the action `actions/checkout ` with
    the ref ` aaaaaaa`, quietly comparing a name no workflow uses. Returning
    None instead routes it to unparsed_uses, which reports it.
    """
    value = value.strip()
    if LOCAL_REF.match(value) or "@" not in value:
        return None
    action, _, ref = value.rpartition("@")
    if not ACTION_NAME.match(action) or not ref or any(c.isspace() for c in ref):
        return None
    # GitHub resolves owner/repo case-insensitively, so `actions/Checkout` and
    # `actions/checkout` are one action. Keyed by the raw spelling they became
    # two, each one-sided, and the intersection discarded BOTH as topology --
    # so a simultaneous ref change between the repos went unreported entirely.
    #
    # ONLY the first two segments. Anything after them is a git tree path and
    # IS case-sensitive, so folding it merges genuinely different targets:
    # `owner/repo/Build@v1` and `owner/repo/build@v2` are two actions, and
    # lowercasing the whole string reports bogus drift between them -- or
    # silent agreement when their refs happen to match. This is not
    # hypothetical here: reusable workflows are referenced as
    # `Studio81Labs/<repo>/.github/workflows/<file>@<ref>`.
    #
    # The REF is deliberately left alone too: git refs are case-sensitive, so
    # `v1` and `V1` can be different tags, and folding them would hide a real
    # difference rather than reveal one.
    owner, repository, *subpath = action.split("/")
    return "/".join([owner.lower(), repository.lower(), *subpath]), ref


def unparsed_uses(text: str, path: str) -> list[str]:
    """`uses:` values that name something remote but are not a pinned action.

    THIS IS THE POINT. Several review findings on this file were one failure
    wearing different clothes: an occurrence that failed to parse vanished
    silently, which is indistinguishable from an action the sibling does not
    use, so the intersection discarded it as topology and a real pin regression
    went unreported.

    Handling each shape as it is found leaves the class alive. A value that
    looks remote and does not resolve to `owner/repo@ref` is therefore a
    finding in its own right: the parse may still be incomplete, but it can no
    longer be incomplete QUIETLY.
    """
    return [
        value
        for value, _ in uses_entries(text, path)
        if not LOCAL_REF.match(value) and split_ref(value) is None
    ]


def parse_pins(text: str, path: str) -> dict[str, dict[str, str]]:
    """Map action name -> {ref: label} for every occurrence the workflow runs.

    COMPARE THE REF, NOT THE LABEL. Both repos digest-pin but annotate at
    different precisions -- `# v8.0.1` here against `# v8` there for one SHA --
    and comparing the comment reported five differences that did not exist.

    KEEP EVERY OCCURRENCE. These workflows use one action several times
    (`actions/download-artifact` four times in mobile-release.yml), so
    collapsing to the first hid a stale pin in a later job of the same file.
    Keyed by ref rather than position, because a reordered step is not drift.
    """
    lines = text.splitlines()
    pins: dict[str, dict[str, str]] = {}
    for value, line in uses_entries(text, path):
        parts = split_ref(value)
        if parts is None:
            continue
        action, ref = parts
        pins.setdefault(action, {}).setdefault(ref, label_on_line(lines, line) or ref[:7])
    return pins


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments from JSONC, respecting string literals.

    String-aware on purpose: renovate.json holds `"https://docs.renovatebot.com/..."`,
    and a naive strip would cut the URL in half at the `//` and leave the file
    unparseable. Escapes are honoured so a `\"` inside a string does not end it.
    """
    out: list[str] = []
    index, length, in_string = 0, len(text), False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            while index < length and text[index] != "\n":
                index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            index += 2
            while index + 1 < length and not (text[index] == "*" and text[index + 1] == "/"):
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def drop_trailing_commas(text: str) -> str:
    """Remove a comma that closes an object or array. String-aware.

    TypeScript accepts trailing commas in tsconfig.json, so one is a legal edit
    in either repo -- and left in place it makes the strict parser raise, which
    aborts the scheduled job before it can update the standing issue. Failing
    loudly is right for a token problem; it is wrong for valid config.
    """
    out: list[str] = []
    index, length, in_string = 0, len(text), False
    while index < length:
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
        if char == ",":
            ahead = index + 1
            while ahead < length and text[ahead].isspace():
                ahead += 1
            if ahead < length and text[ahead] in "}]":
                index += 1  # drop it
                continue
        out.append(char)
        index += 1
    return "".join(out)


def read_doc(text: str | None, fmt: str, path: str, side: str):
    """Parse a config file. A file that will not parse is a loud failure.

    Not a silent None: that would read as "the key is absent", which is itself
    reported as drift -- so a malformed file would produce a confident finding
    about a value nobody can actually determine.
    """
    if text is None:
        return None
    try:
        if fmt == "yaml":
            return load_yaml(text)
        return json.loads(drop_trailing_commas(strip_jsonc(text)))
    except (yaml.YAMLError, json.JSONDecodeError) as error:
        raise SystemExit(f"::error::{side} {path}: cannot parse as {fmt}: {error}")


def show(value) -> str:
    if value is None:
        return "absent"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


class Sibling:
    """Reads files from the sibling repository over the GitHub API."""

    def __init__(self, repo: str, ref: str, token: str) -> None:
        self.repo, self.ref, self.token = repo, ref, token
        self._cache: dict[str, str | None] = {}

    def _get(self, url: str, path: str, accept: str | None = None) -> str | None:
        """GET with the retry policy. Returns None only on 404.

        Shared by the access probe and by read() so the two cannot drift apart:
        a weekly job that dies on one blip produces no report for a week, and
        the probe runs first, so leaving it un-retried made the retry in read()
        unreachable in exactly the case it was written for.
        """
        request = urllib.request.Request(url, headers=self._headers(accept))
        last_error = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None
                # A 5xx is transient and worth retrying; 401/403 will not fix
                # themselves in seconds, so fail now rather than three times.
                if error.code >= 500 and attempt < 2:
                    last_error = error
                    time.sleep(2 * (attempt + 1))
                    continue
                raise SystemExit(
                    f"::error::{self.repo}/{path}: HTTP {error.code} {error.reason}"
                )
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                last_error = error
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
        raise SystemExit(f"::error::{self.repo}/{path}: {last_error} (3 attempts)")

    def verify_access(self) -> None:
        """Fail loudly if the sibling is not readable with this token.

        GitHub returns 404, not 403, for a private repository the caller cannot
        see -- it will not confirm that the repo exists. Without this probe a
        token that is valid but lacks access to the sibling makes EVERY file
        return 404, every file reads as "absent there", and the run files a
        confident drift report saying the sibling is missing its entire
        infrastructure. That is worse than failing: it is a fabricated finding
        wearing the credibility of an automated check, and it breaks the one
        promise this workflow makes -- that it fails loudly rather than
        inventing convergence or divergence.

        Probing the repository once turns that whole class into a single clear
        error, and lets a per-file 404 keep its honest meaning: the file is
        genuinely absent, which is a real finding.
        """
        try:
            if self._get(f"https://api.github.com/repos/{self.repo}", "") is None:
                raise SystemExit("HTTP 404")
        except SystemExit as error:
            if "HTTP 404" in str(error):
                raise SystemExit(
                    f"::error::cannot read {self.repo}: HTTP 404 Not Found -- a "
                    "private repository returns 404 when the token cannot see "
                    "it, so this is far more likely a token-scope problem than "
                    f"a missing repository. The token needs Contents: Read on "
                    f"{self.repo}."
                )
            raise

    def resolve_ref(self) -> None:
        """Pin the run to one commit, and fail loudly if the ref is gone.

        The repository probe passes for an accessible sibling whose branch was
        renamed or deleted -- and then every file URL 404s, every file reads as
        absent, and the run files a fabricated mass-drift report claiming the
        sibling deleted its infrastructure. Exactly the failure the probe
        exists to prevent, one level down.

        Resolving to a SHA also pins the whole comparison to a single commit,
        so a merge landing mid-run cannot split the report across two trees.
        """
        # GitHub answers 404 for an unknown ref and 422 for one it considers
        # malformed; both mean the same thing here, and neither should surface
        # as a bare HTTP error when the cause is worth explaining.
        try:
            sha = self._get(
                f"https://api.github.com/repos/{self.repo}/commits/{self.ref}",
                f"@{self.ref}",
                accept="application/vnd.github.sha",
            )
        except SystemExit as error:
            if "HTTP 404" in str(error) or "HTTP 422" in str(error):
                sha = None
            else:
                raise
        if sha is None:
            raise SystemExit(
                f"::error::{self.repo} has no ref '{self.ref}'. It was renamed "
                "or deleted; without this check every file would read as absent "
                "and the run would report the sibling as having deleted its "
                "infrastructure."
            )
        self.ref = sha.strip()

    def _headers(self, accept: str | None = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": accept or "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nexcue-sibling-drift",
        }

    def read(self, path: str) -> str | None:
        if path in self._cache:
            return self._cache[path]
        url = f"https://api.github.com/repos/{self.repo}/contents/{path}?ref={self.ref}"
        # None here means a genuine 404: the file is absent, which is a real
        # finding. verify_access() has already ruled out the case where the
        # whole repository 404s because the token cannot see it.
        value = self._get(url, path)
        self._cache[path] = value
        return value


def read_local(path: str) -> str | None:
    """Read a local file WITHOUT translating line endings.

    Python's default universal-newline mode rewrites CRLF to LF on the way in,
    while the sibling arrives as raw bytes over HTTP. That asymmetry breaks the
    comparison in both directions: two matching CRLF files look different, and
    CRLF here against LF there looks identical -- hiding real drift. The
    normalisation happens at ingestion, so no amount of care further down can
    recover it.
    """
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return None


DIFF_LINES = 14


def unified(ours: str, theirs: str, path: str) -> str:
    """A compact unified diff, truncated. `-` is this repo, `+` is the sibling.

    Truncated because the report is a standing issue, not a code review: enough
    to see what changed and which way, without pasting a file into it.
    """
    # The headers say `here`/`there`, matching `detail` and the report's table
    # columns. They said `nexcue/` and `tabletap/`, which was wrong twice over.
    #
    # INVERTED: `fromfile` labels `ours`, so this repo's content printed under
    # the sibling's name and the sibling's under ours -- backwards from the
    # docstring above and from the `-`/`+` signs a reader actually trusts. The
    # report asks the reader to "decide which direction the fix travels", and
    # the labels sent them the wrong way.
    #
    # HARDCODED: every sibling runs this file byte-identically and compares
    # against several repos, so no pair of repo names can be right in it -- the
    # tarmoto section was labelled `nexcue/` too. Naming the repos is what
    # broke this; do not name them again. The section heading already says
    # which sibling a diff belongs to.
    lines = list(
        difflib.unified_diff(
            ours.splitlines(),
            theirs.splitlines(),
            fromfile=f"here/{path}",
            tofile=f"there/{path}",
            lineterm="",
            n=1,
        )
    )
    if len(lines) > DIFF_LINES:
        remaining = len(lines) - DIFF_LINES
        lines = lines[:DIFF_LINES] + [f"... {remaining} more line(s)"]
    return "\n".join(lines)


# The provenance header AGENTS.md requires on every ported file, in BOTH
# spellings it is written in. `# ported from Studio81Labs/<repo>@<sha>` covers
# shell, YAML, Python and TOML -- every file in IDENTICAL today. Markdown
# cannot use it: a line beginning `# ported from ...` renders as an <h1> in the
# middle of the document, so a ported .md carries the marker as an HTML comment
# instead, which is what tabletap's and tarmoto's AGENTS.md do. Recognising one
# spelling and not the other means the first Markdown entry added to IDENTICAL
# reports its own correct marker as drift -- the exact false positive this
# function exists to prevent, wearing the face of a real finding.
#
# strip_provenance matches this pattern only at byte zero, or immediately after
# a leading shebang. A provenance-shaped line later in the body is content and
# must remain visible to the byte comparison.
#
# The Markdown branch consumes the WHOLE comment, through its first `-->`, even
# when that lands on a later line. Line-based stripping was tried first and is
# wrong for the same reason the `#`-only pattern was: a marker one repo wrapped
# and the other did not leaves a continuation line on one side only, which
# reaches the byte comparison as drift the port did not cause. Normalising has
# to erase the whole marker or it has not normalised anything.
#
# `(?:(?!<!--).)*?` bounds that reach. Non-greedy alone stops at the first
# `-->`, but an UNCLOSED marker has no first `-->` and would run on to some
# unrelated comment's, swallowing every line in between -- silently, and as
# convergence. Refusing to cross another `<!--` caps the damage at malformed
# input reporting drift, which is the direction this file fails in everywhere
# else.
_PORTED_FROM = r"ported from Studio81Labs/[\w.-]+@[0-9a-fA-F]{7,40}"
PROVENANCE = re.compile(
    rf"(?:#\s*{_PORTED_FROM}[^\n]*|<!--\s*{_PORTED_FROM}(?:(?!<!--).)*?-->[^\S\n]*)\n",
    re.DOTALL,
)

EDITORCONFIG_DART_HEADER = re.compile(
    r"(?m)^\[\*\.dart\][ \t]*(?=\r(?:\n|$)|\n|$)"
)
EDITORCONFIG_TRAILING_DART_SECTION = re.compile(
    r"(?ms)(?:^[ \t]*(?:\r\n|\n|\r))?^\[\*\.dart\][ \t]*(?:\r\n|\n|\r)(?:(?!^\[).)*\Z"
)
EDITORCONFIG_DART_SECTION = re.compile(
    r"(?ms)^\[\*\.dart\][ \t]*(?:\r\n|\n|\r).*?(?=^\[|\Z)"
)


def strip_provenance(text: str) -> str:
    """Remove provenance headers before comparing two copies of a file.

    Both conventions are real and they collide: AGENTS.md requires a ported
    file to record where it came from, and this check requires the two copies
    to be byte-identical. A header carrying a sha satisfies the first and
    breaks the second by construction -- so the check would report the port it
    had just verified, every week, forever.

    Normalising here keeps both. The header stays in the file for the audit
    trail; the comparison ignores it, because a sha recording WHERE a copy came
    from is metadata about the copy, not part of the content being compared.
    """
    header_start = 0
    if text.startswith("#!"):
        newline = text.find("\n")
        if newline == -1:
            return text
        header_start = newline + 1
    match = PROVENANCE.match(text, header_start)
    if match is None:
        return text
    return text[:header_start] + text[match.end():]


def strip_editorconfig_dart_section(text: str) -> str:
    """Remove only the Dart section while retaining shared editor policy."""
    text = EDITORCONFIG_TRAILING_DART_SECTION.sub("", text)
    return EDITORCONFIG_DART_SECTION.sub("", text)


def line_endings(text: str) -> list[str]:
    """The ending of each line, in order: CRLF, LF, CR, or none (last line)."""
    out = []
    for line in text.splitlines(keepends=True):
        if line.endswith("\r\n"):
            out.append("CRLF")
        elif line.endswith("\n"):
            out.append("LF")
        elif line.endswith("\r"):
            out.append("CR")
        else:
            out.append("none")
    return out


def invisible_difference(ours: str, theirs: str) -> str | None:
    """Describe a difference a line diff cannot show, or None if it can.

    `splitlines()` normalises away line endings and the trailing newline -- the
    very things being compared when two files differ by nothing else. The diff
    then comes out EMPTY, leaving a finding that says the files differ and
    offers no evidence and no direction, which is worse than not reporting it.

    The full ending SEQUENCE is compared, not whether CRLF appears anywhere:
    two files can both contain CRLF and still use it on different lines, and a
    presence test calls that equal while the bytes differ.
    """
    if ours.splitlines() != theirs.splitlines():
        return None  # a normal diff can show it

    ours_endings, theirs_endings = line_endings(ours), line_endings(theirs)
    for number, (mine, yours) in enumerate(zip(ours_endings, theirs_endings), start=1):
        if mine == yours:
            continue
        if "none" in (mine, yours):
            return (
                "identical apart from the trailing newline: "
                f"{'absent' if mine == 'none' else 'present'} here, "
                f"{'absent' if yours == 'none' else 'present'} there"
            )
        return (
            f"identical apart from line endings, first differing at line {number}: "
            f"{mine} here, {yours} there"
        )

    # Nothing above explains it -- say so rather than render an empty diff.
    return f"identical by line, differing by bytes: {len(ours)} here, {len(theirs)} there"


def job_names(text: str | None, path: str, side: str):
    """Map job id -> display name for one workflow.

    Returns None when the file is absent or unreadable, which the caller
    reports rather than swallowing: a workflow that stops parsing silently
    drops every one of its jobs from the comparison, and "no differences"
    would then mean "nothing was compared".
    """
    if text is None:
        return None
    try:
        root = yaml.compose(text, Loader=Yaml12)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        return {"__error__": f"{side}: {exc.__class__.__name__}"}
    jobs = _map_get(root, "jobs")
    if not isinstance(jobs, yaml.MappingNode):
        return {"__error__": f"{side}: no jobs mapping"}
    names = {}
    for key, job in jobs.value:
        if not (isinstance(job, yaml.MappingNode) and job.value):
            continue
        # Parked behind a literal `if: false`, so it never renders in the
        # checks list at all. Comparing its name against the sibling's live one
        # invents drift -- the same reasoning statically_disabled() already
        # encodes for action pins, reused here rather than restated.
        if statically_disabled(job):
            continue
        name = _map_get(job, "name")
        # A job with no explicit `name:` renders under its id, so that is the
        # honest comparison value -- not None, which would read as "absent".
        names[key.value] = name.value if isinstance(name, yaml.ScalarNode) else key.value
    return names


def compare(local_read, sibling_read) -> list[dict]:
    """Return findings. Pure, so the self-test can drive it with stubs."""
    findings: list[dict] = []

    # Memoised per marker, not per entry: one marker gates several entries and
    # sibling reads go over the network.
    marker_state: dict[str, tuple[bool, bool]] = {}

    def marker_sides(marker: str) -> tuple[bool, bool]:
        if marker not in marker_state:
            paths = CAPABILITY_MARKER_PATHS.get(marker, (marker,))
            marker_state[marker] = (
                any(local_read(path) is not None for path in paths),
                any(sibling_read(path) is not None for path in paths),
            )
        return marker_state[marker]

    def marker_open(marker: str) -> bool:
        return all(marker_sides(marker))

    def action_shapes_comparable(path: str) -> bool:
        """Whether one-sided actions represent drift rather than topology."""
        stack_marker = STACK_TOPOLOGY_GATED.get(path)
        return stack_marker is None or len(set(marker_sides(stack_marker))) == 1

    def topology_skips_artifact(
        path: str,
        ours,
        theirs,
        gates=TOPOLOGY_GATED,
        stack_gates=STACK_TOPOLOGY_GATED,
    ) -> bool:
        """Whether topology explains why this artifact should not be compared.

        Markers describe why a capability-owned artifact may be absent; they
        do not disable comparison of an artifact that both repositories still
        carry. Keeping that distinction here prevents an incidental marker
        deletion from making real content, action-pin, or job-name drift quiet.
        A missing stack manifest is different: it says at least one side does
        not implement the Flutter-owned artifact whose whole-file contents or
        job layout is being compared.
        """
        stack_marker = stack_gates.get(path)
        if stack_marker is not None:
            stack_sides = marker_sides(stack_marker)
            cross_stack_owned = False
            if path in CROSS_STACK_REQUIRED:
                capability_marker = gates.get(path)
                capability_sides = (
                    marker_sides(capability_marker)
                    if capability_marker is not None
                    else (False, False)
                )
                if all(capability_sides):
                    # Both repositories own this mobile guard. Its absence is
                    # drift even across stacks; when both copies exist, only
                    # their stack-specific contents may be skipped.
                    if ours is None or theirs is None:
                        return False
                    if stack_sides[0] != stack_sides[1]:
                        return True
                    cross_stack_owned = True
                elif any(capability_sides):
                    # Against a non-mobile repository, require the sole owner
                    # to retain its guard without requiring a counterpart.
                    owned = ours if capability_sides[0] else theirs
                    nonowned = theirs if capability_sides[0] else ours
                    return owned is not None and nonowned is None
            if not cross_stack_owned and not any(stack_sides):
                # Neither repository implements this stack. Its owned helper
                # may legitimately be absent even when both repos have a
                # broader mobile surface (for example, two React Native apps).
                return True
            if stack_sides[0] != stack_sides[1]:
                # Across implementations, contents are not comparable, but
                # the owning side must still retain its artifact. Checking
                # that first prevents deleting the Flutter copy from looking
                # like an expected Flutter/non-Flutter difference.
                owned = ours if stack_sides[0] else theirs
                return owned is not None

        marker = gates.get(path)
        if marker is None:
            return False
        sides = marker_sides(marker)
        if all(sides):
            return False
        if not any(sides):
            # With no owner on either side, absence is expected and a
            # one-sided leftover does not make the capability shared.
            return ours is None or theirs is None

        # Exactly one repository owns the capability. Topology explains the
        # artifact's absence only when the owner still has its copy. Without
        # this ownership check, deleting the owner's file made two absences
        # compare as topology and silently removed the protection.
        owned = ours if sides[0] else theirs
        return owned is not None and (ours is None or theirs is None)

    def validate_local_topology_jobs(
        path: str,
        names: dict[str, str] | None,
        side_index: int,
        side: str,
    ) -> set[str]:
        """Validate repository-local job ownership before pair-level skips."""
        handled: set[str] = set()
        if names is None or "__error__" in names:
            return handled
        for (owned_path, job_id), (
            marker,
            owned_when_marked,
            expected_name,
        ) in EXPECTED_TOPOLOGY_OWNED_JOBS.items():
            if owned_path != path:
                continue
            owns_job = marker_sides(marker)[side_index] == owned_when_marked
            actual_name = names.get(job_id)
            if owns_job and actual_name is None:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": f"topology expects job `{job_id}` {side}, but it is absent",
                    }
                )
            elif owns_job and actual_name != expected_name:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": f"job `{job_id}` {side}: expected `{expected_name}`, found `{actual_name}`",
                    }
                )
            elif not owns_job and actual_name is not None:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": f"topology expects no job `{job_id}` {side}, found `{actual_name}`",
                    }
                )
            handled.add(job_id)
        for (variant_path, job_id), variants in EXPECTED_TOPOLOGY_JOB_NAME_VARIANTS.items():
            if variant_path != path:
                continue
            expected_name = next(
                (
                    name
                    for marker, name in variants
                    if marker_sides(marker)[side_index]
                ),
                None,
            )
            actual_name = names.get(job_id)
            if expected_name is None and actual_name is not None:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": f"topology expects no job `{job_id}` {side}, found `{actual_name}`",
                    }
                )
            elif expected_name is not None and actual_name is None:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": f"topology expects job `{job_id}` {side}, but it is absent",
                    }
                )
            elif expected_name is not None and actual_name != expected_name:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": f"job `{job_id}` {side}: expected `{expected_name}`, found `{actual_name}`",
                    }
                )
            handled.add(job_id)
        return handled

    invalid_topology_paths: set[str] = set()
    for path, capability_marker in TOPOLOGY_GATED.items():
        ours, theirs = local_read(path), sibling_read(path)
        owner_marker = (
            STACK_TOPOLOGY_GATED[path]
            if path in STACK_TOPOLOGY_GATED and path not in CROSS_STACK_REQUIRED
            else capability_marker
        )
        capability_sides = marker_sides(owner_marker)
        missing_owner = (
            capability_sides[0] and ours is None,
            capability_sides[1] and theirs is None,
        )
        unexpected_nonowner = (
            not capability_sides[0] and ours is not None,
            not capability_sides[1] and theirs is not None,
        )
        if not any(missing_owner) and not any(unexpected_nonowner):
            continue
        topology = "mobile topology" if path in CROSS_STACK_REQUIRED else "topology"
        for invalid, detail in (
            (missing_owner, f"{topology} expects an artifact {{side}}, but it is absent"),
            (
                unexpected_nonowner,
                f"{topology} expects no artifact {{side}} without its owning capability",
            ),
        ):
            if not any(invalid):
                continue
            side = "here and there" if all(invalid) else "here" if invalid[0] else "there"
            findings.append(
                {
                    "kind": "workflow" if path.startswith(".github/") else "file",
                    "name": path,
                    "detail": detail.format(side=side),
                }
            )
        invalid_topology_paths.add(path)

    for path in IDENTICAL:
        if path in invalid_topology_paths:
            continue
        ours, theirs = local_read(path), sibling_read(path)
        if topology_skips_artifact(path, ours, theirs):
            continue
        # Absent from BOTH is not agreement. `None == None` used to fall
        # through the equality check below and report nothing, so a renamed or
        # deleted file left an entry here that could never fail again -- the
        # manifest would keep listing a guard that had silently stopped
        # guarding. Same failure mode as an override that matches nothing,
        # and ACTION_WORKFLOWS already reports its own version of it.
        if ours is None and theirs is None:
            findings.append(
                {"kind": "file", "name": path, "detail": "in neither repo — stale entry in IDENTICAL"}
            )
            continue
        if ours is not None and theirs is not None:
            ours, theirs = strip_provenance(ours), strip_provenance(theirs)
            if path == ".editorconfig":
                flutter_sides = marker_sides("apps/mobile/pubspec.yaml")
                has_dart = (
                    bool(EDITORCONFIG_DART_HEADER.search(ours)),
                    bool(EDITORCONFIG_DART_HEADER.search(theirs)),
                )
                missing_dart = (
                    flutter_sides[0] and not has_dart[0],
                    flutter_sides[1] and not has_dart[1],
                )
                if any(missing_dart):
                    side = (
                        "here and there"
                        if all(missing_dart)
                        else "here"
                        if missing_dart[0]
                        else "there"
                    )
                    findings.append(
                        {
                            "kind": "file",
                            "name": path,
                            "detail": f"Flutter topology expects a [*.dart] section {side}, but it is absent",
                        }
                    )
                invalid_dart = (
                    not flutter_sides[0] and has_dart[0],
                    not flutter_sides[1] and has_dart[1],
                )
                if any(invalid_dart):
                    side = (
                        "here and there"
                        if all(invalid_dart)
                        else "here"
                        if invalid_dart[0]
                        else "there"
                    )
                    findings.append(
                        {
                            "kind": "file",
                            "name": path,
                            "detail": f"contains a [*.dart] section {side} without a Flutter app",
                        }
                    )
                if not all(flutter_sides) or any(missing_dart):
                    ours = strip_editorconfig_dart_section(ours)
                    theirs = strip_editorconfig_dart_section(theirs)
        if ours == theirs:
            continue
        if ours is None or theirs is None:
            detail = "present here, absent there" if theirs is None else "absent here, present there"
            findings.append({"kind": "file", "name": path, "detail": detail})
            continue
        # A line count is not evidence. `.nvmrc` going from one Node version to
        # another is "1 lines here, 1 there" -- it names neither the values nor
        # the direction, so the standing issue cannot say what to port without
        # someone repeating the comparison by hand. These files are on the
        # noise-free list precisely so their diff is worth printing.
        hidden = invisible_difference(ours, theirs)
        findings.append(
            {
                "kind": "file",
                "name": path,
                "detail": hidden
                or f"{len(ours.splitlines())} lines here, {len(theirs.splitlines())} there",
                "diff": "" if hidden else unified(ours, theirs, path),
            }
        )

    parsed: dict[tuple[str, str], object] = {}
    for path, label, fmt, getter in KEYS:
        # Parsed once per file, not once per key.
        for side, read in (("here", local_read), ("there", sibling_read)):
            if (path, side) not in parsed:
                parsed[(path, side)] = read_doc(read(path), fmt, path, side)
        ours = getter(parsed[(path, "here")])
        theirs = getter(parsed[(path, "there")])
        if ours == theirs:
            continue
        findings.append(
            {
                "kind": "key",
                "name": f"{path} — {label}",
                "detail": f"`{show(ours)}` here, `{show(theirs)}` there",
            }
        )

    # Keyed by (workflow, action), NOT by action alone. Collapsing to the first
    # occurrence hides a stale pin in a later file: `actions/checkout` appears
    # in most of these workflows, so if the first pair agreed, a drifted pin in
    # mobile-release.yml was discarded and the run reported no action drift at
    # all. Both repos happen to be internally consistent today, which is exactly
    # why that bug would have gone unnoticed until it mattered.
    ours_pins: dict[tuple[str, str], dict[str, str]] = {}
    theirs_pins: dict[tuple[str, str], dict[str, str]] = {}
    for path in ACTION_WORKFLOWS:
        local_text, sibling_text = local_read(path), sibling_read(path)
        # Entry ownership is a repository-local invariant, so validate it
        # before a whole-workflow topology gate can skip the pair. Otherwise,
        # an owner deleting its required action went quiet whenever the other
        # repository legitimately lacked the entire workflow.
        our_job_actions = job_actions(local_text, path) if local_text else set()
        their_job_actions = job_actions(sibling_text, path) if sibling_text else set()
        for (entry_path, job_id, action), (
            marker,
            owned_when_marked,
        ) in ACTION_ENTRY_TOPOLOGY_GATED.items():
            if entry_path != path:
                continue
            our_marker, their_marker = marker_sides(marker)
            for actions, has_marker, side in (
                (our_job_actions, our_marker, "here"),
                (their_job_actions, their_marker, "there"),
            ):
                owns_action = has_marker == owned_when_marked
                has_owned_action = (job_id, action) in actions
                has_action_anywhere = any(
                    found_action == action for _, found_action in actions
                )
                if owns_action and not has_owned_action:
                    findings.append(
                        {
                            "kind": "action",
                            "name": f"{action} — {path.rsplit('/', 1)[-1]}",
                            "detail": f"topology expects the action in job `{job_id}` {side}, but it is absent",
                        }
                    )
                elif not owns_action and has_action_anywhere:
                    findings.append(
                        {
                            "kind": "action",
                            "name": f"{action} — {path.rsplit('/', 1)[-1]}",
                            "detail": f"topology expects no action anywhere {side}, but it is present",
                        }
                    )
        if path in invalid_topology_paths:
            continue
        if topology_skips_artifact(
            path, local_text, sibling_text, ACTION_TOPOLOGY_GATED, {}
        ):
            continue
        # The manifest DEFINES these as workflows both repos have, so a missing
        # one is a finding in its own right -- and silently skipping it is worse
        # than missing a pin: every action in that file becomes one-sided, the
        # intersection discards them all as topology, and losing a whole shared
        # workflow could REDUCE the count to zero and close the standing issue.
        # A check reporting convergence because a file vanished is the exact
        # inversion of its purpose.
        name = path.rsplit("/", 1)[-1]
        our_file_pins = parse_pins(local_text, path) if local_text else {}
        their_file_pins = parse_pins(sibling_text, path) if sibling_text else {}
        our_unparsed = unparsed_uses(local_text, path) if local_text else []
        their_unparsed = unparsed_uses(sibling_text, path) if sibling_text else []
        # PRESENCE is `is None`, never truthiness. An empty file is present,
        # and conflating the two reversed the reported direction: an empty
        # sibling copy read as "absent here, present there", sending the reader
        # to fix the wrong repo.
        here, there = local_text is not None, sibling_text is not None
        if here != there:
            findings.append(
                {
                    "kind": "workflow",
                    "name": name,
                    "detail": "present here, absent there"
                    if here
                    else "absent here, present there",
                }
            )
        elif here and there and is_blank(local_text) != is_blank(sibling_text):
            # Blank on exactly ONE side. Not an absence, and not something the
            # pin comparison can see -- an empty workflow yields no pins and
            # would otherwise pass as agreement.
            #
            # Blank on BOTH is agreement and reports nothing. The earlier
            # condition fired there too and printed a direction that was simply
            # false, which would have held a standing issue open over two
            # identical files.
            findings.append(
                {
                    "kind": "workflow",
                    "name": name,
                    "detail": "no runnable jobs here, present there"
                    if is_blank(local_text)
                    else "present here, no runnable jobs there",
                }
            )
        elif (
            here
            and there
            and bool(our_file_pins) != bool(their_file_pins)
            # ...unless the empty side's pins are empty BECAUSE something there
            # did not parse. The unparsed report below names that value exactly;
            # adding a generic "pins nothing" beside it is two findings for one
            # cause, which inflates the count and dilutes a report whose only
            # value is being worth reading.
            and not (our_unparsed if their_file_pins else their_unparsed)
        ):
            # A manifest workflow that pins NOTHING on one side. Every pin on
            # the other side is then one-sided, and the intersection below
            # discards them all as topology -- so the whole comparison for this
            # file goes silent and the run reports convergence over a workflow
            # that has been gutted.
            #
            # Keyed on the pin set rather than on why it is empty. Asking "does
            # this workflow run" took three rounds of review and kept admitting
            # one more shape (`{}`, comments only, `jobs:`, empty steps); this
            # asks the question the comparison actually depends on, so a cause
            # nobody enumerated -- a job renamed out, an action replaced by an
            # inline `run:` -- lands here anyway (#768).
            findings.append(
                {
                    "kind": "workflow",
                    "name": name,
                    "detail": f"pins {len(our_file_pins)} action(s) here, none there"
                    if their_file_pins == {}
                    else f"pins nothing here, {len(their_file_pins)} action(s) there",
                }
            )
        elif not here and not there:
            # Gone from both: not drift, but a manifest entry that matches
            # nothing, which is how a comparison list quietly stops comparing.
            findings.append(
                {
                    "kind": "workflow",
                    "name": name,
                    "detail": "in neither repo — stale entry in ACTION_WORKFLOWS",
                }
            )
        # In a shared workflow owned by both repositories, adding or replacing
        # an action on only one side is drift too. A broad capability gate
        # excuses this only while ownership is asymmetric, and a stack gate
        # only across different implementations; merely listing a workflow in
        # ACTION_TOPOLOGY_GATED must not silence drift between two owners. Keep
        # the existing pins-nothing finding singular when one whole set is
        # empty; this closes the quieter case where both sides still share at
        # least one other action and a set intersection would discard the new
        # action.
        poker_topology_actions: set[str] = set()
        if (
            here
            and there
            and our_file_pins
            and their_file_pins
            and path in POKER_ACTION_LAYOUTS
        ):
            python_sides = marker_sides("apps/backend/pyproject.toml")
            if python_sides[0] != python_sides[1]:
                layouts = POKER_ACTION_LAYOUTS[path]
                poker_topology_actions = set(layouts["python"]) | set(layouts["node"])
                for action in sorted(poker_topology_actions):
                    expected = (
                        action in layouts["python" if python_sides[0] else "node"],
                        action in layouts["python" if python_sides[1] else "node"],
                    )
                    actual = (action in our_file_pins, action in their_file_pins)
                    if actual == expected:
                        continue
                    expected_side = "here" if expected[0] else "there"
                    actual_side = (
                        "here and there"
                        if all(actual)
                        else "here"
                        if actual[0]
                        else "there"
                        if actual[1]
                        else "nowhere"
                    )
                    findings.append(
                        {
                            "kind": "action",
                            "name": f"{action} — {name}",
                            "detail": (
                                f"topology expects the action {expected_side} only, "
                                f"but it is present {actual_side}"
                            ),
                        }
                    )
        if (
            here
            and there
            and our_file_pins
            and their_file_pins
            and action_shapes_comparable(path)
        ):
            for action in sorted(set(our_file_pins) ^ set(their_file_pins)):
                if action in poker_topology_actions:
                    continue
                # Capability-owned entries were asserted above, including
                # ownership polarity and owner-side deletion. Do not add a
                # second generic one-sided finding for the same violation.
                if any(
                    entry_path == path and entry_action == action
                    for entry_path, _, entry_action in ACTION_ENTRY_TOPOLOGY_GATED
                ):
                    continue
                refs = our_file_pins.get(action) or their_file_pins[action]
                described = " + ".join(
                    sorted(f"{label} ({ref})" for ref, label in refs.items())
                )
                is_here = action in our_file_pins
                findings.append(
                    {
                        "kind": "action",
                        "name": f"{action} — {name}",
                        "detail": f"`{described}` here, absent there"
                        if is_here
                        else f"absent here, `{described}` there",
                    }
                )
        for values, side in ((our_unparsed, "here"), (their_unparsed, "there")):
            for value in values:
                findings.append(
                    {
                        "kind": "unparsed",
                        "name": f"{name} ({side})",
                        "detail": f"`{value}` — not recognised as a pinned action, "
                        "so it was NOT compared",
                    }
                )
        for action, refs in our_file_pins.items():
            ours_pins[(path, action)] = refs
        for action, refs in their_file_pins.items():
            theirs_pins[(path, action)] = refs

    # Compare ref versions for action names BOTH repositories have. One-sided
    # actions in topology-independent workflows were reported above; capability
    # workflows retain this intersection because their implementations differ.
    #
    # Collapsed by (action, our_ref, their_ref): one action drifting identically
    # across eight workflows is ONE fact, and eight rows saying so is the same
    # noise problem from the other direction. The workflows are listed instead.
    shared_keys = sorted(set(ours_pins) & set(theirs_pins))
    # How many workflows use this action in BOTH repos, drifted or not. Drift in
    # every one of them is uniform and needs no file list; drift in only some is
    # the anomaly, and naming those files is the whole point of comparing per
    # workflow rather than per action.
    usage: dict[str, int] = {}
    for _, action in shared_keys:
        usage[action] = usage.get(action, 0) + 1

    grouped: dict[tuple[str, str, str], list[str]] = {}
    labels: dict[tuple[str, str, str], tuple[str, str]] = {}
    for key in shared_keys:
        path, action = key
        our_refs, their_refs = ours_pins[key], theirs_pins[key]
        # Compare the SET of refs the file uses. A workflow pinning one action
        # at two refs is itself worth surfacing, and set comparison catches it
        # without treating a reordered step as drift.
        if set(our_refs) == set(their_refs):
            continue
        group = (action, tuple(sorted(our_refs)), tuple(sorted(their_refs)))
        grouped.setdefault(group, []).append(path.rsplit("/", 1)[-1])
        labels[group] = (our_refs, their_refs)

    for group, paths in grouped.items():
        action = group[0]
        our_refs, their_refs = labels[group]
        # Sorted by LABEL: sorting by ref would order `v6.0.0 + v7.0.1` by an
        # opaque SHA and read as arbitrary.
        our_label = " + ".join(sorted(our_refs.values()))
        their_label = " + ".join(sorted(their_refs.values()))
        # Labels must IDENTIFY the refs, not merely differ from each other.
        # Two SHAs can carry the same coarse annotation, and there are two ways
        # that hides the answer: the rendered sides come out equal (`v8` here,
        # `v8` there), or one side collapses two distinct SHAs into a repeated
        # label (`v8 + v8` versus `v8`) -- which differs as a string while
        # still naming neither pin. Disambiguate whenever the labels within
        # either set are not unique, or the two sides render identically.
        # A label must identify its ref, on each side AND across the two.
        # Three ways it can fail to: the sides render identically; a label
        # repeats within one side; or the SAME label appears on both sides
        # against different refs -- `v1 + v2` here against `v1 + v3` there,
        # where each `v1` is a different SHA. The last one makes `v1` look
        # shared when it is precisely what differs, and none of the earlier
        # conditions can see it.
        def by_label(refs):
            grouped: dict[str, set[str]] = {}
            for ref, label in refs.items():
                grouped.setdefault(label, set()).add(ref)
            return grouped

        ours_by_label, theirs_by_label = by_label(our_refs), by_label(their_refs)
        ambiguous = (
            our_label == their_label
            or len(set(our_refs.values())) != len(our_refs)
            or len(set(their_refs.values())) != len(their_refs)
            or any(
                label in theirs_by_label and ours_by_label[label] != theirs_by_label[label]
                for label in ours_by_label
            )
        )
        if ambiguous:
            # FULL refs, not abbreviated. Two unannotated refs can share their
            # first seven characters -- `release-2026-a` and `release-2026-b`
            # both label as `release` -- and appending the same truncation
            # again renders `release (release)` on both sides, disambiguating
            # nothing. This branch is rare; verbosity here is the cheap half of
            # the trade.
            our_label = f"{our_label} ({'/'.join(sorted(our_refs))})"
            their_label = f"{their_label} ({'/'.join(sorted(their_refs))})"
        where = "" if len(paths) == usage[action] else f" — {', '.join(paths)}"
        findings.append(
            {
                "kind": "action",
                "name": f"{action}{where}",
                "detail": f"`{our_label}` here, `{their_label}` there",
            }
        )

    for path in JOB_NAME_WORKFLOWS:
        local_text, sibling_text = local_read(path), sibling_read(path)
        ours = job_names(local_text, path, "here")
        theirs = job_names(sibling_text, path, "there")
        broken = (ours or {}).get("__error__") or (theirs or {}).get("__error__")
        if broken:
            findings.append(
                {"kind": "jobname", "name": path, "detail": f"could not read jobs — {broken}"}
            )
            continue
        handled_topology_jobs = validate_local_topology_jobs(path, ours, 0, "here")
        handled_topology_jobs.update(
            validate_local_topology_jobs(path, theirs, 1, "there")
        )
        poker_pair = marker_sides("apps/backend/pyproject.toml")[0] != marker_sides(
            "apps/backend/pyproject.toml"
        )[1]
        if poker_pair and path in POKER_JOB_LAYOUTS:
            python_sides = marker_sides("apps/backend/pyproject.toml")
            layouts = POKER_JOB_LAYOUTS[path]
            controlled_jobs = set(layouts["python"]) | set(layouts["node"])
            if path == ".github/workflows/backend-ci.yml":
                database_pair = EXPECTED_TOPOLOGY_JOB_PAIRS[
                    (path, "apps/backend/src/data-source.ts")
                ]
                controlled_jobs.update((database_pair[0][0], database_pair[1][0]))
            for names, is_python, side_index, side in (
                (ours, python_sides[0], 0, "here"),
                (theirs, python_sides[1], 1, "there"),
            ):
                if names is None:
                    continue
                expected = dict(layouts["python" if is_python else "node"])
                if path == ".github/workflows/backend-ci.yml" and not is_python:
                    database_marker = marker_sides("apps/backend/src/data-source.ts")
                    marked, unmarked = EXPECTED_TOPOLOGY_JOB_PAIRS[
                        (path, "apps/backend/src/data-source.ts")
                    ]
                    job_id, expected_name = marked if database_marker[side_index] else unmarked
                    expected[job_id] = expected_name
                for job_id in sorted(controlled_jobs):
                    actual_name = names.get(job_id)
                    expected_name = expected.get(job_id)
                    if expected_name is None and actual_name is not None:
                        findings.append(
                            {
                                "kind": "jobname",
                                "name": path,
                                "detail": f"topology expects no job `{job_id}` {side}, found `{actual_name}`",
                            }
                        )
                    elif expected_name is not None and actual_name is None:
                        findings.append(
                            {
                                "kind": "jobname",
                                "name": path,
                                "detail": f"topology expects job `{job_id}` {side}, but it is absent",
                            }
                        )
                    elif expected_name is not None and actual_name != expected_name:
                        findings.append(
                            {
                                "kind": "jobname",
                                "name": path,
                                "detail": f"job `{job_id}` {side}: expected `{expected_name}`, found `{actual_name}`",
                            }
                        )
            handled_topology_jobs.update(controlled_jobs)
        if path in invalid_topology_paths:
            continue
        if topology_skips_artifact(path, local_text, sibling_text):
            continue
        # A workflow the manifest names but a repo does not have is itself the
        # finding, for the same reason ACTION_WORKFLOWS reports it: silently
        # skipping shrinks the comparison and a smaller comparison looks like
        # convergence.
        if ours is None or theirs is None:
            if ours is None and theirs is None:
                findings.append(
                    {
                        "kind": "jobname",
                        "name": path,
                        "detail": "in neither repo — stale entry in JOB_NAME_WORKFLOWS",
                    }
                )
            else:
                missing = "absent here, present there" if ours is None else "present here, absent there"
                findings.append({"kind": "jobname", "name": path, "detail": missing})
            continue
        for (pair_path, marker), (marked, unmarked) in EXPECTED_TOPOLOGY_JOB_PAIRS.items():
            if pair_path != path:
                continue
            if poker_pair and pair_path == ".github/workflows/backend-ci.yml":
                continue
            our_marked, their_marked = marker_sides(marker)
            if our_marked == their_marked:
                continue
            for names, is_marked, side in (
                (ours, our_marked, "here"),
                (theirs, their_marked, "there"),
            ):
                job_id, expected_name = marked if is_marked else unmarked
                actual_name = names.get(job_id)
                if actual_name is None:
                    findings.append(
                        {
                            "kind": "jobname",
                            "name": path,
                            "detail": f"backend topology expects job `{job_id}` {side}, but it is absent",
                        }
                    )
                elif actual_name != expected_name:
                    findings.append(
                        {
                            "kind": "jobname",
                            "name": path,
                            "detail": f"job `{job_id}` {side}: expected `{expected_name}`, found `{actual_name}`",
                        }
                    )
            marked_id, unmarked_id = marked[0], unmarked[0]
            for job_id, expected_here in (
                (marked_id, our_marked),
                (unmarked_id, not our_marked),
            ):
                if (
                    (job_id in ours) == expected_here
                    and (job_id in theirs) != expected_here
                ):
                    handled_topology_jobs.add(job_id)
        for job in sorted(set(ours) | set(theirs)):
            our_name, their_name = ours.get(job), theirs.get(job)
            if job in handled_topology_jobs:
                continue
            if our_name == their_name:
                continue
            if (path, job) in EXPECTED_JOB_DIFFS:
                marker = EXPECTED_JOB_DIFF_MARKERS.get((path, job))
                if (
                    marker is not None
                    and marker_sides(marker)[0] != marker_sides(marker)[1]
                    and our_name is not None
                    and their_name is not None
                    and frozenset((our_name, their_name))
                    == EXPECTED_PRESENT_JOB_NAME_PAIRS.get((path, job))
                ):
                    continue
            if our_name is None or their_name is None:
                side = "present here, absent there" if their_name is None else "absent here, present there"
                detail = f"job `{job}` {side}"
            else:
                detail = f"job `{job}`: `{our_name}` here, `{their_name}` there"
            findings.append({"kind": "jobname", "name": path, "detail": detail})

    return findings


HEADINGS = {
    "file": "Files that should be identical",
    "jobname": "Job names in shared workflows",
    "workflow": "Shared workflows",
    "unparsed": "Action references that could not be compared",
    "key": "Shared configuration values",
    "action": "GitHub Action pins",
}


def render(findings: list[dict]) -> str:
    lines = [
        f"Automated comparison of shared infrastructure against "
        f"[`{SIBLING}`](https://github.com/{SIBLING}) (`{SIBLING_REF}`).",
        "",
        "**This reports that two things differ, not that either repo is wrong.**",
        "Nexcue is the default baseline for shared infrastructure. The valid",
        "exceptions are capability topology or a linked back-port; infrastructure",
        "can still move in either direction. Read each row before choosing.",
        "",
        f"{len(findings)} difference(s).",
        "",
    ]
    for kind in ("file", "jobname", "workflow", "unparsed", "key", "action"):
        rows = [f for f in findings if f["kind"] == kind]
        if not rows:
            continue
        lines += [f"### {HEADINGS[kind]}", ""]
        if kind == "file":
            # A diff does not fit in a table cell, and these are the findings
            # where the content IS the information.
            for row in rows:
                lines += [f"**`{row['name']}`** — {row['detail']}", ""]
                if row.get("diff"):
                    lines += ["```diff", row["diff"], "```", ""]
            continue
        lines += ["| what | here vs there |", "| --- | --- |"]
        lines += [f"| `{row['name']}` | {row['detail']} |" for row in rows]
        lines.append("")
    lines += [
        "---",
        "",
        "Raised by `.github/workflows/sibling-drift.yml`. The comparison list and",
        "the reasons for every deliberate omission are in",
        "`scripts/ci/check-sibling-drift.py`. Re-running updates this issue in",
        "place rather than opening another.",
    ]
    return "\n".join(lines)


def self_test() -> int:
    def wf(*values):
        """A realistic workflow: `uses:` lives in a step list, not a bare key.

        It matters now that pins are parsed rather than grepped -- two bare
        `uses:` keys in one mapping is a YAML duplicate key, so the earlier
        fixtures silently collapsed to the last one and could not express "the
        same action twice in one file" at all.
        """
        lines = ["jobs:", "  build:", "    steps:"]
        lines += [f"      - uses: {value}" for value in values]
        return "\n".join(lines) + "\n"

    def repo(**overrides):
        """A stub repository that HAS every manifest workflow.

        Without this the fixtures were unrealistic in a way that mattered: a
        stub missing most of ACTION_WORKFLOWS looks like a repo that deleted
        them, so the stale-manifest check fired on every baseline. Tests should
        describe a plausible repo and then vary one thing.

        The workflow bodies carry a `jobs:` mapping because JOB_NAMES parses
        them. A bare comment is not a plausible workflow -- it has no jobs, so
        every baseline would report "could not read jobs" and the fixtures
        would be testing the error path instead of the quiet one.
        """
        files = {path: "jobs:\n  build:\n    name: \"ci: build\"\n" for path in ACTION_WORKFLOWS}
        files.update({
            path: "jobs:\n  build:\n    name: \"ci: build\"\n"
            for path in JOB_NAME_WORKFLOWS
            if path not in files
        })
        # ...and every IDENTICAL entry, for the same reason. These used to be
        # absent from both stubs and stayed quiet on None == None -- the very
        # hole the stale-entry check closes, which would otherwise fire on
        # every baseline.
        files.update({path: "stub\n" for path in IDENTICAL if path not in files})
        # Established siblings declare both broad capabilities compared by the
        # action-pin manifest. Individual tests can remove a marker explicitly
        # to model a deliberately smaller sibling.
        broad_markers = set(ACTION_TOPOLOGY_GATED.values()) - set(
            STACK_TOPOLOGY_GATED.values()
        )
        for marker in broad_markers:
            paths = CAPABILITY_MARKER_PATHS.get(marker, (marker,))
            files.setdefault(paths[0], "marker\n")
        files.update(
            {
                "packages/core/package.json": "{}\n",
                ".github/workflows/admin-ci.yml": (
                    "jobs:\n"
                    "  build:\n"
                    "    name: \"ci: build\"\n"
                    "    steps:\n"
                    "      - uses: actions/download-artifact@1111111 # v1\n"
                    "      - uses: actions/upload-artifact@1111111 # v1\n"
                    "  prepare-openapi:\n    name: \"contract: openapi spec\"\n"
                ),
                ".github/workflows/backend-deploy.yml": (
                    "jobs:\n"
                    "  build:\n    name: \"ci: build\"\n"
                    "  version-gate:\n    name: \"release: version gate\"\n"
                ),
                ".github/workflows/admin-deploy.yml": (
                    "jobs:\n"
                    "  build:\n    name: \"ci: build\"\n"
                    "  resolve:\n    name: \"admin: resolve environment\"\n"
                ),
                ".github/workflows/packages-ci.yml": (
                    "jobs:\n"
                    "  build:\n"
                    "    name: \"packages: build & test\"\n"
                ),
            }
        )
        files.update(overrides)
        # Keep the default fixture internally valid: a repository without the
        # Flutter stack marker does not carry Flutter-only artifacts. Explicit
        # overrides are preserved so tests can still model a stale non-owner
        # copy deliberately.
        if files.get("apps/mobile/pubspec.yaml") is None:
            for path in set(STACK_TOPOLOGY_GATED) - CROSS_STACK_REQUIRED:
                if path not in overrides:
                    files[path] = None
        return {k: v for k, v in files.items() if v is not None}

    ours = {
        ".nvmrc": "22\n",
        ".editorconfig": "root = true\n[*.py]\nindent_size = 4\n",
        "pnpm-workspace.yaml": "minimumReleaseAge: 1440\ntrustPolicy: no-downgrade\n",
        "tsconfig.base.json": '{ "strict": true, "noImplicitOverride": true }',
        ".github/workflows/labeler.yml": wf("actions/labeler@aaaaaaa # v7.0.0"),
        ".github/workflows/lint-pr.yml": wf("actions/checkout@bbbbbbb # v7.0.1"),
    }
    theirs = dict(ours)

    assert compare(repo(**ours).get, repo(**theirs).get) == [], "identical inputs must be quiet"

    # A differing file.
    theirs[".editorconfig"] = "root = true\n"
    found = compare(repo(**ours).get, repo(**theirs).get)
    assert [f["name"] for f in found] == [".editorconfig"], found

    common_editorconfig = "root = true\n[*.py]\nindent_size = 4\n"
    flutter_editorconfig = "root = true\n[*.dart]\nindent_size = 2\n\n[*.py]\nindent_size = 4\n"
    flutter_editor = {
        ".editorconfig": flutter_editorconfig,
        "apps/mobile/pubspec.yaml": "name: mobile\n",
    }
    plain_editor = {".editorconfig": common_editorconfig}
    found = [
        f for f in compare(repo(**flutter_editor).get, repo(**plain_editor).get)
        if f["name"] == ".editorconfig"
    ]
    assert found == [], f"Dart-only editor policy is stack topology: {found}"
    trailing_flutter_editor = {
        ".editorconfig": common_editorconfig + "\n[*.dart]\nindent_size = 2\n",
        "apps/mobile/pubspec.yaml": "name: mobile\n",
    }
    found = [
        f
        for f in compare(repo(**trailing_flutter_editor).get, repo(**plain_editor).get)
        if f["name"] == ".editorconfig"
    ]
    assert found == [], f"a trailing Dart section must not leave its separator behind: {found}"
    missing_flutter_editor = {
        ".editorconfig": common_editorconfig,
        "apps/mobile/pubspec.yaml": "name: mobile\n",
    }
    found = [
        f
        for f in compare(repo(**missing_flutter_editor).get, repo(**plain_editor).get)
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "expects a [*.dart] section here" in found[0]["detail"], found
    found = [
        f
        for f in compare(
            repo(**missing_flutter_editor).get,
            repo(**missing_flutter_editor).get,
        )
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "here and there" in found[0]["detail"], found
    found = [
        f
        for f in compare(repo(**flutter_editor).get, repo(**missing_flutter_editor).get)
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "expects a [*.dart] section there" in found[0]["detail"], found
    invalid_plain_editor = {".editorconfig": flutter_editorconfig}
    found = [
        f for f in compare(repo(**invalid_plain_editor).get, repo(**plain_editor).get)
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "without a Flutter app" in found[0]["detail"], found
    crlf_common_editorconfig = common_editorconfig.replace("\n", "\r\n")
    crlf_invalid_plain_editor = {
        ".editorconfig": (
            "root = true\r\n[*.dart]\r\nindent_size = 2\r\n\r\n"
            "[*.py]\r\nindent_size = 4\r\n"
        )
    }
    crlf_plain_editor = {".editorconfig": crlf_common_editorconfig}
    found = [
        f
        for f in compare(
            repo(**crlf_invalid_plain_editor).get,
            repo(**crlf_plain_editor).get,
        )
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "without a Flutter app" in found[0]["detail"], found
    found = [
        f
        for f in compare(
            repo(**invalid_plain_editor).get,
            repo(**invalid_plain_editor).get,
        )
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "here and there" in found[0]["detail"], found
    differing_invalid_plain_editor = {
        ".editorconfig": flutter_editorconfig.replace("indent_size = 2", "indent_size = 4")
    }
    found = [
        f
        for f in compare(
            repo(**invalid_plain_editor).get,
            repo(**differing_invalid_plain_editor).get,
        )
        if f["name"] == ".editorconfig"
    ]
    assert len(found) == 1 and "here and there" in found[0]["detail"], found

    # A file absent on the sibling. `None` rather than `del`: repo() seeds
    # every manifest path, so deleting the key only gets it seeded back with
    # the stub body -- which reads as a CONTENT difference, not an absence,
    # and quietly stopped testing what this case is named for.
    theirs = dict(ours)
    theirs[".nvmrc"] = None
    found = compare(repo(**ours).get, repo(**theirs).get)
    assert found[0]["detail"] == "present here, absent there", found

    # A key that differs, and one absent entirely.
    theirs = dict(ours)
    theirs["pnpm-workspace.yaml"] = "minimumReleaseAge: 10080\n"
    found = compare(repo(**ours).get, repo(**theirs).get)
    names = [f["name"] for f in found]
    assert "pnpm-workspace.yaml — minimumReleaseAge" in names, names
    assert "pnpm-workspace.yaml — trustPolicy" in names, names
    assert "`no-downgrade` here, `absent` there" in [f["detail"] for f in found], found

    # JSONC: a commented-out historical value BEFORE the live one. A regex
    # over the raw text reads the comment and either invents drift or, if both
    # sides' comments agree while the live values differ, hides a real
    # strictness regression.
    live_true = {"tsconfig.base.json":
                 '{ // "strict": false,\n  "compilerOptions": { "strict": true } }'}
    live_false = {"tsconfig.base.json":
                  '{ // "strict": false,\n  "compilerOptions": { "strict": false } }'}
    found = [f for f in compare(repo(**live_true).get, repo(**live_true).get) if f["kind"] == "key"]
    assert found == [], f"agreeing live values must be quiet, got {found}"
    found = [f for f in compare(repo(**live_true).get, repo(**live_false).get) if f["kind"] == "key"]
    assert any("strict" in f["name"] for f in found), found
    assert any(f["detail"] == "`true` here, `false` there" for f in found), found

    # Differences a line diff cannot show. splitlines() normalises exactly
    # these, so the diff came out empty and the finding carried no evidence.
    lf = {".nvmrc": "24\n"}
    crlf = {".nvmrc": "24\r\n"}
    found = [f for f in compare(repo(**lf).get, repo(**crlf).get) if f["kind"] == "file"]
    assert len(found) == 1, found
    assert found[0]["detail"] == (
        "identical apart from line endings, first differing at line 1: LF here, CRLF there"
    ), found
    assert found[0]["diff"] == "", found
    assert "```diff" not in render(found), render(found)

    no_eol = {".nvmrc": "24"}
    found = [f for f in compare(repo(**lf).get, repo(**no_eol).get) if f["kind"] == "file"]
    assert found[0]["detail"] == (
        "identical apart from the trailing newline: present here, absent there"
    ), found

    # MIXED layouts: both files contain CRLF, on different lines. A presence
    # test calls that equal and falls through to a byte count that names
    # neither the line nor the direction.
    mixed_a = {".nvmrc": "a\r\nb\n"}
    mixed_b = {".nvmrc": "a\nb\r\n"}
    found = [f for f in compare(repo(**mixed_a).get, repo(**mixed_b).get) if f["kind"] == "file"]
    assert len(found) == 1, found
    assert found[0]["detail"] == (
        "identical apart from line endings, first differing at line 1: CRLF here, LF there"
    ), found

    # A real content difference still gets a real diff.
    found = [f for f in compare(repo(**lf).get, repo(**{".nvmrc": "22\n"}).get) if f["kind"] == "file"]
    assert found[0]["detail"] == "1 lines here, 1 there", found
    assert "-24" in found[0]["diff"] and "+22" in found[0]["diff"], found

    # ...and the HEADER agrees with the signs. Asserting `-24`/`+22` alone
    # passed happily while the labels named the wrong side, so a reader who
    # trusted the filenames over the signs ported every fix backwards.
    assert "--- here/.nvmrc" in found[0]["diff"], found
    assert "+++ there/.nvmrc" in found[0]["diff"], found
    # No repo name belongs in a file every sibling runs byte-identically.
    assert "nexcue/" not in found[0]["diff"], found
    assert "tabletap/" not in found[0]["diff"], found

    # A provenance header must not, by itself, count as drift. AGENTS.md
    # requires ported files to carry one; identity requires them not to differ.
    # Normalising keeps both, where dropping the header discards the source
    # revision a future audit needs.
    ported = {".nvmrc": "# ported from Studio81Labs/tabletap@9db05645\n24\n"}
    plain = {".nvmrc": "24\n"}
    found = [f for f in compare(repo(**ported).get, repo(**plain).get) if f["kind"] == "file"]
    assert found == [], f"a provenance header alone is not drift: {found}"

    # ...both sides carrying one, with DIFFERENT shas, is still not drift.
    other = {".nvmrc": "# ported from Studio81Labs/nexcue@e204d2fc\n24\n"}
    found = [f for f in compare(repo(**ported).get, repo(**other).get) if f["kind"] == "file"]
    assert found == [], found

    # ...but an ORDINARY comment is content, not metadata. Normalising every
    # comment line would hide real drift in a file whose whole purpose is
    # documentation, which is what `resolve-flutter.sh` mostly is.
    documented = {".nvmrc": "# explains what this pins\n24\n"}
    undocumented = {".nvmrc": "24\n"}
    found = [f for f in compare(repo(**documented).get, repo(**undocumented).get)
             if f["kind"] == "file"]
    assert len(found) == 1, f"a normal comment difference IS drift: {found}"

    # ...and a line merely mentioning the phrase is not a header either.
    mentions = {".nvmrc": "# see: ported from Studio81Labs/tabletap@9db05645\n24\n"}
    found = [f for f in compare(repo(**mentions).get, repo(**undocumented).get)
             if f["kind"] == "file"]
    assert len(found) == 1, found

    # ...and the Markdown spelling of the same header is stripped too. A line
    # beginning `# ported from ...` renders as an <h1> in the middle of the
    # document, so ported Markdown carries the marker as an HTML comment
    # instead -- a form the `#`-anchored pattern could not see. Asserted on the
    # function rather than through compare() because no .md file is in
    # IDENTICAL yet; the first one added would otherwise report its own correct
    # marker as drift, which looks exactly like a real finding.
    md_header = "<!-- ported from Studio81Labs/nexcue@e204d2fc -->\n"
    assert strip_provenance(md_header + "# Title\n") == "# Title\n"

    # ...carrying a trailing note, which the `#` form already allows.
    noted = "<!-- ported from Studio81Labs/nexcue@e204d2fc (delegation section) -->\n"
    assert strip_provenance(noted + "# Title\n") == "# Title\n"

    # ...while a line merely MENTIONING the phrase is content in either
    # spelling, and so is an ordinary HTML comment.
    mention_md = "<!-- see: ported from Studio81Labs/nexcue@e204d2fc -->\n"
    assert strip_provenance(mention_md) == mention_md
    ordinary_md = "<!-- explains what this pins -->\n"
    assert strip_provenance(ordinary_md) == ordinary_md

    # ...and a marker whose comment WRAPS is removed whole, closing line
    # included. Stripping only the opener line leaves a continuation behind on
    # one side, so a marker one repo wrapped and the other did not reports as
    # drift -- the same false positive in a new shape, which is why this
    # asserts the mixed pair normalises to the identical text.
    body = "# Title\n\nSame in both repos.\n"
    wrapped = "<!-- ported from Studio81Labs/nexcue@e204d2fc\n     delegation only -->\n"
    one_line = "<!-- ported from Studio81Labs/tabletap@9db05645 -->\n"
    assert strip_provenance(wrapped + body) == body
    assert strip_provenance(wrapped + body) == strip_provenance(one_line + body)

    # ...but an UNCLOSED marker must not reach for some later comment's `-->`
    # and swallow the document in between. Reported as drift, not normalised
    # into agreement: malformed input is the one case where a false positive
    # beats a false negative, because the negative is silent.
    unclosed = (
        "<!-- ported from Studio81Labs/nexcue@e204d2fc\n"
        "real content that must survive\n"
        "<!-- an unrelated comment -->\n"
    )
    assert strip_provenance(unclosed) == unclosed

    # ...and the reach stops at the marker's OWN `-->`, not at the last one in
    # the file. A greedy match runs to a later line that merely ends in `-->`
    # and takes every line before it along, which hides drift rather than
    # reporting it -- the silent direction, and the one no report can show you.
    arrow = md_header + "# Title\n\nThe arrow points -->\n"
    assert strip_provenance(arrow) == "# Title\n\nThe arrow points -->\n"

    # ...and the `#` spelling still strips, which is the one every IDENTICAL
    # entry uses today.
    assert strip_provenance("# ported from Studio81Labs/nexcue@e204d2fc\n24\n") == "24\n"

    # A leading shebang is part of the executable, not an obstacle to the
    # header. Provenance-shaped lines anywhere else are ordinary body content.
    shebang = "#!/usr/bin/env bash\n# ported from Studio81Labs/nexcue@e204d2fc\nset -e\n"
    assert strip_provenance(shebang) == "#!/usr/bin/env bash\nset -e\n"
    body_marker = "first\n# ported from Studio81Labs/nexcue@e204d2fc\nlast\n"
    assert strip_provenance(body_marker) == body_marker
    body_html_marker = "first\n" + md_header + "last\n"
    assert strip_provenance(body_html_marker) == body_html_marker

    # ...but real content differences are still reported through the header.
    changed = {".nvmrc": "# ported from Studio81Labs/tabletap@9db05645\n22\n"}
    found = [f for f in compare(repo(**ported).get, repo(**changed).get) if f["kind"] == "file"]
    assert len(found) == 1, found

    # A URL inside a string must survive comment stripping -- `//` in
    # `https://` is not a comment, and cutting it leaves the file unparseable.
    url = {"renovate.json":
           '{"$schema": "https://docs.renovatebot.com/renovate-schema.json",'
           ' "extends": ["github>Studio81Labs/.github:renovate-base"]}'}
    found = [f for f in compare(repo(**url).get, repo(**url).get) if f["kind"] == "key"]
    assert found == [], found
    no_preset = {"renovate.json": '{"extends": ["config:recommended"]}'}
    found = [f for f in compare(repo(**url).get, repo(**no_preset).get) if f["kind"] == "key"]
    assert any("shared preset" in f["name"] for f in found), found

    # YAML 1.1 legacy booleans. pnpm accepts `trustPolicy: off`, and unquoted
    # it parses as False under PyYAML while the quoted spelling parses as
    # "off" -- so a formatting-only difference fabricates supply-chain drift.
    assert load_yaml("trustPolicy: off")["trustPolicy"] == "off"
    assert load_yaml('trustPolicy: "off"')["trustPolicy"] == "off"
    assert load_yaml("a: true")["a"] is True, "true/false must stay boolean"
    assert load_yaml("a: no")["a"] == "no"

    # YAML 1.1 numbers are not only about booleans. `01440` is octal 800,
    # `1_440` is 1440 and `12:00` is sexagesimal 720 under PyYAML -- so a
    # harmless respelling of the supply-chain gate fabricated drift on the one
    # value here most worth trusting. The constructor re-parses too, so
    # replacing the resolver alone left `01440` arriving as 800.
    assert load_yaml("a: 01440")["a"] == 1440
    assert load_yaml("a: 0o1440")["a"] == 800
    assert load_yaml("a: 0x10")["a"] == 16
    assert load_yaml("a: -5")["a"] == -5
    assert load_yaml("a: 1_440")["a"] == "1_440"
    assert load_yaml("a: 12:00")["a"] == "12:00"
    # 1.2 floats too: PyYAML's 1.1 grammar needs a decimal point and a signed
    # exponent, so `1e3` was a STRING while any 1.2 reader makes it 1000.
    assert load_yaml("a: 1e3")["a"] == 1000.0
    assert load_yaml("a: -1e-3")["a"] == -0.001
    assert load_yaml("a: .5")["a"] == 0.5
    assert load_yaml("a: .inf")["a"] == float("inf")
    assert load_yaml("a: 1.2.3")["a"] == "1.2.3", "a version string is not a float"
    exponent = {"pnpm-workspace.yaml": "minimumReleaseAge: 1e3\n"}
    thousand = {"pnpm-workspace.yaml": "minimumReleaseAge: 1000\n"}
    found = [f for f in compare(repo(**exponent).get, repo(**thousand).get) if f["kind"] == "key"]
    assert found == [], f"1e3 and 1000 are the same number: {found}"

    padded = {"pnpm-workspace.yaml": "minimumReleaseAge: 01440\n"}
    plain = {"pnpm-workspace.yaml": "minimumReleaseAge: 1440\n"}
    found = [f for f in compare(repo(**padded).get, repo(**plain).get) if f["kind"] == "key"]
    assert found == [], f"a respelt number is not drift: {found}"
    bare = {"pnpm-workspace.yaml": "trustPolicy: off\n"}
    quoted_off = {"pnpm-workspace.yaml": 'trustPolicy: "off"\n'}
    found = [f for f in compare(repo(**bare).get, repo(**quoted_off).get) if f["kind"] == "key"]
    assert found == [], f"quoting must not read as drift: {found}"

    # Trailing commas are valid JSONC and TypeScript accepts them, so one is a
    # legal edit in either repo. Left unhandled it aborts the whole run.
    trailing = {"tsconfig.base.json":
                '{\n  "compilerOptions": {\n    "strict": true,\n  },\n}'}
    plain_ts = {"tsconfig.base.json": '{"compilerOptions": {"strict": true}}'}
    found = [f for f in compare(repo(**trailing).get, repo(**plain_ts).get) if f["kind"] == "key"]
    assert found == [], f"a trailing comma must parse, not abort: {found}"

    # ...but a comma inside a STRING is not a trailing comma. Asserted on the
    # function directly: routing it through compare() passed even against a
    # naive regex, because the corruption changes a value without breaking the
    # parse -- a test that cannot fail is not a test.
    assert json.loads(drop_trailing_commas('{"a": "x,]", "b": 1,}')) == {"a": "x,]", "b": 1}
    assert json.loads(drop_trailing_commas('{"a": "y,}"}')) == {"a": "y,}"}
    assert json.loads(strip_jsonc('{"u": "https://x/y", "b": 1}')) == {"u": "https://x/y", "b": 1}

    # An input legitimately named `uses` under `with:` is NOT an executed
    # action; treating it as one invents pin drift out of a deliberate input.
    with_input = {".github/workflows/backend-ci.yml":
                  "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@aaaaaaa # v7\n"
                  "        with:\n          uses: some/other@bbbbbbb\n"}
    other = {".github/workflows/backend-ci.yml":
             "jobs:\n  build:\n    steps:\n      - uses: actions/checkout@aaaaaaa # v7\n"
             "        with:\n          uses: different/thing@ccccccc\n"}
    found = compare(repo(**with_input).get, repo(**other).get)
    assert found == [], f"a `with:` input named uses must not be compared, got {found}"

    # Two actions sharing a tag ref. Keyed by ref alone, the second comment
    # overwrote the first and the report attributed y's version to x --
    # wrong evidence, which points at the wrong pin and possibly the wrong repo.
    shared_tag = {".github/workflows/backend-ci.yml":
                  wf("actions/x@v1 # v1.0", "actions/y@v1 # v1.9")}
    moved = {".github/workflows/backend-ci.yml":
             wf("actions/x@v2 # v2.0", "actions/y@v1 # v1.9")}
    found = [f for f in compare(repo(**shared_tag).get, repo(**moved).get)
             if f["kind"] == "action" and f["name"].startswith("actions/x")]
    assert len(found) == 1, found
    assert found[0]["detail"] == "`v1.0` here, `v2.0` there", found

    # A commented-out or embedded `uses:` for the SAME action@ref, annotated
    # differently. The refs compare correctly either way; the danger is the
    # LABEL being taken from the non-executable line, so the report shows a
    # version that is not the one running.
    live_lbl = ".github/workflows/backend-ci.yml"
    honest = {live_lbl: wf("actions/x@aaaaaaa # v1.0")}
    decoyed = {
        live_lbl: wf("actions/x@aaaaaaa # v1.0")
        + "      # - uses: actions/x@aaaaaaa # v9.9\n"
        + '      - run: "echo uses: actions/x@aaaaaaa # v9.9"\n'
    }
    other_side = {live_lbl: wf("actions/x@bbbbbbb # v2.0")}
    found = [f for f in compare(repo(**decoyed).get, repo(**other_side).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "`v1.0` here, `v2.0` there", found
    assert compare(repo(**honest).get, repo(**decoyed).get) == [], "decoys are not drift"

    # One side pins two distinct SHAs under the SAME coarse label while the
    # sibling pins one. The rendered sides differ (`v8 + v8` vs `v8`), so an
    # equality test appends nothing and the report names neither pin.
    dup = {".github/workflows/backend-ci.yml":
           wf("actions/x@1111111 # v8", "actions/x@2222222 # v8")}
    one = {".github/workflows/backend-ci.yml": wf("actions/x@1111111 # v8")}
    found = [f for f in compare(repo(**dup).get, repo(**one).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert "1111111" in found[0]["detail"] and "2222222" in found[0]["detail"], found

    # A stale action pin.
    theirs = dict(ours)
    theirs[".github/workflows/labeler.yml"] = wf("actions/labeler@ccccccc # v6.1.0")
    found = compare(repo(**ours).get, repo(**theirs).get)
    assert [f["name"] for f in found] == ["actions/labeler"], found
    assert found[0]["detail"] == "`v7.0.0` here, `v6.1.0` there", found

    # The SAME pin annotated at a different precision is NOT drift. Both repos
    # digest-pin but comment differently -- `# v8.0.1` here, `# v8` there for
    # one SHA. Comparing the comment reported five differences that did not
    # exist; this is the regression pin for that.
    theirs = dict(ours)
    theirs[".github/workflows/labeler.yml"] = wf("actions/labeler@aaaaaaa # v7")
    assert compare(repo(**ours).get, repo(**theirs).get) == [], "same SHA, coarser comment, must be quiet"

    # An action only ONE repo uses in a topology-independent workflow is drift.
    theirs = dict(ours)
    theirs[".github/workflows/lint-pr.yml"] = (
        wf("actions/checkout@bbbbbbb # v7.0.1", "pwa-only/action@ddddddd # v1")
    )
    found = [f for f in compare(repo(**ours).get, repo(**theirs).get) if f["kind"] == "action"]
    assert len(found) == 1 and found[0]["name"].startswith("pwa-only/action"), found

    # A pin with no version comment still participates, by SHA.
    theirs = dict(ours)
    theirs[".github/workflows/labeler.yml"] = wf("actions/labeler@eeeeeee")
    found = compare(repo(**ours).get, repo(**theirs).get)
    assert found[0]["detail"] == "`v7.0.0` here, `eeeeeee` there", found

    # A stale pin in a LATER workflow, where an earlier one agrees. Keying by
    # action alone discarded this and reported no action drift at all.
    both = {
        ".github/workflows/backend-ci.yml": wf("actions/checkout@aaaaaaa # v7.0.1"),
        ".github/workflows/mobile-release.yml": wf("actions/checkout@aaaaaaa # v7.0.1"),
    }
    stale = dict(both)
    stale[".github/workflows/mobile-release.yml"] = wf("actions/checkout@fffffff # v6.0.0")
    found = compare(repo(**both).get, repo(**stale).get)
    assert len(found) == 1, found
    assert found[0]["name"] == "actions/checkout — mobile-release.yml", found
    assert "backend-ci.yml" not in found[0]["name"], found

    # The same action drifting identically across several workflows is ONE
    # fact; reporting it once per file is noise from the other direction.
    stale = {k: wf("actions/checkout@fffffff # v6.0.0") for k in both}
    found = compare(repo(**both).get, repo(**stale).get)
    assert len(found) == 1, found
    # Uniform across every workflow that uses it -- no file list to add.
    assert found[0]["name"] == "actions/checkout", found

    # A stale pin in a LATER JOB of the same workflow, where the first
    # occurrence agrees. These workflows use one action up to four times, so
    # keeping only the first occurrence per file hid this.
    same = {".github/workflows/mobile-ci.yml":
            wf("actions/checkout@aaaaaaa # v7.0.1", "actions/checkout@aaaaaaa # v7.0.1")}
    later = {".github/workflows/mobile-ci.yml":
             wf("actions/checkout@aaaaaaa # v7.0.1", "actions/checkout@fffffff # v6.0.0")}
    found = compare(repo(**same).get, repo(**later).get)
    assert len(found) == 1, found
    assert found[0]["detail"] == "`v7.0.1` here, `v6.0.0 + v7.0.1` there", found

    # A reordered step is not drift -- the refs are compared as a set.
    a = {".github/workflows/mobile-ci.yml":
         wf("actions/checkout@aaaaaaa # v7", "actions/x@bbbbbbb # v1")}
    b = {".github/workflows/mobile-ci.yml":
         wf("actions/x@bbbbbbb # v1", "actions/checkout@aaaaaaa # v7")}
    assert compare(repo(**a).get, repo(**b).get) == [], "reordering must not report"

    # A shared workflow deleted or renamed on one side. Skipping it made every
    # action in the file one-sided, so the loss produced no finding at all and
    # could even lower the count enough to close the standing issue.
    only_here = {".github/workflows/format-check.yml": wf("actions/checkout@aaaaaaa # v7")}
    found = [
        f
        for f in compare(repo(**only_here).get, repo(**{k: None for k in ACTION_WORKFLOWS}).get)
        if f["kind"] == "workflow" and f["name"] == "format-check.yml"
    ]
    assert len(found) == 1, found
    assert found[0]["detail"] == "present here, absent there", found
    found = [
        f
        for f in compare(repo(**{k: None for k in ACTION_WORKFLOWS}).get, repo(**only_here).get)
        if f["kind"] == "workflow" and f["name"] == "format-check.yml"
    ]
    assert found[0]["detail"] == "absent here, present there", found

    # An EMPTY sibling copy is present, not absent. Truthiness conflated the
    # two and reversed the direction, sending the reader to fix the wrong repo.
    mobile_only_here = {
        ".github/workflows/mobile-release.yml": wf("actions/checkout@aaaaaaa # v7")
    }
    only_here = mobile_only_here
    empty_there = dict.fromkeys(ACTION_WORKFLOWS, "")
    empty_there[".github/workflows/mobile-release.yml"] = ""
    found = [f for f in compare(repo(**mobile_only_here).get, repo(**empty_there).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "present here, no runnable jobs there", found

    # ...and the reverse.
    found = [f for f in compare(repo(**empty_there).get, repo(**mobile_only_here).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert found[0]["detail"] == "no runnable jobs here, present there", found

    # A manifest workflow that RUNS but pins nothing, while the sibling pins
    # something. Every one of the sibling's pins is then one-sided and
    # discarded, so the comparison for that file went completely silent (#768).
    # All three shapes below reported nothing before this check, including the
    # `run:` one -- which is the valid, likely shape, and the one the fix
    # proposed in review would have left silent.
    for gutted in (
        "jobs:\n  a:\n    steps:\n      - run: make\n",   # valid, and likely
        "jobs:\n  a:\n    steps:\n      - {}\n",
        "jobs:\n  a:\n    steps:\n      - name: nothing\n",
    ):
        no_pins = dict(only_here)
        no_pins[".github/workflows/mobile-release.yml"] = gutted
        found = [f for f in compare(repo(**only_here).get, repo(**no_pins).get)
                 if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
        assert len(found) == 1, (gutted, found)
        assert found[0]["detail"] == "pins 1 action(s) here, none there", (gutted, found)

    # ...and the reverse direction.
    found = [f for f in compare(repo(**{".github/workflows/mobile-release.yml":
                                        "jobs:\n  a:\n    steps:\n      - run: make\n"}).get,
                                repo(**only_here).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert found[0]["detail"] == "pins nothing here, 1 action(s) there", found

    # An unparsed `uses:` is why THAT side has no pins, and the unparsed report
    # names the value exactly. A generic "pins nothing" beside it is two
    # findings for one cause.
    unpinned = dict(only_here)
    unpinned[".github/workflows/mobile-release.yml"] = (
        "jobs:\n  a:\n    steps:\n      - uses: actions/checkout\n"
    )
    found = [f for f in compare(repo(**only_here).get, repo(**unpinned).get)
             if f["name"].startswith("mobile-release.yml")]
    assert len(found) == 1, found
    assert found[0]["kind"] == "unparsed", found

    # ...but a side with NO pins and NO unparsed values is still reported: the
    # suppression must not swallow the plain case it sits next to.
    plainly_empty = dict(only_here)
    plainly_empty[".github/workflows/mobile-release.yml"] = (
        "jobs:\n  a:\n    steps:\n      - run: make\n"
    )
    found = [f for f in compare(repo(**only_here).get, repo(**plainly_empty).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "pins 1 action(s) here, none there", found

    # ...and an unparsed value on the side that DOES have pins must not
    # suppress the other side's genuine emptiness.
    ours_messy = dict.fromkeys(ACTION_WORKFLOWS, "# workflow\n")
    ours_messy[".github/workflows/mobile-release.yml"] = (
        "jobs:\n  a:\n    steps:\n"
        "      - uses: actions/x@1111111 # v1\n"
        "      - uses: actions/broken\n"
    )
    found = [f for f in compare(repo(**ours_messy).get, repo(**plainly_empty).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found

    # A workflow that uses no actions in BOTH repos is agreement, not drift --
    # this is the noise case that would fire every week if got wrong.
    neither = dict.fromkeys(ACTION_WORKFLOWS, "jobs:\n  a:\n    steps:\n      - run: make\n")
    neither["apps/mobile/pubspec.yaml"] = "name: app\n"
    found = [f for f in compare(repo(**neither).get, repo(**neither).get) if f["kind"] == "workflow"]
    assert found == [], found

    # A gutted file is reported ONCE, as no-runnable-jobs, not also as
    # pins-nothing -- the two conditions overlap and would double-report.
    dead = dict(only_here)
    dead[".github/workflows/mobile-release.yml"] = "# disabled\n"
    found = [f for f in compare(repo(**only_here).get, repo(**dead).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "present here, no runnable jobs there", found

    # Blank on BOTH sides is agreement, not drift -- and certainly not a
    # direction. The earlier condition reported "empty here, has content
    # there" for two identical empty files.
    blank = dict.fromkeys(ACTION_WORKFLOWS, "   \n")
    blank["apps/mobile/pubspec.yaml"] = "name: app\n"
    found = [f for f in compare(repo(**blank).get, repo(**blank).get) if f["kind"] == "workflow"]
    assert found == [], f"two blank files agree: {found}"

    # A workflow reduced to COMMENTS is semantically empty: it composes to
    # nothing and contributes no pins, so the other side's pins become
    # one-sided and are discarded as topology -- the loss produced no finding
    # at all. `strip()` alone cannot see this.
    commented_out = dict(only_here)
    commented_out[".github/workflows/mobile-release.yml"] = "# disabled temporarily\n"
    found = [f for f in compare(repo(**only_here).get, repo(**commented_out).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "present here, no runnable jobs there", found

    # A workflow with no runnable jobs. `{}` and `jobs: {}` both compose to a
    # mapping, so a document-exists test cannot see them -- yet they pin
    # nothing, which makes the other side's pins one-sided and discarded.
    for gutted in ("{}\n", "name: disabled\njobs: {}\n", "# disabled temporarily\n"):
        dead = dict(only_here)
        dead[".github/workflows/mobile-release.yml"] = gutted
        found = [f for f in compare(repo(**only_here).get, repo(**dead).get)
                 if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
        assert len(found) == 1, (gutted, found)
        assert found[0]["detail"] == "present here, no runnable jobs there", (gutted, found)

    # `jobs:` with no value, and a sequence-valued jobs. Both compose to
    # something that is not a mapping, so enumerating empty shapes missed them.
    for gutted in ("name: disabled\njobs:\n", "jobs: null\n", "jobs: []\n"):
        dead = dict(only_here)
        dead[".github/workflows/mobile-release.yml"] = gutted
        found = [f for f in compare(repo(**only_here).get, repo(**dead).get)
                 if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
        assert len(found) == 1, (gutted, found)
        assert found[0]["detail"] == "present here, no runnable jobs there", (gutted, found)

    # A non-empty jobs mapping can still hold nothing runnable.
    for hollow in ("jobs:\n  build:\n", "jobs:\n  build: {}\n"):
        dead = dict(only_here)
        dead[".github/workflows/mobile-release.yml"] = hollow
        found = [f for f in compare(repo(**only_here).get, repo(**dead).get)
                 if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
        assert len(found) == 1, (hollow, found)
        assert found[0]["detail"] == "present here, no runnable jobs there", (hollow, found)

    # EVERY job disabled: runnable by a fields-only test, but contributing no
    # pins -- so the active side's pins become one-sided and are discarded.
    all_off = dict(only_here)
    all_off[".github/workflows/mobile-release.yml"] = (
        "jobs:\n  a:\n    if: false\n    steps:\n      - uses: actions/x@1111111 # v1\n"
        "  b:\n    if: false\n    steps:\n      - uses: actions/y@2222222 # v2\n"
    )
    found = [f for f in compare(repo(**only_here).get, repo(**all_off).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "present here, no runnable jobs there", found

    # An ENABLED job whose every STEP is disabled does no work either. The
    # previous predicate looked one level up and called it runnable while
    # uses_entries discarded all of it -- the same disagreement, one level in.
    steps_off = dict(only_here)
    steps_off[".github/workflows/mobile-release.yml"] = (
        "jobs:\n  a:\n    steps:\n"
        "      - if: false\n        uses: actions/x@1111111 # v1\n"
        "      - if: false\n        uses: actions/y@2222222 # v2\n"
    )
    found = [f for f in compare(repo(**only_here).get, repo(**steps_off).get)
             if f["kind"] == "workflow" and f["name"] == "mobile-release.yml"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "present here, no runnable jobs there", found

    # Every falsy constant disables, not just the word `false`.
    for falsy in ("0", "-0", "+0", "0.0", "-0.0", "0e0", "0x0", "0X0", "-0x0",
                  "null", "''", '""'):
        off = {".github/workflows/backend-ci.yml":
               "jobs:\n  build:\n    steps:\n"
               "      - uses: actions/x@2222222 # v2\n"
               f"      - if: ${{{{ {falsy} }}}}\n        uses: actions/x@1111111 # v1\n"}
        on = {".github/workflows/backend-ci.yml": wf("actions/x@2222222 # v2")}
        assert compare(repo(**off).get, repo(**on).get) == [], f"{falsy} must disable"

    # ...but a non-zero number is TRUTHY and must not disable anything.
    for truthy in ("1", "-1", "0.5", "true", "0x1", "-0x1"):
        on_step = {".github/workflows/backend-ci.yml":
                   "jobs:\n  build:\n    steps:\n"
                   f"      - if: ${{{{ {truthy} }}}}\n        uses: actions/x@1111111 # v1\n"}
        other = {".github/workflows/backend-ci.yml": wf("actions/x@2222222 # v2")}
        found = [f for f in compare(repo(**on_step).get, repo(**other).get) if f["kind"] == "action"]
        assert len(found) == 1, (truthy, found)

    # ...but ONE enabled job among disabled ones still runs.
    one_on = dict.fromkeys(
        ACTION_WORKFLOWS,
        "jobs:\n  a:\n    if: false\n    steps:\n      - run: make\n"
        "  b:\n    steps:\n      - run: make\n",
    )
    one_on["apps/mobile/pubspec.yaml"] = "name: app\n"
    found = [f for f in compare(repo(**one_on).get, repo(**one_on).get) if f["kind"] == "workflow"]
    assert found == [], found

    # ...but ONE runnable job among empty ones still runs.
    mixed_jobs = dict.fromkeys(
        ACTION_WORKFLOWS, "jobs:\n  empty:\n  real:\n    steps:\n      - run: make\n"
    )
    mixed_jobs["apps/mobile/pubspec.yaml"] = "name: app\n"
    found = [f for f in compare(repo(**mixed_jobs).get, repo(**mixed_jobs).get)
             if f["kind"] == "workflow"]
    assert found == [], found

    # ...but a workflow whose jobs only `run:` things still RUNS. It pins
    # nothing, and reporting that would be noise.
    runs_only = dict.fromkeys(ACTION_WORKFLOWS, "jobs:\n  build:\n    steps:\n      - run: make\n")
    runs_only["apps/mobile/pubspec.yaml"] = "name: app\n"
    found = [f for f in compare(repo(**runs_only).get, repo(**runs_only).get) if f["kind"] == "workflow"]
    assert found == [], found

    # An inline comment that is not a version must not become the label.
    prose = {".github/workflows/backend-ci.yml": wf("actions/x@aaaaaaa # keep pinned manually")}
    versioned = {".github/workflows/backend-ci.yml": wf("actions/x@bbbbbbb # v2")}
    found = [f for f in compare(repo(**prose).get, repo(**versioned).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "`aaaaaaa` here, `v2` there", found
    zizmor = {".github/workflows/backend-ci.yml":
              wf("actions/x@aaaaaaa # zizmor: ignore[unpinned-uses]")}
    found = [f for f in compare(repo(**zizmor).get, repo(**versioned).get) if f["kind"] == "action"]
    assert found[0]["detail"] == "`aaaaaaa` here, `v2` there", found

    # The SAME label on both sides against DIFFERENT refs. Each side's labels
    # are internally unique and the two rendered strings differ, so no earlier
    # condition fires -- yet `v1` is exactly what differs, and the report would
    # make it look shared.
    cross_a = {".github/workflows/backend-ci.yml":
               wf("actions/x@1111111 # v1", "actions/x@2222222 # v2")}
    cross_b = {".github/workflows/backend-ci.yml":
               wf("actions/x@9999999 # v1", "actions/x@3333333 # v3")}
    found = [f for f in compare(repo(**cross_a).get, repo(**cross_b).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert "1111111" in found[0]["detail"] and "9999999" in found[0]["detail"], found

    # ...but the same label against the SAME ref on both sides is genuinely
    # shared and must not trigger the verbose rendering.
    same_a = {".github/workflows/backend-ci.yml":
              wf("actions/x@1111111 # v1", "actions/x@2222222 # v2")}
    same_b = {".github/workflows/backend-ci.yml":
              wf("actions/x@1111111 # v1", "actions/x@3333333 # v3")}
    found = [f for f in compare(repo(**same_a).get, repo(**same_b).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert found[0]["detail"] == "`v1 + v2` here, `v1 + v3` there", found

    # Owner/repo casing. GitHub resolves both to one action; keyed by the raw
    # spelling they became two one-sided entries and BOTH were discarded, so a
    # simultaneous ref change was reported as nothing at all.
    upper = {".github/workflows/backend-ci.yml": wf("Actions/Checkout@1111111 # v1")}
    lower = {".github/workflows/backend-ci.yml": wf("actions/checkout@2222222 # v2")}
    found = [f for f in compare(repo(**upper).get, repo(**lower).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert found[0]["name"] == "actions/checkout", found
    assert found[0]["detail"] == "`v1` here, `v2` there", found

    # Casing alone is not drift -- the same action at the same ref agrees.
    same_ref_upper = {".github/workflows/backend-ci.yml": wf("Actions/Checkout@1111111 # v1")}
    same_ref_lower = {".github/workflows/backend-ci.yml": wf("actions/checkout@1111111 # v1")}
    found = [f for f in compare(repo(**same_ref_upper).get, repo(**same_ref_lower).get)
             if f["kind"] == "action"]
    assert found == [], found

    # A SUBPATH is a git tree path and is case-sensitive. Folding it merges
    # genuinely different targets -- here into bogus drift.
    build_upper = {".github/workflows/backend-ci.yml": wf("owner/repo/Build@1111111 # v1")}
    build_lower = {".github/workflows/backend-ci.yml": wf("owner/repo/build@2222222 # v2")}
    found = [f for f in compare(repo(**build_upper).get, repo(**build_lower).get)
             if f["kind"] == "action"]
    assert len(found) == 2, f"different subpaths are one-sided actions: {found}"

    # ...and the owner/repo halves of such a reference still normalise.
    reusable_upper = {".github/workflows/backend-ci.yml":
                      wf("Studio81Labs/Shared/.github/workflows/x.yml@1111111 # v1")}
    reusable_lower = {".github/workflows/backend-ci.yml":
                      wf("studio81labs/shared/.github/workflows/x.yml@2222222 # v2")}
    found = [f for f in compare(repo(**reusable_upper).get, repo(**reusable_lower).get)
             if f["kind"] == "action"]
    assert len(found) == 1, found
    assert found[0]["name"] == "studio81labs/shared/.github/workflows/x.yml", found

    # ...but a REF differing only in case is NOT normalised: git refs are
    # case-sensitive, so `v1` and `V1` can be different tags.
    tag_lower = {".github/workflows/backend-ci.yml": wf("actions/x@v1")}
    tag_upper = {".github/workflows/backend-ci.yml": wf("actions/x@V1")}
    found = [f for f in compare(repo(**tag_lower).get, repo(**tag_upper).get) if f["kind"] == "action"]
    assert len(found) == 1, found

    # Two unannotated refs sharing a seven-character prefix. The fallback
    # labels collide, and appending the same truncation again disambiguates
    # nothing -- `release (release)` on both sides.
    coll_a = {".github/workflows/backend-ci.yml": wf("actions/x@release-2026-a")}
    coll_b = {".github/workflows/backend-ci.yml": wf("actions/x@release-2026-b")}
    found = [f for f in compare(repo(**coll_a).get, repo(**coll_b).get) if f["kind"] == "action"]
    assert len(found) == 1, found
    assert "release-2026-a" in found[0]["detail"], found
    assert "release-2026-b" in found[0]["detail"], found

    # Gone from both: a manifest entry that no longer compares anything.
    gone_actions = {path: None for path in ACTION_WORKFLOWS}
    for marker in set(ACTION_TOPOLOGY_GATED.values()):
        for marker_path in CAPABILITY_MARKER_PATHS.get(marker, (marker,)):
            gone_actions[marker_path] = "marker\n"
    found = [
        f
        for f in compare(repo(**gone_actions).get, repo(**gone_actions).get)
        if f["kind"] == "workflow" and "stale entry" in f["detail"]
    ]
    # Missing owned cross-stack workflows are reported by the stronger
    # presence contract above, so they do not also produce stale-manifest
    # duplicates here.
    expected_stale = set(ACTION_WORKFLOWS) - set(TOPOLOGY_GATED)
    assert len(found) == len(expected_stale), len(found)

    # A commented-out step and an embedded string. Grepping the raw text read
    # both as active pins and INVENTED drift, which keeps the standing issue
    # open forever -- the mirror image of the silent-drop failures.
    live = ".github/workflows/backend-ci.yml"
    clean = {live: wf("actions/checkout@aaaaaaa # v7.0.1")}
    noisy = {
        live: clean[live]
        + "      # - uses: actions/checkout@fffffff # v6.0.0\n"
        + '      - run: "echo uses: actions/checkout@fffffff"\n'
    }
    assert compare(repo(**clean).get, repo(**noisy).get) == [], (
        "a commented-out or embedded uses: must not be treated as a pin"
    )

    # THE CLASS ITSELF: a `uses:` line that names a remote action and does not
    # parse is reported, whatever the reason. Without this, an unhandled
    # spelling silently drops the occurrence and reads as convergence.
    weird = {".github/workflows/backend-ci.yml": wf("actions/checkout @ aaaaaaa")}
    found = [f for f in compare(repo(**weird).get, repo().get) if f["kind"] == "unparsed"]
    assert found, "an unparseable remote action must be reported, not dropped"
    assert "NOT compared" in found[0]["detail"], found

    # Local and docker refs are not pinned remote actions and never were in
    # scope -- they must NOT be reported as unparsed.
    localref = {".github/workflows/backend-ci.yml":
                wf("./.github/workflows/_build-openapi.yml", "docker://alpine:3.19")}
    found = [f for f in compare(repo(**localref).get, repo(**localref).get) if f["kind"] == "unparsed"]
    assert found == [], found

    # A remote reusable workflow (owner/repo/path@ref) parses normally.
    reusable = {".github/workflows/backend-ci.yml":
                wf("Studio81Labs/shared/.github/workflows/x.yml@aaaaaaa # v1")}
    found = [f for f in compare(repo(**reusable).get, repo(**reusable).get) if f["kind"] == "unparsed"]
    assert found == [], found

    # A stale step parked behind a literal `if: false` never runs, so
    # comparing its ref against the sibling's live one invents drift.
    disabled = {".github/workflows/backend-ci.yml":
                "jobs:\n  build:\n    steps:\n"
                "      - uses: actions/x@2222222 # v2\n"
                "      - if: false\n        uses: actions/x@1111111 # v1\n"}
    active = {".github/workflows/backend-ci.yml": wf("actions/x@2222222 # v2")}
    assert compare(repo(**disabled).get, repo(**active).get) == [], "if: false must not compare"

    # Expression form, and a disabled JOB.
    expr = {".github/workflows/backend-ci.yml":
            "jobs:\n  build:\n    steps:\n"
            "      - uses: actions/x@2222222 # v2\n"
            "      - if: ${{ false }}\n        uses: actions/x@1111111 # v1\n"}
    assert compare(repo(**expr).get, repo(**active).get) == [], "${{ false }} must not compare"
    dead_job = {".github/workflows/backend-ci.yml":
                "jobs:\n  build:\n    steps:\n      - uses: actions/x@2222222 # v2\n"
                "  old:\n    if: false\n    steps:\n      - uses: actions/x@1111111 # v1\n"}
    assert compare(repo(**dead_job).get, repo(**active).get) == [], "a disabled job must not compare"

    # ...but a DYNAMIC condition is not statically disabled. Guessing at
    # runtime conditions would hide pins that really do run.
    dynamic = {".github/workflows/backend-ci.yml":
               "jobs:\n  build:\n    steps:\n"
               "      - if: github.event_name == 'push'\n        uses: actions/x@1111111 # v1\n"}
    found = [f for f in compare(repo(**dynamic).get, repo(**active).get) if f["kind"] == "action"]
    assert len(found) == 1, found

    # A quoted YAML scalar. Valid, and previously dropped -- which reads as
    # "the sibling does not use this action" and is discarded as topology.
    plain = {".github/workflows/backend-ci.yml": wf("actions/checkout@aaaaaaa # v7.0.1")}
    quoted = {".github/workflows/backend-ci.yml": wf("\"actions/checkout@fffffff\" # v6")}
    found = compare(repo(**plain).get, repo(**quoted).get)
    assert len(found) == 1, found
    assert found[0]["detail"] == "`v7.0.1` here, `v6` there", found
    # Single quotes, and a quoted ref carrying no comment: the label falls back
    # to the ref, which must not include the quote.
    sq = {".github/workflows/backend-ci.yml": wf("'actions/checkout@fffffff'")}
    found = compare(repo(**plain).get, repo(**sq).get)
    assert found[0]["detail"] == "`v7.0.1` here, `fffffff` there", found

    # An action moved off a digest onto a floating branch in ONE repo. The
    # old regex matched only digests and `v*` tags, so this occurrence was
    # dropped, the action looked one-sided, and the intersection discarded it
    # as topology -- hiding the worst supply-chain regression there is.
    pinned = {".github/workflows/backend-ci.yml": wf("actions/checkout@aaaaaaa # v7.0.1")}
    floating = {".github/workflows/backend-ci.yml": wf("actions/checkout@main")}
    found = compare(repo(**pinned).get, repo(**floating).get)
    assert len(found) == 1, found
    assert found[0]["detail"] == "`v7.0.1` here, `main` there", found

    # ...and the reverse direction, so neither repo is privileged.
    found = compare(repo(**floating).get, repo(**pinned).get)
    assert found[0]["detail"] == "`main` here, `v7.0.1` there", found

    shared_plus_ours = {
        ".github/workflows/backend-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "owner/ours@2222222 # v2",
        )
    }
    shared_plus_theirs = {
        ".github/workflows/backend-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "owner/theirs@3333333 # v3",
        )
    }
    found = [
        f for f in compare(repo(**shared_plus_ours).get, repo(**shared_plus_theirs).get)
        if f["kind"] == "action" and "backend-ci.yml" in f["name"]
    ]
    assert len(found) == 2, f"one-sided shared actions must report: {found}"

    admin_with_download = {
        ".github/workflows/admin-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "actions/download-artifact@2222222 # v2",
            "actions/upload-artifact@3333333 # v3",
        )
    }
    admin_without_capability = {
        ".github/workflows/admin-ci.yml": wf("actions/checkout@1111111 # v1"),
        "apps/marketing/package.json": None,
    }
    found = [
        f for f in compare(repo(**admin_with_download).get, repo(**admin_without_capability).get)
        if f["kind"] == "action" and "admin-ci.yml" in f["name"]
    ]
    assert found == [], f"optional job actions follow their capability: {found}"
    admin_with_preview = {
        ".github/workflows/admin-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "actions/download-artifact@2222222 # v2",
            "actions/upload-artifact@2222222 # v2",
        )
    }
    found = [
        f
        for f in compare(repo(**admin_with_preview).get, repo(**admin_without_capability).get)
        if f["kind"] == "action" and "admin-ci.yml" in f["name"]
    ]
    assert found == [], f"admin preview uploads follow deployment capability: {found}"
    admin_without_capability_with_download = {
        ".github/workflows/admin-ci.yml": admin_with_download[".github/workflows/admin-ci.yml"],
        "apps/marketing/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**admin_without_capability_with_download).get,
            repo(**admin_without_capability).get,
        )
        if f["kind"] == "action" and "admin-ci.yml" in f["name"]
    ]
    assert len(found) == 2, f"entry gates require asymmetric ownership: {found}"
    admin_owner_without_download = {
        ".github/workflows/admin-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "actions/upload-artifact@3333333 # v3",
        ),
    }
    found = [
        f for f in compare(repo(**admin_with_download).get, repo(**admin_owner_without_download).get)
        if f["kind"] == "action" and "admin-ci.yml" in f["name"]
    ]
    assert len(found) == 1, f"an owner losing an optional action must report: {found}"
    owner_without_download = admin_owner_without_download
    non_owner_without_download = {
        ".github/workflows/admin-ci.yml": wf("actions/checkout@1111111 # v1"),
        "apps/marketing/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**owner_without_download).get,
            repo(**non_owner_without_download).get,
        )
        if f["kind"] == "action"
        and f["name"].startswith("actions/download-artifact")
    ]
    assert len(found) == 1, f"a sole owner must retain its gated action: {found}"
    inverted_download = {
        ".github/workflows/admin-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "actions/download-artifact@2222222 # v2",
        ),
        "apps/marketing/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**owner_without_download).get,
            repo(**inverted_download).get,
        )
        if f["kind"] == "action"
        and f["name"].startswith("actions/download-artifact")
    ]
    assert len(found) == 2, f"an inverted gated action must report both sides: {found}"
    non_owner_download_in_other_job = {
        ".github/workflows/admin-ci.yml": (
            "jobs:\n"
            "  other:\n"
            "    steps:\n"
            "      - uses: actions/checkout@1111111 # v1\n"
            "      - uses: actions/download-artifact@2222222 # v2\n"
        ),
        "apps/marketing/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**admin_with_download).get,
            repo(**non_owner_download_in_other_job).get,
        )
        if f["kind"] == "action"
        and f["name"].startswith("actions/download-artifact")
    ]
    assert len(found) == 1, f"a non-owner action in any job must report: {found}"
    assert "no action anywhere there" in found[0]["detail"], found

    PACKAGE_ACTION_WF = ".github/workflows/packages-ci.yml"
    package_with_download = {
        PACKAGE_ACTION_WF: wf(
            "actions/checkout@1111111 # v1",
            "actions/download-artifact@2222222 # v2",
        ),
        "apps/ingest/package.json": "{}\n",
    }
    package_without_ingest = {
        PACKAGE_ACTION_WF: wf("actions/checkout@1111111 # v1"),
    }
    found = [
        f
        for f in compare(
            repo(**package_with_download).get,
            repo(**package_without_ingest).get,
        )
        if f["kind"] == "action" and "packages-ci.yml" in f["name"]
    ]
    assert found == [], f"the ingest app owns the package artifact handoff: {found}"
    package_without_app = {
        **package_with_download,
        "apps/ingest/package.json": None,
        "packages/ingest/package.json": "{}\n",
    }
    found = [
        f
        for f in compare(
            repo(**package_without_app).get,
            repo(**package_without_ingest).get,
        )
        if f["kind"] == "action" and "packages-ci.yml" in f["name"]
    ]
    assert len(found) == 1, f"a shared ingest package alone must not gate the handoff: {found}"
    package_download_in_wrong_job = {
        PACKAGE_ACTION_WF: (
            "jobs:\n"
            "  prepare-openapi:\n"
            "    name: \"contract: openapi spec\"\n"
            "    steps:\n"
            "      - uses: actions/download-artifact@2222222 # v2\n"
            "  build:\n"
            "    name: \"packages: build, test & typecheck\"\n"
            "    steps:\n"
            "      - uses: actions/checkout@1111111 # v1\n"
        ),
        "apps/ingest/package.json": "{}\n",
    }
    found = [
        f
        for f in compare(
            repo(**package_download_in_wrong_job).get,
            repo(**package_without_ingest).get,
        )
        if f["kind"] == "action"
        and f["name"].startswith("actions/download-artifact")
    ]
    assert len(found) == 1, f"a gated action in the wrong job must report: {found}"
    assert "job `build`" in found[0]["detail"], found
    package_owner_missing_action = {
        PACKAGE_ACTION_WF: wf("actions/checkout@1111111 # v1"),
        "apps/ingest/package.json": "{}\n",
    }
    package_capability_absent = {
        PACKAGE_ACTION_WF: None,
        "packages/core/package.json": None,
        "packages/shared/package.json": None,
        "apps/ingest/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**package_owner_missing_action).get,
            repo(**package_capability_absent).get,
        )
        if f["kind"] == "action"
        and f["name"].startswith("actions/download-artifact")
    ]
    assert len(found) == 1, (
        "a whole-workflow gate must not bypass the owner's entry assertion: "
        f"{found}"
    )
    assert "job `build` here" in found[0]["detail"], found

    mobile_plus_ours = {
        ".github/workflows/mobile-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "owner/flutter-only@2222222 # v2",
        ),
        "apps/mobile/pubspec.yaml": "name: flutter_app\n",
    }
    mobile_plus_theirs = {
        ".github/workflows/mobile-ci.yml": wf(
            "actions/checkout@1111111 # v1",
            "owner/native-only@3333333 # v3",
        )
    }
    found = [
        f for f in compare(repo(**mobile_plus_ours).get, repo(**mobile_plus_theirs).get)
        if f["kind"] == "action" and "mobile-ci.yml" in f["name"]
    ]
    assert found == [], f"capability workflow actions may be topology: {found}"

    # A same-line-count content change must still show WHAT changed.
    n1 = {".nvmrc": "22\n"}
    n2 = {".nvmrc": "24\n"}
    found = compare(repo(**n1).get, repo(**n2).get)
    assert found[0]["detail"] == "1 lines here, 1 there", found
    assert "-22" in found[0]["diff"] and "+24" in found[0]["diff"], found
    assert "```diff" in render(found), render(found)

    # Two different SHAs behind the SAME coarse annotation. Rendering the label
    # alone gives "`v8` here, `v8` there", which tells the reader nothing.
    ours_v8 = {".github/workflows/backend-ci.yml": wf("actions/x@1111111 # v8")}
    theirs_v8 = {".github/workflows/backend-ci.yml": wf("actions/x@2222222 # v8")}
    found = compare(repo(**ours_v8).get, repo(**theirs_v8).get)
    assert found[0]["detail"] == "`v8 (1111111)` here, `v8 (2222222)` there", found

    assert "0 difference(s)." in render([])
    assert "GitHub Action pins" in render([{"kind": "action", "name": "a", "detail": "d"}])

    # A manifest entry naming a file NEITHER repo has is a guard that stopped
    # guarding. Silence there is indistinguishable from agreement. Topology-
    # gated entries are exempt while no shared marker exists: between two
    # React Native repos a Flutter guard is absent by design, not stale.
    gone = {path: None for path in IDENTICAL}
    for marker in set(TOPOLOGY_GATED.values()):
        for marker_path in CAPABILITY_MARKER_PATHS.get(marker, (marker,)):
            gone[marker_path] = None
    found = [f for f in compare(repo(**gone).get, repo(**gone).get) if f["kind"] == "file"]
    ungated = [path for path in IDENTICAL if path not in TOPOLOGY_GATED]
    assert len(found) == len(ungated), found
    assert all("stale entry in IDENTICAL" in f["detail"] for f in found), found
    # With the marker on both sides the gate opens and a gated entry absent
    # from both repos is a stale guard again, exactly as before the gate.
    gone_flutter = dict(gone)
    for marker in set(TOPOLOGY_GATED.values()) | set(STACK_TOPOLOGY_GATED.values()):
        marker_path = CAPABILITY_MARKER_PATHS.get(marker, (marker,))[0]
        gone_flutter[marker_path] = "marker\n"
    found = [f for f in compare(repo(**gone_flutter).get, repo(**gone_flutter).get) if f["kind"] == "file"]
    assert len(found) == len(IDENTICAL), found

    # --- topology gating ---------------------------------------------------
    BACKEND_WORKFLOW = ".github/workflows/backend-deploy.yml"
    node_backend = {
        "apps/backend/package.json": "{}\n",
        "apps/backend/pyproject.toml": None,
        "apps/marketing/package.json": "{}\n",
        BACKEND_WORKFLOW: (
            "jobs:\n"
            "  version-gate:\n"
            "    name: \"release: version gate\"\n"
            "    steps: []\n"
            "  deploy:\n"
            "    name: \"backend: deploy\"\n"
            "    steps: []\n"
        ),
    }
    python_backend_missing_deploy = {
        "apps/backend/package.json": None,
        "apps/backend/pyproject.toml": "[project]\nname = \"backend\"\n",
        "apps/marketing/package.json": None,
        BACKEND_WORKFLOW: None,
    }
    found = [
        f
        for f in compare(
            repo(**node_backend).get,
            repo(**python_backend_missing_deploy).get,
        )
        if f["name"] == BACKEND_WORKFLOW
    ]
    assert any(
        f["kind"] == "workflow"
        and "absent" in f["detail"]
        and ("present here" in f["detail"] or "expects an artifact" in f["detail"])
        for f in found
    ), f"a backend owner may not lose its deploy workflow: {found}"

    node_backend_action = {
        **node_backend,
        BACKEND_WORKFLOW: (
            "jobs:\n"
            "  version-gate:\n"
            "    name: \"release: version gate\"\n"
            "    steps: []\n"
            "  deploy:\n"
            "    name: \"backend: deploy\"\n"
            "    steps:\n"
            "      - uses: actions/checkout@1111111 # v1\n"
        ),
    }
    python_backend_without_action = {
        "apps/backend/package.json": None,
        "apps/backend/pyproject.toml": "[project]\nname = \"backend\"\n",
        "apps/marketing/package.json": None,
        BACKEND_WORKFLOW: wf("actions/setup-python@2222222 # v2"),
    }
    backend_action_findings = compare(
        repo(**node_backend_action).get,
        repo(**python_backend_without_action).get,
    )
    found = [
        f
        for f in backend_action_findings
        if f["kind"] == "action" and "actions/checkout" in f["name"]
    ]
    assert found and "backend-deploy.yml" in found[0]["name"], (
        "backend topology must not hide a one-sided deploy action: "
        f"{backend_action_findings}"
    )

    taven_backend_without_deploy = {
        "apps/backend/package.json": "{}\n",
        "apps/backend/pyproject.toml": None,
        "apps/marketing/package.json": None,
        BACKEND_WORKFLOW: None,
    }
    found = [
        f
        for f in compare(
            repo(**node_backend_action).get,
            repo(**taven_backend_without_deploy).get,
        )
        if f["name"] == BACKEND_WORKFLOW
        or (f["kind"] == "action" and "backend-deploy.yml" in f["name"])
    ]
    assert found == [], f"a backend without a deploy surface is not an owner: {found}"

    MARKER = "apps/mobile/pubspec.yaml"
    MOBILE_MARKER = "apps/mobile/package.json"
    GATED_FILE = "scripts/lib/resolve-flutter.sh"
    both_flutter = {MARKER: "name: app\n"}

    # Present on one side only, no marker anywhere: stack topology, silent.
    flutterless = {GATED_FILE: None}
    found = [f for f in compare(repo().get, repo(**flutterless).get) if f["name"] == GATED_FILE]
    assert found == [], f"a gated file missing on the stackless side is topology: {found}"
    # The same absence between two Flutter repos is a real finding again.
    absent_there = {MARKER: "name: app\n", GATED_FILE: None}
    found = [f for f in compare(repo(**both_flutter).get, repo(**absent_there).get) if f["name"] == GATED_FILE]
    assert found and found[0]["detail"] == (
        "topology expects an artifact there, but it is absent"
    ), found
    # Content drift in a gated file is reported when both sides share the
    # owning stack. Across stacks the non-owner must not retain a stale copy.
    changed = {MARKER: "name: app\n", GATED_FILE: "different\n"}
    found = [f for f in compare(repo(**both_flutter).get, repo(**changed).get) if f["name"] == GATED_FILE]
    assert len(found) == 1, found
    marker_one_side = {GATED_FILE: "different\n"}
    found = [f for f in compare(repo(**both_flutter).get, repo(**marker_one_side).get) if f["name"] == GATED_FILE]
    assert len(found) == 1 and "expects no artifact there" in found[0]["detail"], found

    # Release guards exist in both mobile stacks even though their contents
    # differ. A React Native owner deleting its copy must not be hidden by the
    # Flutter stack gate.
    RELEASE_HELPER = "scripts/ci/check-release-tag.sh"
    flutter_release = {
        MARKER: "name: app\n",
        MOBILE_MARKER: None,
        RELEASE_HELPER: "flutter guard\n",
    }
    react_native_missing_release = {
        MARKER: None,
        MOBILE_MARKER: "{}\n",
        RELEASE_HELPER: None,
    }
    found = [
        f
        for f in compare(
            repo(**flutter_release).get,
            repo(**react_native_missing_release).get,
        )
        if f["name"] == RELEASE_HELPER
    ]
    assert found and found[0]["detail"] == (
        "mobile topology expects an artifact there, but it is absent"
    ), found
    react_native_release = {
        **react_native_missing_release,
        RELEASE_HELPER: "react native guard\n",
    }
    found = [
        f
        for f in compare(
            repo(**flutter_release).get,
            repo(**react_native_release).get,
        )
        if f["name"] == RELEASE_HELPER
    ]
    assert found == [], f"cross-stack release guard contents are topology: {found}"
    non_mobile_with_release = {
        MARKER: None,
        MOBILE_MARKER: None,
        RELEASE_HELPER: "flutter guard\n",
    }
    found = [
        f
        for f in compare(
            repo(**flutter_release).get,
            repo(**non_mobile_with_release).get,
        )
        if f["name"] == RELEASE_HELPER
    ]
    assert len(found) == 1 and "without its owning capability" in found[0]["detail"], found
    missing_mobile_release = {
        MARKER: "name: app\n",
        MOBILE_MARKER: None,
        RELEASE_HELPER: None,
    }
    found = [
        f
        for f in compare(
            repo(**missing_mobile_release).get,
            repo(**non_mobile_with_release).get,
        )
        if f["name"] == RELEASE_HELPER
    ]
    assert len(found) == 2, found
    assert any("expects an artifact here" in f["detail"] for f in found), found
    assert any("expects no artifact there" in f["detail"] for f in found), found

    # Capability-owned workflows are repository-local invariants too. An
    # identical copy on a non-owner is stale topology, not agreement, and an
    # owner deletion plus that stale copy must expose both repairs at once.
    MARKETING_WF = ".github/workflows/marketing-ci.yml"
    MARKETING_MARKER = "apps/marketing/package.json"
    marketing_copy = wf("actions/checkout@1111111 # v1")
    marketing_owner = {MARKETING_MARKER: "{}\n", MARKETING_WF: marketing_copy}
    marketing_nonowner_stale = {MARKETING_MARKER: None, MARKETING_WF: marketing_copy}
    found = [
        f
        for f in compare(
            repo(**marketing_owner).get,
            repo(**marketing_nonowner_stale).get,
        )
        if f["name"].endswith("marketing-ci.yml")
    ]
    assert len(found) == 1 and "expects no artifact there" in found[0]["detail"], found
    found = [
        f
        for f in compare(
            repo(**marketing_nonowner_stale).get,
            repo(**marketing_nonowner_stale).get,
        )
        if f["name"].endswith("marketing-ci.yml")
    ]
    assert len(found) == 1 and "here and there" in found[0]["detail"], found
    marketing_owner_missing = {MARKETING_MARKER: "{}\n", MARKETING_WF: None}
    found = [
        f
        for f in compare(
            repo(**marketing_owner_missing).get,
            repo(**marketing_nonowner_stale).get,
        )
        if f["name"].endswith("marketing-ci.yml")
    ]
    assert len(found) == 2, found
    assert any("expects an artifact here" in f["detail"] for f in found), found
    assert any("expects no artifact there" in f["detail"] for f in found), found
    changed_react_native_release = {
        **react_native_release,
        RELEASE_HELPER: "changed react native guard\n",
    }
    found = [
        f
        for f in compare(
            repo(**react_native_release).get,
            repo(**changed_react_native_release).get,
        )
        if f["name"] == RELEASE_HELPER
    ]
    assert len(found) == 1, f"same-stack release guard drift must report: {found}"
    # Job names behind the gate follow the same rule: the whole workflow being
    # one-sided is silent across stacks, reported within one.
    GATED_WF = ".github/workflows/flutter-pin-check.yml"
    found = [f for f in compare(repo().get, repo(**{GATED_WF: None}).get) if f["name"] == GATED_WF]
    assert found == [], found
    found = [
        f
        for f in compare(repo(**both_flutter).get, repo(**{MARKER: "name: app\n", GATED_WF: None}).get)
        if f["name"] == GATED_WF
    ]
    assert found and found[0]["detail"] == (
        "topology expects an artifact there, but it is absent"
    ), found

    # Action workflows use a broader capability gate. A repo with no mobile
    # surface is not behind on mobile-release.yml; two repos that both declare
    # mobile still must report a missing workflow.
    MOBILE_ACTION_WF = ".github/workflows/mobile-release.yml"
    no_mobile = {MARKER: None, MOBILE_MARKER: None, MOBILE_ACTION_WF: None}
    found = [
        f for f in compare(repo(**no_mobile).get, repo(**no_mobile).get)
        if f["name"].endswith("mobile-release.yml")
    ]
    assert found == [], f"a missing capability must gate its action workflow: {found}"
    mobile_here = {MARKER: None, MOBILE_MARKER: "{}\n"}
    mobile_missing_there = {
        MARKER: None,
        MOBILE_MARKER: "{}\n",
        MOBILE_ACTION_WF: None,
    }
    found = [
        f for f in compare(repo(**mobile_here).get, repo(**mobile_missing_there).get)
        if f["name"].endswith("mobile-release.yml")
    ]
    assert found and found[0]["detail"] == (
        "mobile topology expects an artifact there, but it is absent"
    ), found
    mobile_pin_here = {
        MARKER: "name: app\n",
        MOBILE_ACTION_WF: wf("actions/x@1111111 # v1"),
    }
    mobile_pin_there = {
        MOBILE_MARKER: None,
        MARKER: "name: app\n",
        MOBILE_ACTION_WF: wf("actions/x@2222222 # v2"),
    }
    found = [
        f for f in compare(repo(**mobile_pin_here).get, repo(**mobile_pin_there).get)
        if f["kind"] == "action" and f["name"].startswith("actions/x")
    ]
    assert len(found) == 1, f"present gated workflows must compare pins: {found}"

    mobile_actions_here = {
        MARKER: "name: app\n",
        MOBILE_ACTION_WF: wf("actions/shared@1111111 # v1", "actions/extra@2222222 # v2")
    }
    mobile_actions_there = {
        MOBILE_MARKER: None,
        MARKER: "name: app\n",
        MOBILE_ACTION_WF: wf("actions/shared@1111111 # v1"),
    }
    found = [
        f for f in compare(repo(**mobile_actions_here).get, repo(**mobile_actions_there).get)
        if f["kind"] == "action" and f["name"].startswith("actions/extra")
    ]
    assert len(found) == 1, f"present workflows must report one-sided actions: {found}"

    PACKAGE_WF = ".github/workflows/packages-ci.yml"
    found = [
        f
        for f in compare(
            repo(**{"packages/core/package.json": None}).get,
            repo(
                **{
                    "packages/core/package.json": None,
                    PACKAGE_WF: None,
                }
            ).get,
        )
        if f["name"] == "packages-ci.yml"
    ]
    assert found == [], f"one-sided package workflow is capability topology: {found}"
    package_owner = {
        PACKAGE_WF: (
            "jobs:\n"
            "  build:\n"
            "    name: \"packages: build & test\"\n"
            "    steps:\n"
            "      - uses: actions/x@1111111 # v1\n"
        ),
        "packages/core/package.json": "{}\n",
    }
    package_owner_missing = {PACKAGE_WF: None, "packages/core/package.json": "{}\n"}
    found = [
        f for f in compare(repo(**package_owner).get, repo(**package_owner_missing).get)
        if f["name"].endswith("packages-ci.yml")
    ]
    assert len(found) == 1, f"an owner deleting package CI must report: {found}"
    package_non_owner = {
        PACKAGE_WF: None,
        "packages/core/package.json": None,
        "packages/shared/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**package_owner_missing).get,
            repo(**package_non_owner).get,
        )
        if f["name"].endswith("packages-ci.yml")
    ]
    assert len(found) == 1, f"an owner deletion must report against a non-owner: {found}"
    package_pin_here = {PACKAGE_WF: wf("actions/x@1111111 # v1")}
    package_pin_there = {PACKAGE_WF: wf("actions/x@2222222 # v2")}
    found = [
        f for f in compare(repo(**package_pin_here).get, repo(**package_pin_there).get)
        if f["kind"] == "action" and f["name"].startswith("actions/x")
    ]
    assert len(found) == 1, f"shared package workflows must compare pins: {found}"

    # The Semgrep fixture verifier is shared across Flutter and React Native.
    # Its gate must use the broad mobile capability, not Flutter's pubspec, or
    # every Tarmoto comparison silently stops checking the helper.
    SEMGREP_HELPER = "scripts/ci/check-semgrep-fixture.py"
    flutter_helper = {
        SEMGREP_HELPER: "flutter copy\n",
        "apps/mobile/pubspec.yaml": "name: app\n",
    }
    react_native_helper = {
        SEMGREP_HELPER: "react native copy\n",
        "apps/mobile/pubspec.yaml": None,
    }
    found = [
        f for f in compare(repo(**flutter_helper).get, repo(**react_native_helper).get)
        if f["name"] == SEMGREP_HELPER
    ]
    assert len(found) == 1, f"cross-stack Semgrep helper drift must report: {found}"
    react_native_without_incidental_marker = {
        **react_native_helper,
        MOBILE_MARKER: None,
    }
    found = [
        f
        for f in compare(
            repo(**flutter_helper).get,
            repo(**react_native_without_incidental_marker).get,
        )
        if f["name"] == SEMGREP_HELPER
    ]
    assert len(found) == 1, f"an incidental marker deletion must not hide drift: {found}"
    no_mobile_helper = {MOBILE_MARKER: None, SEMGREP_HELPER: None}
    found = [
        f for f in compare(repo().get, repo(**no_mobile_helper).get)
        if f["name"] == SEMGREP_HELPER
    ]
    assert found == [], f"a sibling without mobile has no fixture helper: {found}"

    # --- job names -------------------------------------------------------
    JOB_WF = ".github/workflows/backend-ci.yml"

    def jobs_yaml(*pairs):
        out = ["jobs:"]
        for job_id, name in pairs:
            out.append(f"  {job_id}:")
            if name is not None:
                out.append(f'    name: "{name}"')
            out.append("    steps:")
            out.append("      - uses: actions/x@1111111 # v1")
        return "\n".join(out) + "\n"

    CAPABILITY_GATED_WF = ".github/workflows/_release-version-gate.yml"
    gated_jobs_here = {
        CAPABILITY_GATED_WF: jobs_yaml(("build", "mobile: build")),
    }
    gated_jobs_there = {
        CAPABILITY_GATED_WF: jobs_yaml(("build", "mobile: changed")),
        MOBILE_MARKER: "{}\n",
    }
    found = [
        f for f in compare(repo(**gated_jobs_here).get, repo(**gated_jobs_there).get)
        if f["kind"] == "jobname" and f["name"] == CAPABILITY_GATED_WF
    ]
    assert len(found) == 1, f"present gated workflows must compare job names: {found}"

    valid_package = {
        PACKAGE_WF: jobs_yaml(("build", "packages: build & test"))
    }
    renamed_package = {
        PACKAGE_WF: jobs_yaml(("build", "packages: build, test & typecheck"))
    }
    found = [
        f
        for f in compare(repo(**valid_package).get, repo(**renamed_package).get)
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert len(found) == 1 and "expected" in found[0]["detail"], found
    taven_package = {
        PACKAGE_WF: jobs_yaml(
            ("build", "packages: lint, typecheck, test & build")
        ),
        "packages/slicer-contracts/package.json": "{}\n",
    }
    found = [
        f
        for f in compare(repo(**valid_package).get, repo(**taven_package).get)
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert found == [], f"the slicer package topology owns Taven's exact claim: {found}"
    taven_with_tabletap_claim = {
        PACKAGE_WF: jobs_yaml(("build", "packages: build & test")),
        "packages/slicer-contracts/package.json": "{}\n",
    }
    found = [
        f
        for f in compare(
            repo(**taven_package).get,
            repo(**taven_with_tabletap_claim).get,
        )
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert len(found) == 1 and "expected" in found[0]["detail"], found
    tarmoto_package = {
        PACKAGE_WF: jobs_yaml(
            ("prepare-openapi", "contract: openapi spec"),
            ("build", "packages: build, test & typecheck"),
        ),
        "apps/ingest/package.json": "{}\n",
    }
    tarmoto_without_prepare = {
        PACKAGE_WF: (
            "jobs:\n"
            "  build:\n"
            "    name: \"packages: build, test & typecheck\"\n"
            "    steps:\n"
            "      - uses: actions/download-artifact@1111111 # v1\n"
        ),
        "apps/ingest/package.json": "{}\n",
    }
    found = [
        f
        for f in compare(
            repo(**tarmoto_without_prepare).get,
            repo(**package_non_owner).get,
        )
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert len(found) == 1 and "expects job `prepare-openapi` here" in found[0]["detail"], found
    package_stale_non_owner = {
        PACKAGE_WF: jobs_yaml(("stale", "packages: stale placeholder")),
        "packages/core/package.json": None,
        "packages/shared/package.json": None,
    }
    found = [
        f
        for f in compare(
            repo(**tarmoto_without_prepare).get,
            repo(**package_stale_non_owner).get,
        )
        if f["name"].endswith("packages-ci.yml")
    ]
    assert len(found) == 2, found
    assert any("expects job `prepare-openapi` here" in f["detail"] for f in found), found
    assert any("expects no artifact there" in f["detail"] for f in found), found
    tarmoto_without_build = {
        PACKAGE_WF: jobs_yaml(
            ("prepare-openapi", "contract: openapi spec"),
        ),
        "apps/ingest/package.json": "{}\n",
    }
    found = [
        f
        for f in compare(
            repo(**tarmoto_without_build).get,
            repo(**package_non_owner).get,
        )
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert len(found) == 1 and "expects job `build` here" in found[0]["detail"], found
    tarmoto_with_weaker_claim = {
        **tarmoto_package,
        PACKAGE_WF: jobs_yaml(
            ("prepare-openapi", "contract: openapi spec"),
            ("build", "packages: build & test"),
        ),
    }
    found = [
        f
        for f in compare(
            repo(**tarmoto_package).get,
            repo(**tarmoto_with_weaker_claim).get,
        )
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert len(found) == 1 and "expected" in found[0]["detail"], found
    missing_package_build = {PACKAGE_WF: "jobs: {}\n"}
    found = [
        f
        for f in compare(repo(**valid_package).get, repo(**missing_package_build).get)
        if f["kind"] == "jobname" and f["name"] == PACKAGE_WF
    ]
    assert len(found) == 1 and "expects job `build` there" in found[0]["detail"], found

    named = {JOB_WF: jobs_yaml(("build", "backend: typecheck, test & build"))}
    renamed = {JOB_WF: jobs_yaml(("build", "backend: lint, test & build"))}
    found = [f for f in compare(repo(**named).get, repo(**renamed).get) if f["kind"] == "jobname"]
    assert len(found) == 1, found
    assert "`backend: typecheck, test & build` here" in found[0]["detail"], found
    assert "Job names in shared workflows" in render(found), render(found)

    # A job only one repo has. One-sided is drift too -- reporting only
    # renames would miss a check that exists in one repo and not the other,
    # which is the larger of the two failures.
    extra = {JOB_WF: jobs_yaml(("build", "backend: build"), ("smoke", "backend: smoke"))}
    base = {JOB_WF: jobs_yaml(("build", "backend: build"))}
    found = [f for f in compare(repo(**extra).get, repo(**base).get) if f["kind"] == "jobname"]
    assert len(found) == 1 and "present here, absent there" in found[0]["detail"], found

    # Python and Node workflows have a small exact set of one-sided actions.
    # Everything else remains shared policy, including presence and pin refs.
    python_backend_actions = {
        JOB_WF: wf(
            "actions/checkout@1111111 # v1",
            "actions/setup-node@3333333 # v3",
            "pnpm/action-setup@4444444 # v4",
            "actions/setup-python@2222222 # v2",
            "actions/download-artifact@5555555 # v5",
        ),
        "apps/backend/pyproject.toml": "[project]\nname = 'fixture'\n",
    }
    node_backend_actions = {
        JOB_WF: wf(
            "actions/checkout@1111111 # v1",
            "actions/setup-node@3333333 # v3",
            "pnpm/action-setup@4444444 # v4",
        ),
    }
    found = [
        f
        for f in compare(
            repo(**python_backend_actions).get,
            repo(**node_backend_actions).get,
        )
        if f["kind"] == "action" and "backend-ci.yml" in f["name"]
    ]
    assert found == [], f"backend setup actions are stack topology: {found}"
    node_backend_with_stale_checkout = {
        JOB_WF: wf(
            "actions/checkout@6666666 # v6",
            "actions/setup-node@3333333 # v3",
            "pnpm/action-setup@4444444 # v4",
        ),
    }
    found = [
        f
        for f in compare(
            repo(**python_backend_actions).get,
            repo(**node_backend_with_stale_checkout).get,
        )
        if f["kind"] == "action" and f["name"].startswith("actions/checkout")
    ]
    assert len(found) == 1, f"shared cross-stack action pins remain strict: {found}"
    node_backend_without_checkout = {
        JOB_WF: wf(
            "actions/setup-node@3333333 # v3",
            "pnpm/action-setup@4444444 # v4",
        ),
    }
    found = [
        f
        for f in compare(
            repo(**python_backend_actions).get,
            repo(**node_backend_without_checkout).get,
        )
        if f["kind"] == "action" and f["name"].startswith("actions/checkout")
    ]
    assert len(found) == 1, f"removing a shared cross-stack action must report: {found}"
    python_backend_without_setup = {
        **python_backend_actions,
        JOB_WF: wf(
            "actions/checkout@1111111 # v1",
            "actions/setup-node@3333333 # v3",
            "pnpm/action-setup@4444444 # v4",
            "actions/download-artifact@5555555 # v5",
        ),
    }
    found = [
        f
        for f in compare(
            repo(**python_backend_without_setup).get,
            repo(**node_backend_actions).get,
        )
        if f["kind"] == "action" and f["name"].startswith("actions/setup-python")
    ]
    assert len(found) == 1 and "expects the action here only" in found[0]["detail"], found

    # Poker-only layout exemptions must activate for Python-vs-Node, but the
    # same job IDs remain strict between two Node siblings.
    poker_backend = {
        JOB_WF: jobs_yaml(
            ("prepare-openapi", "contract: openapi spec"),
            ("test", "backend: tests and solver"),
            ("image", "backend: immutable image"),
        ),
        "apps/backend/pyproject.toml": "[project]\nname = 'fixture'\n",
    }
    node_backend = {
        JOB_WF: jobs_yaml(
            ("build", "backend: lint, typecheck, test & build"),
            ("test-e2e", "backend: e2e (real postgres)"),
        )
    }
    found = [
        f
        for f in compare(repo(**poker_backend).get, repo(**node_backend).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert found == [], f"Python-vs-Node job layout is pair topology: {found}"
    poker_without_image = {
        **poker_backend,
        JOB_WF: jobs_yaml(
            ("prepare-openapi", "contract: openapi spec"),
            ("test", "backend: tests and solver"),
        ),
    }
    found = [
        f
        for f in compare(repo(**poker_without_image).get, repo(**node_backend).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert len(found) == 1 and "expects job `image` here" in found[0]["detail"], found
    poker_renamed_test = {
        **poker_backend,
        JOB_WF: jobs_yaml(
            ("prepare-openapi", "contract: openapi spec"),
            ("test", "backend: renamed tests"),
            ("image", "backend: immutable image"),
        ),
    }
    found = [
        f
        for f in compare(repo(**poker_renamed_test).get, repo(**node_backend).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert len(found) == 1 and "expected `backend: tests and solver`" in found[0]["detail"], found
    POKER_OPENAPI_WF = ".github/workflows/openapi-check.yml"
    poker_openapi = {
        POKER_OPENAPI_WF: jobs_yaml(
            ("changes", "contract: detect inputs"),
            ("prepare-openapi", "contract: openapi spec"),
            ("validate", "contract: generated artifacts"),
            ("gate", "contract: gate"),
        ),
        "apps/backend/pyproject.toml": "[project]\nname = 'fixture'\n",
    }
    node_openapi = {
        POKER_OPENAPI_WF: jobs_yaml(("validate", "contract: emit + validate"))
    }
    found = [
        f
        for f in compare(repo(**poker_openapi).get, repo(**node_openapi).get)
        if f["kind"] == "jobname" and f["name"] == POKER_OPENAPI_WF
    ]
    assert found == [], f"Python-vs-Node OpenAPI layout is topology: {found}"
    poker_without_gate = {
        **poker_openapi,
        POKER_OPENAPI_WF: jobs_yaml(
            ("changes", "contract: detect inputs"),
            ("prepare-openapi", "contract: openapi spec"),
            ("validate", "contract: generated artifacts"),
        ),
    }
    found = [
        f
        for f in compare(repo(**poker_without_gate).get, repo(**node_openapi).get)
        if f["kind"] == "jobname" and f["name"] == POKER_OPENAPI_WF
    ]
    assert len(found) == 1 and "expects job `gate` here" in found[0]["detail"], found
    other_node = {
        JOB_WF: jobs_yaml(
            ("build", "backend: lint, test & build"),
            ("test-e2e", "backend: e2e (real postgres)"),
        )
    }
    found = [
        f
        for f in compare(repo(**node_backend).get, repo(**other_node).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert len(found) == 1 and "job `build`" in found[0]["detail"], found

    # Optional jobs are gated independently so the shared jobs in the same
    # workflow remain strict for a sibling without the owning capability.
    ADMIN_WF = ".github/workflows/admin-ci.yml"
    with_prepare = {
        ADMIN_WF: jobs_yaml(
            ("build", "admin: build"),
            ("prepare-openapi", "contract: openapi spec"),
        )
    }
    without_prepare = {
        ADMIN_WF: jobs_yaml(("build", "admin: build")),
        "apps/marketing/package.json": None,
    }
    found = [
        f for f in compare(repo(**with_prepare).get, repo(**without_prepare).get)
        if f["kind"] == "jobname" and f["name"] == ADMIN_WF
    ]
    assert found == [], f"an optional job without its capability is topology: {found}"
    owner_without_prepare = {
        ADMIN_WF: jobs_yaml(("build", "admin: build")),
    }
    found = [
        f for f in compare(repo(**owner_without_prepare).get, repo(**without_prepare).get)
        if f["kind"] == "jobname" and f["name"] == ADMIN_WF
    ]
    assert len(found) == 1 and "expects job `prepare-openapi` here" in found[0]["detail"], found

    SIBLING_DRIFT_WF = ".github/workflows/sibling-drift.yml"
    renamed_drift = {SIBLING_DRIFT_WF: jobs_yaml(("drift", "ci: renamed drift"))}
    expected_drift = {SIBLING_DRIFT_WF: jobs_yaml(("drift", "ci: sibling drift"))}
    found = [
        f for f in compare(repo(**expected_drift).get, repo(**renamed_drift).get)
        if f["kind"] == "jobname" and f["name"] == SIBLING_DRIFT_WF
    ]
    assert len(found) == 1, f"the drift workflow's own claim must be compared: {found}"

    # An unnamed job compares under its id rather than reading as absent --
    # otherwise adding an explicit `name:` to one repo would report the job as
    # newly missing from the other.
    unnamed = {JOB_WF: jobs_yaml(("build", None))}
    found = [f for f in compare(repo(**unnamed).get, repo(**base).get) if f["kind"] == "jobname"]
    assert len(found) == 1 and "`build` here" in found[0]["detail"], found

    # A job parked behind `if: false` never renders in the checks list, so its
    # name must not be compared.
    disabled = {JOB_WF: jobs_yaml(("build", "backend: build"))
                + "  old:\n    if: false\n    name: \"backend: gone\"\n    steps:\n"
                  "      - uses: actions/x@1111111 # v1\n"}
    found = [f for f in compare(repo(**disabled).get, repo(**base).get) if f["kind"] == "jobname"]
    assert found == [], found

    # A workflow that stops parsing must SAY so. Silently dropping it would
    # remove every one of its jobs from the comparison, and a smaller
    # comparison reads as convergence.
    broken = {JOB_WF: "jobs: [this is a sequence, not a mapping]\n"}
    found = [f for f in compare(repo(**broken).get, repo(**base).get) if f["kind"] == "jobname"]
    assert len(found) == 1 and "could not read jobs" in found[0]["detail"], found

    # An EXPECTED_JOB_DIFFS entry suppresses exactly its own job, and nothing
    # else in the same file.
    assert (".github/workflows/mobile-ci.yml", "mobile") in EXPECTED_JOB_DIFFS
    MOB = ".github/workflows/mobile-ci.yml"
    FLAVOR_MARKER = "apps/mobile/android/app/src/staging/google-services.json"
    # mobile-ci is topology-gated now, and this case describes the Flutter
    # pair — both sides carry the stack marker, while only one carries the
    # per-flavor source-set marker that forces the expected name difference.
    allowed = {
        MOB: jobs_yaml(
            (
                "mobile",
                "mobile: format, analyze & test (+ android builds when mobile changes)",
            ),
            ("other", "mobile: x"),
        ),
        MARKER: "name: app\n",
        FLAVOR_MARKER: "{}\n",
    }
    against = {
        MOB: jobs_yaml(
            (
                "mobile",
                "mobile: format, analyze & test (+ android release when mobile changes)",
            ),
            ("other", "mobile: y"),
        ),
        MARKER: "name: app\n",
    }
    found = [f for f in compare(repo(**allowed).get, repo(**against).get) if f["kind"] == "jobname"]
    assert len(found) == 1 and "`other`" in found[0]["detail"], found
    missing_mobile = {
        MOB: jobs_yaml(("other", "mobile: y")),
        MARKER: "name: app\n",
        FLAVOR_MARKER: "{}\n",
    }
    found = [
        f for f in compare(repo(**missing_mobile).get, repo(**against).get)
        if f["kind"] == "jobname" and f["name"] == MOB
    ]
    assert len(found) == 1 and "job `mobile` absent here" in found[0]["detail"], found
    same_flavor = {
        MOB: jobs_yaml(
            (
                "mobile",
                "mobile: format, analyze & test (+ android builds when mobile changes)",
            ),
            ("other", "mobile: x"),
        ),
        MARKER: "name: app\n",
    }
    found = [
        f for f in compare(repo(**same_flavor).get, repo(**against).get)
        if f["kind"] == "jobname"
    ]
    assert len(found) == 2, f"same-topology job names must stay strict: {found}"

    INGEST_MARKER = "apps/ingest/package.json"
    BACKEND_DEPLOY_WF = ".github/workflows/backend-deploy.yml"
    deploy_with_gate = {
        BACKEND_DEPLOY_WF: jobs_yaml(
            ("version-gate", "release: version gate"),
            ("deploy", "backend: deploy"),
        )
    }
    ingest_without_gate = {
        BACKEND_DEPLOY_WF: jobs_yaml(("deploy", "backend: deploy")),
        INGEST_MARKER: "{}\n",
    }
    found = [
        f for f in compare(repo(**deploy_with_gate).get, repo(**ingest_without_gate).get)
        if f["kind"] == "jobname" and f["name"] == BACKEND_DEPLOY_WF
    ]
    assert found == [], f"ingest orchestration owns the one-sided gate: {found}"
    deploy_without_gate = {
        BACKEND_DEPLOY_WF: jobs_yaml(("deploy", "backend: deploy")),
    }
    found = [
        f for f in compare(repo(**deploy_without_gate).get, repo(**ingest_without_gate).get)
        if f["kind"] == "jobname" and f["name"] == BACKEND_DEPLOY_WF
    ]
    assert len(found) == 1 and "expects job `version-gate` here" in found[0]["detail"], found

    ADMIN_DEPLOY_WF = ".github/workflows/admin-deploy.yml"
    deploy_with_resolve = {
        ADMIN_DEPLOY_WF: jobs_yaml(
            ("resolve", "admin: resolve environment"),
            ("deploy", "admin: deploy"),
        )
    }
    ingest_admin_deploy = {
        ADMIN_DEPLOY_WF: jobs_yaml(("deploy", "admin: deploy")),
        INGEST_MARKER: "{}\n",
    }
    found = [
        f for f in compare(repo(**deploy_with_resolve).get, repo(**ingest_admin_deploy).get)
        if f["kind"] == "jobname" and f["name"] == ADMIN_DEPLOY_WF
    ]
    assert found == [], f"ingest admin deploy resolves inline: {found}"
    admin_deploy_without_resolve = {
        ADMIN_DEPLOY_WF: jobs_yaml(("deploy", "admin: deploy")),
    }
    found = [
        f
        for f in compare(
            repo(**admin_deploy_without_resolve).get,
            repo(**ingest_admin_deploy).get,
        )
        if f["kind"] == "jobname" and f["name"] == ADMIN_DEPLOY_WF
    ]
    assert len(found) == 1 and "expects job `resolve` here" in found[0]["detail"], found
    renamed_gate = {
        BACKEND_DEPLOY_WF: jobs_yaml(
            ("version-gate", "release: renamed gate"),
            ("deploy", "backend: deploy"),
        )
    }
    found = [
        f for f in compare(repo(**deploy_with_gate).get, repo(**renamed_gate).get)
        if f["kind"] == "jobname" and f["name"] == BACKEND_DEPLOY_WF
    ]
    assert len(found) == 1, f"same-topology deploy names must stay strict: {found}"

    RELEASE_GATE_WF = ".github/workflows/_release-version-gate.yml"
    flutter_gate = {
        RELEASE_GATE_WF: jobs_yaml(("check", "tag matches pubspec")),
        "apps/mobile/package.json": None,
        "apps/mobile/pubspec.yaml": "name: mobile\n",
    }
    react_native_gate = {
        RELEASE_GATE_WF: jobs_yaml(("check", "tag matches the mobile version")),
        "apps/mobile/package.json": "{}\n",
        "apps/mobile/pubspec.yaml": None,
    }
    found = [
        f for f in compare(repo(**flutter_gate).get, repo(**react_native_gate).get)
        if f["kind"] == "jobname" and f["name"] == RELEASE_GATE_WF
    ]
    assert found == [], f"version-source topology may rename the check: {found}"
    poker_missing_release_gate = {
        RELEASE_GATE_WF: None,
        "apps/mobile/package.json": None,
        "apps/mobile/pubspec.yaml": None,
        "apps/backend/pyproject.toml": "[project]\nname = \"backend\"\n",
    }
    found = [
        f
        for f in compare(
            repo(**flutter_gate).get,
            repo(**poker_missing_release_gate).get,
        )
        if f["name"] == RELEASE_GATE_WF
    ]
    assert any(
        f["kind"] == "workflow"
        and "absent" in f["detail"]
        and ("present here" in f["detail"] or "expects an artifact" in f["detail"])
        for f in found
    ), f"a versioned Python owner may not lose its release gate: {found}"
    taven_without_release_gate = {
        RELEASE_GATE_WF: None,
        "apps/mobile/package.json": None,
        "apps/mobile/pubspec.yaml": None,
        "apps/backend/package.json": "{}\n",
        "apps/backend/pyproject.toml": None,
    }
    found = [
        f
        for f in compare(
            repo(**flutter_gate).get,
            repo(**taven_without_release_gate).get,
        )
        if f["name"] == RELEASE_GATE_WF
        or (f["kind"] == "action" and "_release-version-gate.yml" in f["name"])
    ]
    assert found == [], f"an unversioned backend is not a release-gate owner: {found}"
    unrelated_native_gate = {
        RELEASE_GATE_WF: jobs_yaml(("check", "release: unrelated claim")),
        "apps/mobile/package.json": "{}\n",
        "apps/mobile/pubspec.yaml": None,
    }
    found = [
        f for f in compare(repo(**flutter_gate).get, repo(**unrelated_native_gate).get)
        if f["kind"] == "jobname" and f["name"] == RELEASE_GATE_WF
    ]
    assert len(found) == 1, f"topology cannot excuse an arbitrary name: {found}"
    renamed_flutter_gate = {
        RELEASE_GATE_WF: jobs_yaml(("check", "tag matches renamed pubspec")),
        "apps/mobile/package.json": None,
        "apps/mobile/pubspec.yaml": "name: mobile\n",
    }
    found = [
        f for f in compare(repo(**flutter_gate).get, repo(**renamed_flutter_gate).get)
        if f["kind"] == "jobname" and f["name"] == RELEASE_GATE_WF
    ]
    assert len(found) == 1, f"same-source release names must stay strict: {found}"

    # Backend schema/e2e exceptions are Tarmoto-specific, not global. Two
    # Prisma repositories must report a missing e2e job; a TypeORM-to-Prisma
    # comparison suppresses the one-sided schema/e2e pair as topology.
    TYPEORM_MARKER = "apps/backend/src/data-source.ts"
    prisma_e2e = {
        JOB_WF: jobs_yaml(
            ("build", "backend: build"),
            ("test-e2e", "backend: e2e (real postgres)"),
        )
    }
    prisma_without_e2e = {JOB_WF: jobs_yaml(("build", "backend: build"))}
    found = [
        f for f in compare(repo(**prisma_e2e).get, repo(**prisma_without_e2e).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert len(found) == 1 and "test-e2e" in found[0]["detail"], found

    typeorm_schema = {
        JOB_WF: jobs_yaml(
            ("build", "backend: build"),
            ("schema", "backend: schema from zero (real postgres)"),
        ),
        TYPEORM_MARKER: "export const dataSource = true;\n",
    }
    found = [
        f for f in compare(repo(**prisma_e2e).get, repo(**typeorm_schema).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert found == [], f"TypeORM schema vs Prisma e2e is topology: {found}"

    typeorm_without_schema = {
        JOB_WF: jobs_yaml(("build", "backend: build")),
        TYPEORM_MARKER: "export const dataSource = true;\n",
    }
    found = [
        f for f in compare(repo(**prisma_e2e).get, repo(**typeorm_without_schema).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert len(found) == 1 and "expects job `schema` there" in found[0]["detail"], found

    typeorm_schema_renamed = {
        JOB_WF: jobs_yaml(
            ("build", "backend: build"),
            ("schema", "backend: renamed schema check"),
        ),
        TYPEORM_MARKER: "export const dataSource = true;\n",
    }
    found = [
        f for f in compare(repo(**prisma_e2e).get, repo(**typeorm_schema_renamed).get)
        if f["kind"] == "jobname" and f["name"] == JOB_WF
    ]
    assert len(found) == 1 and "job `schema` there: expected" in found[0]["detail"], found

    print("check-sibling-drift self-test passed")
    return 0


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()

    out_path = None
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]

    if not SIBLING:
        # Loud, for the same reason as the token below: a drift check pointed at
        # nothing reports no drift, which reads exactly like convergence.
        print(
            "::error::SIBLING_REPO is not set. This script does not assume a "
            "sibling -- the workflow names the repository to compare against, "
            "so the same file can run unchanged in every sibling repo.",
            file=sys.stderr,
        )
        return 1

    token = os.environ.get("SIBLING_TOKEN", "").strip()
    if not token:
        # Loud, not silent. A drift check that quietly does nothing is
        # indistinguishable from a drift check that finds nothing.
        print(
            "::error::SIBLING_TOKEN is not set. The sibling repository is "
            "private, so the comparison cannot run without a token that can "
            "read it.",
            file=sys.stderr,
        )
        return 1

    sibling = Sibling(SIBLING, SIBLING_REF, token)
    sibling.verify_access()
    sibling.resolve_ref()
    findings = compare(read_local, sibling.read)

    report = render(findings)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(report)

    print(f"  {len(findings)} difference(s) against {SIBLING}")
    for finding in findings:
        print(f"    [{finding['kind']}] {finding['name']}: {finding['detail']}")

    # The count goes to the workflow, which decides whether to open an issue.
    step_output = os.environ.get("GITHUB_OUTPUT")
    if step_output:
        with open(step_output, "a", encoding="utf-8") as handle:
            handle.write(f"count={len(findings)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
