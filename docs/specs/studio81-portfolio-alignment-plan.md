# Studio81 Labs Portfolio Alignment Plan

Status: proposed

Date: 2026-08-26

## Objective

Bring Poker Hero into the Studio81 Labs repository and infrastructure baseline
used by Nexcue, TableTap, and Tarmoto without changing Poker Hero's product
behavior or forcing unrelated application surfaces into the monorepo.

This plan is based on the local default branches at these revisions:

- Nexcue: `314cec8972589780072e641591b16eca9805d7dd`
- TableTap: `6bfbddc11466cd662089763f81e2d8bdaa689b12`
- Tarmoto: `84e94d72d97e2733b4d99b91715d81f832a12503`

## Narrowing Decisions

1. Rename `apps/frontend` to `apps/pwa`.
   `pwa` is already the portfolio convention for an installable web product in
   TableTap. `app` would introduce a new ambiguous name beside existing
   `admin`, `marketing`, `mobile`, and other product-specific app names.
2. Align shared posture, not application topology.
   GitHub action pins, supply-chain settings, release guards, cache cleanup,
   formatting, security scanning, CI naming, and deployment promotion should
   converge. Workflow bodies and app inventories may differ where the runtime
   stacks differ.
3. Do not add empty `admin`, `marketing`, or `mobile` applications.
   A new application belongs under `apps/` when it has an approved product
   purpose. Portfolio publication is handled in the Studio81 organization and
   marketing repositories, not by creating placeholder Poker Hero apps.
4. Keep `solver-plugins/postflop` in place.
   It is an intentional Rust runtime extension, comparable to other
   project-specific top-level tooling. Moving it would add deployment risk
   without improving the shared monorepo contract.
5. Keep the current deployment topology.
   The PWA remains a Cloudflare Worker Static Assets application with the
   same-origin API and MCP proxy. The backend remains a Coolify Docker service.
   TableTap's SSR PWA needs Coolify; Poker Hero's static Vite PWA does not.
6. Never cache poker data in the service worker.
   PWA support may cache the versioned application shell and static assets only.
   `/api/**`, `/mcp`, screenshots, uploads, recommendations, history, backups,
   and benchmark data must remain network-only and keep their existing
   privacy and consistency rules.

## Target Repository Shape

```text
apps/
  backend/                 FastAPI API, MCP gateway, parsers, providers, storage
  pwa/                     React/Vite product app and Cloudflare Worker proxy
packages/
  openapi/                 Deterministic backend OpenAPI artifact and tooling
  openapi-client/          Generated TypeScript contract consumed by the PWA
infra/
  docker/
    docker-compose.yml     Local stack, using repository-root build contexts
solver-plugins/
  postflop/                Rust postflop solver runtime extension
docs/
  decisions/               ADRs
  process/                 Runbooks
  reference/               Current architecture
  specs/                   Current product and migration specifications
scripts/
  ci/                      Shared and repository-specific CI guards
  lib/                     Shared shell helpers when required
```

The root should also contain the shared Studio81 repository shell:

- Node 24 and pnpm 11 pins;
- `tsconfig.base.json` for TypeScript workspace strictness;
- the organization Renovate preset plus Poker Hero-specific rules;
- pnpm supply-chain gates;
- Prettier, commitlint, Husky, labels, and contribution metadata;
- vendored Semgrep rules and scanner configuration.

## Delivery Plan

Each wave is independently reviewable and must leave `main` green. Do not mix a
directory rename with contract extraction or security-policy rollout; those
changes have different failure modes and rollback paths.

### Wave 1: Rename The Product App

Rename `apps/frontend` to `apps/pwa` without changing runtime behavior.

Required changes:

- move the directory with Git history preserved;
- rename the workspace package to `@poker-hero/pwa`;
- introduce `pwa:dev`, `pwa:test`, `pwa:test:watch`, `pwa:build`,
  `pwa:performance`, and PWA E2E root scripts;
- keep deprecated `frontend:*` aliases, including `frontend:test:watch`, for one
  migration cycle only, then remove them in Wave 3 after local scripts and
  deployment configuration are updated;
- rename `frontend-ci.yml` and `frontend-deploy.yml` to `pwa-ci.yml` and
  `pwa-deploy.yml` and update path filters, job names, concurrency groups, and
  deployment comments;
- update the `main` repository ruleset or branch protection in the same rollout
  so the required `Frontend CI / Frontend Test & Build` context is replaced by
  the exact renamed PWA workflow and job context;
- make `pwa-ci.yml` trigger on every pull request, move path selection inside
  the workflow, and expose one always-emitted required gate that succeeds only
  when PWA validation passed or was intentionally skipped;
- rename the Compose service from `frontend` to `pwa` and change Dockerfile,
  bundle-budget, OpenAPI export, Playwright, labeler, Renovate, and generated
  contract paths;
- update current README, contributor, product-spec, architecture, deployment,
  and agent documentation. Do not rewrite archived specifications;
- change the preferred conventional-commit scope from `frontend` to `pwa`, add
  `pwa` to the scope allowlists in `commitlint.config.js` and
  `.github/workflows/lint-pr.yml`, and retain `frontend` in both allowlists only
  through the one-cycle migration window.

Acceptance gates:

- no live reference to `apps/frontend` remains outside archived documentation;
- `main` requires the renamed PWA CI context, no longer requires the obsolete
  frontend context, and a test PR is blocked until the PWA check succeeds;
- a documentation-only or backend-only test PR emits and completes the required
  PWA gate instead of waiting forever on a path-filtered workflow;
- representative `fix(pwa): ...` commit and pull-request titles pass their
  respective commitlint and `lint-pr.yml` enforcement paths;
- `pnpm pwa:test`, `pnpm pwa:performance`, and `pnpm test:e2e` pass;
- both Docker images build from the repository root;
- `docker compose -f infra/docker/compose.yaml config` succeeds using the
  pre-alignment Compose filename.

### Wave 2: Extract The API Contract Packages

Match the portfolio's `packages/openapi` and `packages/openapi-client` boundary
without changing the backend contract.

Required changes:

- add a numbered ADR before moving files. It must define generator and artifact
  ownership, package dependency direction, Docker and CI build inputs,
  deployment and supply-chain consequences, and rollout and rollback behavior
  for the new contract boundary;
- move the deterministic OpenAPI JSON artifact out of the PWA source tree;
- generate the TypeScript contract into `packages/openapi-client`;
- expose generated types from `@poker-hero/openapi-client` and update PWA
  imports to use that package instead of relative generated paths;
- add `packages/*` to `pnpm-workspace.yaml` and add the root TypeScript base;
- add `_build-openapi.yml` as the reusable artifact producer and
  `openapi-check.yml` as the freshness gate;
- run `openapi-check.yml` on every pull request with internal change detection
  and an always-emitted final context, then add that exact context to the `main`
  ruleset as a required check;
- make `pnpm api:check` verify that every expected generated artifact is tracked,
  regenerate the contract, and reject staged, unstaged, or untracked changes in
  the generated output paths instead of relying on `git diff --exit-code` alone;
- make backend, PWA, and E2E workflows depend on the same generated contract
  artifact where appropriate;
- add `packages/openapi/**`, `packages/openapi-client/**`, and the root
  `tsconfig.base.json` to the internal PWA CI change detector so contract and
  shared compiler configuration changes run PWA validation instead of taking
  the intentional-skip path;
- add the same OpenAPI package and root TypeScript configuration paths to
  Browser E2E selection so a contract-only or shared compiler change starts the
  browser workflow instead of being excluded by its pull-request path filter;
- add `packages/openapi/**`, `packages/openapi-client/**`, and the root
  `tsconfig.base.json` to the PWA deployment push paths so contract or shared
  compiler configuration changes rebuild staging;
- update the PWA Dockerfile and its build context so workspace package manifests
  are available before `pnpm install` and the OpenAPI package sources are
  available before the production build;
- preserve deterministic generation and the existing backend contract tests.

Acceptance gates:

- the numbered ADR is linked from the architecture reference and describes the
  implemented package boundary;
- `pnpm api:generate` produces no uncommitted diff on a clean tree;
- `pnpm api:check` passes;
- a controlled stale-contract test PR fails the required OpenAPI freshness
  context and cannot merge, while an unrelated test PR still emits and
  completes that context;
- controlled deletion of each generated output fails `pnpm api:check` and the
  required freshness context even when regeneration recreates it as an
  untracked file;
- the PWA has no relative imports into an app-owned generated contract folder;
- `docker build -f apps/pwa/Dockerfile -t poker-hero-pwa:wave-2 .` succeeds with
  the extracted workspace packages available inside the build;
- a change set touching only either OpenAPI package or `tsconfig.base.json`
  selects and passes PWA tests and build rather than reporting an intentional
  skip from the required gate;
- the same package-only and shared-config-only change sets select and pass
  Browser E2E;
- a change set touching only either OpenAPI package or `tsconfig.base.json`
  selects `pwa-deploy.yml` instead of leaving staging on stale generated client
  or compiler configuration;
- backend tests, PWA tests/build, and browser E2E remain green.

### Wave 3: Align Repository And CI Infrastructure

Port the shared Studio81 baseline, adapting only topology-dependent details.

Before enforcing the baseline, add a numbered ADR that defines required-check
ownership, release-version policy, dependency/action/container/OS-package trust
sources and pin/update rules, exception governance, operational ownership,
rollout, and rollback for the new security and deployment posture.

Shared workflows and guards to add or converge:

- `_release-version-gate.yml` using the root Poker Hero version as the source;
- `format-check.yml`, running on every pull request with an always-emitted final
  context that is required by the `main` ruleset;
- `security-scan.yml` with secret scanning; Node, Python, and Rust dependency
  scanning over `pnpm-lock.yaml`, committed Python lockfiles, and
  `solver-plugins/postflop/Cargo.lock`; and JavaScript/TypeScript/Python Semgrep
  coverage, including the PWA edge Worker proxy boundary;
- `ci-scripts.yml` with self-tests for every added CI helper;
- `cleanup-pr-caches.yml` and `prune-stale-caches.yml`;
- `sibling-drift.yml` and its checked script;
- `labeler.yml`, `lint-pr.yml`, action digest pins, and job-name grammar;
- app-specific `backend-ci`, `backend-deploy`, `pwa-ci`, `pwa-deploy`, and E2E
  workflows on the same conventions.

Concrete convergence rules:

- use `github.event.pull_request.number || github.sha` for CI concurrency so
  quick merges cannot cancel validation of an intervening `main` commit;
- use the same pinned GitHub Action revisions across all four repositories;
- pin every external container image used by production Dockerfiles, CI
  workflows, or scripts, including Dockerfile `# syntax` frontend images, the
  backend CI `docker run` Rust image, and the backend and PWA build/runtime
  images, to an immutable SHA-256 digest while retaining its readable version
  tag, and configure Renovate to update those pins;
- replace the backend image's live Debian package resolution with a dated,
  immutable Debian snapshot and an exact `gosu` package version, retain package
  signature verification, and add a checked update procedure for both pins;
- generate committed production and development Python lockfiles with complete
  transitive pins and hashes from `apps/backend/pyproject.toml` using a pinned
  compiler; define exact `[build-system].requires` versions and include their
  build backend in both locks; require a no-diff freshness check; install the
  development lock in backend CI and the production lock in the backend image
  with hash checking, then install the local project with `--no-deps` and
  `--no-build-isolation` instead of resolving runtime or build-system ranges;
- use job names in `<area>: <what it proves>` form;
- whenever that naming change affects a required check, atomically replace the
  old context in the `main` ruleset or branch protection with the exact emitted
  context before relying on the renamed workflow;
- add the final secret, dependency, and Semgrep policy contexts emitted by
  `security-scan.yml` to the `main` ruleset as required checks in the same
  rollout;
- keep every required context observable on every pull request. Path-scoped
  workflows must move change detection inside the workflow and finish through
  an always-emitted gate rather than filtering out the complete workflow;
- keep deployment promotion as `main` to staging, `v*` to production, and
  explicit manual environment selection;
- require the release-version gate before every production-capable deploy;
- include every Docker/workspace/CI script input in deployment path filters;
- install deployment CLIs, including Wrangler and the Sentry CLI, as exact
  workspace development dependencies and invoke their lockfile-resolved
  binaries through `pnpm exec`; deployment workflows must not resolve
  `wrangler@latest` or an unversioned CLI from the network;
- rename `infra/docker/compose.yaml` to the portfolio-standard
  `infra/docker/docker-compose.yml` and update every script and current
  documentation reference atomically;
- update to the portfolio pnpm pin and enable the common
  `minimumReleaseAge`, `blockExoticSubdeps`, and `trustPolicy` posture;
- extend `github>Studio81Labs/.github:renovate-base`, retaining only Poker
  Hero-specific scopes, Python/Rust managers, and exclusions locally;
- remove the deprecated `frontend:*` root-script aliases and the `frontend`
  commit/PR-title scope after every live consumer uses the `pwa:*` commands and
  scope;
- preserve `uptime-monitor.yml` as a Poker Hero-specific additional workflow.

The sibling drift checker must be generalized in this wave before Poker Hero is
enrolled in Wave 5. Its current manifest assumes that every sibling has admin,
marketing, mobile, and shared OpenAPI workflows. Add marker-based topology gates
for those surfaces and copy the generalized checker to all four repositories.
Install Poker Hero's workflow with manual dispatch only, and leave every
`SIBLING_REPOS` list and the Poker Hero schedule unchanged until Wave 5. This
keeps the checker testable without prematurely enrolling the repository or
creating permanent topology noise.

Acceptance gates:

- the numbered security-baseline ADR is linked from the architecture reference
  and matches the implemented ruleset, release gates, scanners, trust policy,
  pinning, exception, and rollback behavior;
- every workflow parses and every referenced local reusable workflow exists;
- every final required-check context matches a check emitted by the converged
  workflows, no superseded context remains required, and a test PR cannot merge
  before those checks succeed;
- a controlled formatting violation fails the always-emitted required format
  context and blocks its test PR from merging;
- test PRs with a controlled secret, vulnerable Node, Python, and Rust dependency
  fixtures, or a Semgrep violation fail the corresponding required security
  context and cannot merge; the Semgrep cases include a JavaScript violation in
  the PWA edge Worker;
- regenerating both Python locks from the backend manifest produces no diff;
  backend CI and Docker use hash-checked frozen inputs, `pip check` passes, and
  a network-disabled local project installation succeeds with both `--no-deps`
  and `--no-build-isolation`; no backend build path performs unconstrained
  runtime or isolated build-system dependency resolution;
- documentation-only and backend-only test PRs emit every required gate and do
  not remain pending because a workflow-level path filter skipped the context;
- the PWA deployment reports the declared lockfile-pinned Wrangler version and
  no deployment workflow contains `pnpm dlx wrangler@latest` or another
  floating CLI invocation;
- every Dockerfile `# syntax` frontend and `FROM` base, plus every CI workflow or
  script `container`, `services`, or `docker run` image, uses a tag plus
  `@sha256:` digest; Renovate recognizes each pin, both application images
  build, and the solver CI job passes from those pins;
- the backend Dockerfile uses only the declared Debian snapshot and exact `gosu`
  version, the installed package matches that version, and a guard rejects a
  live Debian mirror or unversioned OS-package installation;
- CI helper self-tests pass locally;
- formatting and security scans pass on the migration branch;
- backend, PWA, E2E, Docker, deployment-probe, and OpenAPI checks pass;
- `docker compose -f infra/docker/docker-compose.yml config` succeeds after the
  Compose rename;
- no deprecated `frontend:*` command alias or enforced `frontend` commit scope
  remains in root scripts, current workflow, lint configuration, or current
  process documentation;
- a dry local four-way drift comparison reports only documented topology
  differences;
- Poker Hero is not yet present in a sibling list and its drift schedule remains
  disabled.

### Wave 4: Add Installable PWA Support

Add PWA capability after the app is named and deployed as `apps/pwa`.

Required changes:

- add a numbered ADR before registering the service worker. It must define cache
  ownership and versioning, private-route exclusions, offline behavior,
  activation and update coordination, threat boundaries, and rollback through
  worker unregistration and cache removal;
- add a web app manifest with Poker Hero name, short name, scope, start URL,
  standalone display mode, theme colors, categories, and complete regular and
  maskable icon sets;
- add Apple touch icon and mobile web metadata;
- register a service worker with an explicit update lifecycle;
- cache only immutable hashed application assets and the minimum navigation
  shell needed to open the app;
- use network-only handling for all API, MCP, screenshot, upload, history,
  recommendation, benchmark, and backup routes;
- show a clear offline state instead of presenting stale analysis as current;
- add a centralized dirty-state contract for every user-authored local draft,
  including detected-state corrections, screenshot title/notes/tags, training
  answers, lesson notes, and any other unsaved workspace form;
- ensure a newly deployed service worker cannot force a reload while that dirty
  state is present, or during an active upload, approval, recommendation,
  restore, or benchmark operation;
- configure Worker/static-asset headers so the service worker is revalidated
  while content-addressed assets remain cacheable;
- document install, update, offline, and privacy behavior in the product spec
  and architecture reference.

Acceptance gates:

- the numbered service-worker ADR is linked from the architecture reference and
  matches the implemented persistence, security, update, and rollback behavior;
- Chromium recognizes the deployed application as installable;
- manifest icons, start URL, scope, display mode, and theme metadata validate;
- the service worker serves the shell offline after one successful load;
- requests below `/api/` and the exact `/mcp` route never enter Cache Storage;
- upload and recommendation flows still fail visibly and recover correctly
  when the network disappears;
- update-lifecycle tests cover every registered workspace form, including dirty
  detected-state corrections, screenshot title/notes/tags, training answers,
  and lesson notes; each defers reload and preserves the full draft until it is
  saved or cleared, or the user explicitly confirms discarding it;
- desktop and mobile Playwright projects cover installation metadata, worker
  scope, update behavior, offline shell, and network-only private routes.

### Wave 5: Publish Portfolio Membership

Complete the cross-repository organization work after a stable public PWA URL
and release status are known.

Required changes:

- add a numbered ADR before granting cross-repository workflow access. It must
  define token ownership, credential type, least-privilege scopes and repository
  access, secret storage, rotation and revocation, blast radius, incident
  response, and rollout and rollback behavior;
- add Poker Hero to `Studio81Labs/.github/profile/README.md` with its approved
  public URL, status badge, and post-hand training description;
- add the product to the Studio81 Labs marketing site's product surface when
  that surface is implemented, or track that work separately rather than
  editing unrelated journal content;
- set GitHub repository description, homepage, and topics consistently;
- add Poker Hero to the sibling lists in Nexcue, TableTap, and Tarmoto and add
  all three siblings to Poker Hero's list;
- configure the same `SIBLING_READ_TOKEN` and `infra-drift` workflow posture in
  every repository, then enable Poker Hero's scheduled drift trigger;

Acceptance gates:

- the numbered sibling-token ADR is linked from the architecture reference, and
  each repository's configured access matches its ownership, scope, rotation,
  revocation, and rollback requirements;
- the organization profile links to the correct deployed environment;
- no portfolio copy presents the tool as live-play assistance;
- every sibling drift workflow can read and compare all other private repos;
- each repository owns and updates only its own drift issue.

## Explicit Non-Goals

- changing poker parsing, approval, recommendation, training, or storage
  behavior;
- moving backend Python modules or Rust solver sources;
- switching the PWA from Cloudflare to Coolify or changing the backend's
  persistence model;
- adding placeholder admin, marketing, or mobile apps;
- caching screenshots, API responses, recommendations, job state, or MCP
  traffic for offline use;
- combining the five waves into one repository-wide rename and infrastructure
  rewrite.

## Final Validation

Before the portfolio alignment is considered complete, run:

```bash
pnpm install --frozen-lockfile
pnpm backend:test
pnpm api:check
pnpm pwa:test
pnpm pwa:performance
pnpm test:e2e
pnpm monitor:test
docker compose -f infra/docker/docker-compose.yml config
docker build -f apps/backend/Dockerfile -t poker-hero-backend:test .
docker build -f apps/pwa/Dockerfile -t poker-hero-pwa:test .
```

Also run the Rust solver suite, CI helper self-tests, Semgrep, the dependency
scanner, the deployment probe tests, and an isolated backup
export/verify/restore drill. Inspect the final diff for stale `frontend` paths,
unintended archived-doc churn, unpinned actions or container bases, cached
private routes, and undocumented deployment variables.
