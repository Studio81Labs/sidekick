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
- introduce `pwa:dev`, `pwa:test`, `pwa:build`, `pwa:performance`, and PWA E2E
  root scripts;
- keep deprecated `frontend:*` aliases for one migration cycle only, then
  remove them after local scripts and deployment configuration are updated;
- rename `frontend-ci.yml` and `frontend-deploy.yml` to `pwa-ci.yml` and
  `pwa-deploy.yml` and update path filters, job names, concurrency groups, and
  deployment comments;
- rename the Compose service from `frontend` to `pwa` and change Dockerfile,
  bundle-budget, OpenAPI export, Playwright, labeler, Renovate, and generated
  contract paths;
- update current README, contributor, product-spec, architecture, deployment,
  and agent documentation. Do not rewrite archived specifications;
- change the preferred conventional-commit scope from `frontend` to `pwa`.

Acceptance gates:

- no live reference to `apps/frontend` remains outside archived documentation;
- `pnpm pwa:test`, `pnpm pwa:performance`, and `pnpm test:e2e` pass;
- both Docker images build from the repository root;
- `docker compose -f infra/docker/compose.yaml config` succeeds using the
  pre-alignment Compose filename.

### Wave 2: Extract The API Contract Packages

Match the portfolio's `packages/openapi` and `packages/openapi-client` boundary
without changing the backend contract.

Required changes:

- move the deterministic OpenAPI JSON artifact out of the PWA source tree;
- generate the TypeScript contract into `packages/openapi-client`;
- expose generated types from `@poker-hero/openapi-client` and update PWA
  imports to use that package instead of relative generated paths;
- add `packages/*` to `pnpm-workspace.yaml` and add the root TypeScript base;
- add `_build-openapi.yml` as the reusable artifact producer and
  `openapi-check.yml` as the freshness gate;
- make backend, PWA, and E2E workflows depend on the same generated contract
  artifact where appropriate;
- update the PWA Dockerfile and its build context so workspace package manifests
  are available before `pnpm install` and the OpenAPI package sources are
  available before the production build;
- preserve deterministic generation and the existing backend contract tests.

Acceptance gates:

- `pnpm api:generate` produces no uncommitted diff on a clean tree;
- `pnpm api:check` passes;
- the PWA has no relative imports into an app-owned generated contract folder;
- `docker build -f apps/pwa/Dockerfile -t poker-hero-pwa:wave-2 .` succeeds with
  the extracted workspace packages available inside the build;
- backend tests, PWA tests/build, and browser E2E remain green.

### Wave 3: Align Repository And CI Infrastructure

Port the shared Studio81 baseline, adapting only topology-dependent details.

Shared workflows and guards to add or converge:

- `_release-version-gate.yml` using the root Poker Hero version as the source;
- `format-check.yml`;
- `security-scan.yml` with secret, dependency, and TypeScript/Python Semgrep
  coverage;
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
- use job names in `<area>: <what it proves>` form;
- keep deployment promotion as `main` to staging, `v*` to production, and
  explicit manual environment selection;
- require the release-version gate before every production-capable deploy;
- include every Docker/workspace/CI script input in deployment path filters;
- rename `infra/docker/compose.yaml` to the portfolio-standard
  `infra/docker/docker-compose.yml` and update every script and current
  documentation reference atomically;
- update to the portfolio pnpm pin and enable the common
  `minimumReleaseAge`, `blockExoticSubdeps`, and `trustPolicy` posture;
- extend `github>Studio81Labs/.github:renovate-base`, retaining only Poker
  Hero-specific scopes, Python/Rust managers, and exclusions locally;
- preserve `uptime-monitor.yml` as a Poker Hero-specific additional workflow.

The sibling drift checker must be generalized before Poker Hero is enrolled.
Its current manifest assumes that every sibling has admin, marketing, mobile,
and shared OpenAPI workflows. Add marker-based topology gates for those
surfaces, copy the generalized checker to all four repositories, and only then
add Poker Hero to each `SIBLING_REPOS` list. Otherwise the scheduled report will
permanently flag intentionally absent applications and become noise.

Acceptance gates:

- every workflow parses and every referenced local reusable workflow exists;
- CI helper self-tests pass locally;
- formatting and security scans pass on the migration branch;
- backend, PWA, E2E, Docker, deployment-probe, and OpenAPI checks pass;
- `docker compose -f infra/docker/docker-compose.yml config` succeeds after the
  Compose rename;
- a dry local four-way drift comparison reports only documented topology
  differences;
- the required `SIBLING_READ_TOKEN` secret is configured before enabling the
  schedule.

### Wave 4: Add Installable PWA Support

Add PWA capability after the app is named and deployed as `apps/pwa`.

Required changes:

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
- ensure a newly deployed service worker cannot force a reload during an
  active upload, approval, recommendation, restore, or benchmark operation;
- configure Worker/static-asset headers so the service worker is revalidated
  while content-addressed assets remain cacheable;
- document install, update, offline, and privacy behavior in the product spec
  and architecture reference.

Acceptance gates:

- Chromium recognizes the deployed application as installable;
- manifest icons, start URL, scope, display mode, and theme metadata validate;
- the service worker serves the shell offline after one successful load;
- requests below `/api/` and the exact `/mcp` route never enter Cache Storage;
- upload and recommendation flows still fail visibly and recover correctly
  when the network disappears;
- desktop and mobile Playwright projects cover installation metadata, worker
  scope, update behavior, offline shell, and network-only private routes.

### Wave 5: Publish Portfolio Membership

Complete the cross-repository organization work after a stable public PWA URL
and release status are known.

Required changes:

- add Poker Hero to `Studio81Labs/.github/profile/README.md` with its approved
  public URL, status badge, and post-hand training description;
- add the product to the Studio81 Labs marketing site's product surface when
  that surface is implemented, or track that work separately rather than
  editing unrelated journal content;
- set GitHub repository description, homepage, and topics consistently;
- add Poker Hero to the sibling lists in Nexcue, TableTap, and Tarmoto and add
  all three siblings to Poker Hero's list;
- configure the same `SIBLING_READ_TOKEN` and `infra-drift` workflow posture in
  every repository.

Acceptance gates:

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
