# ADR 0041: Compose the Frontend by Feature Boundaries

## Status

Accepted, amended 2026-08-25

The Wave 12 compatibility-removal program supersedes this decision where it
designated `src/shared/types.ts` as a stable type barrel and
`src/shared/api/client.ts` as a stable client barrel. Focused contract and API
modules remain, but all consumers now import their owning module directly and
the source-architecture suite prevents either facade from being recreated.
Other compatibility surfaces named in this ADR remain in force until
separately amended or superseded.

## Context

The control panel accumulated capture, queue recovery, hand correction,
training, recommendation, benchmark, metadata, and dialog behavior in
`App.tsx`. The root component mixed deterministic poker transformations,
feature-local asynchronous state, and page rendering with the cross-feature
queue/history mutation protocol. This made otherwise focused changes depend on
one very large implementation and encouraged further growth in the same file.

Moving all root code into a single custom hook would preserve the same coupling
behind a different name. Splitting every callback into an isolated hook would
also obscure the persistence transactions that intentionally coordinate queue
and history state.

## Decision

Compose the frontend using four explicit boundaries:

- `src/app` owns the router shell, route registry, error boundary, and other
  application-wide concerns.
- `src/pages` owns route-level composition. The analyzer page coordinates the
  queue/history mutation, lease, recovery, and automation transactions that
  span multiple features.
- `src/features` groups components, colocated styles, hooks, and non-React
  support by product domain.
- `src/shared` contains reusable UI controls, API access, primitive types, and
  domain-independent helpers.

Shared API access separates transport, response decoding, and human-readable
errors from jobs, history, training, benchmark, system, and MCP endpoints.
Consumers import those focused owners directly, while endpoint tests stay
beside their owning module; no cross-domain API client facade is retained.

Shared API contracts follow the same ownership split. Poker state,
recommendations, training, jobs, pipeline capabilities, benchmarks, system,
backup, and MCP contracts live in focused `shared/types` modules. Application,
feature, test, and API modules import their owning contracts directly; no
cross-domain type barrel is retained.

The workspace feature separates browser-cache validation, mutation leases,
processing-queue persistence, history persistence, and reconciliation into
focused library modules. `workspace/lib/persistence.ts` remains a compatibility
barrel for the page coordinator, not an owner of persistence behavior.
Cache validation further separates primitive bounds, poker and completed-street
state, recommendation and training payloads, and full parser/job records.
`workspace/lib/cacheValidation.ts` remains the stable validation compatibility
barrel.
Mutation leases further separate their persisted contracts, job and projection
expectations, lease matching, legacy decoding, browser storage, and factories.
`workspace/lib/mutationLeases.ts` remains the stable lease compatibility barrel.

Recommendation presentation follows the same pattern under the recommendation
domain model: parser routing, preflop and postflop evidence, candidate ranking,
formatting, and metadata validation are separate modules. The former
recommendation, postflop-evidence, and preflop-evidence compatibility barrels
are removed; feature consumers import their precise domain owner.

Training presentation separates queue status and focus ranking into focused
feature modules. Decision comparison, sizing, and shared option definitions
live in the training domain model; the former
`training/lib/trainingPresentation.ts` compatibility barrel is removed.
Training progress delegates report loading, query filters, stale-response
protection, and optimistic-filter rollback to a focused state hook. Its
controller retains dialog commands and opening a selected training hand.

Poker state separates card and number parsing, form/canonical conversion,
stable identity keys, constants, and preflop position normalization under the
poker domain model. Hand review retains confidence presentation and imports the
precise domain owners; the former `hand-review/lib/pokerState.ts` compatibility
barrel is removed.

Cross-feature hand-review rendering is composed at the analyzer page layer.
`HandReviewPanel` receives its decision content as a slot, while
`HandReviewWorkspace` owns recommendation and training-decision component
composition from separate typed prop groups.

The parser benchmark dialog composes focused owners for pipeline comparison,
report overview, result sections, expandable case review, and dataset/run
actions. The dialog itself retains only its public contract, close lifecycle,
ground-truth toggle, and loading or empty-state composition.
The benchmark controller delegates report catalog loading, stale-request
protection, report caching and selection, and previous-run comparison to a
focused report-state hook. It retains parser selection, benchmark execution,
dialog commands, and opening benchmark hands.
Benchmark report comparison, case trends, report caching, parser-route
aggregation, and value formatting are separate library modules behind the
stable `benchmark/lib/benchmarkPresentation.ts` compatibility barrel.

`App.tsx` remains deliberately small and mounts the route registry. The
analyzer page passes explicit state and commands into feature hooks and
components. New feature behavior belongs in the closest existing boundary; it
may enter a page coordinator only when it participates in cross-feature
orchestration. New top-level experiences receive their own page and route.

## Consequences

- Feature rendering and lifecycles can be tested without reproducing the full
  application coordinator.
- Page styles describe page composition; feature and shared-component selectors
  are loaded by their owning component boundary.
- Poker, persistence, benchmark, recommendation, and training support no longer
  depends on React rendering.
- Queue/history recovery stays centralized and reviewable instead of being
  fragmented across feature hooks.
- The application shell is ready for authentication and account routes without
  coupling those experiences to the analyzer workspace.
- The analyzer page can remain larger than a conventional component, but its
  size represents explicit orchestration rather than embedded feature UIs and
  domain algorithms.
- Component tests are colocated with their owners, while analyzer integration
  tests are grouped by workflow domain.
- Dense dialogs remain readable composition roots; independently interactive
  sections own their calculations, local disclosure state, and direct tests.
- The shared transport barrel remains a compatibility surface rather than an
  implementation owner. Type definitions have no compatibility barrel and are
  imported from matching domain modules.
- Workspace recovery keeps one public import surface while storage schemas,
  lease durability, pagination, and reconciliation can be tested independently.
- Benchmark components and controller code keep one presentation import surface
  without coupling report caching, case comparison, or route aggregation.
- A source-architecture test enforces downward imports between app, page,
  feature, and shared layers. It also keeps feature library and hook code
  independent from UI components and requires colocated component tests. The
  root `main.tsx` bootstrap may import only the application layer; other
  undeclared top-level source locations fail the architecture check. Feature
  production code must live below `components`, `hooks`, or `lib`; feature-root
  barrels and undeclared feature areas are rejected so they cannot conceal
  component dependencies from hooks or libraries. Production modules also may
  not import colocated tests, integration suites, or shared test helpers. TSX
  and CSS feature source must live below `components`, and parsed CSS imports,
  module compositions, value imports, and ICSS imports follow the same layer
  direction as TypeScript imports. The audit rejects JavaScript modules below
  `src` so they cannot bypass the TypeScript source graph, and it resolves
  static Vite glob, `import.meta.url`, and triple-slash path dependencies before
  applying the same boundaries.
- Future reviews should reject new feature-local UI, effects, or transformation
  logic added directly to `App.tsx` or the analyzer page without the matching
  application-level or cross-feature reason.
