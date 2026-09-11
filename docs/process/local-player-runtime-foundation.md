# Local Player Runtime and Recovery PWA

The local player command starts the isolated security substrate defined by
[ADR 0050](../decisions/0050-establish-local-player-runtime-security-substrate.md).
The dedicated local player PWA delivery is defined by
[ADR 0053](../decisions/0053-serve-a-dedicated-local-player-pwa.md). It remains
a development checkpoint for the V2 runtime boundary, not the completed V2
player product.

## Approved next delivery scope

[ADR 0082](../decisions/0082-deliver-a-review-first-local-mvp.md) approves a
review-first controlled macOS arm64 pilot. #527 owns structured review and the
stateless local preview contract; #528 owns the missing manual application-file
update procedure and its verification. These are planned, not implemented by
the scope decision. #414 qualifies the exact candidate; #409 still needs the
real public corpus under `review-mvp/v1`. #412 and the remaining teaching loop
are deferred and no longer block bounded review implementation.

The application-file procedure must verify and stage a separate current bundle,
finish operations, verify/rehearse a current-format backup, stop the old runtime,
use the existing exclusive runtime lease, and launch the new bundle against the
same explicit data root with fresh sessions and a safe browser-shell handoff.
No migration, legacy fallback, automatic update/rollback, public installer or
other-platform support is authorized. Exact design and failure cases are in
[#405](https://github.com/Studio81Labs/sidekick/issues/405#technical-implementation-plan)
and [#528](https://github.com/Studio81Labs/sidekick/issues/528).

## Prerequisites

Bootstrap the repository so `apps/backend/.venv` and the pinned dependencies
exist:

```bash
pnpm bootstrap
```

`POKER_DATA_DIR` selects the player-controlled local data directory. If it is
not set, the backend default is `apps/backend/data` when the workspace command
is used. The directory must be owned by the current user and have no group or
world permissions (mode `0700` on Unix-like systems). A newly created directory
uses that mode; an existing shared directory is rejected rather than changed
silently. On macOS, extended ACL entries are also rejected because they can
grant access not represented by the mode bits.

The runtime creates `.player-runtime-key` there with owner-only file
permissions and opens the V2 imported-hand store under `imported-hands/` plus
the owner-only `.poker-hero-remote-reference-consent.json` and
`.poker-hero-reference-activation-catalog.json` states and the owner-only
`.poker-hero-learning-content-catalog.json` authority. The hand store directory
must satisfy the same ownership, mode, and macOS ACL checks. The runtime does
not open the V1 screenshot-job or benchmark stores. Do not copy the key into
browser storage, a URL, logs, or a hosted deployment.

## Current-only workspace layout

The player data root is identified by the owner-only
`.poker-hero-player-workspace.json` manifest. The local storage panel reports
its layout version next to the resolved data directory. Version 6 contains the
private `imported-hands/` store and its existing recovery journal, the
install-local remote-reference consent state, and the current
reference-activation and learning-content catalog authorities. Backup ZIPs have
their own independent schema version and contain none of the workspace
manifest, consent state, or either product/reference catalog.

Only a new empty private data directory can initialize this layout. First start
takes the exclusive data-volume lock, creates the complete imported-hand,
consent, reference-activation, and learning-content state set, and publishes
the version 6 manifest durably. A concurrent first start coordinates through
the data-volume lock; an existing version 6 manifest is revalidated and used.
Interrupted imported-hand writes retain their same-version recovery path.

Do not edit or replace the manifest manually. A symlink, shared permissions,
malformed JSON, an older or future version, a nonempty manifestless directory,
or a versioned workspace whose `imported-hands/` directory is missing fails
startup before stores open or mutate data. Preserve a rejected directory outside
the active `POKER_DATA_DIR`, start the current runtime with a new empty private
directory, then reimport authorized source text as fresh unapproved detections.
Do not delete or relabel a marker to force adoption. A missing, symlinked,
shared-permission, malformed, or unsupported consent, reference-catalog, or
learning-content-catalog state file under layout version 6 also fails startup.

Remote-reference consent is local-only by default. The packaged runtime does
not supply a provider policy, so consent cannot be accepted and no remote
request is possible. An embedding application must supply an already validated,
active provider-policy snapshot before the authenticated API will disclose an
offer or accept consent. Consent records the exact complete policy digest,
policy/disclosure revisions, and disclosed outbound categories. The offer
includes the exact terms, privacy, retention, training-use, and logging policy
text, and validates each text against its declared SHA-256 before it can be
shown or accepted. Revocation takes effect in the authoritative local state
immediately. No remote transport consumes this state yet. Consent is
intentionally absent from backup and restore, so a restored installation must
consent again after a future provider is configured.

## Start and stop

Run:

```bash
pnpm player:start
```

The command first builds and verifies the dedicated player PWA, then binds only
to `127.0.0.1:8765`, starts with proxy-header handling disabled, and opens the
default browser with a short-lived ticket in the URL fragment. Use
`pnpm player:build` when only the player assets need rebuilding. The PWA removes
the fragment before exchanging it, creates a process-local authenticated
session, and reports whether the boundary and player store are ready. The
authenticated page displays the resolved data location. Stop the service with
`Ctrl-C`; all browser sessions expire when the process exits.

Before listening, the runtime recovers interrupted imported-hand cascades under
the data-volume lock. The authenticated `/api/player/storage` status preserves
completed, quarantined, and failed recovery identifiers separately. A
quarantined or failed recovery is shown as requiring attention; completed
roll-forward recovery alone remains ready.

## Browser shell updates

When the same loopback origin serves a newer verified player PWA, its service
worker installs beside the controlling version and waits. The local page shows
an update notice; it never activates the waiting worker during the one-use
session bootstrap, backup export or restore, hand reads, lifecycle mutations,
permanent deletion, or session revocation. It also protects a selected backup
and edited approval, lifecycle, or deletion fields as local drafts.

Finish the active operation first. If drafts remain, either save or clear them,
or choose **Discard and reload** and confirm their loss. The page rechecks the
operation state and exact draft revision after the new worker takes control. If
anything changed during activation, it defers the reload and keeps the notice
visible until a later safe, explicit reload.

This is only the browser PWA shell handoff. It does not download, replace,
install, sign, or remove the runtime archive or migrate player data. Stop the
old runtime, verify and replace its application bundle through the applicable
release procedure, and start the new runtime; the separate player workspace
continues to follow the manifest and migration rules above.

## Build and verify a release bundle

The release-bundle checkpoint produces one self-contained archive for the
current Darwin or Linux build host:

```bash
pnpm player:package
```

The output under `dist/player-runtime/` is named with the root product version,
host operating system, architecture, and Python ABI. It contains the Python
runtime and dependencies plus the already verified player PWA assets. It does
not require a repository checkout, Node, pnpm, or a separately installed Python
runtime after extraction. It never contains the player workspace, installation
credential, backup, or other user data.

Verify the archive checksum, complete internal file manifest, clean-extraction
launch, one-use bootstrap and session flow, Host/Origin/CSRF and direct-LAN
boundaries, local shell/authentication boundary, and packaged export/remove
handoff:

```bash
pnpm player:package:test -- /absolute/path/poker-hero-player-*.tar.gz
```

After verification, extract the archive and run `./poker-hero-player`. The
packaged runtime keeps the fixed `127.0.0.1:8765` origin and opens the browser in
the same way as `pnpm player:start`. Its default data locations are:

- macOS: `~/Library/Application Support/Poker Hero/data`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/poker-hero/player/data`

Set `POKER_DATA_DIR` before launch to select a different private player-owned
directory. The data root remains outside the extracted application directory,
so replacing or deleting an extracted bundle does not update, migrate, export,
or remove player data. Export and remove it through the packaged executable:

```bash
./poker-hero-player export-and-remove \
  /absolute/private/player-backup.zip \
  --confirm-remove-data
```

These archives are unsigned release-engineering artifacts. They are not yet a
supported end-user installer or update channel. ADR 0082 chooses a controlled
macOS arm64 pilot; #528/#414 still must qualify
its installation/update/removal lifecycle. Public signing/notarization,
publication and additional platform support require a separate decision.

## Imported-hand backup and restore

The authenticated player API can export the current V2 imported-hand store as a
checksummed `poker-hero-player-backup` ZIP from
`GET /api/player/backups/export`. Restore accepts that ZIP at
`POST /api/player/backups/restore`; like every player mutation, it requires the
exact local Origin, the process-local bearer session, and its matching CSRF
token. The local recovery PWA exposes both controls. **Download backup** streams
the archive to the browser. **Restore backup** sends the selected ZIP only to
the same-origin loopback API, blocks page unload while the non-replayable request
is active, and refreshes storage status after success. A lost or incomplete
response is potentially committed: the PWA clears the selected archive, blocks
an immediate retry, and refreshes only after the runtime finishes the in-flight
restore. Storage status takes the shared data-volume lock; if that bounded wait
cannot produce a stable snapshot, the UI keeps the restore outcome explicitly
unresolved, hides stale totals and backup controls, and requires restart before
export or retry. Status waits behind the restore asynchronously before it uses
the shared worker pool, so queued refreshes cannot prevent restore completion. A
`503` restore storage failure is also unresolved because journal
intent or some files may already be durable. The PWA hides the pre-restore
status and requires a local runtime restart so startup recovery finishes before
export or another restore attempt.

Export includes each record, every retained decision artifact, and every
retained reference-activated grade artifact, including inactive audit history.
Current exports use player-backup schema version 4 and restore accepts only
that current schema. Older, future, malformed, and unsafe archives fail the
complete preflight before any restore mutation. Restore skips stale record and deletion generations,
and rejects conflicts, an attempt to reactivate a tombstone, or an unbound
tombstone targeting a live record. An active record must carry the exact
decision artifact re-derived from its canonical state, and a restored grade
must bind the named retained canonical revision and its exact decision. Accepted
changes are published through one recoverable multi-record cascade; a tombstone
bound to the same deletion-pending generation removes retained decision and
grade artifacts in that unit. Restored grades remain historical audit evidence
and never replace the install-local current reference or learning-content
catalogs. The format deliberately excludes those catalogs, remote-reference
consent, V1 screenshot jobs, parser benchmarks, and any hosted data.

## Export and remove local player data

Stop the local runtime before removing its workspace. From the repository
checkout, choose a new archive path in an existing private directory outside
`POKER_DATA_DIR`, then run:

```bash
pnpm player:export-and-remove /absolute/private/player-backup.zip --confirm-remove-data
```

Use `--data-dir /absolute/player-data` when the workspace is not selected by
the current environment. The command is local-only and refuses to continue
without `--confirm-remove-data`. It requires an existing versioned workspace;
it never creates or silently adopts a missing or manifestless source, follows
a workspace symlink, writes inside the workspace, or overwrites an archive.
Source and output parents must be owned by the current user and must not be
writable by another user or grant access through a macOS extended ACL. The
production player launcher holds an external lifetime lease for the complete
serve interval. The removal command acquires it exclusively and tells the
operator to stop the runtime even when that runtime is idle. It rescans for a
prior interrupted removal after acquiring the lease before it opens the active
workspace.

The command recovers an ordinary interrupted lifecycle write, then holds the
whole data volume exclusively. Quarantined or failed recovery evidence blocks
removal until it is repaired or separately preserved. The portable player
inventory must also account for every workspace entry; orphan records,
unrecognized decision artifacts, and other bytes omitted from the backup block
removal instead of being silently deleted. The backup is written owner-only,
synced, hashed, fully parsed, published without replacement, directory-synced,
reread, rehashed, and reparsed before the active workspace is renamed. The
renamed directory is verified as the exact source before best-effort cleanup.
No network service receives the archive or player data.

Exit status `0` means the verified archive is durable and player data removal
completed. Status `1` means the archive is safe but a moved/recreated data path
or final filesystem durability step requires the attention printed on stderr.
Status `2` means removal did not complete. When backup publication fails the
source remains active. When the later rename fails, both the source and the
already verified archive remain; preserve that archive and select a different
new output path before retrying. Never delete a reported retained removal
directory until its contents and the archive have been inspected. A later run
detects a path retained by an interruption after rename and reports it even
when the active source is already absent.

The player backup uses schema version 4 and contains portable V2 imported-hand
records with their retained decision and historical grade audit artifacts. Its
decoder accepts only schema version 4; older, future, malformed, and unsafe
archives are rejected during complete preflight before restore mutation. The
installation credential, in-workspace data and record locks, workspace manifest,
consent, current reference and learning-content catalogs, and recovered journal
machinery are installation metadata or product/reference authority and are
removed with the workspace rather than copied into the archive. The empty
sibling runtime-lease file contains no player data and may remain for future
coordination. This command does not remove the repository/application binary or
the browser's PWA installation; those remain operating-system and browser
lifecycle steps.

There is intentionally no player-runtime host or port flag. A non-loopback
operator development service would be a different runtime and would require
TLS plus its own server-enforced authorization design.

## Boundary verification

Run the direct-network browser checkpoint with:

```bash
pnpm player:test:e2e
```

The command builds both PWA entries, starts the production Uvicorn player
application on `127.0.0.1:8765`, and consumes a one-use launch URL through an
owner-readable test handoff file. It verifies the authenticated same-origin
storage and backup/restore flow, service-worker control, static-shell-only
caches, and a failed offline storage read. The same suite starts the production
Worker under local Wrangler with a recording backend. Direct and repeatedly
encoded player API POSTs must return `404` with `Cache-Control: no-store`, and
the recording backend must receive neither a request nor its sentinel body.
The backend transport test also connects through a discovered non-loopback
IPv4 address and requires connection refusal; Linux CI fails when it cannot
produce that LAN-side evidence instead of silently skipping it.

The browser harness uses only test-side launch and recording processes. It does
not add a ticket endpoint, configurable player bind address, hosted player
route, or production credential transport.

## Current limit

The local runtime now exposes authenticated session lifecycle, health, store
status, conflict-safe backup/restore, bounded multipart PokerStars text import,
sanitized imported-hand audit reads, approval/reapproval, withdrawal/rejection,
explicit imported-source conflict resolution, and permanent deletion under
`/api/player`, with an installable player PWA and
an explicit draft- and operation-safe browser-shell update handoff. Import
accepts one or more UTF-8 `.txt` files from the bounded English no-limit cash
adapter plus the single reviewed historical tournament-header form, isolates
every file and hand, and retains successful parser proposals as unapproved
audit; new hand identities remain pending review. Exact
response-loss retries reuse the same request UUID and ordered files; they keep
the first server timestamps and do not add another source occurrence. The PWA
persists only that outstanding UUID plus ordered filename/content hashes, so a
restart can safely reuse it after the exact files are reselected without
placing filenames or hand-history text in browser storage. A confirmed terminal
outcome erases the retry metadata. This is not the representative corpus or 99%
clean-parse evidence required by #409. The workspace now has a current-only
version 6 marker, current-only schema 4 backup/restore, and a verified
export-before-remove command for player data. Its durable reference-activation
and learning-content catalogs are install-local product/reference authority;
the packaged catalogs remain empty and no API publishes them. Persisted
reference-activated grades are immutable historical audit evidence and retain
their current-catalog/hand/content revalidation requirement. They do not grant
mastery or drill eligibility merely by existing on disk or in a restored
archive.

Authenticated local clients can page that retained history at
`GET /api/player/hands/{record_key}/grade-audits`. The response is a redacted
`historical_only` audit projection: it does not expose storage names, canonical
decision snapshots, evidence pointers, or principle text, and it does not
revalidate or authorize current mastery or drill use.

A host-platform release archive now embeds the runtime and verified PWA and is
exercised without a repository checkout, but it remains unsigned and does not
choose or implement an operating-system installer, application update channel,
application-file update, or browser installation/removal lifecycle. No
configured remote provider or transport consumes the retained consent state,
and there is no production solved-reference publication, HTTP/PWA grading
workflow, mastery, drill, or learning-proof store. The hosted Worker and V1
FastAPI deployment deny the player namespace, and the direct-network checkpoint
verifies that denial without proxying a request body. Do not use the runtime or
its test command alone as evidence that the shared Phase 1 gate is complete.
Issue #432's repository delivery scope is complete. The active review-release
work is #409 corpus evidence, #527 structured review, #528 application-file
lifecycle and #414 final decision. #412 is deferred, as summarized by the
[gate-readiness ledger](../reference/v2-phase-0-gate-readiness.md).
