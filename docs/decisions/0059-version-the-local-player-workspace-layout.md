# ADR 0059: Version the Local Player Workspace Layout

Status: accepted

Date: 2026-09-01

## Context

The local player runtime already opens an owner-only workspace containing the
imported-hand store, its recoverable lifecycle journal, and the installation
credential. That workspace has no durable layout identifier. A future release
therefore cannot distinguish an older supported layout from a corrupt or newer
one before it opens stores and starts recovery.

Issue #432 requires a supported upgrade and migration boundary before the Phase
1 gate can open. Existing local workspaces must remain usable, but adopting
them must not rewrite raw histories, canonical revisions, decision artifacts,
or interrupted recovery evidence merely to label the layout.

## Decision

The player data root contains an immutable
`.poker-hero-player-workspace.json` manifest. Layout version 1 has the strict
shape:

```json
{ "layout_version": 1, "schema": "poker-hero-player-workspace" }
```

The manifest is an owner-only regular file read without following symlinks.
Unknown fields, non-integer or unsupported versions, excessive size, insecure
permissions, and malformed JSON fail startup explicitly. A valid versioned
workspace must already contain its private `imported-hands/` store; startup
does not silently recreate a missing store under an established manifest.

An absent manifest is the only legacy layout recognized by this migration. The
runtime acquires the exclusive data-volume lock, rechecks for a manifest after
the lock is held, then validates or creates the private imported-hand directory.
It publishes the version 1 manifest with a same-directory owner-only temporary
file, file `fsync`, create-only hard link, and data-directory `fsync`. A race
that finds another published marker rereads and validates it. A crash before
publication leaves the manifestless layout eligible for another idempotent
adoption; a failure after publication leaves the valid marker authoritative on
retry.

An existing version is reread and its store is constructed beneath a shared
data-volume hold, so a future exclusive migration cannot change the layout in
the middle of startup. A successfully read marker's parent directory is synced
before the workspace is accepted, which also completes durability after a
previous publication attempt failed between linking the marker and syncing its
directory. Every later store operation rereads the marker under its volume
hold, so a still-running older process fails closed if another process upgrades
the layout between requests.

The version 0-to-1 adoption adds only this sidecar. It does not scan or mutate
record, decision-artifact, backup, or cascade-journal bytes. Interrupted
imported-hand recovery runs under the same exclusive startup hold after
adoption, preserving the existing lock order. Existing version 1 workspaces
validate the marker before opening the store and retain the established
recovery path.

The authenticated storage status and local PWA disclose the active layout
version alongside the resolved player data location. Backup archives keep
their independent schema version; a workspace-layout marker is not player
record data and is not copied into the archive.

Future layout upgrades must define an explicit staged migration from a known
version under the exclusive data-volume lock. They must preserve or atomically
rebuild affected active state, remain retryable after interruption, reject
downgrades and unknown future versions, and update the manifest only after the
new layout is durable.

## Consequences

Current users receive an automatic, payload-preserving adoption on first
startup. New and adopted workspaces have an unambiguous compatibility gate, so
a binary cannot accidentally open a future or malformed layout with older
storage assumptions.

This is the first concrete player-workspace migration and progresses #432. It
does not add future grade, mastery, drill, or proof stores; migrate those
schemas; provide an operating-system installer/uninstaller; enable imports or
remote solved lookup; or close the Phase 1 gate.
