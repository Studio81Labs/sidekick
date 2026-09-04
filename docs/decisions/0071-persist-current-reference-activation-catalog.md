# ADR 0071: Persist the Current Reference Activation Catalog

Status: accepted

Date: 2026-09-04

## Context

ADR 0070 introduced a pure immutable reference-activation catalog. Its digest
chain can detect an inconsistent snapshot, but it cannot establish which
internally consistent snapshot is current. `ReferenceActivatedGrade` therefore
remains `requires_current_catalog_hand_and_content`, and later mastery or drill
composition must reload an independently owned current catalog authority.

The local player workspace already owns private install-local state and a
volume-wide interprocess lock. No grade, mastery, or drill artifacts are yet
persisted, and there is no player-facing or administrative activation surface.
The next safe checkpoint is to give the catalog a durable current owner without
claiming that the empty packaged catalog authorizes learning.

## Decision

Add `FileReferenceActivationCatalogStore` as an install-local product/reference
authority in the player workspace. It is configuration and audit state, not a
player-derived learning record.

The store uses a closed versioned JSON envelope containing the canonical
`ReferenceActivationCatalog` and its exact semantic digest. Reads are bounded
and reject symlinks, non-regular files, non-owner permissions, foreign ownership,
malformed schema, noncanonical nested evidence, digest mismatch, and invalid
catalog history. Writes use an owner-only temporary file, file fsync, atomic
replace, and directory fsync.

Publication is compare-and-swap under the workspace's exclusive volume lock.
The caller must supply the exact expected current catalog revision and digest.
The successor must preserve the catalog identity and every prior activation and
append exactly one validated event. A stale or divergent writer fails without
replacement. Retrying an exact successor after replacement but before a
successful directory fsync is idempotent: the store reconstructs and verifies
the expected predecessor before publishing the same bytes again.

Player workspace layout version 3 requires this catalog file. Fresh and
manifestless workspaces initialize an empty fixed-identity catalog before
publishing the v3 manifest. A v1 migration first ensures the v2 consent state and
then initializes the catalog; a v2 migration preserves consent and hand data and
initializes only the catalog. The manifest changes only after all required state
is durable. Current v3 startup requires the catalog to load successfully.

`PlayerWorkspace` exposes locked current-catalog load and publication methods to
future application composition. No HTTP, MCP, PWA, or automatic activation path
is added.

The catalog is deliberately excluded from player backup and restore. A player
archive must not roll product/reference authority backward or reactivate an old
reference series. Future deployment or administrative tooling must define its
own catalog distribution and recovery policy.

## Consequences

The local runtime now has one durable, concurrency-safe source for the trusted
current catalog revision and digest. A completely reconstructed snapshot cannot
replace it through the supported publication path merely by recomputing internal
hashes; it must be the exact next append from the current authority.

The packaged catalog remains empty, and nothing becomes mastery- or
drill-eligible. This decision does not configure or promote a solved reference,
persist content-ready grades, persist taxonomy or principle libraries, revalidate
current hand/content state, calculate mastery, schedule drills, change player
backup schema, or expose catalog mutation. Those remain later checkpoints under
#412, #416, #418, and #420.
