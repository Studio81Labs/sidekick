# Architecture

The repository security, release, dependency-trust, and required-check baseline
is defined by
[ADR 0043](../decisions/0043-adopt-studio81-security-and-ci-baseline.md).
The installable browser shell, private-route cache exclusions, and coordinated
update lifecycle are defined by
[ADR 0044](../decisions/0044-installable-pwa-cache-and-update-lifecycle.md).
Cross-repository drift access, credential ownership, and incident handling are
defined by
[ADR 0045](../decisions/0045-enroll-portfolio-sibling-drift-access.md).
The V2 target player/operator boundary, import-first persistence lifecycle, and
capture-first migration are defined by
[ADR 0046](../decisions/0046-adopt-import-first-learning-boundary.md). This
reference continues to describe the currently deployed V1 architecture until
the ADR's gated migration work is implemented. In particular, the Worker proxy
and hosted file-backed API below are not an approved V2 player-data path: Phase 1
requires the ADR's loopback-only, authenticated co-located player runtime and
local writable system of record.
[ADR 0050](../decisions/0050-establish-local-player-runtime-security-substrate.md)
implements the first runtime security substrate as a separate loopback-only
application, one-use browser bootstrap, process-local authenticated session,
CSRF boundary, and reserved hosted namespace. Later checkpoints extend this
local composition, while V1 remains the deployed hosted product and the Phase 1
gate remains closed.
[ADR 0051](../decisions/0051-isolate-the-local-player-store-composition.md)
attaches only the imported-hand store to that runtime, enforces a private
player-owned data directory, performs interrupted-write recovery before
startup, and exposes authenticated read-only storage status. It still adds no
player-record or mutation route at that checkpoint.
[ADR 0059](../decisions/0059-version-the-local-player-workspace-layout.md)
adds the durable player-workspace compatibility boundary. A private immutable
version 1 manifest is validated before stores open; an existing manifestless
imported-hand layout is adopted under the exclusive data-volume lock without
rewriting retained record, artifact, or recovery bytes. Unknown, malformed,
insecure, or structurally incomplete layouts fail startup, and the authenticated
storage view discloses the active layout version.
[ADR 0060](../decisions/0060-export-before-removing-local-player-data.md)
adds a local-only export-before-remove transaction for the versioned player
workspace. It durably publishes and independently reparses a new portable
player backup before atomically moving the exact workspace out of service,
then cleans only that verified sibling path. Unsafe sources or destinations,
unresolved recovery evidence, unexported workspace entries, publication
failures, and layout drift fail closed. A stable sibling lifetime lease excludes
the running player process across the whole transaction and makes retained
post-rename paths discoverable on retry; application and browser installation
removal remain outside this checkpoint.
[ADR 0061](../decisions/0061-build-platform-scoped-player-runtime-bundles.md)
defines an unsigned host-platform release-bundle contract. The archive embeds
the Python runtime and verified player PWA, inventories application files with
SHA-256 digests, and exposes the existing export-before-remove transaction from
the same executable. Its clean-extraction smoke test proves repository-free
loopback launch, one-use bootstrap/session security, Host/Origin/CSRF and LAN
boundaries, and data removal. A supported OS installer, signing/publishing,
automatic updates, application-file removal, and browser-PWA removal remain
outside this checkpoint.
[ADR 0062](../decisions/0062-expose-bounded-local-pokerstars-import.md) adds
authenticated multipart PokerStars text import to the local player runtime.
Files and parsed hands are isolated, the first server timestamps remain
authoritative across an exact request replay, and every successful parser
proposal stays unapproved; new hand identities stay pending review. The PWA
preserves an outstanding request UUID across a required runtime restart only
when SHA-256 filename/content fingerprints match the reselected ordered files;
no filename or hand-history content enters browser storage. The UI and API
expose only the bounded adapter subset and make no #409 corpus or Phase 1 claim.
[ADR 0053](../decisions/0053-serve-a-dedicated-local-player-pwa.md) replaces
the inline readiness document with a separately built local recovery PWA. It
exposes storage/recovery status and the existing player backup/restore workflow
without importing the hosted administrative application or adding player
import, lifecycle, or learning routes at that checkpoint.
[ADR 0054](../decisions/0054-expose-local-approval-deactivation.md) adds the
first player-record mutations: stale-safe approval withdrawal and rejection
through the imported-hand cascade, serialized by stable thread and
process-shared record stripes.
[ADR 0055](../decisions/0055-expose-local-permanent-hand-deletion.md) adds
stale-safe permanent deletion for any retained player hand. It first publishes
an inactive deletion-pending generation, then purges hand-linked evidence to a
receipt-only tombstone that older backups cannot resurrect.
[ADR 0056](../decisions/0056-expose-local-canonical-hand-approval.md) adds
stale-safe correction and explicit approval/reapproval from one retained
detection. The server derives correction audit, preserves private evidence, and
binds exact retries to a unique approval ID.
[ADR 0063](../decisions/0063-expose-local-import-conflict-resolution.md) adds
stale-safe explicit resolution of retained import conflicts. Keeping the
preserved source may retain active learning; selecting a source first returns
an active hand to pending review and requires a separate explicit approval.
[ADR 0064](../decisions/0064-expose-authorized-deleted-hand-reimport.md) adds
explicit deleted-hand reimport. It advances the deletion generation and creates
a fresh pending-review aggregate while atomically removing the old
incarnation's retained decision artifacts.
[ADR 0065](../decisions/0065-expose-active-player-decision-read-model.md) adds
an authenticated local-only read model for the exact active decision artifact.
It re-derives the extraction from current canonical state, refuses inactive,
conflicted, missing, stale, or mismatched evidence, preserves an explicit
non-extractable verdict as reviewable but non-gradeable, and strips private
source excerpts from the response. Grading and later learning routes remain
unwired.
CI exercises that separation over real listeners. A browser consumes a one-use
launch URL from the production Uvicorn player application, proves all player
API traffic stays on its exact loopback origin, and verifies the service worker
cannot satisfy an offline player-data read. A separate local Wrangler process
runs the production hosted Worker against a recording backend; direct and
encoded `/api/player` POSTs must be denied without any backend request. The
test-only launch handoff and recorder do not participate in either production
runtime.
The retirement of the V1 screenshot-bound learning surface (recommendation
requests, training decisions, training review, progress, and lessons) is
defined by
[ADR 0047](../decisions/0047-retire-v1-screenshot-learning-surface.md). Every
stored screenshot job is now administrative OCR test data: upload/capture,
parser review and approval, benchmarking, history/archive, and backups remain,
while recommendation providers, local solvers, and the offline recommendation
benchmark remain only as settings-driven infrastructure with no per-job route.

## System Shape

Poker Hero is a two-app monorepo. The browser control panel never talks to OCR
or recommendation engines directly; the FastAPI backend owns those integrations
and normalizes all results into stable API models.

```text
Browser
  -> React/Vite PWA
  -> same-origin /api proxy (environment-specific Cloudflare Worker)
  -> FastAPI backend
     -> parser registry -> OCR/CV or external vision service
     -> file-backed job store in POKER_DATA_DIR
     -> parser benchmark -> explicit approved-state corpus and persisted reports
     -> provider registry -> local solver router, rule engine, or external service
        -> preflop chart, postflop-solver plugin, or bundled range/EV fallback

Post-hand agent
  -> environment-fixed MCP gateway (local stdio or authenticated hosted HTTP)
  -> environment Worker or trusted backend API
  -> the same FastAPI state flow
```

## Applications

### Backend

`apps/backend` owns upload validation, parser selection, canonical
state validation, automation-compatible job transitions, persisted job/image
data, and read-only parser benchmark runs. Environment-driven
registries define installed defaults and runtime allowlists. New uploads and
live captures may select an advertised parser and layout profile; that
selection is persisted on the job so the PWA flow does not depend on a
concrete engine.
Each installed parser is represented by one immutable catalog descriptor that
owns its factory, label, readiness check, and supported-layout policy. Runtime
construction and pipeline capabilities consume the same descriptor, while the
configuration allowlist remains a separately validated deployment boundary.
Recommendation providers follow the same catalog contract for their factory,
label, and readiness check. Local solver engines remain a nested selection of
the `local_solver` provider, chosen by `POKER_LOCAL_SOLVER_ENGINE` alone. Each
local engine descriptor owns its subprocess command factory, label, and
execution mode. The custom command is a deployment-fixed engine descriptor
rather than a selectable entry.
Layout profile IDs are deployment-defined data. The capability response includes
a parser/layout compatibility matrix: multi-layout external vision can accept
custom profiles such as `pokerstars`, while fixed-region OCR is selectable only
with profiles for which its coordinates and templates are calibrated.
Installed local OCR profiles resolve through an immutable layout registry. Each
layout supplies the reference dimensions and every card, pot, control, stack,
stakes-header, and opponent-seat region used during parsing. The legacy
`generic`, `fortuna`, `nations`, and `fortuna_nations` IDs intentionally alias
the same calibrated engine; an unknown local profile fails closed instead of
borrowing those coordinates.
Per-job mutations use bounded lock stripes around short storage transitions.
Screenshot parsing runs outside those stripes, then reloads and merges into the
latest job record so slow OCR does not block unrelated jobs and deleted uploads
cannot be recreated by parser completion.

Screenshot upload is an administrative OCR test surface, not a player data
path (ADR 0046). `POST /api/jobs` fails closed unless
`POKER_ADMIN_OCR_TEST_ENABLED` is set and the request carries the deployment's
`POKER_ADMIN_OCR_TEST_TOKEN` as a bearer credential; the application-layer
`AdminOcrTestAccessPolicy` compares it in constant time.
`POST /api/benchmarks/import` and `POST /api/backups/restore` share that gate,
because both persist screenshots the boundary would otherwise refuse, and both
check it before the application reads the archive or opens any store (the
framework still parses the multipart body first). `GET /api/admin/ocr-test/session`
lets a client confirm a credential before it reveals any capture control; it
answers `no-store` and shares the upload rate-limit budget. `GET /api/pipeline`
advertises `administrative_ocr_test.enabled` so operators can see the
deployment state.

FastAPI composition remains in `app/bootstrap.py`, while extracted transport
adapters live under `app/api/routers`. Health and pipeline queries dispatch
through `app/application/system.py`; MCP configuration and principal operations
dispatch through `app/application/mcp_admin.py`.
Processing-job reads, uploads, short mutations, and history list/archive
operations dispatch through the storage-independent `app/application/jobs.py`
services. Benchmark dataset, report, import, and run operations dispatch
through `app/application/benchmarks.py`; backup export and restore operations
dispatch through `app/application/backups.py`;
hosted MCP reaches the same boundaries through its internal ASGI API client.
Remaining storage, locking, aggregation, and persistence stay behind
bootstrap-owned callables until later application-service slices replace those
concrete dependencies. Backup transport owns multipart limits and streaming
responses, while archive creation, restore coordination, and interprocess lock
timing remain behind application-owned callbacks.

PWA job-detail and processing-page reads are owned by
`domains/jobs/api/jobsApi.ts`, with stable TanStack Query keys and options in
`domains/jobs/api/jobsQueries.ts`. The legacy `shared/api/jobs.ts` and
`shared/api/history.ts` compatibility aliases have been removed; consumers use
the jobs and history domain API owners directly.
Analyzer job-detail, processing-extent, history-page, and history-search reads
execute those domain options through the application QueryClient. Browser
queue and history persistence remains a bounded recovery projection rather
than an authoritative server-state cache. Screenshot metadata writes use a
screenshot-owned command: the jobs domain owns transport, the detail cache is
updated from the response, and only processing/history query families are
invalidated. Consumers import the screenshot command owner directly.
Permanent screenshot deletion uses a parallel screenshot service: confirmed
success removes the detail entry and invalidates processing/history families;
transport failure leaves Query state untouched so mutation-lease recovery can
determine whether the backend committed the deletion. Confirmed deletion
cancels Query-managed reads and supersedes matching imperative read generations
before applying cache outcomes, preventing stale responses from restoring the
deleted record or projection.
Batch archive uses a history-owned command with the same stale-read boundary.
It invalidates archived detail keys and processing/history families, then seeds
returned job details and the authoritative default history page. Consumers
import the history command owner directly.
Benchmark ground-truth inclusion now uses a benchmark-owned command. Its
generated-contract transport returns the updated job detail, invalidates only
processing, history, and benchmark-overview families, and leaves immutable
benchmark-report caches intact. The Analyzer retains mutation-lease recovery and
local corpus-count presentation while consumers import the benchmark command
owner directly.
Benchmark dataset upload now uses a benchmark-owned multipart command that
preserves the caller-generated import request ID. Confirmed imports guard and
invalidate imported job details, processing, history, and benchmark overviews;
reports remain immutable, failures leave Query state untouched, and Analyzer
composition continues to own projection leases and imported-result rendering.
Application backup restore now uses a backup-owned multipart command. A
confirmed restore cancels and supersedes stale reads, then removes job,
history, and benchmark Query families before Analyzer composition schedules
projection recovery. System and pipeline caches remain intact; transport
failure leaves every cache untouched so the same archive can be retried.
Approval now uses an abort-aware hand-review command. The generated-contract
job adapter preserves the legacy signals; confirmed results seed job detail
and invalidate processing/history. Cache seeding preserves newer concurrent
screenshot metadata from an older workflow response, while a
delete-superseded write generation prevents a late approval response from
recreating a permanently removed detail entry. Analyzer composition retains
lease handoff and abort registration; control-panel automation was removed
with the import-first boundary.
Screenshot upload now uses a capture-owned command over the generated jobs
adapter. It preserves the caller upload request ID, selected pipeline, and abort
signal, seeds confirmed job detail, and invalidates processing only. Analyzer
composition continues to own per-file queue progress, independent failures,
projection leases, and capture sources while the administrator OCR test tools
are unlocked.

The player workspace is import-first: the control rail shows an import-first
notice instead of capture controls. An operator can unlock the administrative
OCR test tools from the toolbar **Administrator tools** dialog; the token is
held only in component state and sent as `Authorization: Bearer ...` with each
upload or capture. While unlocked, the capture panel renders under an explicit
administrative banner; a `401`/`403` upload response re-locks the tools.

Provider-neutral pipeline selection and capability contracts live under
`app/domain/pipeline`. Runtime configuration and HTTP adapters import that
domain package directly.

Poker card values, constrained numeric types, and validated preflop and
postflop action histories live under `app/domain/poker`. Parsers and solvers
import those primitives directly. The same domain owns
detected parser state, parser evidence, and canonical user-approved state plus
their cross-field wager and history validation.

The Phase 0 V2 import contracts live separately under
`app/domain/imported_hands`. They define immutable hand-history source evidence,
site-agnostic detected and approved revisions, exact dealt-in-ring positions,
action-origin evidence, explicit per-player/big-blind/unknown ante schemes,
re-import conflicts, lifecycle/deletion tombstones, and a pure
pot-reconciliation oracle. Omitted ante mode is canonicalized as unknown; a
positive unknown mode remains reviewable but blocks decision extraction, while
zero ante requires no poster mode and ignores retained poster labels in the
source-location-independent re-import fingerprint. Complete actions with
missing results or award-only pot evidence remain indeterminate, and extraction
requires a passing zero-discrepancy comparison against an independent source
total. Decision extraction proves that independence from the active detection's non-empty,
stated-pot-scoped raw field evidence or from a value-changing correction on the
active canonical revision; decimal formatting alone is not a value change.
Numeric agreement without that provenance remains
reviewable but is not extractable. Cash extraction treats either explicit rake
or a positive difference between stated gross and net totals as material rake
evidence. Zero schedules accept only zero deductions; nonzero schedules fail
closed until their calculation semantics are modeled. Tournament extraction
treats identified
`remaining_stacks` as the same hand-start snapshot
and absolute tournament-chip unit as the dealt-in seats' `starting_stack`
values, and binds each pair exactly; unrelated remaining field players may
coexist. The aggregate exposes only voluntary actions from its active approved
revision for later decision extraction. Activation, extraction, and restore
preflight all verify canonical raw-source lineage: a transition to another
retained source requires a resolved conflict that binds the preserved canonical
source and selects the new one, while same-source corrections remain ordinary
revisions. Every additional materially distinct retained raw source must also
remain covered by a retained conflict, even before detection or approval. Because
nested audit collections remain mutable while a transition is assembled, every
aggregate serialization, extraction, and restore comparison first rebuilds and
validates a complete snapshot; an invalid graph cannot be persisted or exposed
as learning evidence. Conflict resolutions are retained audit events, so a
deletion request must be ordered after them before deletion can proceed.

Parsed hand-history candidates enter this aggregate through
`app/application/imported_hand_ingestion.py`, composed under the local
workspace's stable thread/process record stripes and shared data-volume lock.
New identities become pending review. Byte-identical reimports append a source
occurrence with its own chronology and import provenance without copying raw
text, canonical revisions, or derived data; each occurrence retains its full
detection audit so confidence, warnings, and source evidence remain reviewable.
Unchanged-meaning reimport detections are audit-only and cannot be selected for
canonical approval. Materially different bytes, or a different detected
meaning for identical bytes, append unresolved conflict evidence and therefore
fail decision extraction closed. Deleted and deletion-pending records require
a separate authorized lifecycle reimport and cannot be resurrected by this
boundary. ADR 0058 records why the
parsed-candidate transaction lands before the #409 PokerStars adapter and
player upload route. Sanitized player audit detail nests these later occurrences
under their retained raw source, and its source count includes every occurrence.

The first bounded PokerStars text adapter now lives in
`app/infrastructure/hand_history/pokerstars.py`. It splits a file into
independent hand blocks and emits either an unapproved
`ParsedImportedHandCandidate` plus its amount-only pot reconciliation, or a
structured rejection for that hand. The current format revision deliberately
accepts only English no-limit cash headers and syntax it can map without
guessing. Exact source lines remain attached to detected fields and actions;
ordinary table actions remain origin-`unknown`, while explicit blind, ante,
straddle, and uncalled-return markers are forced/system evidence. Source times
are preserved with their source zone, and ambiguous/nonexistent ET wall times
are rejected. Synthetic development fixtures verify the contract and isolation
behavior but are not the representative corpus or 99% clean-parse evidence
required to close #409. Every successful parse separately reports whether pot
reconciliation is clean, failed, or indeterminate. Authenticated
`POST /api/player/imports` invokes the adapter for bounded UTF-8 `.txt` uploads
and returns sanitized per-file and per-hand outcomes without exposing raw text.

These contracts are now backed by a player-local file store. Authenticated,
loopback-only player routes expose bounded record summaries and sanitized audit
detail, while raw hand-history text stays inside the store.
`app/storage/imported_hand_store.py` persists
each record at `<data>/imported-hands/<record_key>/record.json`, keyed by a
SHA-256 of the hand's stable identity, with derived decision artifacts beside
it under `decisions/`. Because a purged record's tombstone keeps neither its
identity nor its audit collections, that key is derived once when the record is
first written and the directory name is afterwards the only way to reach the
record - which is what lets a re-import find the tombstone of the hand it
replaces.

Writes that touch more than one file go through the cascade journal in
`app/storage/cascade_journal.py`, which stages them under
`<data>/imported-hands/.cascade/` and publishes them as one durable unit, so a
record and the decision artifacts derived from it can never disagree about which
canonical revision is current. `WorkspaceCoordinator.open` recovers an
interrupted cascade at startup: it finishes one whose commit had begun,
discards one whose commit had not, and
sets aside a structurally unusable one under `.cascade/corrupt/` for a human
rather than deleting the evidence. That sweep needs the exclusive data-volume
lock, so it is skipped entirely when the journal holds nothing to recover - see
`docs/process/deployment.md`.

The local runtime uses the narrower `PlayerWorkspace` composition instead of
the hosted `WorkspaceCoordinator`. It opens only the imported-hand repository,
requires the resolved data directory to be current-user-owned and inaccessible
to group/world users through mode bits or Darwin extended ACLs, rejects a
symlinked imported-hand root, and runs the same interrupted-cascade recovery
before the loopback listener starts. Authenticated `/api/player/storage`
reports the data location, record count, and distinct recovery buckets without
exposing record contents. `GET /api/player/hands` pages opaque-key summaries,
and `GET /api/player/hands/{record_key}` returns provenance, confidence and
warning metadata, conflicts, sanitized detected and approved state, lifecycle
state including deletion-cleanup failures, and deletion receipts. Collection
responses omit source content; detail responses also omit raw text and evidence
excerpts, including scalar correction values whose JSON pointer directly names
an excerpt. Authenticated `POST /api/player/imports` accepts one or more bounded
PokerStars text exports; each successful candidate enters the same per-record
ingestion locks without changing approved canonical state, and new identities
stay pending review. A request UUID, ordered file slot, and file SHA-256 bind
deterministic source, import, and detection IDs. Exact replays
retain the first durable server timestamps and return duplicate outcomes;
changed bytes cannot alias those IDs and follow the ordinary reimport/conflict
rules. Files and hands remain independent, so one diagnostic or conflict cannot
roll back successful siblings. Authenticated
`POST /api/player/hands/{record_key}/approve`,
`POST /api/player/hands/{record_key}/withdraw`, and
`POST /api/player/hands/{record_key}/reject` expose retained approval writes;
`POST /api/player/hands/{record_key}/delete` exposes permanent deletion.
Withdrawal and rejection require the active canonical revision, deletion
generation, and lifecycle timestamp from the loaded detail plus a non-empty
player reason.
Stale requests fail without writing; a retry whose exact requested inactive
state is already current returns that retained state idempotently. The server
supplies every transition instant. Canonical approval accepts the complete
player-reviewed state but never client-authored correction pointers, detected
values, revision numbers, or audit timestamps; the other lifecycle routes
accept no canonical state. That instant advances strictly beyond the stored
lifecycle marker even when restored data is ahead of local wall time, keeping
the successor orderable against older backups. Permanent deletion additionally
requires a UUID request id, a SHA-256 version over the complete retained record,
and its exact lifecycle status and active-revision nullability. It publishes
`deletion_pending` before purging to a receipt-only tombstone. The receipt binds
the attempt to the exact record version and target generation without retaining
the player reason or removed audit. An exact completed retry is idempotent; a
cleanup retry from the refreshed pending record keeps the current generation.
The player renders parser proposals, approved revisions,
field-level confidence, retained conflict resolutions, and cleanup failures
with source/detection/revision lineage rather than collapsing uncertain or
failed records into generic inactive copy. Active details expose explicit,
confirmed withdrawal/rejection controls, while every non-deleted detail exposes
an explicit irreversible deletion control. Interrupted mutation responses are
reconciled by rereading the audit before the UI reports the outcome; deletion is
reported as committed only when the refreshed receipt id and generation match
the attempted request. Approval/reapproval additionally requires the complete
record version, exact lifecycle and revision-count preconditions, a selected
detection, and complete reviewed state. The server preserves hidden evidence
excerpts, validates the rebuilt state, derives all correction pointers and
audit values, and binds the resulting revision to the request UUID. The player
reports an interrupted approval as committed only when that exact ID belongs to
the latest active revision. A durable
ready cascade makes both its failed mutation and subsequent detail reads return
recovery-required, while collection pages report that key as unavailable, so
the pre-replay record cannot be mistaken for a final outcome. Storage status
and backup export/restore take an exclusive volume snapshot and refuse any
durable ready cascade, preventing backup of a lifecycle state that startup
recovery will supersede. This volume-wide gate does not close unrelated hand
keys. Detail reads and lifecycle writes take the stable
per-record thread stripe, matching named process-shared flock, and shared
data-volume hold. Lifecycle writes retain that volume hold across the request
precondition read and cascade; the store's nested shared hold and leaf journal
lock follow. This prevents either another local-runtime process or a concurrent
restore from replacing the record between validation and transition. V1
screenshot and benchmark stores are neither constructed nor reachable from
this composition.

The loopback backend serves the verified `apps/pwa/dist-player` build from the
same local origin. Only its document, manifest, service worker,
content-addressed assets, and icons are public; player data remains behind the
authenticated API. The player service worker precaches only the static shell
and treats `/api` and encoded equivalents as network-only. A player-only update
coordinator detects a waiting worker but never activates it during session
bootstrap or an authenticated player operation. Selected backups, selected
hand-history files, and edited approval, lifecycle, or deletion fields require
an explicit, revision-bound discard confirmation. The coordinator reloads only
after controller handoff
and rechecks that no new busy work or draft revision appeared; otherwise it
leaves the new shell installed and asks for a later safe reload. This governs
browser-shell replacement only and does not install, update, or remove the
packaged runtime. `pnpm player:start` builds this dedicated entry before
launching the backend, which refuses missing or symlinked asset roots rather
than falling back to an inline shell. Startup snapshots every served asset into
process memory before the workspace opens, so later filesystem replacement
cannot change code on the authenticated origin.

The local runtime's imported-hand backup contract is a separate V2-only
`poker-hero-player-backup` ZIP, not the hosted application's V1 job/benchmark
archive. Export holds the data volume exclusively while validating and
checksumming exact record and retained decision-artifact bytes. Restore verifies
the whole archive before taking that exclusive hold, then classifies every
candidate against live deletion generation and lifecycle state. Active
artifacts are re-derived from their canonical record, not trusted from checksum
validity alone. Stale evidence is skipped; merge requirements, tombstone
reactivation, and a tombstone not bound to the same deletion-pending generation
reject the request before writes. Accepted records and missing artifacts publish
through one multi-record cascade, preserving local audit artifacts the archive
does not contain. A bound tombstone removes every retained artifact in that same
cascade (ADR 0052). Within the local runtime, ordinary status, hand, lifecycle,
and export requests share an asynchronous access gate and remain concurrent
until their record and data-volume locks require narrower serialization. Restore
owns that gate exclusively for the full request, including upload and archive
parsing, and a waiting restore prevents new ordinary entrants from starving it.
Status therefore waits asynchronously before dispatching filesystem work,
preventing queued refreshes from exhausting the worker pool needed to finish
restore. A browser refresh after an ambiguous transport failure waits for the
restore to finish rather than presenting a stale or intermediate count; if a
stable refresh fails, stale status and backup controls are hidden until restart.
A restore storage failure remains unresolved even when returned explicitly as
`503`, because cascade intent or partial publication may already exist. The
runtime invalidates every active session and pending launch ticket, refuses new
tickets, and rechecks storage/export authorization after the restore gate. The
player clears its credentials, status, and restore input, so no browser can
re-enable work before restart recovery. Export and retry remain unavailable
until the local runtime restarts.

`app/application/imported_hand_lifecycle.py` is the single boundary every
lifecycle transition crosses (approve, reapprove, withdraw, reject, deletion
request, permanent purge), publishing each record's new state and the artifacts
derived from it in one cascade.
Reapproval extraction and validation happen before the cascade opens. A failure
there rejects the attempted correction without superseding the prior approved
revision, so its matching decision artifact remains current and the caller can
retry after refreshing lifecycle state. The raised storage error does not expose
whether durable intent exists, so callers report only that reapproval did not
complete and never infer that the correction was saved. After the journal
records durable publish intent, a recoverable pending cascade closes the affected
hand to newer lifecycle writes until replay finishes. Structurally unusable
intent is instead quarantined with its evidence for explicit repair; the
matching-revision read gate continues to prevent mismatched learning artifacts
from being served (ADR 0048).

A permanent-deletion request advances the deletion generation and atomically
publishes `deletion_pending` with no active canonical pointer. The source,
canonical revisions, conflicts, and superseded decision artifacts remain
available for audit while cleanup is pending, but both lifecycle status and
generation make them immediately learning-ineligible. Purge accepts a deletion
receipt only for that pending generation, replaces the retained record with a
non-sensitive tombstone, and deletes every exact decision-artifact filename the
store reports in the same cascade. A failure before durable intent leaves the
complete pending hand intact; after durable intent, the tombstone is already
inactive and startup recovery rolls any remaining artifact deletions forward.
Retries of the published request or completed purge are idempotent. Older
backups remain subject to `classify_restore`, so they cannot reactivate a
purged generation without an explicit authorized reimport.

The hosted screenshot workflow is not a V2 player-data path.
The local runtime constructs and recovers the player store and exposes
authenticated storage metadata, sanitized record projections, canonical
correction/approval/reapproval, approval withdrawal/rejection, permanent
deletion, bounded PokerStars import, explicit deleted-hand reimport, import
conflict resolution, active decision extraction, and whole-store V2
backup/restore.
These lifecycle mutations inherit the session, Host/Origin, and CSRF boundary
established by ADR 0050. Withdrawal and rejection retain inactive audit;
deletion first deactivates the record, then purges its hand-linked audit and
derived artifacts to a generation-bound tombstone. Authorized reimport advances
that generation again, replaces only the selected deleted incarnation with
fresh parser evidence at `pending_review`, and removes any prior-incarnation
artifact in the same cascade. No player route can promote V1 screenshot state;
canonical approval accepts only a complete review of one retained imported-hand
detection.

Hero decision-point extraction lives in
`app/domain/imported_hands/decisions.py` and consumes the aggregate's
per-action decision contexts instead of recomputing pot, wager, call, or
stack arithmetic. Each decision point binds its stable identity, source
chronology, import provenance, active canonical revision, and deletion
generation. Only a hero action whose approved origin is player-selected
becomes a decision point; forced/system, client-automatic, and
unresolved-origin hero actions are retained as excluded actions with
reasons and are never graded. A hand with no voluntary hero action (a
big-blind walk) is an explicit `no_decision` outcome, not a failure, and
a hand that cannot be extracted reports one rejection reason
(`not_active`, `unresolved_conflict`, `invalid_revision_lineage`,
`incomplete_hand_state`, `incomplete_economics`, or `unreconciled_pot`)
instead of failing silently. The amount to call and the current wager
exclude dead antes; a seat's street and hand commitments include them.
The state also carries the wager and full-increment yardstick from the hero's
prior action, allowing rehydration to verify the short-all-in reopening verdict
through the aggregate's shared rule without replaying the betting line.
Decision points are `Decimal`-native and N-player rather than reusing
`app/domain/poker`'s `float`-typed, single-opponent `CanonicalState`. The
versioned learning-content contracts live separately under
`app/domain/learning_content`: immutable taxonomy and mapping revisions produce
an explicit absent result or one primary tag pinned to the decision, taxonomy
series and revision, mapping revision, and concept-definition revision.
Overlapping rules fail closed.
Versioned selectors may bind the full ordered pre-decision route, structural
actor positions, BB-normalized action sizing, and stack-depth ranges; unresolved
action sizing remains unresolved and cannot satisfy a numeric range.
Principle revisions begin as drafts, retain append-only reviewer provenance,
and become activation- or reveal-eligible only after compatible human approval.
Complete-lineage successor validation prevents principle revision identities
from being recycled. Activation checks cover every concept reachable from the
mapping; principle reveals and cache keys bind the exact taxonomy series,
taxonomy revision, mapping, definition, reference, principle version, and
immutable principle-content digest and apply conditional educational framing.
These pure contracts do not attach live taxonomy state to
`HandDecisionExtraction` or yet
publish persisted learning artifacts; ADR 0057 records that boundary and the
remaining #417 persistence/migration work. The application lifecycle boundary
atomically supersedes or deactivates current decision artifacts and permanently
purges them with their imported hand.

Per-decision solved-policy comparison lives under `app/domain/grading`. It
accepts only an already-extracted voluntary `HeroDecisionPoint` and an optional
application-supplied reference policy that is bound to the SHA-256 of the exact
route-critical decision state. Missing or mismatched references remain
heuristic and ungraded; policy-incomplete solved evidence stays visible but is
also ungraded. A complete policy retains reference, policy, tolerance, route,
engine, economics, utility, artifact, and EV-unit provenance, treats any
meaningfully supported mixed-policy realization as supported, and labels an
action a mistake only when it falls outside that complete support. Candidate
EVs are retained and the action's cost is re-derived from them. Reference
actions and wager sizes must be legal in the bound canonical state. Bet and
raise sizes compare exact total commitments in BB using a pinned tolerance; an
unverified blind or commitment leaves the comparison heuristic and ungraded.
The result is immutable and persistence-free, and even a gradeable comparison
remains `requires_content_activation`; this domain does not activate a
reference, authorize a remote provider, persist grades, calculate aggregate
mixing deviations, move mastery, or schedule drills. Those application and
Phase 0 gates remain open under issues #412, #414, #416, and #418.

The local player runtime exposes the current checkpoint at
`GET /api/player/hands/{record_key}/evaluations`. It reads only the
integrity-checked active decision artifact and returns a revision- and
generation-bound `player-active-hand-decision-evaluations/v1` projection. This
schema is intentionally limited to the default local-only state: every decision
is visibly `heuristic`, `reference_unavailable`, `ungraded`, and ineligible for
learning, while remote-reference preflight is visibly `unavailable` with the
`local_only` reason and contains no outbound request. The read performs no
provider selection, network access, consent mutation, grade persistence,
content activation, mastery update, or drill scheduling. A future solved-policy
application seam must use a new response contract rather than widening this
fail-closed v1 projection in place.

Optional remote-reference preflight contracts live under
`app/domain/remote_references`. This pure, non-networking boundary is local-only
by default and evaluates a dispatch candidate only when active provider-policy
snapshots, the semantic policy digest, exact disclosure, explicit unexpired
consent generation, canonical DNS-only HTTPS origin, route schema, and sorted
field-category allowlist all match. A provider-owned route manifest explicitly
allowlists every revision or digest in a currently eligible cash no-limit
preflop route
and the internally computed semantic digest of each exact eligible request
context. That exact context binding includes limit, table size, position,
position-bound stacks and commitments, sizing, and action-line state rather than
letting a broad economics or abstraction declaration imply provider coverage.
Cash economic coverage is derived locally from the approved currency, complete
rake/drop schedule, and absolute blind/ante level before BB normalization; a
caller-supplied economic digest cannot substitute for that canonical binding.
Closed component models
make raw histories, hand/site/session and canonical-record identities, player
names, timestamps, screenshots, and learning/profile state unrepresentable in
the outbound DTO. A pure local factory accepts the full validated canonical
decision point, derives its stable binding and local state digest, and
reconstructs every route-critical field in BB units before it can create an
immutable route envelope. Preflight independently repeats that reconstruction,
so a caller cannot associate an allowlisted request from one decision with
another decision even when it forges the envelope binding and state digest.
Unsupported postflop, ante, straddle, or uncalled-return state fails closed at
this derivation boundary. Route revisions, abstraction digests, and range digests must
match that independently selected provider manifest, never player data. Active
players and their position-bound remaining stacks are explicit, so multiway
routes cannot collapse materially different stack configurations.
Current wager, amount-to-call, and pot values are checked against the complete
position-bound commitments and a reconstructed running wager rather than
accepted as independent claims. Check, call, bet, raise, minimum-raise, and
short-all-in reopening semantics are validated across the action line; active
players are derived from its folds while all-in survivors remain visible with
zero remaining stack. Players exhausted by represented forced contributions are
excluded from pending action. A short all-in blind contributes its exact posted
amount to the pot; heads-up uses the actual posted wager while multiway retains
the nominal big-blind bring-in, and a stackless hero cannot become a candidate.
Unordered hole cards and equivalent Decimal exponents are canonicalized before
exact-route and local decision-state hashing. A route
cannot claim another decision after all pending
responders have matched or left the hand. Pot-limit routes remain unavailable
until their running-pot maximum sizing can be reconstructed; tournament routes
remain unavailable until payout, field, stack, and bounty state is representable.
Postflop routes remain unavailable
until each conditioned-range artifact can be bound to its exact board, action
line, position, and derivation context instead of a global digest allowlist.
Provider configuration, policy, reference-source, commercial
serving-rights, derived-output-rights, disclosure, consent, request, economics,
utility, and abstraction revisions remain pinned in local audit provenance;
the canonical decision binding and state digest remain pinned through dispatch
preflight and recorded lookup failures, but stay local and are never promoted
to an outbound identifier or digest.
The candidate is not transport authorization: a future application boundary
must atomically re-read authoritative provider status, consent status, and the
current consent generation immediately before each dispatch or retry. Revocation,
policy drift, missing routes, and provider, network, or response failure remain
visibly unavailable and ungraded, with no remote or heuristic-to-solved fallback;
response digests are computed locally instead of accepted as provider claims.
There is intentionally no provider selection, HTTP adapter, credential loading,
persistence for provider results, source activation, or resolved-reference
promotion yet, so this checkpoint does not close the source qualification and
lifecycle work in issues #412 and #416. A future transport must also enforce its
configured-origin allowlist after DNS resolution and reject private, loopback,
link-local, and redirected destinations.

The local player application can now persist one authoritative
remote-reference consent snapshot when its embedding composition supplies a
fully validated active provider-policy snapshot. Consent remains unavailable
when no such policy is supplied; the default packaged composition does not
configure one. Authenticated local API routes disclose the active policy, exact
outbound categories, and exact UTF-8 terms, privacy, retention, training-use,
and logging policy text whose individual hashes are covered by the complete
policy digest. They accept only affirmative acknowledgements bound to that
displayed digest and the policy/disclosure revisions, and revoke the current
generation idempotently. Acceptance and revocation use compare-and-set
generations under the exclusive player-volume lock and atomically replace an
owner-only state file. The file contains no credentials, outbound request,
route binding, response, or player record. Consent is deliberately excluded
from player backup and restore so an archive cannot resurrect authorization
after revocation. Workspace layout v2 and ADR 0066 record the v1-to-v2
migration. The runtime remains local-only because no transport consumes the
consent yet, and a future dispatch owner must still atomically reread provider
and consent state immediately before each request or retry.

The canonical `ImportedHandRecord` is the trust authority for active decision
artifacts. `FileImportedHandStore.active_decisions` first selects the artifact
whose filename matches the record's active revision and deletion generation,
then re-runs `extract_hero_decision_points` against that freshly validated
record and requires full equality. A structurally valid but canonically
different payload raises `DecisionArtifactIntegrityError`; it is never served
or silently rewritten. `get_decisions` is the lower-level retained-audit reader:
it schema-validates historical bytes but makes no derivation claim for an
inactive revision. Chronology and provenance intentionally remain on both the
envelope and every point: the envelope preserves no-decision provenance, while
each point stays a self-contained grading/audit unit. ADR 0049 records the
boundary and the remaining structural choices.
The local player route `GET /api/player/hands/{record_key}/decisions` exposes
only that active read under the runtime's authenticated, loopback-only,
restore-excluded and no-store boundary. The workspace rejects inactive or
unresolved-conflict state; a missing active artifact or canonical mismatch is a
sanitized integrity failure, never a historical fallback. A current
`not_extractable` artifact remains visible with its rejection and no decision
points. The response retains the complete decision-state, table-action, origin,
exclusion, chronology and provenance contract while recursively removing
source excerpts. ADR 0065 records this application boundary; it does not
connect grading or a remote provider.

Provider-neutral recommendation actions, requests, and result evidence live
under `app/domain/recommendations`. Providers, local engines, and benchmarks
import those contracts directly.

Upload/job-lifecycle contracts now live under `app/domain/hands`. `JobRecord`,
`JobQueue`, `JobHistory`, `ScreenshotMetadataRequest`, and
`ArchiveJobsRequest` are owned there and imported directly by consumers.

Parser benchmark data contracts now live under `app/domain/benchmarks`.
`BenchmarkReport`, `BenchmarkCaseResult`, dataset import receipts and related
normalization helpers (`normalize_benchmark_value`, `benchmark_values_match`,
and canonical field constants) are owned there.

Health and backup transport contracts live in `app/domain/health` and
`app/domain/backups`. `HealthResponse` and
`ApplicationBackupRestoreResult` are imported directly from their owning domain
packages.

File-backed persistence is organized under `app/storage`. Repository contracts
live in `app/storage/ports.py`, job and benchmark adapters are split between
`file_job_store.py` and `file_benchmark_store.py`, and shared durability helpers
and a strict job-record loader live in `persistence.py`. The package root
preserves the package namespace without re-exporting adapter or persistence
symbols; consumers import the owned modules directly.

`app/workspace.py` composes those repositories with the process-wide and
cross-process coordination boundary. `WorkspaceCoordinator` owns startup job
recovery and the lock ordering for job, history, benchmark import, backup export,
and restore transactions; transport callbacks continue to own HTTP error mapping.

Backend API integration tests share transport setup through
`tests/api_test_support.py`, and route-domain suites live in focused modules.
Health, capability, and pipeline-selection coverage lives in
`test_pipeline_api.py`, while request
observability, streaming/disconnect handling, CORS, and proxy-guard coverage
lives in `test_api_observability.py`. History archive, paging, concurrency, and
search coverage lives in `test_history_api.py`. Job request identity, queue
projection, metadata, approval, read/image behavior, deletion, and storage
guards live in `test_jobs_api.py`. Upload validation, parser lifecycle,
mutation coordination during parsing, and auto-approval coverage lives in
`test_job_upload_api.py`. Benchmark corpus selection, archive import/export,
recovery, concurrency, scoring, and report coverage lives in
`test_benchmarks_api.py`.

The `local_solver` provider has a second configurable boundary for local engine
plugins. Supported preflop states use a position-aware 169-hand training chart.
When a reviewed state supplies an ordered preflop action history, the chart can
route one to five ordered 1 BB limps to hero's big-blind option, a single open,
one open plus one to four callers before hero, or exactly one hero open followed
by one later-position 3-bet. It can also route a hero 1 BB limp followed by one
bounded later-position isolation raise when action returns heads-up, or one
opponent open and one opponent 3-bet before hero when exactly three players
remain, or one opponent open, hero 3-bet, and opener 4-bet when exactly two
players remain.
It can additionally route one opponent limp, one hero isolation raise, and a
reraise by the original limper after action returns heads-up.
It also supports a later-position cold 4-bet after the opener folds and exactly
two players remain, plus a later-position squeeze after hero cold-calls and the
opener folds heads-up.
The sequence stores canonical seat, action, and total committed BB. The
called-open routes require exactly three through six active players, matching
open and call totals, distinct represented seats, and legal ordered
opener-callers-hero action. Their explicit conservative multipliers
tighten continue and squeeze boundaries, and their raise targets start at 4x
through 7x the open. The cold 3-bet route requires legal
opener-3-bettor-hero order and uses an explicit policy for every supported seat
triple. The chart validates position order,
full-raise minimums, amount to call, pot composition, and stack availability. A
structured first raise also supplies the
legacy opener position and total opening size fields at the provider boundary.
Older states retain the structured single-opener fields and a conservative
free-text fallback. Every resolved open must remain within the supported 2-4 BB
range. Supported 3-bets select an ordered size-ratio band and matchup-specific
continue/four-bet boundaries. Recommendation evidence records the resolved
actors and totals, base response boundaries, size multipliers, stack policy,
adjusted boundaries, represented caller seats, cold 3-bet policy, and maximum
legal raise total. The heads-up 4-bet response uses explicit opener-versus-hero
continue/five-bet boundaries and ordered 4-bet-size bands; five-bets use the
reconstructed all-in cap from both represented commitments. The cold 4-bet
response uses narrower opener-hero-four-bettor policies and validates the pot
against all three commitments, including the folded opener's dead money.
The squeeze response uses explicit opener-hero-squeezer policies and includes
hero's prior call in both pot validation and the reconstructed raise cap.
The heads-up limp route requires exactly two active players, one canonical
limper before hero in the big blind, a matching 1 BB call, and a pot reconstructed
from blinds plus that limp. Explicit limper-position isolation ranges adjust by
stack depth, while the target isolation size is capped by the effective total.
The multi-limper variants require exactly one more active player than the two
through five distinct, legally ordered 1 BB calls. Explicit policies cover
every possible limper pair, triple, four-seat group, and full-table sequence;
their progressively tighter isolation boundaries adjust by stack depth, target
at least 5 BB through 8 BB respectively or 1.5x the pot, and use the same
effective-total cap. Evidence retains all limper seats, their count, the named
policy, adjusted range, target, and cap.
The isolation-response route likewise requires exactly two active players, but
hero is the represented limper and a later seat raises to 2-5 BB. It validates
the amount to call, both commitments, blind replacement, and available stacks,
then applies explicit hero-versus-raiser boundaries plus raise-size and stack
adjustments. Evidence uses isolation-specific actor, size, policy, range, and
cap fields rather than presenting the action as an open/3-bet sequence. Its
call-first structured history takes precedence over stale legacy opener fields,
which the approval serializer clears and the route ignores for compatibility.
The limp-reraise response route also requires exactly two active players. It
accepts one 1 BB limp before hero, a 2-5 BB hero isolation raise, and a full
reraise by that same limper up to 4x the isolation total. Pot reconstruction
uses only each player's final commitment so the initial limp is not counted
twice. Explicit limper-versus-isolator policies tighten across ordered
limp-reraise ratio bands and stack depth; evidence uses original-limper,
hero-isolation, and limp-reraise terminology and includes the adjusted
continue/four-bet range plus the reconstructed cap.
Effective stack selects a
short (up to 20 BB), medium (up to 50 BB),
standard (up to 150 BB), or deep policy. That policy adjusts first-in ranges and
sizing plus continue/reraise boundaries; its band and multipliers are retained
in the same evidence payload. Capped blind reraises reconstruct a total amount
from stack behind, the hero's posted blind, and hero stack when available; the
resolved effective cap is retained for review.
`postflop_solver` runs as a pinned Rust stdin/stdout process for heads-up
postflop decisions with explicit relative position. Canonical `dealer` labels
map to button/IP. When both reviewed seats are available, distinct normalized
six-max seats establish their postflop order; explicit relative labels take
precedence. Contradictory labels, duplicate seats, and a small-blind versus
big-blind pair remain ambiguous and use fallback. A limp/check line cannot
resolve that pair because it is also valid heads-up. An exact called big-blind
isolation or called limp-reraise line resolves the pair under its six-max chart
contract, with the small blind OOP and big blind IP. On the limp-reraise route,
a reviewed `dealer`/`button` alias maps to the small-blind action actor and
proves the heads-up order instead, with that player IP and the big blind OOP.
An exact reviewed squeeze or cold 4-bet line can also resolve the pair because
the additional seats prove the preflop order.
First-bet decisions retain the compact
reconstruction path. In `contextual` range mode, an exact reviewed heads-up
state with one 1 BB limp checked by the big blind uses the limper's
stack-adjusted first-in range as an explicit proxy and the complement of the
big blind's isolation-raise band as the checked range. Both reviewed survivor
seats and the reconstructed flop-root pot must match that line. The exact
three-action continuation in which the big blind instead isolation-raises to
2-5 BB and the original limper calls uses the adjusted big-blind isolation
band for the raiser and the limper's matchup-, size-, and stack-adjusted
continue band after excluding limp-reraises. The call-first structured history
takes precedence over legacy opener metadata. Both final commitments, the
survivor pair, and the reconstructed flop-root pot must agree. A consistent
opposing OOP/IP label pair assigns the represented limper and big blind from
their six-max postflop order when concrete seats are unavailable; duplicate or
contradictory labels retain configured ranges. Other isolator
positions keep the configured ranges because no initial isolation policy is
charted for them. When those survivors are the small blind and big blind, this
exact six-max chart route establishes the small blind as OOP and the big blind
as IP. A reviewed dealer/button alias distinguishes the heads-up form of this
line and maps that IP player to the small-blind action actor. An exact
four-action limp/isolation-raise/limp-reraise/call line can
instead use every charted limper/isolator matchup. The limper uses its
isolation-response reraise band, while the isolator uses its adjusted continue
band after excluding 4-bets. Both final commitments, the full-raise and ratio
bounds, reviewed actor labels, and the reconstructed root pot must agree. An
open-and-call preflop history whose actors match the reviewed seats replaces
the configured generic ranges with the chart's opener
range and its flat-caller continue band after excluding the reraise segment.
An exact open/3-bet/call history can instead use the chart's adjusted 3-bettor
range and the opener's continue band after excluding its 4-bet segment. The
same three-action shape with a distinct later cold-caller and a folded opener
uses the chart's three-seat cold-3-bet continue band against the adjusted
3-bettor range. The folded opener receives no postflop range, but its final
opening commitment remains mandatory dead money in the reconstructed root pot.
An exact open/call/squeeze/call line with that opener folded uses the
one-caller-adjusted reraise band for the squeezer and the named squeeze-response
continue band for the caller after excluding its 4-bet segment. The caller's
initial call is not counted twice; its matching squeeze call is the final
commitment. The exact continuation through a 4-bet by the opener and matching
call by the original 3-bettor can use the opener's adjusted 4-bet band and the
3-bettor's continue band after excluding its 5-bet segment. When a distinct
later player cold 4-bets and the opener folds, that player's cold 4-bet band is
paired with the original 3-bettor's continue band after excluding 5-bets. The
folded opener receives no range, but its opening commitment remains mandatory
dead money. The supported 2-4 BB open, matching final commitments, legal seat
order, optional legacy opener metadata, both reviewed survivor seats, and
reconstructed flop-root pot must agree. With no current-street wager, the effective stack behind plus each
player's matching final preflop commitment reconstructs the starting depth.
Once money is wagered postflop, both visible stacks and either explicit
first-bet context or ordered
OOP/IP contributions must reconcile. The resulting short, medium, standard, or
deep policy adjusts the range boundaries. Incomplete or contradictory stack
evidence retains an explicit 100 BB standard assumption instead of blocking an
otherwise verified range. Turn states require one exact terminal completed-flop
line; river states require exact completed-flop and completed-turn lines. Their
final OOP/IP commitments plus current-street contributions reconstruct the
original flop pot and, with visible stacks, starting depth. Partial or
contradictory completed histories retain configured ranges. For exact later-
street histories with both visible stacks, the adapter first solves a bounded
flop-root conditioning tree, replays the reviewed actions and actual dealt
cards, and carries each player's resulting reach weights into the normal
current-street decision tree. The conditioning tree preserves reviewed bet and
raise sizes, limits unobserved downstream branches, and is released before the
decision tree is allocated. If the conditioning tree exceeds the configured
memory ceiling or either reviewed line has zero reach, the adapter keeps the
selected starting ranges and records why conditioning was skipped. Range
source, depth source, decision street, completed-street count, boundaries, and
conditioning status, replayed line, reach, memory, and exploitability are
retained as solver evidence. Raised
decisions additionally carry both visible stacks and ordered current-street
OOP/IP actions; the adapter validates and replays that line before reading the
hero strategy. `local_ev` remains available directly and is used as a
recorded fallback for ambiguous or unsupported preflop history, ambiguous
position, unsupported multiway states, incomplete context, resource-limited, or
failed postflop solves. For multiway fallback aggression, `local_ev` converts
its per-opponent response estimate into the probability that the entire field
folds under an explicit independent equal-response assumption. It enumerates
every possible caller count, estimates equity against that surviving field,
and weights each branch using its own final pot and continuation value. Each
branch samples runouts after removing only the opponents present in that
branch, so cards assigned to non-participating opponents remain available. When
raising into an outstanding wager already included in the pot, the canonical
state can record both how many opponents have committed it and their total
current-street wager. The total wager is distinct from hero's remaining amount
to call and is resolved from explicit review, structured action history,
preflop opening context, or a simple first-bet state. Hero's existing wager is
derived from their difference. When structured preflop history represents all
active opponents, each actor's latest commitment contributes to an aggregate
opponent total, including lower wager levels in re-raised pots. The
equal-response model reconstructs each caller's additional contribution from
that aggregate and hero's existing wager. Fallback is withheld until any
commitment context that cannot be derived has been reviewed.
Because OOP/IP postflop history cannot identify multiple opponents, a multiway
raise with different active wager levels requires a reviewed aggregate
opponent commitment total. Heads-up states, first bets, complete preflop
histories, and fields entirely at the latest wager remain automatic.
Preflop states with no call amount retain hero's posted blind or latest
structured action. Complete active-player history provides the opponent
commitment total; otherwise the remaining pre-action pot forms that aggregate,
so open branches account for posted blinds and limps.
Preflop opening context is eligible only when the opening total agrees with the
call amount plus hero's posted blind; stale initial-open metadata is not reused
after later aggression.
Candidate evidence retains the fold probabilities and continuation branches so
the approximation remains reviewable.
Explicit custom
commands still override the bundled engine selection.

External vision, solver, and LLM adapters use independent optional bearer
tokens held as masked settings and a shared configurable request timeout. The
tokens are attached only as `Authorization` headers, and authenticated external
URLs must use HTTPS. This keeps external provider credentials behind the
backend integration boundary without changing the PWA workflow.

The offline recommendation benchmark calls the same provider registry with
canonical states from a strict, versioned JSON corpus. It does not create jobs
or read persisted application data. Failures are isolated per case. Aggregate
output separates supported-action agreement from exact sizing-line agreement,
and reports mixed-policy total-variation distance, reference EV loss, and
recorded fallback use only when the corpus or provider supplies the required
evidence. Evaluation coverage makes missing optional evidence explicit, while
street and scenario-tag breakdowns localize weak solver spots. Corpora may
record the independent reference source, version, and configuration so CI can
require provenance for trusted regression runs. Version-3 turn and river cases
may also require the provider to report whether reviewed prior-street actions
were applied to range conditioning or deliberately skipped. Agreement and
evidence-coverage thresholds catch incorrect or missing conditioning metadata.
Version-4 postflop cases may additionally require the exact `raw.range_source`
selected by the provider. The benchmark validates that value against the
configured and contextual source registry, then reports independent agreement
and evidence coverage with optional CI thresholds for both.
Version-5 corpora require a grading-reference evidence envelope with immutable
source/policy/tolerance revisions and digests, exact dealt-in structural
positions, stack/street coverage, economic and utility models, an EV unit,
delivery-specific rights evidence, and passing convergence measurements. The
case state repeats the exact normalized economic and utility configurations,
which are fingerprinted and revalidated before execution. Schema-v5 evaluation
snapshots each provider's no-argument configured binding catalog once before any
case execution. The benchmark canonicalizes and hashes the raw configured
contexts itself. Each context contains the complete provider-visible canonical
decision state—cards, board, pot, wager and stack amounts, player counts,
positions, opener and action context, current and completed action histories,
street, and approval state—plus structural actor mapping, economics, and utility.
Trusted schema-v5 cases require exactly two distinct hero hole cards and the
street's exact board cardinality independently of provider-required fields or
route-shape matching.
Catalog JSON must match the benchmark-generated recursive shape exactly. Every
canonical decision-state null, empty, and default-valued key remains explicit;
the surrounding structural, economic, and utility objects must mirror the
benchmark-generated field presence. Unknown or omitted required keys at any
nested object fail before provider execution instead of being dropped or filled.
Exactly one route must match. The economic route identity includes the exact
blind denominations, ante amount, and canonical ante posting mode; a positive
ante with an omitted or unknown poster scheme fails before route matching. The
corpus and its fingerprint are snapshotted before provider hooks, and the report
retains the declared schema version. A structurally invalid dataset snapshot
fails without calling the catalog, required-field inspection, or provider. A
separately serialized and revalidated dataset-level trust snapshot plus a shared
validation pass over corpus-wide case rules prevents a non-serializable nested
case from masking a schema-version, tagged/range expectation, or grading-evidence
mutation. After those global rules pass, a non-serializable nested case fails
before its own case-scoped hooks while valid cases continue from the deep
snapshot; the report omits the unavailable corpus fingerprint and cannot be an
attested baseline. Mutating a v5 corpus's version or removing its grading
reference cannot select legacy execution or baseline behavior.
Required-field inspection and execution receive separate validated state copies,
and the complete execution copy must remain byte-for-byte canonically equivalent
to its pre-call snapshot after the provider returns. The selected route context
is then revalidated independently. Reports retain the case-context and
attestation digests, route ID, engine ID and immutable revision,
configuration/artifact digest, and adapter binding revision; schema-v5 baselines
compare all of those identities. A case-aware callback or recommendation
response cannot establish this binding. After
provider execution and before any scoring, the benchmark also requires
the result's canonical `raw.engine` to equal the selected binding's engine ID
exactly and rejects every present fallback marker, including malformed metadata.
Rejected results are case errors: they retain runtime and intended-binding audit
identity but omit recommendations, scores, policy/EV values, and actual
range-conditioning/source evidence. Completed schema-v5 baselines must preserve
the same runtime-engine attestation and cannot contain a fallback. Older report
shapes remain readable but cannot serve as unattested schema-v5 baselines.
Current built-in providers return no binding because their
Python/Rust/HTTP engine contracts do not consume and attest the complete
context, so they fail closed before their execution boundary. The CLI can
require the evidence envelope, but declarations and artifact pointers are not
themselves source approval; production route matching and real retained evidence
remain Phase 0 gate work.
Reports also carry a SHA-256 fingerprint over normalized scoring inputs and
reference provenance. The CLI can load a full prior JSON report for the same
provider and fingerprint, display aggregate deltas, and gate direction-aware
accuracy, coverage, policy-distance, EV-loss, conditioning, range-source, and
fallback regressions. JSON stdout remains only the current report so it can be
captured as a later baseline.
Reference frequencies must sum to one, sizing identities must be
unambiguous at the configured tolerance, and EV labels cover either every line
in a case or none.

### MCP Gateway

`apps/backend/app/mcp_gateway.py` is a curated adapter over the public FastAPI
contract. It does not open the file-backed stores or call parser/provider
registries directly. This preserves the same validation, locking, rate limits,
request correlation, and persisted review evidence used by the browser.

Each stdio process or hosted endpoint is configured for exactly one `staging`
or `production` target. The backend advertises
`POKER_DEPLOYMENT_ENVIRONMENT` on its public health response, and the gateway
verifies that identity before data access. Production configuration rejects
write enablement and omits every mutation from tool discovery. Staging remains
read-only unless an operator explicitly sets `POKER_MCP_ALLOW_WRITES=true`.

The read surface exposes environment status, the processing queue, individual
jobs, history search, and parser benchmark summaries. The staging write surface
is limited to approving a user-reviewed canonical state. Administrative backup,
dataset, benchmark-run, and bulk-archive APIs remain outside the gateway.

Hosted MCP is mounted on the existing backend at `/mcp`, disabled by default,
and uses stateless Streamable HTTP. Opaque `phmcp_` credentials are bound to
the deployment environment and persisted as one-way hashes under
`POKER_DATA_DIR/mcp`. The protected application surface creates, rotates, and
revokes principals with read or read/write scopes. Production cannot enable
writes; staging writes require both credential scope and the deployment gate.
Separate per-principal read/write limits protect the protocol surface.
Token-issuance and MCP responses are non-cacheable. Credential state is a
deployment concern and is excluded from portable application backups.

The Worker protects `/api/mcp/principals` and all descendants with a dedicated
per-environment `MCP_ADMIN_TOKEN`. The PWA asks an operator to unlock the
credential-management controls and retains that secret only in component
memory. Those calls always use the same-origin Worker rather than the general
API base URL override. After minimum-length and character validation plus a
constant-time digest comparison, the Worker strips the operator `Authorization`
header and forwards the request using only its Worker-to-backend credential.
This secret is separate from both the individual agent bearer credentials and
`API_PROXY_SECRET`; deployment rejects equal values. Percent-encoded proxied
paths are rejected before route classification so backend decoding cannot
reinterpret an unprotected path as a principal-management route.

The local gateway may authenticate through Cloudflare Access service headers
or—in a trusted server deployment only—the private Worker-to-backend shared
secret. Hosted callers authenticate with their MCP principal bearer token;
inbound agent identity is never treated as the Worker credential. Secrets are
masked settings, require HTTPS, and never enter tool results. Backend API
credentials are withheld from the unauthenticated environment identity probe;
Cloudflare Access service headers remain available to cross the protected edge.
API failures retain bounded status, request-ID, and retry metadata for agent
recovery without logging request bodies or poker evidence.

### Contract Packages

`packages/openapi` owns the deterministic OpenAPI JSON document and the
isolated export, validation, and freshness tooling. The backend application
factory remains the source of truth; export always uses temporary empty storage
and never reads an operator data directory. `packages/openapi-client` owns the
committed `openapi-typescript` output and exposes its wire declarations from
`@poker-hero/openapi-client`.

PWA domain API adapters import the workspace package and translate its wire
schemas into stable domain values. No application owns generated API files or
imports them from another application tree. CI exports an exact-ref artifact,
compares it byte-for-byte with the committed document, regenerates the client,
and rejects missing, untracked, staged, or unstaged outputs. The package
ownership, Docker inputs, deployment consequences, and rollback contract are
recorded in
[ADR 0042](../decisions/0042-extract-openapi-contract-packages.md).

### PWA

`apps/pwa` owns two intentionally separate builds. The default hosted build owns
administrator-only screenshot upload and capture, queue navigation, review and
approval, parser benchmarking, and history. The `player/` entry owns only the
loopback session bootstrap, local storage/recovery presentation, and player
backup/restore controls. It imports no hosted application routes, API adapters,
browser projections, administrative controls, or error-reporting integrations.

The hosted build is organized into application, page, feature, and shared
layers. `src/app`
contains the browser-router shell, route registry, top-level error monitoring,
and other application-wide concerns. `src/pages/analyzer/AnalyzerPage.tsx` is a
route-scoped provider wrapper. `useAnalyzerWorkspaceController.ts` retains the
queue/history mutation protocol because those transactions span capture,
review, benchmark labels, and recovery, while
`AnalyzerWorkspaceComposition.tsx` owns only the grouped feature render tree.
The controller invokes Query-aware commands and consumes an injected workflow
projection interface; it neither owns raw HTTP transport nor imports concrete
browser persistence. Source-architecture tests reject any production module
that directly owns or imports both transport and browser persistence.
Snapshot-consistent history-search and processing-queue extent reads live in
`features/workspace/lib/queryReads.ts`, separate from browser cache codecs.
`src/pages/analyzer/AnalyzerLayout.tsx` owns only the page shell, notification
host, workspace landmarks, control rail, and dialog layer; it receives rendered
feature content and has no workflow, transport, or persistence authority.
Each directory under `src/features` owns its components, colocated component
styles, hooks, and non-React presentation or domain support. Route-level styles
are limited to page composition; feature selectors must stay with their owning
component or feature. Reusable form and dialog controls, API access, primitive
types, and generic formatting helpers live under `src/shared`.

The production Vite build has separate document and
`src/app/pwa/service-worker.ts` entries. The build plugin emits the worker at the
stable `/sw.js` URL, derives a `poker-hero-shell-<build digest>` cache name, and
injects an exact allowlist containing `/` plus every emitted content-addressed
file below `/assets/`. It rejects a mutable asset in that list, and the
post-build verifier checks the generated worker, manifest, icon dimensions,
and install metadata. The worker owns the application-shell network boundary,
so the source-architecture inventory grants only that exact module direct
`fetch` access outside a domain API adapter.

The install handler fetches and validates the whole version before writing it:
`/` must be successful HTML, hashed assets must be successful non-HTML
responses, and redirects are rejected. A validation or write failure deletes
the version cache so no partial shell can activate.

Navigations are network-first and may fall back to the cached `/` shell.
Content-addressed bundles are cache-first. Cross-origin requests, `/api`, every
path below `/api/`, and the exact `/mcp` path receive no service-worker
response; encoded private equivalents fail closed. No runtime response outside
the generated allowlist enters Cache Storage. The Cloudflare edge Worker runs
before Static Assets to revalidate `/sw.js` and stable metadata while marking
only successful non-HTML hashed-bundle responses immutable. Missing assets and
successful HTML SPA fallbacks remain revalidatable so a rollback can restore
them. `apps/pwa/nginx.conf` applies the same header contract for the container
deployment path.

`shared/pwa/updateSafety.tsx` aggregates named dirty and busy reasons from
independent feature owners. The analyzer registers all correction, screenshot,
capture, mutation, restore, and benchmark state; Agent access
registers administrator and credential drafts, unacknowledged one-time tokens,
and mutations. The information dialog blocks every close path for the complete
MCP mutation and unacknowledged-token lifetime, keeping that owner mounted.
`PwaRuntime` uses the aggregate for unload protection and worker
updates. Its disconnected status probes the stable manifest with cache bypass
and a bounded timeout rather than trusting `navigator.onLine`; it retries on
launch, browser focus, restored link status, and a 30-second interval. A newly
installed worker waits until the user asks to activate it, never exposes the
activation action while work is busy, and requires confirmation before
discarding dirty state. The coordinator rechecks safety on `controllerchange`
before reloading. New forms and non-replayable operations must register with
this owner before shipping.
The shared API layer keeps base URL selection, response decoding, retry
metadata, and readable error conversion in one transport core. Product
endpoints live in focused domain adapters with colocated tests. MCP
configuration and principal administration transport live in
`domains/mcp/api/mcpApi.ts`; principal writes pass through focused system
feature commands. The former shared endpoint facades have been removed, and
the source-architecture suite prevents them from being recreated.

Benchmark HTTP transport and dataset-export URL construction are owned by
`domains/benchmarks/api/benchmarksApi.ts`. Parser benchmark writes pass through
`features/benchmark/services/runParserBenchmarkCommand.ts`, which declares the
benchmark-overview Query invalidation outcome. The former
`shared/api/benchmarks.ts` facade has been removed.

Health and pipeline reads use their existing system and pipeline domain
adapters. Backup export URL construction now belongs to the backup domain and
is exposed through the backup feature service used by the analyzer page. The
former `shared/api/system.ts` facade and duplicate transport are removed.
PWA-only data contracts mirror those domains under `src/shared/types`; backend
wire schemas come from `@poker-hero/openapi-client` and are confined to domain
API adapters.
The former `src/shared/types.ts` compatibility barrel has been removed;
production and test code import narrowly owned domain contract modules directly.

Cross-feature error formatting, abort classification, uncertain-write
classification, and stable toast IDs live in `src/shared/lib/errors.ts`.
Feature hooks import those primitives downward instead of depending on the
workspace feature; workspace workflow helpers retain only workspace-specific
job-state behavior.

Preflop position labels, aliases, and normalization live in
`domains/poker/model/preflopPosition.ts`. Hand-review and benchmark features
consume that poker-domain model directly; no benchmark or hand-review peer
adapter owns the shared primitive.

Provider labels, parser-layout compatibility, and pipeline-selection
reconciliation live in `domains/pipeline/model/pipelineSelection.ts`.
Pipeline and benchmark features consume the same
provider-neutral model; the analyzer page receives display-ready values from
the pipeline feature hook rather than importing domain internals.

Parser-routing evidence, metadata guards, and presentation helpers live under
`domains/pipeline/model/parserRouting*.ts`, consumed directly by the benchmark
feature and the system-info display without a feature-to-feature dependency.

The persisted analyzer history projection uses
`domains/history/model/historyItem.ts` as its shared domain shape. Screenshot
label formatting and the reusable screenshot rail row live under `shared/lib`
and `shared/components`, so history, queue, screenshot, and workspace features
do not depend on one another for presentation primitives.

A feature must not move unrelated persistence orchestration into its hook merely
to make the page coordinator shorter. New feature behavior should extend the
closest feature boundary, while future top-level experiences such as account or
authentication pages should enter through `src/app/routes.tsx` and a dedicated
directory under `src/pages`.

The review workspace is split into hand-state editing and approval panels.
Capture, administrator access, parser selection, benchmarks, screenshot
details, and system information each have a dedicated state hook or
controller. Dialogs and panels receive explicit
values and commands from those boundaries, which keeps them independently
testable while leaving user corrections and persisted mutation recovery under
one visible coordinator. Component tests are colocated with their components;
the analyzer coordinator's end-to-end state transitions are split into
domain-named integration suites under `src/pages/analyzer/__tests__`.
`src/test/analyzerHarness.tsx` supplies the shared workflow render boundary and
domain API defaults instead of duplicating monolithic fixtures. PWA CI
reports architecture, application-shell/edge-worker, analyzer-workflow, and
feature/domain failures in separate named steps. Non-cancelled slices continue
after an earlier domain failure so one run reports every independent result.
Backend tests are separated by router,
application service, domain model, repository contract, persistence/archive
compatibility, and provider policy; large static poker-policy suites remain
cohesive where splitting would obscure their ownership.
The application route shell owns canonical analyzer workspace, job, and
benchmark URLs. Typed analyzer route state restores the represented surface
and optional job identity, while workspace selections and surface closes update
the same URLs. Transient dialog internals and draft state remain outside the URL.
The source-architecture suite keeps `AnalyzerRoute.tsx`, `AnalyzerPage.tsx`, and
`AnalyzerWorkspaceComposition.tsx` below 300 lines and rejects raw transport,
browser persistence, mutation-lease, and poker-state transformation ownership
in every composition root. Visible session status remains owned by the tested
analyzer toolbar; the product currently has no separate status-footer surface.
The browser workflow matrix runs the same analyzer scenarios with
desktop Chrome and a Pixel-class mobile Chromium viewport. Each viewport runs
in a separate Playwright process so the backend harness provisions an isolated
temporary workspace for both project suites.
The analyzer route mounts a typed `AnalyzerWorkflowProvider`. Its pure reducer
owns cross-feature workflow state without copying server job records; queue
attention messages, queue-processing progress, and active job selection are
reducer-owned state families. Selection stores only the job ID; hand-review form
alignment, dirty tracking, and the synchronous service ref remain feature-owned.
A focused provider hook exposes the selection value and command, keeping its raw
event out of the analyzer composition root. Queue progress and attention use a
parallel focused hook for mark, clear, progress, finish, and abort commands;
abort controllers and upload effects remain runtime services outside the store.
Claimed processing and history mutation leases are initialized in provider state
and updated through a focused command. Runtime refs preserve synchronous reads,
while lease storage, compare-and-swap, settlement, timers, and recovery requests
remain outside the reducer.
The reducer derives abort progress while API, cancellation, and
browser-persistence side effects remain in commands and projection adapters.
Processing restore and mutation-lease revalidation use independent typed
request generations in the same store; promises, timers, and retry policy
remain runtime concerns outside the reducer. A focused recovery hook exposes
both generations and phases plus memoized request, start, retry, and finish
commands, keeping raw recovery events out of page composition. Each channel
also exposes explicit idle, requested, running, and retry-scheduled phases
advanced by those runtime effects without storing the effects themselves.
Pending restore promises, retry timers, active restore IDs, and retry flags are
stable refs owned by a focused recovery runtime-service hook; the page retains
the effects that consume those handles while the reducer remains serializable.
Queue abort controllers, mounted-state guards, and stale history-request
generations use a parallel request runtime-service hook. Media stream
ownership remains inside `useCaptureSource`.
The raw analyzer workflow context accessor is module-private. Production code
can consume only the focused selection, queue, mutation-lease, recovery, and
projection hooks, preventing page composition from bypassing command APIs.
PWA writes follow the same ownership rule. Upload/capture, approve, screenshot
metadata and deletion, history archive, benchmark inclusion/import, and
backup restore calls are confined to their domain API adapters and focused
feature command services. Commands return
explicit Query cache outcomes and preserve request identities, abort behavior,
mutation leases, and ambiguous-failure recovery. The source-architecture suite
audits the exact mutation inventory so pages and shared compatibility exports
cannot become write orchestrators again.
When benchmark-import recovery overlaps a lease retry timer, the active request
keeps the mutation-lease channel in the running phase; request settlement then
selects retry-scheduled or idle from the remaining lease state.

Workspace persistence is implemented by focused cache-validation,
mutation-lease, processing-queue, history, and reconciliation modules. The
former persistence, cache-validation, and mutation-lease compatibility barrels
are removed; consumers import those owners directly. Browser-facing processing,
history, and mutation-lease
operations are grouped in a stable projection adapter injected by
`AnalyzerWorkflowProvider`; the analyzer consumes that adapter through a focused
hook, while tests may replace it without patching browser globals.
Cache validation keeps primitive bounds, poker and completed-street state, and
parser/job records in focused modules.
Mutation-lease contracts, job and projection expectations, lease matching,
legacy decoding, browser storage, and lease factories are separate modules.

Poker card parsing, form conversion, canonical identity, state constants, and
preflop-position normalization live in focused modules under
`domains/poker/model`. Hand-review retains only confidence presentation and
consumes the domain model directly; the former poker-state compatibility barrel
has been removed. Persisted job-ID recognition and screenshot metadata
normalization live under `shared/lib` for page, workspace, and screenshot use.

`HandReviewPanel` owns only hand-state editing and review actions. The analyzer
page-level `HandReviewWorkspace` renders that single panel from typed
controller props, so no feature component imports a peer feature component.
The parser benchmark dialog is likewise a composition root: pipeline
comparison, report overview, result presentation, expandable case review, and
dataset/run actions live in focused benchmark components with direct tests.
Its controller separates report catalog loading, request invalidation, report
caching and selection, and previous-run comparison into
`useBenchmarkReportState`; parser selection, benchmark execution, dialog
commands, and case review remain in `useBenchmarkController`.
Benchmark report comparison, case trends, report caching, parser-route
aggregation, and value formatting live in focused modules; the former
`features/benchmark/lib/benchmarkPresentation.ts` barrel is removed.

Vitest enforces the source layout: shared code cannot depend on upper layers,
features and pages cannot depend on the application shell, feature libraries
and hooks cannot depend on their UI components, and production components
retain colocated tests. The root `main.tsx` bootstrap may import only `src/app`;
other undeclared top-level source locations fail the same check. Feature source
must live below `components`, `hooks`, or `lib`; feature-root barrels and
undeclared feature areas are rejected instead of bypassing UI dependency rules.
Production modules cannot import colocated tests, integration suites, or shared
test helpers. Feature TSX and CSS source must live below `components`, and CSS
imports, module compositions, value imports, and ICSS imports follow the same
layer direction as TypeScript imports. JavaScript modules below `src` are
rejected so they cannot bypass the typed source graph. Static Vite glob,
`import.meta.url`, and triple-slash path dependencies are resolved and checked
against the same layer rules.

The PWA
defensively normalizes optional provider metadata such as equity, candidate
EVs/frequencies, exploitability, preflop stack/range/sizing policy, and fallback
context. Supported postflop results also expose bounded tree/history metadata,
later-street conditioning status, replayed line, posterior reach, active
combinations, memory, and exploitability, while keeping exact configured OOP/IP
ranges behind a collapsed disclosure; providers remain free to omit those
fields. In production it uses same-origin `/api/*`;
`worker.js` forwards those requests and the exact `/mcp` route to `BACKEND_URL`,
replaces any browser-supplied proxy credential with its private
`API_PROXY_SECRET` binding, enforces the separate administration bearer on MCP
principal-management routes, and serves all other routes from Worker Static
Assets. When
`POKER_PROXY_SHARED_SECRET` is configured, FastAPI uses a constant-time
comparison to reject application API traffic that bypasses or misconfigures the
Worker. The Worker requires an HTTPS backend before attaching the secret,
follows only bounded same-origin redirects, and rejects cross-origin redirect
targets without exposing them to the browser. The health route stays public for
container orchestration. Empty secret configuration preserves the direct
local-development path.

The benchmark dialog lets a user explicitly include the current approved hand
as ground truth, run the active parser across the corpus, and inspect aggregate,
per-field, and per-case results. Case drill-downs compare expected and detected
values; selecting Review hand refetches the persisted job before opening it in
the correction workspace. The overview returns bounded recent-run summaries for
the requested parser/layout pair, defaulting to the deployment pair when the
query is omitted. Report controls identify that pair, compact field metrics
support trend comparisons, and full archived reports are loaded only when
selected. The same overview includes one lightweight latest-run entry and the
nearest preceding same-corpus entry for each enabled parser plugin compatible
with the selected layout. The control panel uses those entries to compare
accuracy, same-corpus point changes, and failures, then switches the active
parser and scoped report history in place; unavailable plugins remain read-only.
The preceding-run lookup scans persisted summary metadata beyond the bounded
history response and streams any unindexed legacy metadata without loading case
payloads or expanding the bounded sidecar backfill, so an older valid baseline
is not hidden by intervening runs. The PWA uses that pipeline baseline for
the selected latest report's overall and field-level detail trends while keeping
the report selector itself bounded. It retrieves the immutable prior report
through the existing detail endpoint, validates the parser, layout, and corpus
identity, then derives per-case regressions, recoveries, and mixed field changes
in the browser. A small bounded report cache reuses that detail when the user
selects it. Expanded changed cases join comparisons by field to expose prior
and current detections whose match state changed; completed/error transitions
use the same diagnostic surface without altering persisted reports.
The client can sequence the existing single-parser run endpoint across every
available compatible plugin. Progress identifies the active parser, each report
is persisted independently, and a provider-level failure does not stop later
plugins or roll back earlier results.
Reports and lightweight summaries persist a SHA-256 fingerprint over the sorted
selected job IDs, benchmarked approved-state fields, and source screenshot
bytes. The overview computes the same value for the current selected-layout
corpus. The client marks a
different or legacy missing report fingerprint as stale, excludes cross-corpus
trend comparisons, and clears the warning only after a fresh run followed by an
authoritative overview read. Metadata that does not participate in parser
scoring is intentionally excluded from the hash.
Rebuildable per-report summary sidecars keep overview reads independent of full
case payloads. A legacy store receives sidecars through a newest-first,
streaming metadata pass that stops once the requested history is populated and
does not materialize archived case details. Once history is full, overview reads
still repair unindexed report files new enough to displace its current cutoff,
covering interrupted writes and missing sidecars without migrating the older
archive. For automatic-parser reports, the client derives
a per-selected-provider accuracy and fallback breakdown from trusted case route
evidence. Its attribution denominator remains the report's full case count, so
older or failed cases without route metadata remain visible rather than being
silently omitted.

Benchmark run requests may carry the control panel's current parser provider and
layout profile. The backend applies the same deployment allowlist, readiness,
and parser/layout compatibility checks used for new uploads, then persists the
resolved pair on the report. A request without a body continues to use the
deployment defaults so existing operational scripts remain compatible. Parser
benchmark validation is independent of recommendation-provider readiness.
The overview exposes the global selected count, counts partitioned by effective
stored layout, and the deployment-default layout. Legacy jobs without a stored
layout are assigned to that default. A run reads only labels for its resolved
layout, so one client's screenshots cannot affect another layout's metrics.

The explicitly selected benchmark corpus can be exported as a ZIP without
running the parser. An explicit parser/layout query exports only the matching
layout corpus; an omitted selection uses the deployment defaults. `manifest.json`
identifies schema version 1, parser/layout context, and each approved canonical
state. Original screenshots are stored at stable `images/<job-id>.<ext>` paths
referenced by the manifest. Unselected jobs, other layouts, and parser output
are excluded.

The same archive can be imported to restore or share a corpus. Import validates
the complete manifest, paths, limits, and image payloads before creating jobs.
Schema version and declared case count must be JSON integers; coercion from
booleans, strings, or floating-point values is rejected.
Stable job IDs make exact re-imports idempotent; an existing job with different
image bytes, approved state, or effective layout rejects the archive instead of
being overwritten.
Imported cases are approved benchmark jobs. Ground-truth labels are not
copied into parser results, so an imported job never presents user-approved
state as detected OCR evidence.
Import results return the refreshed global and per-layout corpus counts. Legacy
completed import receipts without the layout map remain readable during rolling
upgrades.
The shared import/export corpus contract is capped at 250 selected hands; the
selection API prevents the app from producing a dataset that import rejects.
The offline runner can gate the corpus size and each field's labeled-case count
and accuracy independently. Repeated `FIELD=VALUE` requirements make the same
archive suitable for CI while exposing missing labels instead of allowing
well-covered card fields to mask weaker pot, bet, stack, or position parsing.
It can load a full prior JSON report and enforce maximum overall or per-field
accuracy drops only after validating parser, layout, and corpus fingerprint
identity. The fingerprint covers selected job IDs, approved labels, and source
screenshot bytes. JSON mode continues to emit only the current report on
stdout, keeping the output reusable as a later baseline while diagnostics and
gate failures use stderr.
Client/layout corpora are benchmarked separately with the parser profile under
test, keeping coverage and regression ownership explicit.

Full application backups are a separate schema and recovery boundary. A
versioned ZIP contains every durable `JobRecord`, its original image, and all
persisted benchmark reports. Because notes, tags, history timestamps, and
benchmark selection are job fields, they travel with the record. API
mutations hold a shared data-volume lock across the full request, including
background work. Browser and CLI exports take its exclusive side while
building the archive, then refuse to capture any persisted active parser work
or a pending benchmark import journal. Browser export bounds the exclusive
acquire and returns a conflict response when active mutations keep the snapshot
lock busy; CLI export retains its operational blocking behavior.

Restore parses and verifies the complete archive before acquiring the mutation
locks. It checks declared paths, entry counts and sizes, supported images,
record models, report references, and SHA-256 checksums. Schema version, entry
counts, and image byte sizes must be JSON integers. Under the locks it
rechecks current state, reuses exact records, creates only missing records, and
rejects divergent stable IDs. New job directories and report files are
published atomically; a write failure rolls back files created by that restore
and recomputes the latest-report pointer. Configuration, credentials, and
transient benchmark-import journals remain deployment concerns and are not
portable user data.

The backend image also exposes an operational backup CLI over this same archive
contract. It can export timestamped archives with bounded retention, validate
an archive without opening the production stores, and perform an isolated
restore drill in temporary storage. The drill repeats the restore to verify
idempotency, then re-exports and compares all jobs, images, and benchmark
reports. A separately mounted `POKER_BACKUP_DIR` is made writable by the
container entrypoint; completed archives still require independent off-host
replication because a second directory or volume on one host is not a disaster
recovery boundary.
An operator explicitly enrolls the verified production data mount by atomically
writing a versioned marker bound to `POKER_DATA_VOLUME_ID`. Application startup
does not manufacture this marker. Operational export requires an exact identity
match before it opens the stores or touches the backup destination, preventing
an unmounted or wrong data volume from producing an empty success and pruning
valid archives. Enrollment fsyncs both the marker contents and data-directory
entry before reporting success. Export revalidates the marker and required store
directories under the snapshot lock before constructors may create anything.
Each backup destination has a persistent advisory lock file. Atomic publication
and retention execute under its exclusive operating-system lock so overlapping
schedules cannot prune each other's preserved output. Archive bytes and the
destination directory are fsynced after publication, newly created destination
entries are made durable through their existing parent, and the directory is
fsynced again after retention changes.

Restored benchmark reports also require strict JSON booleans, non-negative
integer counters, and finite numeric accuracy/confidence values. Boolean and
string coercion is rejected throughout, and floating-point values cannot be
coerced into integer counters. Report, case, and per-field totals must agree
with their nested comparisons, including exact accuracy ratios and unique case
and field identities. Comparison fields are limited to the benchmark schema,
their expected and detected values must conform to each field's canonical
shape, card identities must remain unique across hero and board fields, numeric
comparison evidence must be finite and representable, normalized text must
remain canonical, and each persisted match flag must agree with the shared
benchmark matcher.

## State Flow

1. A capture or upload creates an independent job.
2. The configured parser returns detected state, confidence, warnings, and raw
   metadata. Field confidence values must be finite JSON numbers between zero
   and one; boolean and string coercion is rejected before approval evaluates
   them. The backend still records whether the result met the deployment's
   configured auto-approval thresholds as reviewable evidence; no browser
   automation consumes it any more. Detected pot, bet, and stack values must be
   finite
   non-negative JSON numbers, detected preflop open size must be positive, and
   player count must be a positive JSON integer. Boolean and string coercion is
   rejected.
3. The user approves a canonical state when requirements are met; deployment
   auto-approval may approve a confidence-eligible, warning-free parse. Approved
   numeric table state follows the same finite-number and integer contract as
   detected state; rejected input leaves the parsed job unchanged. Deployment
   auto-approval always leaves warning-bearing parser results for browser
   review; control-panel automation no longer exists, so every other approval
   is an explicit user action.
4. Completed queue items remain in processing until explicitly cleared into
   backend-persisted history. Unarchived upload and capture jobs restore in
   stable queue order after reload.
5. Explicitly selected approved states can be re-parsed as a benchmark corpus
   without mutating the job flow.

Batch items are isolated. A parser failure affects that item only and leaves
other queue items free to continue.

## Persistence

The backend stores jobs, images, and benchmark reports under `POKER_DATA_DIR`.
The PWA retains no automation preferences (control-panel automation was removed
with the import-first boundary); browser-local storage holds only the queue,
history, and recovery projections described below, and invalid or unavailable
storage falls back to the established application defaults.
Unarchived upload and capture jobs are exposed through a stable oldest-first,
offset-paged processing projection with a snapshot hash. The PWA caches at
most 100 of those records for immediate reload display, retains the complete
persisted count, and reconciles all backend pages once per browser session or
after queue membership changes. Snapshot changes restart the bounded page walk.
Once that authoritative backend projection completes, its matching processing
records replace in-memory and cached records regardless of `updated_at`; dirty
active form values remain separate until a persisted revision confirms the
user's uncertain mutation committed. The PWA records bounded,
browser-session mutation leases before persisted operations begin. Single-job
writes carry the job ID and an operation-specific expected effect for approval
or benchmark inclusion. An unrelated `updated_at` change cannot settle that
lease. If a leased job is missing from processing, including when its expected
mutation removes it from that projection, the PWA revalidates it by ID before
settling or removing it from the workspace. Legacy single-job leases without
operation-specific evidence remain conservative until their bounded expiry.
Upload and capture leases carry the baseline queue plus a client-generated
upload request ID; every upload now targets the parsed stage for each file.
The upload ID is sent with the multipart request and persisted on the backend
job, letting a replacement document distinguish a completed upload from work
that never began.
Benchmark dataset imports use a separate client-generated request identity in
both projection leases and the multipart request. Import identities are
alphanumeric-led and resolve to a strict child of the journal root. After
enforcing the compressed upload limit, the backend atomically publishes a
journal directory containing the ZIP and a pending receipt before parsing the
archive or changing the corpus.
Imported jobs retain that request identity, so a pending journal can
idempotently resume validation or repair a partial case after process
interruption. The receipt transitions atomically to failed after deterministic
validation errors or to completed only after every corpus write succeeds, and
is exposed through a recovery endpoint. This is the authoritative completion
evidence because newly created pristine benchmark cases are deliberately absent
from processing and history. Replaying the same terminal identity returns the
stored result or error without parsing or changing the corpus again.
Deterministic non-timeout 4xx responses release both import leases immediately;
ambiguous failures keep polling for the receipt. An observed pending receipt
keeps its browser recovery leases alive beyond the ordinary mutation window;
the backend either finishes the active import or resumes its durable archive.
Once a benchmark hand is edited or reapproved, it is no longer pristine and
remains in the processing projection and browser cache for correction across
reloads.
The upload ID is used instead of the display filename when matching a restored
queue. Dataset imports may also carry processing IDs expected to disappear. Batch
archive leases carry every target ID and baseline revision in both processing
and history scopes. A replacement document claims the leases, keeps the
affected projections unsynchronized, and revalidates with bounded backoff until
the required operation effect, queue appearance, removal confirmation, or
archive membership is observed. Batch upload leases record every selected
request ID before the first request. Ambiguous write failures retain their lease
through unchanged projections, and a replacement document cannot overwrite a
claimed lease with a second mutation in the same projection. Verified archives
additionally refresh the full newest-history projection so newly added
membership appears in the rail. Ordinary cache writes
still merge matching records by `updated_at`, avoid no-op storage writes, and
emit storage events so one tab cannot silently replace another tab's newer
local record. Invalid or substantially future-dated processing timestamps
invalidate the browser snapshot and force an authoritative reload instead of
outranking server state.
Processing records must also carry an explicit null archive marker; missing or
non-null markers are reconciled rather than treated as active work. Imported
benchmark-only jobs have approved labels but no parser result or error, so
untouched imports remain in the benchmark corpus without appearing as
processing work. Once an imported hand is reapproved or receives a retryable
error, it returns to the processing projection until that work is completed.
An untouched import explicitly opened for review remains workspace-only
across processing reconciliations even though
it stays excluded from the processing projection and browser queue cache. If
the same job later enters the processing projection, its authoritative record
replaces that workspace-only copy without creating a duplicate.
Archiving sets `archived_at` on the existing job rather than copying its data;
the history projection orders those jobs by archive time and returns a bounded
latest list plus the complete count. Offset-based reads let the PWA append
older pages inside the fixed history rail. The PWA restores the newest
projection once per browser session and retains only that bounded first page in
its local cache for immediate display and compatibility with history saved
before the backend archive contract. Server-confirmed changes to a reopened
archived job update the in-memory history projection and bounded cache through
the same shared job-replacement path; unsaved form edits do not alter history.
Incoming refresh pages reconcile matching jobs by `updated_at`, so an older
in-flight response cannot overwrite a newer saved correction.
Optional all-term history search filters the complete persisted archive before
offset paging. A history-specific lock gives each archive scan and snapshot hash
a consistent view without blocking unrelated active-job updates. Search pages
carry that snapshot version so the PWA appends the next page directly while
the archive is unchanged, and rebuilds the loaded extent in bounded larger
requests only after a version change. Search results and their match count remain
separate from the global archive count and newest-page browser cache.
Local development uses `apps/backend/data`; the container contract uses
`/app/data`. Coolify must mount persistent storage at `/app/data`. The container
entrypoint repairs volume ownership, then runs a strict deployment cleanup as
the non-root `poker` user before starting the requested process. Cleanup deletes
only valid screenshot job directories whose raw record has the retired V1
`recommended` status. It acquires the exclusive data-volume lock and rechecks
the candidates before deletion; current, malformed, unknown, and untrusted-path
records are not rewritten or removed. Current application models remain strict
and never load the retired status.

## Deployment Topology

- Environments: pushes to `main` promote to `staging`; `v*` tags promote to
  `production`; manual deployment workflows select either target explicitly.
- PWA: one Cloudflare Worker Static Assets deployment plus `/api/*` and
  `/mcp` proxy routes per environment.
- Backend: one Coolify Docker application per environment, built from the
  repository root with `apps/backend/Dockerfile`.
- MCP: local stdio processes and optional hosted `/mcp` routes use separate
  environment-specific client configurations. Hosted routes use revocable
  environment-bound bearer principals and remain dark unless explicitly
  configured.
- Access control: Cloudflare Access can allowlist users at the public
  PWA boundary. A shared Worker-to-backend secret protects the public
  Coolify application API from direct access.
- Resource protection: authenticated expensive operations use bounded in-memory
  token buckets keyed by full opaque identity digests. Inactive buckets expire
  after one refill window, with least-recently-used eviction enforcing the
  fixed memory bound without aliasing unrelated clients. The Worker strips
  unverified Access identity headers; the backend hashes a validated Cloudflare
  connecting IP only after Worker-secret authentication, then falls back to a
  shared proxy or direct-client identity.
  Limits are configurable independently for uploads, benchmarks, and archive
  transfers. The API client preserves server
  `Retry-After` metadata, and interrupted benchmark-import recovery suppresses
  receipt requests until that backoff expires.
  Buckets are process-local for each single-container environment; a future
  multi-replica deployment must enforce the same policy at the edge or in a
  shared limiter.
- Monitoring: a scheduled GitHub Actions probe checks the SPA, proxied health,
  and protected queue boundaries. It opens one incident issue after bounded
  retries and closes that issue on recovery. Optional Cloudflare Access service
  credentials are restricted to same-origin requests and redirects.
- Error reporting: optional backend and browser Sentry adapters capture only
  unhandled exceptions. Provider-specific initialization stays behind local
  adapters, reporting is disabled without a DSN, and an allowlisted evidence
  shape removes poker/request/user data before transmission. The backend adds
  only route, method, and opaque UUIDv4 request-ID correlation tags.

The PWA Worker proxy removes mixed-content and browser CORS issues from the
normal deployed path. Backend CORS remains configurable for local and direct API
testing.

## Portfolio Drift Monitoring

Poker Hero participates in the Studio81 Labs sibling-drift watch with Nexcue,
TableTap, Tarmoto, and Taven. A scheduled repository-owned workflow compares the
narrow shared infrastructure contract against each sibling and writes only a
single `infra-drift` issue in Poker Hero. Cross-repository source reads use the
read-only credential boundary from ADR 0045; issue writes continue to use the
repository-scoped GitHub Actions token and cannot affect a sibling repository.
