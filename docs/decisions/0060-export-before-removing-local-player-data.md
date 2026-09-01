# ADR 0060: Export Before Removing Local Player Data

Status: accepted

Date: 2026-09-01

## Context

Issue #432 requires local uninstall and export behavior without sending player
data to a central service. The repository does not yet package an
operating-system installer or own removal of application binaries, but it does
own the versioned player workspace and the portable V2 imported-hand backup
format.

Removing that workspace directly would risk deleting the only copy of raw hand
histories, approved revisions, inactive audit, deletion generations, and
derived decision artifacts. Reusing hand-level permanent deletion would also
be incorrect: those transitions deliberately preserve generation-bound
tombstones, while removing one installation must retire the entire workspace,
its local credential, locks, and layout metadata.

## Decision

The repository provides `pnpm player:export-and-remove` as a local-only,
explicitly confirmed data-removal command. It removes player data, not the
application checkout, installed browser shell, or operating-system package.
The operator must stop the local runtime and provide a new `.zip` path outside
the player workspace. Existing destinations are never overwritten.

The production player launcher holds a path-derived lifetime lease in the
workspace's private parent directory. Removal acquires that same lease
exclusively before opening or recovering the workspace, so an idle runtime is
still a named blocker and cannot recreate the active path after cleanup. The
empty sibling lease is coordination metadata, contains no player data, and is
not part of the removable workspace. Removal rescans for an earlier retained
removal directory after acquiring the lease, so concurrent invocations cannot
step past another invocation's interrupted outcome.

The command fails closed unless the source is an existing, non-symlinked,
owner-only workspace with the current versioned layout. It rejects filesystem
roots, the current user's home, a workspace containing the command's current
directory, shared, ACL-extended, or foreign-owned source and destination
parents, an output inside the workspace, and malformed or future layout
manifests. Manifestless legacy stores must first be adopted by a compatible
runtime; the removal path does not create or silently upgrade a source.

Opening the workspace completes ordinary interrupted-cascade recovery. Any
remaining ready write prevents a snapshot, and quarantined or failed recovery
evidence prevents removal because the portable archive cannot stand in for
that evidence. The final transaction holds the data-volume lock exclusively
and revalidates the current layout before it snapshots the store. It also
inventories the complete version 1 workspace and refuses removal when an
orphan record, unrecognized artifact, unexpected root entry, or other byte is
not either present in the portable snapshot or explicitly classified as
disposable installation metadata.

The command builds the existing `poker-hero-player-backup` archive, writes it
to an owner-only temporary file in the destination directory, syncs the file,
checks its exact SHA-256 bytes, and parses the complete archive. It publishes
with a create-only hard link, syncs the destination directory, then rereads,
rehashes, and reparses the published file. A publication or verification
failure leaves the active workspace in place.

Only after that durable verification does the command atomically rename the
exact workspace to a generated sibling removal directory. It verifies that the
moved directory has the source inode and device, syncs the parent, then removes
that exact generated path with the standard filesystem walker and syncs the
parent again. It never invokes a shell deletion command, follows a configured
workspace symlink, or broadens cleanup beyond the verified sibling path.

A rename failure leaves the original workspace and verified archive in place.
Cleanup or final durability failure keeps the archive and reports an
incomplete outcome plus a retained path when one still exists; the operator
must inspect that path before retrying. A successful result means the active
workspace is absent and the portable archive is durable. Generated removal
paths include the workspace-path identity. A later invocation scans for those
paths before requiring the active source, so a process or power interruption
after the rename produces a discoverable, blocking recovery path rather than
orphaned hidden data.

The archive contains the portable imported-hand records and retained decision
artifacts defined by ADR 0052. Installation credentials, in-workspace lock
files, the workspace-layout marker, and recovery machinery are local
installation metadata and are intentionally removed rather than exported. V1
screenshot jobs, parser benchmarks, hosted data, and future stores outside
layout version 1 are not part of this command.

## Consequences

An operator can retire the current local player workspace without trusting a
copy that was only partially written or never parsed. The command preserves a
recoverable boundary across publication, rename, and best-effort cleanup, and
does not weaken hand-level tombstone or backup-restore semantics.

Stopping the runtime is an enforced operational precondition for the production
launcher, but this checkpoint does not add an installer-wide process
supervisor. A verified archive remains at its chosen path when a later rename
fails, so a retry must choose another new destination or deliberately preserve
and manage the first archive.

This progresses the uninstall/export criterion of #432. It does not remove
application binaries or browser installation state, package an
operating-system installer/uninstaller, add future learning stores, or close
the Phase 1 gate.
