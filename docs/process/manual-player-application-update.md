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
different clean revisions. Run it from a clean source checkout at the intended
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
restores the final candidate export in a separate workspace before completing
export-before-data-removal. It also rejects a candidate
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

Validate the complete archive before staging it. The following macOS-only
procedure checks the sidecars, every manifest binding, every regular file's
size/mode/SHA-256, the complete file-and-link inventory, and every link target.
It extracts only to a temporary private inspection directory, which it removes
after validation; it does not stage an application. Run it once for the base
archive and once for the candidate archive. A corrupt, incomplete,
unexpected-platform, unknown-provenance, or failed-manifest archive is
rejected; do not try to repair it in place. It uses only standard macOS tools,
including the built-in `osascript` JavaScript runner to read JSON.

```bash
verify_player_archive() (
  set -eu
  umask 077
  archive=$1
  checksum="$archive.sha256"
  provenance="$archive.provenance.json"
  fail() { printf '%s\n' "archive verification failed: $*" >&2; exit 1; }
  json_value() {
    osascript -l JavaScript -e '
      ObjC.import("Foundation");
      function run(argv) {
        const text = ObjC.unwrap($.NSString.stringWithContentsOfFileEncodingError($(argv[0]), $.NSUTF8StringEncoding, null));
        let value = JSON.parse(text);
        for (const part of argv[1].split(".")) {
          if (value === null || typeof value !== "object" || !(part in value)) throw new Error("missing JSON path");
          value = value[part];
        }
        if (value === null || typeof value === "object") throw new Error("JSON path is not a scalar");
        return String(value);
      }
    ' "$1" "$2"
  }
  test -f "$archive" && test ! -L "$archive" || fail "archive is not a file"
  test -f "$checksum" && test ! -L "$checksum" || fail "checksum is not a file"
  test -f "$provenance" && test ! -L "$provenance" || fail "provenance is not a file"
  test "$(awk 'END { print NR }' "$checksum")" = 1 || fail "checksum has multiple lines"
  expected_digest=$(awk 'NR == 1 { print $1 }' "$checksum")
  test "$expected_digest" = "$(shasum -a 256 "$archive" | awk '{ print $1 }')" || fail "checksum mismatch"
  test "$(awk 'NR == 1 { print $2 }' "$checksum")" = "$(basename "$archive")" || fail "checksum filename mismatch"
  provenance_value() { json_value "$provenance" "$1"; }
  test "$(provenance_value schema_version)" = 1 || fail "unsupported provenance schema"
  test "$(provenance_value archive_name)" = "$(basename "$archive")" || fail "provenance archive name"
  test "$(provenance_value archive_sha256)" = "$expected_digest" || fail "provenance digest"
  test "$(provenance_value artifact)" = poker-hero-player-runtime || fail "provenance artifact"
  test "$(provenance_value source_tree_clean)" = true || fail "unclean source provenance"
  inspection_dir=$(mktemp -d "${TMPDIR:-/tmp}/poker-hero-player-verify.XXXXXX")
  trap 'rm -rf "$inspection_dir"' EXIT HUP INT TERM
  tar -tzf "$archive" | awk '
    /^\// || /(^|\/)\.\.($|\/)/ { exit 1 }
    { split($0, parts, "/"); if (!(parts[1] in roots)) { roots[parts[1]] = 1; root_count += 1 } }
    END { if (root_count != 1) exit 1 }
  ' || fail "unsafe or multi-root archive listing"
  tar -xzpf "$archive" -C "$inspection_dir"
  test "$(find "$inspection_dir" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')" = 1 || fail "archive root count"
  bundle_root=$(find "$inspection_dir" -mindepth 1 -maxdepth 1 -type d -print)
  test -n "$bundle_root" && test ! -L "$bundle_root" || fail "archive root"
  manifest="$bundle_root/manifest.json"
  test -f "$manifest" && test ! -L "$manifest" || fail "missing manifest"
  manifest_value() { json_value "$manifest" "$1"; }
  test "$(manifest_value schema_version)" = 1 || fail "unsupported manifest schema"
  test "$(manifest_value artifact)" = poker-hero-player-runtime || fail "manifest artifact"
  test "$(manifest_value artifact_name)" = "$(basename "$bundle_root")" || fail "manifest name"
  test "$(manifest_value platform.system)" = "$(uname -s | tr '[:upper:]' '[:lower:]')" || fail "platform system"
  test "$(manifest_value platform.machine)" = "$(uname -m)" || fail "platform machine"
  python_abi=$(manifest_value platform.python)
  case "$python_abi" in [0-9]*.[0-9]*.[0-9]*) ;; *) fail "platform Python ABI" ;; esac
  product_version=$(manifest_value product_version)
  product_tag=$(printf '%s' "$product_version" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9][^a-z0-9]*/-/g; s/^-//; s/-$//')
  expected_name="poker-hero-player-$product_tag-$(manifest_value platform.system)-$(manifest_value platform.machine)-cp$(printf '%s' "$python_abi" | awk -F. '{ print $1 $2 }')"
  test "$(manifest_value artifact_name)" = "$expected_name" || fail "manifest platform identity"
  : > "$inspection_dir/expected-paths"
  entry=0
  while inventory_path=$(manifest_value "files.$entry.path" 2>/dev/null); do
    case "/$inventory_path/" in /*//*) fail "empty manifest path segment" ;; *"/../"*) fail "unsafe manifest path" ;; esac
    case "$inventory_path" in /*|'') fail "unsafe manifest path" ;; esac
    kind=$(manifest_value "files.$entry.kind")
    mode=$(manifest_value "files.$entry.mode")
    target="$bundle_root/$inventory_path"
    case "$kind" in
      file)
        test -f "$target" && test ! -L "$target" || fail "missing file $inventory_path"
        test "$(stat -f '%z' "$target")" = "$(manifest_value "files.$entry.size")" || fail "size $inventory_path"
        test "$(stat -f '%Lp' "$target")" = "$(printf '%o' "$mode")" || fail "mode $inventory_path"
        test "$(shasum -a 256 "$target" | awk '{ print $1 }')" = "$(manifest_value "files.$entry.sha256")" || fail "checksum $inventory_path"
        ;;
      symlink)
        test -L "$target" || fail "missing link $inventory_path"
        link_target=$(manifest_value "files.$entry.target")
        test "$(readlink "$target")" = "$link_target" || fail "link target $inventory_path"
        test -e "$target" || fail "broken link $inventory_path"
        resolved_target=$(cd -P "$(dirname "$target")" && cd -P "$(dirname "$link_target")" && printf '%s/%s' "$PWD" "$(basename "$link_target")")
        case "$resolved_target" in "$bundle_root"/*) ;; *) fail "escaping link $inventory_path" ;; esac
        ;;
      *) fail "unknown manifest entry kind $kind" ;;
    esac
    printf '%s\n' "$inventory_path" >> "$inspection_dir/expected-paths"
    entry=$((entry + 1))
  done
  test "$entry" -gt 0 || fail "empty manifest inventory"
  (cd "$bundle_root" && find . -mindepth 1 \( -type f -o -type l \) ! -path './manifest.json' -print | sed 's#^./##' | LC_ALL=C sort) > "$inspection_dir/actual-paths"
  LC_ALL=C sort -u "$inspection_dir/expected-paths" > "$inspection_dir/sorted-expected-paths"
  diff -u "$inspection_dir/sorted-expected-paths" "$inspection_dir/actual-paths" || fail "incomplete manifest inventory"
  entrypoint=$(manifest_value entrypoint)
  test -f "$bundle_root/$entrypoint" && test ! -L "$bundle_root/$entrypoint" && test -x "$bundle_root/$entrypoint" || fail "entrypoint"
  printf 'verified %s\n' "$archive"
)

verify_player_archive /absolute/private/base/poker-hero-player-*.tar.gz
verify_player_archive /absolute/private/candidate/poker-hero-player-*.tar.gz
```

Extract base and candidate into unique private staging directories on the same
filesystem as `APP_ROOT`. The result is side-by-side staging, not replacement.
Publish each completed staging directory with one rename only after extraction
and the archive verification above have finished. If extraction is interrupted,
the trap removes only the incomplete staging directory; it never creates or
alters either final application directory or player data.

```bash
set -eu
umask 077
test ! -e "$APP_ROOT/base" && test ! -e "$APP_ROOT/candidate" || {
  printf '%s\n' 'final application directory already exists; do not overwrite it' >&2
  exit 1
}
BASE_STAGE=$(mktemp -d "$APP_ROOT/.base-staging.XXXXXX")
CANDIDATE_STAGE=$(mktemp -d "$APP_ROOT/.candidate-staging.XXXXXX")
trap 'rm -rf "$BASE_STAGE" "$CANDIDATE_STAGE"' EXIT HUP INT TERM
tar -xzpf /absolute/private/base/poker-hero-player-*.tar.gz -C "$BASE_STAGE"
tar -xzpf /absolute/private/candidate/poker-hero-player-*.tar.gz -C "$CANDIDATE_STAGE"
test "$(find "$BASE_STAGE" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')" = 1
test "$(find "$CANDIDATE_STAGE" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d ' ')" = 1
mv "$BASE_STAGE" "$APP_ROOT/base"
mv "$CANDIDATE_STAGE" "$APP_ROOT/candidate"
trap - EXIT HUP INT TERM
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
