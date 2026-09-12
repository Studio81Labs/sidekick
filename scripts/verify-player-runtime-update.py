#!/usr/bin/env python3
"""Exercise a manual, side-by-side update between two player archives.

This is release-engineering evidence, not an updater. It deliberately stages
two supplied archives in private temporary application directories and leaves
the tested player workspace untouched until the final explicit export/remove
check. Run it only with archives built from two clean, committed revisions.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
from importlib import util
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
from threading import Thread
from time import monotonic, sleep
from types import ModuleType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LAUNCH_CAPTURE_HELPER = ROOT / "scripts" / "capture-player-launch-url.sh"
PLAYER_ORIGIN = "http://127.0.0.1:8765"
PROVENANCE_SCHEMA_VERSION = 1
_UUID_IMPORT = "55555555-5555-4555-8555-555555555555"
_UUID_APPROVE = "33333333-3333-4333-8333-333333333333"
_UUID_DELETE = "11111111-1111-4111-8111-111111111111"
_DELETE_REASON = "Exercise stale-restore protection after manual update"

_SYNTHETIC_HAND = b"""PokerStars Hand #900000000002: Hold'em No Limit ($0.50/$1.00 USD) - 2026/08/30 12:35:56 ET
Table 'Synthetic Heads Up' 2-max Seat #1 is the button
Seat 1: Heads Hero ($100.00 in chips)
Seat 2: Heads Rival ($100.00 in chips)
Heads Hero: posts small blind $0.50
Heads Rival: posts big blind $1.00
*** HOLE CARDS ***
Dealt to Heads Hero [Qc Jh]
Heads Hero: folds
Uncalled bet ($0.50) returned to Heads Rival
Heads Rival collected $1.00 from pot
*** SUMMARY ***
Total pot $1.00 | Rake $0.00
Seat 1: Heads Hero (button) (small blind) folded before Flop
Seat 2: Heads Rival (big blind) collected ($1.00)
"""


class PlayerUpdateValidationError(RuntimeError):
    pass


def _load_smoke_module() -> ModuleType:
    spec = util.spec_from_file_location(
        "player_runtime_smoke", ROOT / "scripts" / "smoke-player-runtime.py"
    )
    if spec is None or spec.loader is None:
        raise PlayerUpdateValidationError("Could not load the runtime verifier")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SMOKE = _load_smoke_module()


@dataclass(frozen=True)
class ValidatedBundle:
    archive_path: Path
    archive_sha256: str
    provenance: dict[str, object]
    bundle_root: Path
    entrypoint: Path
    manifest: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_regular_file(path: Path, *, description: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink() or not expanded.is_file():
        raise PlayerUpdateValidationError(f"{description} must be a regular file")
    return expanded.resolve(strict=True)


def _provenance_path(archive_path: Path) -> Path:
    return archive_path.with_name(archive_path.name + ".provenance.json")


def _read_provenance(archive_path: Path) -> dict[str, object]:
    provenance_path = _provenance_path(archive_path)
    _require_regular_file(provenance_path, description="Runtime build provenance")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlayerUpdateValidationError("Runtime build provenance is invalid") from exc
    expected_fields = {
        "archive_name",
        "archive_sha256",
        "artifact",
        "schema_version",
        "source_revision",
        "source_tree_clean",
    }
    if not isinstance(provenance, dict) or set(provenance) != expected_fields:
        raise PlayerUpdateValidationError("Runtime build provenance fields are invalid")
    if provenance["schema_version"] != PROVENANCE_SCHEMA_VERSION:
        raise PlayerUpdateValidationError("Runtime build provenance schema is unsupported")
    if provenance["artifact"] != "poker-hero-player-runtime":
        raise PlayerUpdateValidationError("Runtime build provenance identity is invalid")
    if provenance["archive_name"] != archive_path.name:
        raise PlayerUpdateValidationError("Runtime build provenance archive name is invalid")
    if provenance["archive_sha256"] != _sha256_file(archive_path):
        raise PlayerUpdateValidationError("Runtime build provenance archive digest is invalid")
    if re.fullmatch(r"[0-9a-f]{40,64}", str(provenance["source_revision"])) is None:
        raise PlayerUpdateValidationError("Runtime build provenance revision is invalid")
    if provenance["source_tree_clean"] is not True:
        raise PlayerUpdateValidationError("Runtime build provenance is not a clean source")
    return provenance


def _stage_archive(archive_path: Path, *, stage_root: Path, label: str) -> ValidatedBundle:
    """Verify first, then publish one complete application directory by rename."""

    archive_path = _require_regular_file(archive_path, description="Runtime archive")
    if re.fullmatch(r"[a-z][a-z0-9-]*", label) is None:
        raise PlayerUpdateValidationError("Runtime staging label is invalid")
    SMOKE._verify_archive_checksum(archive_path)
    provenance = _read_provenance(archive_path)
    archive_sha256 = _sha256_file(archive_path)
    final_stage = stage_root / f"{label}-{archive_sha256[:12]}"
    work_stage = stage_root / f".{label}-{archive_sha256[:12]}.staging"
    if final_stage.exists() or final_stage.is_symlink() or work_stage.exists():
        raise PlayerUpdateValidationError("Runtime staging destination already exists")
    stage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stage_root.is_symlink() or not stage_root.is_dir():
        raise PlayerUpdateValidationError("Runtime staging root is invalid")
    try:
        extracted_root = SMOKE._extract_archive(archive_path, work_stage)
        manifest = SMOKE._bundle_manifest(extracted_root)
        entrypoint = SMOKE._verify_bundle(extracted_root)
        os.replace(work_stage, final_stage)
    except BaseException:
        shutil.rmtree(work_stage, ignore_errors=True)
        raise
    bundle_root = final_stage / extracted_root.name
    return ValidatedBundle(
        archive_path=archive_path,
        archive_sha256=archive_sha256,
        provenance=provenance,
        bundle_root=bundle_root,
        entrypoint=bundle_root / entrypoint.relative_to(extracted_root),
        manifest=manifest,
    )


def _bundle_inventory_digest(manifest: dict[str, Any]) -> str:
    entries = manifest.get("files")
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _embedded_player_asset_path(bundle: ValidatedBundle, filename: str) -> Path:
    matches = [
        entry.get("path")
        for entry in bundle.manifest["files"]
        if isinstance(entry, dict)
        and isinstance(entry.get("path"), str)
        and entry["path"].endswith(f"player-assets/{filename}")
    ]
    if len(matches) != 1:
        raise PlayerUpdateValidationError(
            f"Runtime bundle does not contain one verified embedded {filename}"
        )
    return bundle.bundle_root.joinpath(*Path(matches[0]).parts)


def _executed_application_digest(bundle: ValidatedBundle) -> str:
    executed_paths = {
        bundle.entrypoint.relative_to(bundle.bundle_root).as_posix(),
        _embedded_player_asset_path(bundle, "index.html")
        .relative_to(bundle.bundle_root)
        .as_posix(),
        _embedded_player_asset_path(bundle, "sw.js")
        .relative_to(bundle.bundle_root)
        .as_posix(),
    }
    entries = [
        entry
        for entry in bundle.manifest["files"]
        if isinstance(entry, dict) and entry.get("path") in executed_paths
    ]
    return sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _require_distinct_bundles(base: ValidatedBundle, candidate: ValidatedBundle) -> None:
    if base.archive_sha256 == candidate.archive_sha256:
        raise PlayerUpdateValidationError(
            "Base and candidate archives are identical; a same-bundle restart is not update evidence"
        )
    if base.provenance["source_revision"] == candidate.provenance["source_revision"]:
        raise PlayerUpdateValidationError(
            "Base and candidate have the same source revision; build a changed candidate"
        )
    if _bundle_inventory_digest(base.manifest) == _bundle_inventory_digest(candidate.manifest):
        raise PlayerUpdateValidationError(
            "Base and candidate application files are identical; a same-bundle restart is not update evidence"
        )
    if _executed_application_digest(base) == _executed_application_digest(candidate):
        raise PlayerUpdateValidationError(
            "Base and candidate executed application and shell bytes are identical"
        )


def _runtime_environment(data_dir: Path, capture_path: Path) -> dict[str, str]:
    return {
        "BROWSER": str(LAUNCH_CAPTURE_HELPER),
        "PATH": os.pathsep.join(("/usr/bin", "/bin")),
        "POKER_DATA_DIR": str(data_dir),
        "POKER_DEPLOYMENT_ENVIRONMENT": "local",
        "POKER_HERO_PLAYER_LAUNCH_URL_FILE": str(capture_path),
    }


def _start_runtime(
    bundle: ValidatedBundle,
    *,
    data_dir: Path,
    capture_path: Path,
) -> tuple[subprocess.Popen[bytes], dict[str, object]]:
    capture_path.unlink(missing_ok=True)
    process = subprocess.Popen(
        [str(bundle.entrypoint)],
        cwd=bundle.bundle_root,
        env=_runtime_environment(data_dir, capture_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        SMOKE._wait_for_runtime(process, data_dir=data_dir)
        expected_shell = _embedded_player_asset_path(bundle, "index.html").read_bytes()
        shell = SMOKE._require_response(
            SMOKE._request("/"), status=200, description="Packaged runtime shell"
        )
        if shell != expected_shell:
            raise PlayerUpdateValidationError(
                "Running runtime did not serve its staged application shell"
            )
        expected_worker = _embedded_player_asset_path(bundle, "sw.js").read_bytes()
        worker = SMOKE._require_response(
            SMOKE._request("/sw.js"),
            status=200,
            description="Packaged runtime worker",
        )
        if worker != expected_worker:
            raise PlayerUpdateValidationError(
                "Running runtime did not serve its staged application worker"
            )
        ticket = SMOKE._wait_for_launch_ticket(capture_path)
        return process, _exchange_session(ticket)
    except BaseException:
        _stop_runtime(process)
        raise


def _exchange_session(ticket: str) -> dict[str, object]:
    body = SMOKE._require_response(
        SMOKE._request(
            "/api/player/session",
            method="POST",
            headers={
                "Authorization": f"Bearer {ticket}",
                "Origin": PLAYER_ORIGIN,
            },
            body=b"",
        ),
        status=200,
        description="Fresh bootstrap ticket exchange",
    )
    session = SMOKE._decode_json_object(body, description="Fresh bootstrap ticket")
    if (
        set(session) != {"csrf_token", "expires_in_seconds", "session_token"}
        or not isinstance(session.get("session_token"), str)
        or not isinstance(session.get("csrf_token"), str)
        or session.get("expires_in_seconds") != 86400
    ):
        raise PlayerUpdateValidationError("Fresh bootstrap ticket returned an invalid session")
    return session


def _session_headers(session: dict[str, object], *, mutation: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {session['session_token']}"}
    if mutation:
        headers.update(
            {
                "Origin": PLAYER_ORIGIN,
                "X-Poker-CSRF-Token": str(session["csrf_token"]),
            }
        )
    return headers


def _json_response(
    path: str,
    *,
    session: dict[str, object],
    description: str,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    merged_headers = _session_headers(session, mutation=method != "GET")
    if headers is not None:
        merged_headers.update(headers)
    response = SMOKE._require_response(
        SMOKE._request(path, method=method, headers=merged_headers, body=body),
        status=200,
        description=description,
    )
    return SMOKE._decode_json_object(response, description=description)


def _multipart_import_body() -> tuple[bytes, str]:
    boundary = "poker-hero-update-boundary"
    body = b"".join(
        (
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="request_id"\r\n\r\n',
            _UUID_IMPORT.encode(),
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            (
                b'Content-Disposition: form-data; name="files"; '
                b'filename="update-validation.txt"\r\n'
            ),
            b"Content-Type: text/plain\r\n\r\n",
            _SYNTHETIC_HAND,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        )
    )
    return body, f"multipart/form-data; boundary={boundary}"


def _import_and_reject(session: dict[str, object]) -> tuple[str, dict[str, Any]]:
    body, content_type = _multipart_import_body()
    outcome = _json_response(
        "/api/player/imports",
        session=session,
        method="POST",
        body=body,
        headers={"Content-Type": content_type},
        description="Update-validation hand import",
    )
    try:
        record_key = outcome["files"][0]["hands"][0]["record_key"]
    except (IndexError, KeyError, TypeError) as exc:
        raise PlayerUpdateValidationError(
            "Update-validation hand was not retained by the base runtime"
        ) from exc
    if not isinstance(record_key, str):
        raise PlayerUpdateValidationError("Update-validation hand identity is invalid")
    detail = _hand_detail(record_key, session)
    summary = detail["summary"]
    approval_payload = {
        "request_id": _UUID_APPROVE,
        "detection_id": detail["detections"][-1]["detection_id"],
        "approved_state": detail["detections"][-1]["state"],
        "correction_reason": None,
        "expected_record_version": summary["record_version"],
        "expected_lifecycle_status": summary["lifecycle_status"],
        "expected_active_canonical_revision": summary["active_canonical_revision"],
        "expected_canonical_revision_count": summary["canonical_revision_count"],
        "expected_deletion_generation": summary["deletion_generation"],
        "expected_lifecycle_changed_at": summary["lifecycle_changed_at"],
    }
    detail = _json_response(
        f"/api/player/hands/{record_key}/approve",
        session=session,
        method="POST",
        body=json.dumps(approval_payload).encode(),
        headers={"Content-Type": "application/json"},
        description="Update-validation hand approval",
    )
    approved_summary = detail.get("summary")
    if (
        not isinstance(approved_summary, dict)
        or approved_summary.get("lifecycle_status") != "active"
        or approved_summary.get("active_canonical_revision") != 1
        or approved_summary.get("canonical_revision_count") != 1
    ):
        raise PlayerUpdateValidationError(
            "Update-validation approval did not create a canonical revision"
        )
    reject_payload = {
        "reason": "Exercise lifecycle preservation across a manual update",
        "expected_active_canonical_revision": 1,
        "expected_deletion_generation": approved_summary["deletion_generation"],
        "expected_lifecycle_changed_at": approved_summary["lifecycle_changed_at"],
    }
    detail = _json_response(
        f"/api/player/hands/{record_key}/reject",
        session=session,
        method="POST",
        body=json.dumps(reject_payload).encode(),
        headers={"Content-Type": "application/json"},
        description="Update-validation lifecycle rejection",
    )
    if detail.get("summary", {}).get("lifecycle_status") != "rejected":
        raise PlayerUpdateValidationError(
            "Update-validation lifecycle did not retain the rejected state"
        )
    return record_key, detail


def _hand_detail(record_key: str, session: dict[str, object]) -> dict[str, Any]:
    return _json_response(
        f"/api/player/hands/{record_key}",
        session=session,
        description="Retained update-validation hand",
    )


def _hand_snapshot(detail: dict[str, Any]) -> str:
    fields = {
        "summary": detail.get("summary"),
        "lifecycle": detail.get("lifecycle"),
        "canonical_revisions": detail.get("canonical_revisions"),
        "deletion_receipt": detail.get("deletion_receipt"),
    }
    return json.dumps(fields, sort_keys=True, separators=(",", ":"))


def _export_backup(session: dict[str, object]) -> bytes:
    return SMOKE._require_response(
        SMOKE._request(
            "/api/player/backups/export",
            headers=_session_headers(session),
        ),
        status=200,
        description="Update-validation backup export",
    )


def _restore_backup(session: dict[str, object], archive: bytes) -> None:
    _json_response(
        "/api/player/backups/restore",
        session=session,
        method="POST",
        body=archive,
        headers={"Content-Type": "application/zip"},
        description="Update-validation backup restore",
    )


def _delete_payload(detail: dict[str, Any]) -> dict[str, object]:
    summary = detail["summary"]
    return {
        "request_id": _UUID_DELETE,
        "reason": _DELETE_REASON,
        "expected_record_version": summary["record_version"],
        "expected_lifecycle_status": summary["lifecycle_status"],
        "expected_active_canonical_revision": summary["active_canonical_revision"],
        "expected_deletion_generation": summary["deletion_generation"],
        "expected_lifecycle_changed_at": summary["lifecycle_changed_at"],
    }


def _delete_hand(
    record_key: str, detail: dict[str, Any], session: dict[str, object]
) -> dict[str, Any]:
    payload = _delete_payload(detail)
    deleted = _json_response(
        f"/api/player/hands/{record_key}/delete",
        session=session,
        method="POST",
        body=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        description="Update-validation hand deletion",
    )
    if deleted.get("summary", {}).get("lifecycle_status") != "deleted":
        raise PlayerUpdateValidationError("Update-validation hand was not deleted")
    return deleted


def _ready_cascade_markers(data_dir: Path) -> tuple[Path, ...]:
    cascade_root = data_dir / "imported-hands" / ".cascade"
    if not cascade_root.is_dir() or cascade_root.is_symlink():
        return ()
    return tuple(
        sorted(
            (
                marker
                for marker in cascade_root.glob("*/ready")
                if marker.is_file() and not marker.is_symlink()
            ),
            key=lambda marker: marker.as_posix(),
        )
    )


def _wait_for_ready_cascade(
    data_dir: Path,
    process: subprocess.Popen[bytes],
    *,
    timeout_seconds: float = 10,
) -> Path:
    """Wait for a runtime lifecycle write to cross its durable replay point."""

    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        markers = _ready_cascade_markers(data_dir)
        if len(markers) == 1:
            return markers[0]
        if len(markers) > 1:
            raise PlayerUpdateValidationError(
                "Controlled interruption created multiple pending lifecycle cascades"
            )
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise PlayerUpdateValidationError(
                "Base runtime exited before its interrupted lifecycle write reached "
                "the durable recovery point:\n"
                + stdout.decode(errors="replace")
                + stderr.decode(errors="replace")
            )
        sleep(0.01)
    raise PlayerUpdateValidationError(
        "Controlled interruption did not reach a durable lifecycle recovery point"
    )


def _interrupt_lifecycle_write(
    process: subprocess.Popen[bytes],
    *,
    data_dir: Path,
    record_key: str,
    detail: dict[str, Any],
    session: dict[str, object],
) -> None:
    """Kill a packaged runtime after a real lifecycle write becomes recoverable.

    The record directory is temporarily non-writable before the request starts.
    That lets the runtime stage and durably mark the delete lifecycle cascade,
    while preventing its first live-file replacement.  Once ``ready`` exists,
    the journal contract requires a subsequent runtime to complete it.  The
    process is then terminated rather than stopped normally, so candidate
    startup must perform real recovery rather than merely opening clean data.
    """

    record_dir = data_dir / "imported-hands" / record_key
    if record_dir.is_symlink() or not record_dir.is_dir():
        raise PlayerUpdateValidationError(
            "Could not locate the retained record for interruption validation"
        )
    original_mode = record_dir.stat(follow_symlinks=False).st_mode & 0o777
    request_result: list[tuple[int, bytes, dict[str, str]]] = []
    payload = json.dumps(_delete_payload(detail)).encode()

    def request_delete() -> None:
        try:
            request_result.append(
                SMOKE._request(
                    f"/api/player/hands/{record_key}/delete",
                    method="POST",
                    headers={
                        **_session_headers(session, mutation=True),
                        "Content-Type": "application/json",
                    },
                    body=payload,
                )
            )
        except BaseException:
            # A killed runtime can close the connection before it returns the
            # expected 503.  The durable marker below is the test evidence.
            pass

    request_thread = Thread(target=request_delete, daemon=True)
    os.chmod(record_dir, 0o500)
    ready_marker: Path | None = None
    try:
        request_thread.start()
        ready_marker = _wait_for_ready_cascade(data_dir, process)
        process.kill()
        process.wait(timeout=10)
    finally:
        os.chmod(record_dir, original_mode)
        request_thread.join(timeout=10)

    if request_thread.is_alive():
        raise PlayerUpdateValidationError(
            "Interrupted lifecycle request did not finish after terminating the runtime"
        )
    if process.returncode == 0:
        raise PlayerUpdateValidationError(
            "Controlled interruption stopped the base runtime successfully"
        )
    if ready_marker is None or not ready_marker.is_file():
        raise PlayerUpdateValidationError(
            "Interrupted lifecycle write did not leave durable recovery work"
        )
    if request_result and request_result[0][0] != 503:
        raise PlayerUpdateValidationError(
            "Interrupted lifecycle request did not report recovery as required"
        )


def _assert_recovered_lifecycle_retains_audit_state(
    before: dict[str, Any], after: dict[str, Any]
) -> None:
    before_revisions = before.get("canonical_revisions")
    after_revisions = after.get("canonical_revisions")
    if not isinstance(before_revisions, list) or after_revisions != before_revisions:
        raise PlayerUpdateValidationError(
            "Interrupted lifecycle recovery did not retain canonical audit history"
        )
    summary = after.get("summary")
    lifecycle = after.get("lifecycle")
    if (
        not isinstance(summary, dict)
        or summary.get("lifecycle_status") != "deletion_pending"
        or summary.get("canonical_revision_count") != len(before_revisions)
        or not isinstance(lifecycle, dict)
        or lifecycle.get("reason") != _DELETE_REASON
    ):
        raise PlayerUpdateValidationError(
            "Candidate runtime did not recover the interrupted lifecycle write"
        )


def _stop_runtime(process: subprocess.Popen[bytes]) -> None:
    SMOKE._stop_runtime(process)


def _wait_for_expected_failure(process: subprocess.Popen[bytes], *, description: str) -> None:
    try:
        stdout, stderr = process.communicate(timeout=15)
    except subprocess.TimeoutExpired as exc:
        _stop_runtime(process)
        raise PlayerUpdateValidationError(f"{description} did not fail promptly") from exc
    if process.returncode == 0:
        raise PlayerUpdateValidationError(f"{description} unexpectedly succeeded")
    if not stdout and not stderr:
        raise PlayerUpdateValidationError(f"{description} failed without diagnostics")


def _workspace_digest(data_dir: Path) -> str:
    digest = sha256()
    for path in sorted(data_dir.rglob("*"), key=lambda item: item.as_posix()):
        relative = path.relative_to(data_dir).as_posix().encode()
        digest.update(relative)
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(b"F")
            digest.update(_sha256_file(path).encode())
        elif path.is_dir():
            digest.update(b"D")
        else:
            raise PlayerUpdateValidationError("Player workspace contains an unsafe entry")
    return digest.hexdigest()


def _assert_negative_artifacts_do_not_stage(
    candidate_archive: Path, *, stage_root: Path
) -> None:
    stage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if stage_root.is_symlink() or not stage_root.is_dir():
        raise PlayerUpdateValidationError("Negative-artifact staging root is invalid")
    corrupt = stage_root / "corrupt.tar.gz"
    shutil.copyfile(candidate_archive, corrupt)
    with corrupt.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        last = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes((last[0] ^ 0xFF,)))
    shutil.copyfile(
        candidate_archive.with_name(candidate_archive.name + ".sha256"),
        corrupt.with_name(corrupt.name + ".sha256"),
    )
    try:
        _stage_archive(corrupt, stage_root=stage_root / "negative", label="corrupt")
    except (PlayerUpdateValidationError, SMOKE.PlayerPackageSmokeError):
        pass
    else:
        raise PlayerUpdateValidationError("Corrupt archive was accepted for staging")

    incomplete = stage_root / "incomplete.tar.gz"
    shutil.copyfile(candidate_archive, incomplete)
    try:
        _stage_archive(
            incomplete, stage_root=stage_root / "negative", label="incomplete"
        )
    except (PlayerUpdateValidationError, SMOKE.PlayerPackageSmokeError):
        pass
    else:
        raise PlayerUpdateValidationError("Incomplete archive was accepted for staging")

    interrupted = stage_root / "interrupted.tar.gz"
    remaining = candidate_archive.stat().st_size // 2
    with candidate_archive.open("rb") as source, interrupted.open("xb") as target:
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            target.write(chunk)
            remaining -= len(chunk)
    interrupted_checksum = _sha256_file(interrupted)
    interrupted.with_name(interrupted.name + ".sha256").write_text(
        f"{interrupted_checksum}  {interrupted.name}\n", encoding="ascii"
    )
    interrupted_provenance = _read_provenance(candidate_archive) | {
        "archive_name": interrupted.name,
        "archive_sha256": interrupted_checksum,
    }
    interrupted.with_name(interrupted.name + ".provenance.json").write_text(
        json.dumps(interrupted_provenance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    try:
        _stage_archive(
            interrupted, stage_root=stage_root / "negative", label="interrupted"
        )
    except (
        EOFError,
        PlayerUpdateValidationError,
        SMOKE.PlayerPackageSmokeError,
        tarfile.TarError,
    ):
        pass
    else:
        raise PlayerUpdateValidationError("Interrupted archive staging was accepted")
    negative_root = stage_root / "negative"
    if negative_root.exists() and any(negative_root.iterdir()):
        raise PlayerUpdateValidationError("Failed runtime staging left an application directory")


def _run_update_validation(
    base_archive: Path, candidate_archive: Path
) -> dict[str, object]:
    if LAUNCH_CAPTURE_HELPER.is_symlink() or not os.access(LAUNCH_CAPTURE_HELPER, os.X_OK):
        raise PlayerUpdateValidationError("Player launch URL capture helper is missing")
    SMOKE._require_player_port_available()
    with tempfile.TemporaryDirectory(prefix="poker-hero-player-update-") as raw:
        temporary = Path(raw)
        application_root = temporary / "application-files"
        data_dir = temporary / "player-data"
        data_dir.mkdir(mode=0o700)
        capture_dir = temporary / "browser-capture"
        capture_dir.mkdir(mode=0o700)
        base = _stage_archive(base_archive, stage_root=application_root, label="base")
        candidate = _stage_archive(
            candidate_archive, stage_root=application_root, label="candidate"
        )
        _require_distinct_bundles(base, candidate)
        _assert_negative_artifacts_do_not_stage(candidate.archive_path, stage_root=temporary)

        base_capture = capture_dir / "base-launch-url"
        base_process, base_session = _start_runtime(
            base, data_dir=data_dir, capture_path=base_capture
        )
        base_interrupted = False
        try:
            record_key, before_update = _import_and_reject(base_session)
            before_snapshot = _hand_snapshot(before_update)
            backup_archive = _export_backup(base_session)

            competing_capture = capture_dir / "competing-launch-url"
            competing = subprocess.Popen(
                [str(candidate.entrypoint)],
                cwd=candidate.bundle_root,
                env=_runtime_environment(data_dir, competing_capture),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _wait_for_expected_failure(
                competing, description="Second player runtime using the same data directory"
            )
            _interrupt_lifecycle_write(
                base_process,
                data_dir=data_dir,
                record_key=record_key,
                detail=before_update,
                session=base_session,
            )
            base_interrupted = True
        finally:
            base_capture.unlink(missing_ok=True)
            if not base_interrupted:
                _stop_runtime(base_process)

        candidate_capture = capture_dir / "candidate-launch-url"
        candidate_process, candidate_session = _start_runtime(
            candidate, data_dir=data_dir, capture_path=candidate_capture
        )
        try:
            old_session_status = SMOKE._request(
                "/api/player/health", headers=_session_headers(base_session)
            )[0]
            if old_session_status != 401:
                raise PlayerUpdateValidationError(
                    "The candidate runtime accepted an old runtime session"
                )
            after_update = _hand_detail(record_key, candidate_session)
            _assert_recovered_lifecycle_retains_audit_state(before_update, after_update)
        finally:
            candidate_capture.unlink(missing_ok=True)
            _stop_runtime(candidate_process)

        restore_dir = temporary / "restore-rehearsal-data"
        restore_dir.mkdir(mode=0o700)
        restore_capture = capture_dir / "restore-launch-url"
        restore_process, restore_session = _start_runtime(
            candidate, data_dir=restore_dir, capture_path=restore_capture
        )
        try:
            _restore_backup(restore_session, backup_archive)
            restored = _hand_detail(record_key, restore_session)
            if _hand_snapshot(restored) != before_snapshot:
                raise PlayerUpdateValidationError(
                    "Backup restore rehearsal did not preserve the reviewed hand"
                )
        finally:
            restore_capture.unlink(missing_ok=True)
            _stop_runtime(restore_process)

        candidate_capture = capture_dir / "candidate-delete-launch-url"
        candidate_process, candidate_session = _start_runtime(
            candidate, data_dir=data_dir, capture_path=candidate_capture
        )
        try:
            deleted = _delete_hand(
                record_key, _hand_detail(record_key, candidate_session), candidate_session
            )
            _restore_backup(candidate_session, backup_archive)
            retained_tombstone = _hand_detail(record_key, candidate_session)
            if _hand_snapshot(retained_tombstone) != _hand_snapshot(deleted):
                raise PlayerUpdateValidationError(
                    "Stale backup restore changed a newer deletion generation"
                )
        finally:
            candidate_capture.unlink(missing_ok=True)
            _stop_runtime(candidate_process)

        digest_before_port_failure = _workspace_digest(data_dir)
        port_blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        port_blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        port_blocker.bind(("127.0.0.1", 8765))
        port_blocker.listen(1)
        try:
            blocked = subprocess.Popen(
                [str(candidate.entrypoint)],
                cwd=candidate.bundle_root,
                env=_runtime_environment(data_dir, capture_dir / "blocked-launch-url"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _wait_for_expected_failure(blocked, description="Occupied player runtime port")
        finally:
            port_blocker.close()
        if _workspace_digest(data_dir) != digest_before_port_failure:
            raise PlayerUpdateValidationError(
                "Occupied-port startup changed the player data workspace"
            )

        shutil.rmtree(base.bundle_root)
        if not data_dir.exists():
            raise PlayerUpdateValidationError("Application-only removal removed player data")
        candidate_capture = capture_dir / "post-removal-launch-url"
        candidate_process, candidate_session = _start_runtime(
            candidate, data_dir=data_dir, capture_path=candidate_capture
        )
        try:
            if _hand_detail(record_key, candidate_session).get("summary", {}).get(
                "lifecycle_status"
            ) != "deleted":
                raise PlayerUpdateValidationError(
                    "Application-only removal did not preserve the deleted hand"
                )
        finally:
            candidate_capture.unlink(missing_ok=True)
            _stop_runtime(candidate_process)

        final_backup = temporary / "export-before-data-removal.zip"
        removal = subprocess.run(
            [
                str(candidate.entrypoint),
                "export-and-remove",
                str(final_backup),
                "--data-dir",
                str(data_dir),
                "--confirm-remove-data",
            ],
            cwd=candidate.bundle_root,
            env=_runtime_environment(data_dir, capture_dir / "remove-launch-url"),
            capture_output=True,
            check=False,
            timeout=30,
        )
        if removal.returncode != 0 or data_dir.exists() or not final_backup.is_file():
            raise PlayerUpdateValidationError(
                "Packaged export-before-data-removal did not complete safely"
            )

        print("Player runtime update validation passed")
        print(f"base archive sha256: {base.archive_sha256}")
        print(f"base source revision: {base.provenance['source_revision']}")
        print(f"candidate archive sha256: {candidate.archive_sha256}")
        print(f"candidate source revision: {candidate.provenance['source_revision']}")
        return {
            "schema_version": 1,
            "base": {
                "archive_sha256": base.archive_sha256,
                "source_revision": base.provenance["source_revision"],
            },
            "candidate": {
                "archive_sha256": candidate.archive_sha256,
                "source_revision": candidate.provenance["source_revision"],
            },
        }


def _write_report(path: Path, report: dict[str, object]) -> None:
    target = path.expanduser()
    parent = target.parent
    if parent.is_symlink() or not parent.is_dir():
        raise PlayerUpdateValidationError("Update-validation report parent is invalid")
    if target.exists() or target.is_symlink():
        raise PlayerUpdateValidationError(
            "Refusing to overwrite an update-validation report"
        )
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify a manual update between two player runtime archives"
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write non-replaceable success evidence to this path",
    )
    parser.add_argument("base_archive", type=Path)
    parser.add_argument("candidate_archive", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _argument_parser().parse_args(argv)
    report = _run_update_validation(args.base_archive, args.candidate_archive)
    if args.report is not None:
        _write_report(args.report, report)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (
        EOFError,
        OSError,
        PlayerUpdateValidationError,
        SMOKE.PlayerPackageSmokeError,
        tarfile.TarError,
    ) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc
