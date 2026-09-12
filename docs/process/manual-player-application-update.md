# Manual Player Application Update Runbook

This runbook qualifies a **controlled macOS arm64 repository-build pilot**. It
does not create an installer, update channel, signing identity, notarization
claim, browser-PWA removal feature, rollback mechanism, or support commitment
for another platform. The supplied archive checksum proves artifact integrity;
it does not authenticate a publisher.

Use an archive built from a clean, committed repository revision and retain the
archive, `.sha256`, and `.provenance.json` files together. The provenance file
binds the archive digest to its clean source revision. It is evidence for the
controlled build channel, not a signature.

The package also writes that clean revision into the embedded player shell and
derives a new embedded service-worker cache key from it. A changed candidate
therefore serves and activates distinguishable shell/worker bytes; this is a
release identity marker, not a browser-stored hand draft or a network call.

## Preconditions

Record the exact candidate and base source revisions, archive SHA-256 values,
macOS version, hardware architecture, browser version, commands, observations,
and any limitation in the candidate evidence record for #414. Run the two
archive harness before a human pilot:

```bash
pnpm player:package:update:test \
  /absolute/private/base/poker-hero-player-*.tar.gz \
  /absolute/private/candidate/poker-hero-player-*.tar.gz
```

That release-engineering harness requires two separately built archives from
different clean revisions. Run it from a source checkout at the intended
candidate revision with the base revision available in its Git history. It
rejects an identical archive, the same source revision, a candidate that does
not match that checkout or descend from the base, or identical packaged
application files; a same-bundle restart is not update evidence. It verifies
both checksum/manifest/platform/provenance bindings, stages each bundle independently, confirms the candidate process
serves its own embedded shell, preserves an imported canonical revision and a
rejected lifecycle state, rehearses backup/restore, rejects an old runtime
session and concurrent runtime, checks corrupt/incomplete/interrupted staging,
tests occupied-port startup without workspace mutation, retains a newer
deletion through a stale restore, removes only the old application files, and
finishes with packaged export-before-data-removal. It also rejects a candidate
whose executed binary, shell, and worker bytes are unchanged. The test uses
only a temporary test workspace; it never accepts a production data path.

The target procedure below works from the delivered archives and standard
macOS tools; it does not require a repository checkout, pnpm, Node, or a
separately installed Python runtime. `UPDATE-RUNBOOK.md` in every archive is a
copy of this procedure.

Choose these absolute paths before starting. All four parents must be private
to the current macOS user. `APP_ROOT`, `BACKUP_ROOT`, and `RESTORE_DATA` must
be outside `POKER_DATA_DIR`; application directories and the data directory
must never overlap.

```bash
APP_ROOT="$HOME/Poker Hero Pilot/applications"
POKER_DATA_DIR="$HOME/Library/Application Support/Poker Hero/data"
BACKUP_ROOT="$HOME/Poker Hero Pilot/backups"
RESTORE_DATA="$HOME/Poker Hero Pilot/restore-rehearsal-data"
mkdir -p "$APP_ROOT" "$BACKUP_ROOT"
chmod 700 "$APP_ROOT" "$BACKUP_ROOT"
```

## Verify and stage the candidate without a checkout

Keep the base archive untouched. Put the candidate archive and its two
sidecars in a separate private directory. Do not overwrite an extracted base
directory and do not extract any application files into `POKER_DATA_DIR`.

For each archive, calculate its digest and compare it character-for-character
with both its `.sha256` sidecar and the `archive_sha256` value in its
`.provenance.json` sidecar. Confirm that `archive_name` matches the archive
filename, `artifact` is `poker-hero-player-runtime`, `source_tree_clean` is
`true`, and `source_revision` is the recorded clean revision. Confirm that
base and candidate revisions differ.

```bash
shasum -a 256 /absolute/private/candidate/poker-hero-player-*.tar.gz
cat /absolute/private/candidate/poker-hero-player-*.tar.gz.sha256
cat /absolute/private/candidate/poker-hero-player-*.tar.gz.provenance.json
```

Inspect the archive before extracting it. It must contain exactly one root
application directory, `manifest.json`, `BUNDLE-README.txt`,
`UPDATE-RUNBOOK.md`, an executable `poker-hero-player`, and `player-assets`.
The manifest's artifact name, product version, operating system, architecture,
and Python ABI must match the intended controlled host. A corrupt, incomplete,
unexpected-platform, unknown-provenance, or failed-manifest archive is rejected
before it is staged; do not try to repair it in place.

```bash
tar -tzf /absolute/private/candidate/poker-hero-player-*.tar.gz | sed -n '1,40p'
```

Extract base and candidate into different newly-created application directories.
The result is side-by-side staging, not replacement. Rename a completed
candidate directory into its final application directory only after the
extraction and manifest inspection finish. If extraction is interrupted, remove
only the incomplete candidate application directory; do not alter the old
application or player data.

```bash
mkdir -m 700 "$APP_ROOT/base"
tar -xzf /absolute/private/base/poker-hero-player-*.tar.gz -C "$APP_ROOT/base"
mkdir -m 700 "$APP_ROOT/candidate"
tar -xzf /absolute/private/candidate/poker-hero-player-*.tar.gz -C "$APP_ROOT/candidate"
```

Set `BASE_APP` and `CANDIDATE_APP` to the single root directory produced in
each staging location. Never combine their files or replace a binary while it
is running.

```bash
BASE_APP="$APP_ROOT/base/poker-hero-player-..."
CANDIDATE_APP="$APP_ROOT/candidate/poker-hero-player-..."
```

## Backup, restore rehearsal, and update

1. Start the base bundle with the explicit existing data directory. Complete
   or deliberately cancel any import, restore, approval, deletion, or
   reimport operation. Resolve quarantined or failed recovery evidence before
   continuing; do not update around it.

   ```bash
   POKER_DATA_DIR="$POKER_DATA_DIR" "$BASE_APP/poker-hero-player"
   ```

2. In the locally opened player page, download a current-format backup. Move
   it to a newly named path under `BACKUP_ROOT`, outside both application and
   data roots. The server verifies the export before it is published. Keep the
   original workspace in place.

3. Stop the base runtime with its normal terminal interrupt and close every
   tab opened by it. A stopped server is necessary but not sufficient: do not
   reuse an old URL fragment, session, page, or selected browser draft.

4. Rehearse the backup in a disposable private workspace before touching the
   primary workspace. Start the staged candidate with `RESTORE_DATA`, use its
   newly opened page to restore the backup, and inspect the expected hand
   identities, canonical revisions, lifecycle/deletion records, and source
   audit. Stop it afterwards and retain the primary data directory unchanged.

   ```bash
   POKER_DATA_DIR="$RESTORE_DATA" "$CANDIDATE_APP/poker-hero-player"
   ```

5. Start the same staged candidate against the explicit primary data directory.
   Use only the fresh one-use bootstrap URL it opens. Confirm that the existing
   records, canonical revisions, lifecycle/deletion evidence, and backups are
   present. The old page/session must not authorize this process. The existing
   service-worker coordinator must be allowed to hand off only after drafts and
   operations are clean; do not force activation around a selected backup,
   import/reimport file, canonical draft, approval reason, or deletion reason.

   ```bash
   POKER_DATA_DIR="$POKER_DATA_DIR" "$CANDIDATE_APP/poker-hero-player"
   ```

The runtime lifetime lease intentionally prevents a second bundle from serving
the same data directory. The fixed loopback port intentionally prevents another
runtime from binding it. On either failure, preserve the data directory, stop
the conflicting process, and retry only after the conflict is understood. Do
not reset data, copy files between application roots, downgrade, apply a
schema converter, or automatically roll back. A failed candidate is recovered
by reusing the verified candidate after the fault is fixed, or by restoring a
verified current-format backup into a separate workspace.

## Application and data removal are separate actions

After the candidate has been independently confirmed and stopped, application
removal means removing only the obsolete `BASE_APP` directory with the
operating-system file manager. It must leave `POKER_DATA_DIR`, the candidate
directory, backups, and browser data untouched. Do not claim that removing the
application removes the browser PWA.

Data removal is separate and always exports first. Stop every runtime, choose a
new backup path outside application and data roots, and run the executable in
the retained candidate directory:

```bash
"$CANDIDATE_APP/poker-hero-player" export-and-remove \
  "$BACKUP_ROOT/player-data-final.zip" \
  --data-dir "$POKER_DATA_DIR" \
  --confirm-remove-data
```

Exit code `0` means the verified backup is durable and removal completed. Exit
code `1` means the backup is safe but the printed retained data path requires
inspection. Exit code `2` means data removal did not complete. In either
non-zero case, preserve the printed paths and backup; never delete them to make
the command appear successful.

## What this does not claim

This runbook does not qualify public distribution, public signing,
notarization, a remote update/download service, automatic rollback, a data
migration, V1 compatibility, additional platforms, player-data hosting, or
live-play assistance. The exact integrated candidate still requires the #414
privacy/security/admin-isolation/lifecycle matrix and named review-pilot
decision before release.
