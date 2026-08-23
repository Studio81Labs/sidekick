# Poker Hero Refactoring Program

Status: active implementation plan

## Objective

Finish the structural refactor of Poker Hero without changing its public API,
persisted data, poker behavior, or post-hand training workflows. The completed
application should have explicit domain ownership, generated API contracts,
small route and page composition roots, testable workflow stores, and backend
application services that are independent from FastAPI and file storage.

This program is complete when the exit criteria in this document pass. A file
being smaller is useful evidence, but it is not the goal by itself.

## Current Baseline

The existing refactor established useful frontend feature boundaries and stable
compatibility barrels. The remaining concentration is now visible:

| Area                  | Current concentration                                             | Main risk                                                                  |
| --------------------- | ----------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Frontend page         | `pages/analyzer/AnalyzerPage.tsx`, about 4,200 lines              | Queue, history, recovery, automation, and mutations share one render owner |
| Frontend server state | Handwritten fetch modules plus page and hook state                | Repeated loading, cancellation, cache, and stale-response behavior         |
| Frontend contracts    | Handwritten TypeScript interfaces mirror Pydantic models          | Backend and frontend can drift silently                                    |
| Backend API           | `app/api.py`, about 2,300 lines                                   | Bootstrap, middleware, routes, locks, stores, and use cases are coupled    |
| Backend contracts     | `app/models.py`, about 1,500 lines                                | Poker rules, persistence records, and wire schemas share one module        |
| Backend persistence   | `app/storage.py`, about 900 lines                                 | Repository behavior, blobs, serialization, and import journals are coupled |
| Training backend      | `app/training.py`, about 1,200 lines                              | Filtering, summaries, grading, and Markdown export share one module        |
| Tests                 | Several frontend and backend integration files exceed 2,000 lines | Fixtures and assertions are expensive to reuse or diagnose                 |

Large static poker policy tables and solver data are not split solely to meet a
line-count target. They are split only when ownership, generation, or testing
becomes clearer.

## Architectural Principles

1. Preserve behavior before moving ownership. Every migration begins with a
   contract or characterization test.
2. Server state has one owner. TanStack Query owns authoritative API reads and
   mutation cache updates; browser persistence remains a recovery projection.
3. Workflow state is explicit. Queue recovery, mutation leases, active-hand
   selection, and automation use one route-scoped analyzer reducer and commands,
   not a generic global object store.
4. UI state stays local. Dialog disclosure, input drafts, and transient visual
   state remain in their owning component or focused hook.
5. Generated wire contracts are not domain models. OpenAPI types describe HTTP;
   feature adapters expose stable application-facing values.
6. Runtime validation stays where trust changes. Existing cache and import
   validators remain until a replacement has equivalent legacy coverage.
7. Backend transports are adapters. FastAPI routers and MCP tools call the same
   application services and never implement lifecycle transitions themselves.
8. Persistence is behind ports. File storage remains the production adapter
   during this program; database and multi-user support become replaceable
   follow-up adapters.
9. Compatibility surfaces expire. Every temporary barrel or adapter has an
   owner, removal wave, and test proving it can be deleted.
10. Each pull request is deployable and independently reversible.

## Target Frontend

```text
apps/frontend/src/
  app/
    providers/
      AppProviders.tsx
      queryClient.ts
    router/
      AppRoutes.tsx
      paths.ts
    App.tsx
  pages/
    analyzer/
      AnalyzerRoute.tsx
      AnalyzerLayout.tsx
  workflows/
    analyzer/
      components/
      hooks/
      model/
      services/
      store/
  features/
    <interaction>/
      components/   # rendered feature UI and colocated tests/styles
      hooks/        # thin React integration
      model/        # interaction-local state and commands
      lib/          # interaction-local transformations
  domains/
    <domain>/
      api/          # query keys, query options, mutation adapters
      model/        # domain types, reducers, selectors, policies
      lib/          # pure transformations and compatibility adapters
  shared/
    api/
      generated/    # checked-in OpenAPI output; never hand edited
      transport.ts
      errors.ts
      compatibility/
    components/
    lib/
    types/          # frontend-only domain types, not duplicated wire DTOs
  test/
    apiServer.ts
    factories/
    renderApp.tsx
```

### Frontend State Ownership

| State                                                                                | Owner                                | Persistence                                                           |
| ------------------------------------------------------------------------------------ | ------------------------------------ | --------------------------------------------------------------------- |
| Jobs, history pages, training progress, benchmark reports, capabilities, system info | TanStack Query                       | Backend; selected queue/history snapshots remain recovery projections |
| Active job, queue order, attention markers, recovery phase, active mutation leases   | Route-scoped analyzer workflow store | Existing local/session storage adapters                               |
| Approved hand form and unsaved corrections                                           | Hand-review feature                  | Component lifecycle; user-approved server state wins after save       |
| Automation configuration                                                             | Automation feature store             | Existing browser setting format                                       |
| Capture stream and selected files                                                    | Capture feature                      | Memory only                                                           |
| Dialog open state, search drafts, expanded rows                                      | Owning component/hook                | Memory only unless product behavior explicitly persists it            |

The analyzer workflow store will use React context plus `useReducer`, selector
hooks, and service refs for timers, abort controllers, streams, and promises.
Zustand is not introduced because Query already owns server state and a second
general-purpose cache would obscure lease and recovery transitions. Zod is not
introduced during contract migration; existing runtime validators already own
legacy browser data and imported archive validation.

### Frontend Dependency Rules

- Dependency direction is `bootstrap -> app -> pages -> workflows`, then
  `features -> domains -> shared`.
- `pages` compose workflow and feature entry points, but contain no poker rules,
  persistence codecs, or mutation implementations.
- Workflows may compose features and domains. Features may import domains and
  shared modules. Domains may import shared modules only.
- Peer feature imports are forbidden. Existing peer-feature edges are captured
  in a temporary audited baseline; CI rejects additions while migration removes
  the baseline entries.
- Components may use their owner's hooks/model/lib. Model, API, store, service,
  and library modules may not import components.
- Generated API types may be imported only by transport and domain API adapters,
  not directly by components.
- Compatibility barrels must contain exports only.

## Target Backend

```text
apps/backend/app/
  bootstrap.py
  api/
    dependencies.py
    errors.py
    middleware.py
    routers/
      health.py
      pipeline.py
      jobs.py
      history.py
      training.py
      benchmarks.py
      backups.py
      mcp_admin.py
    schemas/
  application/
    commands/
    services/
      hand_workflow.py
      recommendation.py
      history.py
      training.py
      benchmarks.py
      datasets.py
      backups.py
      recovery.py
    ports/
      repositories.py
      blobs.py
      parsers.py
      recommendations.py
      coordination.py
      auth.py
  domain/
    poker/
    hands/
    training/
    benchmarks/
  infrastructure/
    files/
    plugins/
    auth/
  mcp/
  config/
```

### Backend Dependency Rules

- Domain modules import neither FastAPI, settings, filesystem, locks, HTTP
  clients, nor plugin registries.
- Application services depend on domain types and protocols from
  `application/ports`.
- Infrastructure implements ports and retains atomic writes, fsync, legacy
  decoding, plugin subprocesses, and deployment configuration.
- Routers decode requests, create commands, call services, and map typed errors
  to the existing HTTP contract.
- Browser API and MCP use the same application facade and actor context.
- One workspace coordinator owns lock ordering and cross-process mutation
  boundaries beneath every transport.

## API Contract Strategy

1. Give every public FastAPI operation a stable `operation_id` and explicit
   response model.
2. Export a deterministic OpenAPI 3.1 document from the application factory.
3. Generate checked-in TypeScript contracts with `openapi-typescript`.
4. CI regenerates the artifact and fails on a diff.
5. A shared transport preserves credentials, multipart uploads, abort signals,
   request IDs, retry metadata, 204 responses, and human-readable errors.
6. Feature API adapters translate generated wire contracts into stable domain
   values and own Query keys/options.
7. The current `shared/api/client.ts` remains a temporary compatibility facade
   until all consumers use feature API adapters.

The OpenAPI artifact is a compatibility gate. Route splitting must not change
paths, methods, status codes, request bodies, response fields, or error detail
shapes unless a separate product change explicitly approves it.

## Migration Program

### Wave 0: Baseline And Guardrails

Dependencies: none

- Merge the in-flight training-progress controller extraction.
- Check in this plan and record baseline file/module metrics.
- Add architecture tests for the target frontend areas and backend dependency
  direction before new packages appear. Snapshot current peer-feature imports
  as a shrinking legacy allowlist so new coupling fails immediately.
- Record current OpenAPI and representative JSON fixtures.

Gate: current frontend, backend, browser E2E, Docker build, and contract fixtures
pass without product changes.

### Wave 1: Generated API Contracts

Dependencies: Wave 0

- Add stable operation IDs and missing response models.
- Add deterministic OpenAPI export and `openapi-typescript` generation.
- Check in generated contracts and stale-generation CI.
- Preserve current handwritten types behind compatibility aliases.

Gate: OpenAPI diff is intentional, generated output is reproducible, and every
existing endpoint test still passes.

### Wave 2: Transport And Query Foundation

Dependencies: Wave 1

- Split API transport, error translation, and compatibility adapters.
- Install and configure `@tanstack/react-query` in `AppProviders`.
- Add domain query-key factories and API test utilities.
- Migrate system information and pipeline capabilities first.

Gate: no UI behavior change; retry, credentials, request ID, multipart, abort,
and human-readable error tests pass.

### Wave 3: Backend Router Decomposition

Dependencies: Wave 1; may run parallel with Wave 2

- Extract middleware, exception mapping, dependencies, and domain routers from
  `api.py`.
- Keep existing concrete stores and helper functions behind injected runtime
  dependencies for this wave.
- Split `test_api_flow.py` by route domain while preserving shared fixtures.

Gate: byte-equivalent successful JSON fixtures, equivalent error/status tests,
unchanged OpenAPI, and hosted MCP integration pass.

### Wave 4: Read-Model Query Migration

Dependencies: Wave 2

- Migrate benchmark overview/report, training progress, history reads, job
  reads, and queue reads to feature query adapters.
- Preserve queue/history browser caches as startup projections.
- Replace hook-local request counters only after Query tests cover cancellation
  and stale results.

Gate: reload, pagination, search snapshot, benchmark comparison, and training
review integration suites pass.

### Wave 5: Backend Domain And Contract Split

Dependencies: Wave 3

- Split poker state, job lifecycle, recommendation, training, pipeline, and
  benchmark models into owned modules.
- Pipeline, poker, recommendation, and training contracts now live under
  `app/domain`; `app/models.py` preserves compatibility exports while the job
  lifecycle and benchmark contracts migrate.
- Keep `models.py` as an exports-only compatibility surface during migration.
- Move lifecycle transitions into aggregate/domain functions with direct tests.

Gate: persisted legacy jobs and archives load unchanged; model validation and
OpenAPI remain stable.

### Wave 6: Repository Ports And Coordination

Dependencies: Wave 5

- Introduce hand, benchmark, import-journal, blob, and principal repository
  protocols.
- Split file adapters without changing on-disk formats.
- Move lock ordering, startup recovery, import resume, backup, and restore into
  an application workspace coordinator.
- Run the same repository conformance suite against each file adapter.

Gate: crash/recovery, stale recommendation, deletion during parsing,
multiprocess locking, backup, and import tests pass.

### Wave 7: Analyzer Workflow Store

Dependencies: Wave 4

- Define typed analyzer-workflow events and a pure reducer for active selection,
  attention, recovery phases, queue progress, and mutation leases. Server job
  records remain in Query rather than being copied into the reducer.
- Add `AnalyzerWorkflowProvider`, selector hooks, command hooks, and runtime
  service refs.
- Move browser persistence behind injected projection adapters.
- Keep API side effects in commands, outside the reducer.

Gate: reducer transition table tests plus existing upload, recovery, archive,
delete, and cross-tab integration tests pass.

### Wave 8: Backend Application Services

Dependencies: Wave 6

- Extract upload/parse, approve, recommend, training review, archive/delete,
  benchmark/dataset, backup, and recovery use cases.
- Use typed application errors and commands.
- Route both HTTP and MCP through the same services and actor context.

Gate: routers contain transport code only; service tests run with in-memory
ports; all file-backed integration tests pass.

### Wave 9: Frontend Mutation Commands

Dependencies: Waves 4 and 7

- Migrate upload/capture, approve/recommend, training review, metadata,
  archive/delete, benchmark import, and backup restore into domain commands.
- Update Query caches through explicit command outcomes and invalidate only the
  affected keys.
- Preserve idempotency IDs, abort behavior, mutation leases, and independent
  queue-item failure handling.

Gate: every mutation has success, definite failure, ambiguous failure/recovery,
and retry coverage.

### Wave 10: Analyzer Composition And Routes

Dependencies: Wave 9

- Replace `AnalyzerPage` with a thin `AnalyzerRoute` that mounts providers,
  layout, derived selectors, and feature composition.
- Extract header, input rail, queue/history rail, preview, review workspace,
  status footer, and dialog host as page composition components.
- Remove prop chains replaced by typed feature selectors/commands.
- Add durable routes for `/analyzer`, `/analyzer/jobs/:jobId`,
  `/analyzer/training`, and `/analyzer/benchmarks`; retain `/` as a compatibility
  redirect. Keep transient dialogs and unsaved form drafts out of URL state.

Gate: `AnalyzerRoute.tsx` is at most 300 lines, contains no direct fetch,
local/session storage, mutation lease, or poker transformation code, and all
browser workflows pass at desktop and mobile viewports.

### Wave 11: Test Architecture

Dependencies: may proceed incrementally; completes after Wave 10

- Replace monolithic fixtures with domain factories and a shared render helper.
- Introduce MSW only when the first Query adapter needs request-level tests.
- Split backend tests by router, service, domain, and repository contract.
- Add frontend and backend dependency-architecture checks.
- Add OpenAPI, persistence-format, and archive compatibility fixtures.

Gate: no production component lacks a colocated focused test; integration tests
cover workflows rather than implementation details; CI reports failures by
domain.

### Wave 12: Compatibility Removal And Final Audit

Dependencies: Waves 1-11

- Remove obsolete handwritten wire types, API client facade, temporary barrels,
  dead page helpers, and duplicated fixtures.
- Verify frontend and backend package dependency direction.
- Run security, privacy, accessibility, performance, Docker, backup/restore,
  E2E, and deployment smoke checks.
- Update architecture, contributor, and operational documentation.

Gate: all exit criteria pass and no compatibility layer remains without a
documented external consumer and removal policy.

## Parallel Delivery Map

| Track               | Work           | Dependencies                | Safe parallelism                                                       |
| ------------------- | -------------- | --------------------------- | ---------------------------------------------------------------------- |
| Contracts           | Waves 0-2      | Critical path               | One owner for OpenAPI and package lock                                 |
| Backend transport   | Wave 3         | Generated contract baseline | Parallel with frontend Query foundation                                |
| Backend core        | Waves 5, 6, 8  | Router characterization     | Separate model, repository, and service owners after interfaces freeze |
| Frontend reads      | Wave 4         | Query foundation            | One feature domain per agent                                           |
| Frontend workflow   | Waves 7, 9, 10 | Read migration              | Analyzer workflow owner coordinates command and route owners           |
| Tests/documentation | Wave 11        | Continuous                  | Parallel when file ownership is disjoint                               |

Agents work in isolated branches/worktrees. A coordinator integrates in
dependency order, runs the authoritative checks, and rejects scope expansion.
Parallel agents never edit the same package manifest, lockfile, compatibility
barrel, application bootstrap, or composition root.

## Model Allocation

| Model class                                    | Use                                                                                                          |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Frontier reasoning (`gpt-5.6-sol`, high)       | Workspace reducer/lease protocol, backend coordination and recovery, final cross-cutting architecture review |
| Balanced coding (`gpt-5.6-terra`, medium/high) | Router extraction, API adapters, Query migrations, repository ports, application services                    |
| Fast coding (`gpt-5.6-luna`, low/medium)       | Mechanical file moves, compatibility barrels, generated artifacts, fixture splits, documentation, formatting |

The stronger model is reserved for concurrency, recovery, and state-machine
work where a subtle mistake can corrupt persisted state. Mechanical migrations
use the lower-cost model and must be bounded by characterization tests.

## Agent Work Packages

Each package below is an independently reviewable branch. Packages in the same
row may run in parallel only when their path ownership is disjoint. The
coordinator owns integration, generated artifacts, shared manifests, lockfiles,
compatibility barrels, and the authoritative full-suite run.

| Package | Scope                                                             | Model and effort                                                                                | Exclusive ownership                                             | Depends on |
| ------- | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ---------- |
| A0      | Architecture baselines, metrics, and fixture inventory            | `gpt-5.6-luna`, medium                                                                          | Architecture tests and baseline fixtures                        | None       |
| A1      | OpenAPI IDs, response contracts, generation, and CI drift gate    | `gpt-5.6-terra`, high                                                                           | Backend wire annotations and generated contracts                | A0         |
| A2F     | Shared transport, Query provider, system/pipeline adapters        | `gpt-5.6-terra`, high                                                                           | Frontend manifest/lock, providers, transport, first domain APIs | A1         |
| A2B     | Runtime dependency container and first read-only routers          | `gpt-5.6-terra`, high                                                                           | Backend bootstrap and API package                               | A1         |
| A3R     | Remaining routers, one route domain per branch                    | `gpt-5.6-terra`, medium                                                                         | One router and its focused tests                                | A2B        |
| A4J     | Job, queue, and history read models                               | `gpt-5.6-terra`, high                                                                           | Job/history domain APIs and Query adapters                      | A2F        |
| A4T     | Training and benchmark read models                                | `gpt-5.6-terra`, medium                                                                         | Training/benchmark domain APIs and Query adapters               | A2F        |
| A5      | Domain model split with compatibility exports                     | `gpt-5.6-terra`, high                                                                           | One backend domain plus its model tests per branch              | A3R        |
| A6R     | Repository protocols and file-adapter conformance                 | `gpt-5.6-terra`, high                                                                           | Ports, one repository adapter, and contract tests               | A5         |
| A6C     | Lock ordering, recovery, import, backup, and restore coordinator  | `gpt-5.6-sol`, high                                                                             | Workspace coordinator and concurrency tests                     | A6R        |
| A7      | Analyzer reducer, events, leases, and runtime services            | `gpt-5.6-sol`, high                                                                             | Analyzer workflow store and transition tests                    | A4J, A4T   |
| A8      | Application services, one use-case domain per branch              | `gpt-5.6-terra`, high                                                                           | One service and its in-memory-port tests                        | A6C        |
| A9      | Mutation commands and cache outcomes                              | `gpt-5.6-sol`, high for recovery-sensitive core; `gpt-5.6-terra`, medium for ordinary mutations | One command domain per branch                                   | A7, A8     |
| A10C    | Mechanical pane and dialog composition extraction                 | `gpt-5.6-luna`, medium                                                                          | One component subtree and colocated tests                       | A9         |
| A10R    | Route provider integration, deep links, and navigation guards     | `gpt-5.6-sol`, high                                                                             | Analyzer route, workflow composition, router                    | A10C       |
| A11     | Fixture/test splits and compatibility matrices                    | `gpt-5.6-luna`, medium; escalate failing behavioral gaps to `gpt-5.6-terra`                     | One test domain per branch                                      | Continuous |
| A12     | Compatibility removal, security/performance audit, and final docs | `gpt-5.6-sol`, high for audit; `gpt-5.6-luna`, medium for approved removals/docs                | Coordinator-selected final surfaces                             | A1-A11     |

Agent prompts must name the exact write set, compatibility behavior, required
checks, and prohibited neighboring files. Agents commit only their owned paths.
When a package reveals a cross-cutting interface change, work pauses at the
interface proposal; the coordinator updates the contract before parallel work
resumes. This keeps cheaper agents on bounded mechanical work and spends the
frontier model only where concurrent state or recovery correctness warrants it.

## Pull Request Contract

Every implementation PR must include:

- one migration objective and its wave number;
- explicit compatibility behavior;
- changed dependency direction;
- focused tests and full affected-app validation;
- risk and rollback notes;
- updated architecture or migration status;
- no unrelated formatting or product behavior changes.

## Implementation Status

| Wave | Status      | Current work                                                                                                                                                            |
| ---- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 0    | In progress | Plan, architecture guardrails, dependency baseline, and full-suite baseline are established                                                                             |
| 1    | In progress | Stable operation IDs, deterministic generation, binary contracts, and schema dependency pins landed                                                                     |
| 2    | In progress | Query provider, shared transport, and system/pipeline domain reads landed with compatibility behavior                                                                   |
| 3    | Complete    | All HTTP route domains have focused routers and runtime boundaries; route integration suites are split by domain, and the legacy shared API flow suite has been removed |
| 4    | Pending     | Begin as its documented dependencies and compatibility gates pass                                                                                                       |
| 5    | In progress | Pipeline, poker state, and recommendation contracts moved under `app/domain`; `app.models` preserves compatibility exports while remaining domains migrate              |
| 6-12 | Pending     | Begin as their documented dependencies and compatibility gates pass                                                                                                     |

## Exit Criteria

The refactoring program is finished when all of the following are true:

- `AnalyzerRoute.tsx` is no more than 300 lines and is a composition root.
- No peer feature imports or legacy feature-dependency allowlist entries remain.
- No frontend component or hook owns both HTTP transport and browser persistence.
- Authoritative server data is accessed through domain Query adapters.
- Cross-feature workflow changes are represented as typed reducer events and
  commands with transition tests.
- Frontend wire contracts are generated from deterministic OpenAPI output.
- `api.py` is replaced by bootstrap/router composition and contains no use case.
- FastAPI routers do not access file stores, plugin registries, or locks directly.
- Backend application services run against protocol-based test doubles.
- File persistence formats and backup/dataset archives remain backward compatible.
- HTTP and MCP invoke the same application services and authorization context.
- Frontend and backend dependency architecture is enforced in CI.
- Monolithic tests are split into domain fixtures and focused suites.
- Full frontend, backend, solver, browser E2E, Docker, backup/restore, and
  deployment smoke validation passes.
- Architecture and contributor documentation describe the actual final tree.

## Deferred Product Work

The program prepares, but does not itself add, user registration, account pages,
multi-tenant ownership, a database, or public deployment. Those changes begin
after repository ports, actor context, generated contracts, and route-level
frontend providers are stable.
