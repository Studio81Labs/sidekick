# ADR 0046: Adopt Import-First Learning Boundary

Status: accepted

Date: 2026-08-26

## Context

Poker Hero V1 is a capture-first post-hand analyzer. Its deployed PWA exposes
screenshot upload, browser window/screen/tab capture, queue automation, approval,
and recommendation transitions as one player workflow. Even though the product
is intended for post-hand training, a player-accessible live-capture path coupled
to recommendations resembles real-time assistance and creates an unacceptable
product and security boundary.

V2 changes the product unit from a screenshot/hand review to concept mastery. It
needs lossless hand histories, player actions, stable source chronology, solved
reference provenance, and revision-safe derived learning state. That requires a
new persistence lifecycle rather than reusing V1 screenshot jobs as canonical
player evidence. The current architecture remains deployed while this migration
is implemented, so the transition and rollback boundary must be explicit.

## Decision

The player product becomes import-first. Hand-history files are the only player
data-source path. Site adapters preserve raw input and emit detected state with
confidence, warnings, source evidence, stable hand identity, source chronology,
game/economic context, and voluntary/forced/client-automatic/unknown action
origin. A player reviews/corrects detected state and explicitly approves a
canonical hand revision before decision extraction or grading. User corrections
always win. Only actions approved as player-selected become V2 decision points;
forced, automatic, and unresolved-origin actions remain auditable but excluded
from grading and learning.

Exact and overlapping reimports are idempotent. Materially different inputs for
one stable hand identity become an explicit conflict and never silently replace
approved state or count twice. Reapproval creates a monotonic revision and
atomically supersedes or rebuilds every derived decision, grade, concept tag,
mastery input/aggregate, drill artifact, and proof-of-learning metric. Superseded
records remain auditable but inactive; one failed hand does not stop unrelated
imports.

Screenshot upload and live window/screen/tab capture remain only as an
administrative OCR/parser-test capability. The capability is disabled by default,
requires explicit deployment opt-in and server-enforced operator authorization,
and is absent from player navigation and capabilities. Administrative test data
is visibly marked and isolated from player jobs, recommendations, decision
points, mastery, drills, player exports, and proof metrics. Existing player
capture/recommendation automation is removed before Phase 1 validation. Frontend
hiding is not an authorization control.

Mastery uses only active, user-approved decisions graded against complete,
benchmarked solved-policy evidence with verified route inputs and compatible
economic, table-size, position, reference, taxonomy, and human-approved principle
revisions. Heuristic, assumed-input, policy-incomplete, or incompatible results
remain visible educational estimates but cannot move mastery or generate drills.
Player-facing output describes solved policies as conditional educational
references, never guaranteed optimal play or guaranteed outcomes.

Player data and grading remain local by default. A non-distributed remote solved
feed is an optional provider, never an implicit fallback. Before it is enabled,
the player must explicitly consent to the disclosed minimized lookup fields,
provider retention/use terms, and network dependency. Requests may contain only
pseudonymous route state required for lookup and must omit raw histories,
site/hand/session identifiers, player names, timestamps, screenshots, and
mastery/profile data. Consent is revocable, transport is encrypted, provenance
is auditable, and local-only mode remains usable with remote-only coverage
visibly unavailable.

## Security And Trust Boundaries

The trusted Worker/backend boundary enforces administrative capture/upload
authorization and transition denial. A direct caller cannot bypass the PWA to
turn administrative test input into a recommendation or learning record.
Administrative authorization is an explicit operator capability, not a role
implicitly granted to every local user.

The provider boundary separately enforces remote-feed consent and outbound field
allowlisting. Disabling or revoking a provider stops new requests immediately;
network/provider failure cannot silently fall back to a different remote source
or convert missing coverage into a solved grade.

Raw histories, detected state, approved revisions, conflicts, and derived
learning artifacts are separate persistence layers. Stable identities and active
revision pointers prevent duplicate or superseded evidence from inflating
mastery. Reference, taxonomy, and principle revisions are immutable provenance;
upgrades are staged and either atomically rebuild affected active state or begin
a separately labeled series.

## Consequences

The normal player experience can no longer use screenshots or live capture,
including for clients without hand-history export. Those clients remain outside
the V2 player workflow. Parser development retains representative upload/live
inputs without retaining a real-time recommendation path.

Import review and explicit approval add product friction, but prevent non-pot
parse errors from silently teaching the wrong lesson. Revisioned persistence,
deduplication, and rebuild rules add implementation complexity but keep learning
metrics auditable. Trustworthy solved references and reviewed principles become
release gates; if they are unavailable, V2 shows honest heuristic evidence or
does not grade the spot.

A remotely licensed feed can extend coverage without redistributing its dataset,
but opt-in lookup state leaves the device and offline/local-only users lose that
coverage. Provider contracts, privacy disclosure, minimization, revocation, and
failure behavior are therefore part of the grading gate rather than hidden
deployment details.

## Migration

Phase 0 implements the administrative capture boundary first, before Phase 1
player validation. It then introduces detected/approved imported-hand storage,
stable identity/conflict handling, chronology/economic context, decision
extraction, and benchmarked reference gates. The current V1 architecture
reference continues to describe deployed behavior until those migrations land.

Legacy screenshot jobs and V1 training analytics remain readable/auditable but
cannot be promoted into V2 canonical hands, decisions, mastery, drills, or proof
metrics. They lack the qualifying imported ordered action stream and real table
action; neither later approval nor a trustworthy grade can supply that missing
provenance. The underlying historical hand may enter V2 only through a new
qualifying hand-history import with its own stable identity and source
chronology. A V1 screenshot, recommendation, or pre-reveal training answer is
never reinterpreted as played-hand evidence. Backups must preserve
layer/revision provenance and restore idempotently without merging
administrative test data into player learning state.

## Rollout And Rollback

Rollout follows roadmap Phase 0: disable and authorize capture/upload, remove old
recommendation automation, verify direct-API denials and test-data isolation,
then enable hand-history detection/approval behind its own migration gate. Phase
1 cannot start until both the import/reference viability gates and the safety
prerequisite pass.

Rollback disables new imports and returns the player UI to a read-only view of
existing data; it does not restore player-accessible live capture or automatic
recommendations. If imported persistence must be rolled back, raw inputs and
revision/audit records are preserved for forward recovery while all derived V2
learning state is disabled. Administrative OCR testing may remain disabled
without affecting player history access.
