# ADR 0043: Adopt The Studio81 Security And CI Baseline

Status: accepted

Date: 2026-08-26

## Context

Poker Hero is joining the Studio81 Labs portfolio, but its dependency installs,
container builds, deployment tools, and required checks did not yet have the
same reproducibility and trust boundaries as Nexcue, TableTap, and Tarmoto.
Several production paths resolved packages or CLIs from the network at build or
deploy time. Required-check names also depended on workflow-local wording, so a
rename could leave branch protection waiting for a context no workflow emitted.

## Decision

The repository adopts the shared Studio81 CI and supply-chain posture.

The `main` branch protection contexts are owned jointly by the portfolio
infrastructure maintainers and the Poker Hero application owners. The exact
required contexts are:

- `Validate PR title`;
- `ci: formatting`;
- `pwa: gate`;
- `contract: gate`;
- `security: secrets`;
- `security: dependencies`;
- `security: code (semgrep)`.

Every required context is emitted for every pull request. Path selection for the
PWA and contract runs inside their workflows and ends at an `always()` gate.
Required contexts are replaced atomically in branch protection whenever a job
name changes; a workflow is never removed before its context is removed.

The root `package.json` version is Poker Hero's release source. A `v*` tag may
reach a production-capable deploy only when its suffix exactly equals that
version. Pushes to `main` promote to staging, matching tags promote to
production, and manual dispatch explicitly chooses an environment. Non-tag
staging and manual runs pass the reusable version gate without inventing a tag.

Trusted dependency inputs and update rules are:

- GitHub Actions use reviewed commit SHA pins and the same revisions as sibling
  repositories. Renovate proposes updates through the shared organization
  preset.
- OCI images retain a readable version tag and an immutable SHA-256 digest.
  This includes Dockerfile syntax frontends, build/runtime bases, scanners, and
  images invoked by scripts or CI. A checked helper rejects mutable references.
- Debian packages come only from the dated snapshot declared in the backend
  Dockerfile. Archive signatures remain mandatory, snapshot expiry is the only
  disabled time check, and `gosu` is installed at one exact Debian version.
- npm resolution uses the portfolio pnpm version, a 24-hour release-age window,
  registry-only transitive packages, and the no-downgrade provenance policy.
- Python production and development graphs are compiled under the pinned
  Python 3.12 container with the pinned `pip-tools` version. Both committed
  locks contain hashes and the exact setuptools build backend. CI and Docker
  install a lock with `--require-hashes`, then install local source with both
  `--no-deps` and `--no-build-isolation`.
- Rust dependencies remain fixed by `solver-plugins/postflop/Cargo.lock` and are
  tested with `cargo --locked` in a digest-pinned Rust image.
- Wrangler and the Sentry CLI are exact workspace dependencies invoked through
  `pnpm exec`; deployment must not fetch a floating CLI.

Secret scanning gates each pull-request range and performs a verified-only full
history scan when the scanner changes or an audit is dispatched. OSV scans all
committed Node, Python, and Rust lockfiles on pull requests, pushes, and weekly.
Vendored Semgrep rules cover JavaScript, TypeScript, Python, and configuration
files; a custom fixture proves the PWA Worker dynamic-code rule fires before the
full scan is trusted.

An exception must be narrow, version-specific, documented beside the pin and in
an ADR amendment, assigned to an owner, and include a removal condition. A
scanner, hash check, release gate, signature check, or required context may not
be bypassed merely to make a build green. Emergency production recovery uses a
reviewed revert or a separately approved deployment of the last known-good
commit.

One non-security migration exception is recorded for the PWA TypeScript project:
the shared root enables `noUncheckedIndexedAccess`, `noImplicitOverride`, and
`exactOptionalPropertyTypes`, while `apps/pwa/tsconfig.json` temporarily keeps
those three flags disabled. Enabling them currently exposes a broad existing
application/test typing migration unrelated to this infrastructure rollout.
The Poker Hero application owners own removal; the exception ends when a focused
type-hardening pull request makes `pnpm pwa:build` green without the overrides.
It does not weaken the OpenAPI client project, scanners, dependency controls, or
deployment gates.

TruffleHog's `Lob` detector is excluded temporarily. Version 3.96.0 reports
eleven “verified” Lob credentials on ordinary poker-test expressions and legacy
planning prose; a full-history audit with every other detector reports zero.
The Poker Hero application owners must re-run the full audit without this
exclusion on each TruffleHog update and remove it when the upstream detector no
longer reproduces those false positives. All other detectors still gate both the
pull-request range and deliberate full-history audits.

## Consequences

Builds and deploys are repeatable from reviewed manifests and locks. Newly
published or lower-trust packages can temporarily block an update, and Python
dependency changes require explicit lock regeneration. Security findings become
merge blockers instead of advisory logs. Renaming a required job now requires a
coordinated branch-protection change.

The manual sibling-drift workflow is installed without a schedule or persistent
sibling list. Its checker uses topology markers for admin, marketing, mobile,
and shared OpenAPI surfaces, allowing portfolio convergence without reporting
apps a repository intentionally does not own.

## Operations, Rollout, And Rollback

Pin refresh and verification commands are documented in
`docs/process/dependency-pins.md`. The CI helper suite validates its own fixture,
container, topology, release, and override guards.

Rollout first lands every new workflow and observes its exact context on the
migration pull request. Only after all new contexts succeed does branch
protection replace `PWA Gate` and `OpenAPI Gate` with the final list above in one
API update. The old contexts are not retained.

Rollback reverses that order: restore the previous observable workflows and
required contexts first, then revert the baseline commit. A rollback may restore
the previous reviewed lock or image digest, but must not restore floating CLI,
container, Python, or Debian resolution. Security contexts remain required
unless another ADR records a time-bounded incident response approved by both
owners.
