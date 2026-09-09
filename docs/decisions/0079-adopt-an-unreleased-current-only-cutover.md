# ADR 0079: Adopt an Unreleased Current-Only Cutover

Status: accepted by the product owner; implementation pending in #517 under Epic #405

Date: 2026-09-09

## Context

The product owner confirmed that V1 was never published to production. Breaking
changes are allowed; fallback to the old code or application and retained legacy
code are not allowed. Earlier plans incorrectly treated deployed V1 consumers
and development artifacts as compatibility obligations. PR #500 consequently
added old workspace/backup readers; the Phase 0 plan also retained the V1
recommendation benchmark and hosted audit surface.

At `578c8ed3b87f86d0685ca485696079c9b4a088bb` (#516), the code still reads
workspace layouts 1–5 and player backups 1–3, adapts benchmark schemas 1–5 through
the screenshot recommendation model, and builds the hosted analyzer alongside
the local player UI. This decision changes that target; it does not claim those
paths have already been removed.

This ADR supersedes V1 retention/fallback and pre-release compatibility
requirements in ADRs 0046, 0047, 0059 and 0077 and the Epic plan. It preserves
current V2 domain, security, provenance and lifecycle requirements. Historical
ADRs remain decision history, not instructions to recreate removed code.

## Decision

### One current implementation per capability

Remove compatibility-only readers, migrations, aliases, legacy adapters,
old-application navigation and recommendation fallbacks. A breaking contract
change is permitted when all current consumers and generated artifacts change
in the same mergeable unit. Do not leave a dual implementation, temporary V1
bridge, feature-flag fallback or compatibility re-export after the cutover.

Code is not obsolete merely because it originated in V1. Current requirements
still include administrator-only OCR/capture, parser benchmarks, explicit
review, registries, integrity checks and backup/restore. Retain their required
implementation as the current operator capability, with an explicit operator
entry point and authorization. Do not retain the old analyzer as a second
player application. Shared active code may be reused directly; it must not
route through a retired application contract.

Historical PokerStars text is an external input format, not an old application.
Keep the independently reviewed mappings from #502/#511/#514/#516 and their
provenance. Likewise, a native schema named `v1` is not automatically V1 product
code. Retained V2 grade audits and inactive canonical revisions remain required
current evidence; they do not become current grading authority.

### Current-only local persistence

The cleanup publishes workspace layout **6** and player backup schema **4** as
its only supported formats. Remove layout 1–5 upgrade/adoption paths and backup
1–3 readers. Keep the existing archive structure and current mandatory artifact
inventory, checksums, path/size limits, whole-archive preflight, atomic restore,
exclusive lifetime/volume locks, recovery journals and deletion protection.
Only a new empty directory may initialize layout 6. A nonempty manifestless,
older, future or malformed workspace fails before stores open or mutate data;
an unsupported backup fails before restore mutation. No automatic reset,
relabeling of old manifests or lossy import is allowed.

Use one current serialization/hash definition. Remove the old-hash preservation
branch in `_state_payload_for_hash`; content hashes bind the complete current
state JSON. Use ordinary nullable serialization for tournament entry buy-in,
fee and blind level rather than compatibility-only null exclusion. Semantic
normalization still excludes source occurrence identity and ignores ante-poster
labels when a confirmed zero ante makes them immaterial. Positive unknown ante
mode must remain distinct from a verified per-player or big-blind ante. Retain
all exact current reference/economic binding and aggregate revalidation.

Update all current hash consumers and fixtures together; do not accept either
old or new digests as a fallback. Existing development workspaces/backups are
unsupported by the new application. Operators can retain their files outside
the active workspace and start a fresh directory. Reimporting authorized source
histories creates fresh unapproved detections; old approvals or grade authority
are not copied. No ongoing old-binary reader or conversion service is required.
This decision authorizes compatibility removal, not automatic deletion of user
or developer files.

### Native grading and the operator surface

Remove the screenshot `RecommendationRequest`/`RecommendationResult` execution
path, legacy recommendation-benchmark schemas/runner, heuristic chart and
rule/range/solver/HTTP fallback implementations, and their exclusive settings,
CLI, dependency and test consumers. Preserve native imported-hand/grading,
reference qualification, consent/egress controls and current content/activation
contracts. Reuse any actually shared pure functionality in the current owning
module without an old-path re-export. Administrator parser benchmarks remain.

The planned native reference assessment and lookup under #412 are the sole
future grading instrumentation/provider path. They still require actual source
exports and rights before source-specific implementation. Removing V1 does not
create a solved reference: current player evaluation remains explicitly
unavailable until qualified native evidence and the downstream activation gate
exist. Do not retain a fallback while waiting or fabricate a replacement source.

Convert required hosted OCR/review/benchmark/backup operations into the explicit
operator surface. Serve its UI at `/admin/ocr` and its data routes beneath
`/api/admin/ocr`; apply the existing disabled-by-default test-mode and
server-enforced administrator boundary to every operator data read/write.
Remove `/analyzer` and old job/history/benchmark/backup route aliases; old paths
fail closed instead of redirecting into another application. Health/static
resources may remain public where currently required. Update current operator
callers, Worker routing, OpenAPI/client output, documentation and builds in the
same PR. No player record may traverse the hosted operator service. Keep the
reserved player-namespace denial and local PlayerApp/loopback composition.

### Execution and escalation

Execute serially after the decision documentation:

1. **C1:** current-only persistence, serialization and rejection/recovery tests.
2. **C2:** remove legacy recommendation execution and its exclusive consumers;
   keep native unavailable/qualification boundaries.
3. **C3:** explicit operator application/API cutover and final removal inventory.

Each PR must pass its relevant checks and merge before the next. This cleanup
is independent of the missing #409/#412 source evidence and can proceed now.
The existing evidence-dependent parser/reference work resumes when its inputs
qualify; #414 validates the final candidate including this cutover.

The orchestrator can remove compatibility branches and update current callers
within these contracts without another permission request. Escalate changes to
poker semantics, source support, user approval, audit/deletion/recovery
invariants, required operator functionality, trust boundaries, native public
contracts beyond this cutover, or useful-coverage/gate requirements. A newly
required production migration or real deployed consumer contradicts the premise
and requires escalation. A broken old developer fixture alone does not.

## Validation and consequences

Replace old-reader/upgrade/exact-legacy-hash acceptance tests with current-format
round trips, deterministic current hashes, strict unsupported-version rejection
without mutation, concurrent-process fencing, interrupted-write recovery,
tamper/path/symlink denial, stale-backup/deletion protection and explicit
approval/reimport tests. Keep current semantic-equivalence tests where they
encode poker meaning rather than historical bytes.

C2 proves no runtime/build/default can dispatch legacy advice and that native
qualification/content gates still fail closed. C3 verifies operator mode off,
unauthorized and authorized behavior for all data routes; removed routes;
player/hosted network isolation; generated API freshness; both PWA builds and
relevant browser tests. Run the full backend suite and the exact-candidate
local package/security/lifecycle matrix before the final #414 gate.

Update setup/reset procedures, architecture and issue checklists with actual
cutover versions. Rollback means fixing forward or disabling the affected
current capability; it never restores V1 or downgrades the current workspace.
Current-format audit/export remains available only when safe. No old application
or compatibility subsystem is maintained for rollback.

The representative corpus, verified reconnect/voluntary-action semantics,
solved-reference exports and delivery rights, poker review, budget approval and
owner-backed Phase 0 decision remain unmet. Removing backward compatibility
does not waive them. Full Epic #405 remains blocked; Phase 1 remains NO-GO.
