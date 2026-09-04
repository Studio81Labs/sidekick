# ADR 0072: Persist the Current Learning-Content Catalog

Status: accepted

Date: 2026-09-04

## Context

ADR 0057 defined immutable taxonomy, mapping, principle, and reviewer-lifecycle
contracts without a persistence owner. ADR 0070 consequently requires a future
mastery boundary to reload current principle records as well as the current
reference catalog and approved hand. Accepting taxonomy, mapping, or principle
snapshots supplied by a caller would let a retained grade replay content after
its approval was retired or superseded.

The player workspace already provides a private install-local authority and an
exclusive volume lock. It does not yet persist grades, mastery, drills, or proof
metrics. The smallest safe checkpoint is therefore to own current learning
content without claiming that the empty packaged authority grants learning
eligibility.

## Decision

Add an immutable `LearningContentCatalog` that retains one current concept
series as complete taxonomy and mapping lineages plus complete immutable
principle revisions and their append-only lifecycle histories. The last
taxonomy and mapping revisions are current and must be mutually compatible.
Every retained principle must bind a known taxonomy revision and exact concept
definition. Principle lineages use canonical ordering, immutable revision
identities, contiguous predecessor links, and no more than one approved
revision for one principle identity.

Each non-empty catalog revision binds the exact semantic digest of its
predecessor. A publication may atomically append compatible taxonomy, mapping,
principle-revision, and lifecycle changes, but it cannot remove or rewrite any
retained history. Advancing a taxonomy and its mapping therefore happens in one
catalog publication; no staged taxonomy is presented as current.

`FileLearningContentCatalogStore` owns a fixed-identity catalog in a closed,
versioned JSON envelope with its exact semantic digest. Reads are bounded and
reject symlinks, non-regular files, shared permissions, foreign ownership,
malformed schemas, noncanonical nested content, foreign catalog identities,
and digest mismatch. Writes require the exact current revision and digest,
validate the predecessor binding and append-only history, then use an
owner-only temporary file, file `fsync`, atomic replacement, and directory
`fsync`. Retrying the exact already-replaced successor is idempotent.

Player workspace layout version 4 requires this authority. Fresh and
manifestless workspaces initialize an empty catalog before publishing the v4
manifest. Layout v1 and v2 upgrades initialize their previously introduced
authorities before the content catalog. Layout v3 preserves consent,
reference-activation catalog, and imported-hand bytes while adding only the
empty content catalog. The manifest advances only after all required state is
durable.

`PlayerWorkspace` exposes locked reads and compare-and-swap publication for
future application composition. No HTTP, MCP, PWA, automatic content import,
mastery update, or drill scheduling path is added.

The learning-content catalog is product/reference authority rather than a
portable player-derived record. It is excluded from player backup and restore,
which must not roll back reviewer lifecycle or reactivate obsolete learning
content. Deployment and administrative content distribution remain future
work.

## Consequences

The local runtime now has a durable source from which a later guarded mastery
operation can reload the current taxonomy, mapping, and complete principle
lifecycle evidence. Retired or superseded content no longer needs to be trusted
from a historical grade snapshot.

The packaged catalog remains empty. This decision does not revalidate a grade
against the current hand, reference catalog, and content under one consumption
scope; persist grades; authorize solved-reference sources; calculate mastery;
or schedule drills. Those remain later checkpoints under #416, #418, and #420.
