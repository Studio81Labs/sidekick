import asyncio
import ctypes
from datetime import timedelta
from decimal import Decimal
import errno
from ipaddress import ip_address
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from threading import Event, Thread
from time import monotonic, sleep

import httpx
import pytest
from fastapi.testclient import TestClient

import app.player_main as player_main_module
from app.application.imported_hand_lifecycle import ImportedHandLifecycleService
from app.application.imported_hand_ports import ImportedHandRecoveryReport
from app.bootstrap import create_app
from app.config import Settings
from app.data_lock import (
    DataLockTimeoutError,
    InterprocessDataLock,
    player_runtime_lease,
)
from app.domain.imported_hands import (
    ImportedHandState,
    extract_hero_decision_points,
    imported_hand_state_sha256,
)
from app.player_main import (
    build_player_server,
    configured_player_runtime,
    packaged_player_data_dir,
)
from app.player_backup import PlayerBackupRestoreResult, PlayerBackupStorageError
from app.player_hands import player_hand_record_version
from app.player_namespace import (
    DenyHostedPlayerNamespaceMiddleware,
    is_player_api_path,
    is_player_api_scope,
)
from app.player_runtime import (
    PLAYER_AUTHORITY,
    PLAYER_HOST,
    PLAYER_ORIGIN,
    PLAYER_PORT,
    PLAYER_SECRET_FILENAME,
    PlayerAssetError,
    PlayerCredentialError,
    PlayerRuntime,
    PlayerSessionAuthority,
    create_player_runtime,
    default_player_assets_dir,
    load_or_create_installation_secret,
)
from app.player_workspace import (
    PLAYER_WORKSPACE_LAYOUT_VERSION,
    PLAYER_WORKSPACE_MANIFEST_FILENAME,
    PlayerDataDirectoryError,
    PlayerWorkspace,
    _macos_extended_acl_has_entries,
)
from app.storage.cascade_journal import CascadeJournal
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    imported_hand_record_key,
)
from test_imported_hand_store import (
    RAW_TEXT,
    approved_record,
    pending_review_record,
    sample_identity,
    withdrawn_record,
)


TEST_PLAYER_ASSETS_DIR = Path(__file__).parent / "fixtures" / "player-pwa"
DELETE_REQUEST_ID = "11111111-1111-4111-8111-111111111111"
DELETE_RETRY_REQUEST_ID = "22222222-2222-4222-8222-222222222222"
APPROVAL_REQUEST_ID = "33333333-3333-4333-8333-333333333333"
APPROVAL_RETRY_REQUEST_ID = "44444444-4444-4444-8444-444444444444"


def test_frozen_player_runtime_uses_embedded_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert default_player_assets_dir() == tmp_path / "player-assets"


def _create_player_runtime(data_dir: Path, **kwargs) -> PlayerRuntime:
    return create_player_runtime(
        data_dir,
        player_assets_dir=TEST_PLAYER_ASSETS_DIR,
        **kwargs,
    )


def player_client(tmp_path: Path, **kwargs) -> tuple[TestClient, PlayerRuntime]:
    runtime = _create_player_runtime(tmp_path, **kwargs)
    client = TestClient(
        runtime.app,
        base_url=PLAYER_ORIGIN,
        client=("127.0.0.1", 50000),
    )
    return client, runtime


def exchange_session(
    client: TestClient,
    runtime: PlayerRuntime,
) -> dict[str, object]:
    launch_url = runtime.issue_launch_url()
    ticket = launch_url.split("#ticket=", 1)[1]
    response = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    assert response.status_code == 200
    return response.json()


def player_mutation_headers(session: dict[str, object]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {session['session_token']}",
        "Origin": PLAYER_ORIGIN,
        "X-Poker-CSRF-Token": str(session["csrf_token"]),
    }


def hand_close_payload(record, *, reason: str) -> dict[str, object]:
    lifecycle = record.lifecycle
    assert lifecycle.active_canonical_revision is not None
    return {
        "reason": reason,
        "expected_active_canonical_revision": lifecycle.active_canonical_revision,
        "expected_deletion_generation": lifecycle.deletion_generation,
        "expected_lifecycle_changed_at": lifecycle.changed_at.isoformat(),
    }


def hand_delete_payload(
    record,
    *,
    reason: str,
    request_id: str = DELETE_REQUEST_ID,
) -> dict[str, object]:
    lifecycle = record.lifecycle
    return {
        "request_id": request_id,
        "reason": reason,
        "expected_record_version": player_hand_record_version(record),
        "expected_lifecycle_status": lifecycle.status,
        "expected_active_canonical_revision": lifecycle.active_canonical_revision,
        "expected_deletion_generation": lifecycle.deletion_generation,
        "expected_lifecycle_changed_at": lifecycle.changed_at.isoformat(),
    }


def hand_approval_payload(
    record,
    *,
    approved_state: dict[str, object],
    correction_reason: str | None,
    request_id: str = APPROVAL_REQUEST_ID,
    detection_id: str | None = None,
) -> dict[str, object]:
    lifecycle = record.lifecycle
    return {
        "request_id": request_id,
        "detection_id": detection_id or record.detections[-1].detection_id,
        "approved_state": approved_state,
        "correction_reason": correction_reason,
        "expected_record_version": player_hand_record_version(record),
        "expected_lifecycle_status": lifecycle.status,
        "expected_active_canonical_revision": lifecycle.active_canonical_revision,
        "expected_canonical_revision_count": len(record.canonical_revisions),
        "expected_deletion_generation": lifecycle.deletion_generation,
        "expected_lifecycle_changed_at": lifecycle.changed_at.isoformat(),
    }


def test_installation_secret_is_stable_and_owner_only(tmp_path: Path) -> None:
    first = load_or_create_installation_secret(tmp_path)
    second = load_or_create_installation_secret(tmp_path)

    assert len(first) == 32
    assert second == first
    assert (tmp_path / PLAYER_SECRET_FILENAME).stat().st_mode & 0o777 == 0o600


def test_installation_secret_rejects_insecure_permissions(tmp_path: Path) -> None:
    secret_path = tmp_path / PLAYER_SECRET_FILENAME
    secret_path.write_bytes(os.urandom(32))
    secret_path.chmod(0o644)

    with pytest.raises(PlayerCredentialError, match="readable only by its owner"):
        load_or_create_installation_secret(tmp_path)


def test_installation_secret_rejects_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(os.urandom(32))
    (tmp_path / PLAYER_SECRET_FILENAME).symlink_to(target)

    with pytest.raises(PlayerCredentialError, match="Cannot safely open"):
        load_or_create_installation_secret(tmp_path)


def test_player_runtime_rejects_a_shared_data_directory(tmp_path: Path) -> None:
    data_dir = tmp_path / "shared-player-data"
    data_dir.mkdir(mode=0o755)
    data_dir.chmod(0o755)

    with pytest.raises(PlayerDataDirectoryError, match="only by its owner"):
        _create_player_runtime(data_dir)


@pytest.mark.skipif(sys.platform != "darwin", reason="Darwin extended ACL test")
def test_player_runtime_rejects_a_data_directory_acl(tmp_path: Path) -> None:
    data_dir = tmp_path / "acl-player-data"
    data_dir.mkdir(mode=0o700)
    subprocess.run(
        ["/bin/chmod", "+a", "everyone allow read,search", str(data_dir)],
        check=True,
    )

    with pytest.raises(PlayerDataDirectoryError, match="extended ACL"):
        _create_player_runtime(data_dir)


def test_allocated_empty_macos_acl_is_not_rejected(tmp_path: Path) -> None:
    class FakeFunction:
        def __init__(self, result) -> None:
            self._result = result
            self.argtypes = None
            self.restype = None

        def __call__(self, *_args):
            if callable(self._result):
                return self._result()
            return self._result

    def no_first_entry() -> int:
        ctypes.set_errno(errno.EINVAL)
        return -1

    class FakeAclLibrary:
        acl_get_file = FakeFunction(1)
        acl_get_entry = FakeFunction(no_first_entry)
        acl_free = FakeFunction(0)

    assert not _macos_extended_acl_has_entries(
        tmp_path,
        library=FakeAclLibrary(),
    )


def test_player_runtime_opens_only_the_player_store(tmp_path: Path) -> None:
    runtime = _create_player_runtime(tmp_path)

    assert runtime.workspace.data_dir == tmp_path.resolve()
    assert runtime.workspace.imported_hands.list_keys() == []
    assert {path.name for path in tmp_path.iterdir()} == {
        ".player-runtime-key",
        ".poker-hero-data.lock",
        PLAYER_WORKSPACE_MANIFEST_FILENAME,
        "imported-hands",
    }


def test_player_runtime_rejects_an_imported_hand_store_symlink(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "player-data"
    data_dir.mkdir(mode=0o700)
    target = tmp_path / "outside-store"
    target.mkdir()
    (data_dir / "imported-hands").symlink_to(target, target_is_directory=True)

    with pytest.raises(PlayerDataDirectoryError, match="must be a directory inside"):
        _create_player_runtime(data_dir)


def test_bootstrap_ticket_is_single_use_and_session_requires_csrf() -> None:
    now = [100.0]
    authority = PlayerSessionAuthority(
        b"x" * 32,
        clock=lambda: now[0],
        bootstrap_ttl_seconds=10,
        session_ttl_seconds=20,
    )
    ticket = authority.issue_bootstrap_ticket()

    session = authority.exchange_bootstrap_ticket(ticket)
    assert session is not None
    assert authority.exchange_bootstrap_ticket(ticket) is None
    assert authority.authorize(session.session_token)
    assert not authority.authorize_mutation(session.session_token, "wrong")
    assert authority.authorize_mutation(
        session.session_token,
        session.csrf_token,
    )

    now[0] = 121.0
    assert not authority.authorize(session.session_token)


def test_expired_bootstrap_ticket_cannot_create_a_session() -> None:
    now = [100.0]
    authority = PlayerSessionAuthority(
        b"x" * 32,
        clock=lambda: now[0],
        bootstrap_ttl_seconds=10,
    )
    ticket = authority.issue_bootstrap_ticket()

    now[0] = 111.0
    assert authority.exchange_bootstrap_ticket(ticket) is None


def test_player_runtime_serves_the_dedicated_pwa_and_launch_fragment(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)

    shell = client.get("/")
    manifest = client.get("/manifest.webmanifest")
    service_worker = client.get("/sw.js")
    application = client.get("/assets/player-test-12345678.js")
    icon = client.get("/icons/test-icon.svg")
    launch_url = runtime.issue_launch_url()

    assert shell.status_code == 200
    assert "Dedicated local player PWA" in shell.text
    assert "/assets/player-test-12345678.js" in shell.text
    assert shell.headers["Cache-Control"] == "no-store"
    assert manifest.status_code == 200
    assert manifest.headers["Content-Type"].startswith(
        "application/manifest+json"
    )
    assert manifest.json()["name"] == "Poker Hero Local Player Test PWA"
    assert service_worker.status_code == 200
    assert service_worker.headers["Content-Type"].startswith("text/javascript")
    assert application.status_code == 200
    assert icon.status_code == 200
    assert icon.headers["Content-Type"].startswith("image/svg+xml")
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/icons/missing.png").status_code == 404
    assert client.get("/assets/%2e%2e/manifest.webmanifest").status_code == 404
    assert client.get("/player-bootstrap.js").status_code == 404
    assert "#ticket=" in launch_url
    assert "?ticket=" not in launch_url
    assert "script-src 'self'" in shell.headers["Content-Security-Policy"]


def test_player_runtime_serves_an_immutable_startup_asset_snapshot(
    tmp_path: Path,
) -> None:
    assets = tmp_path / "player-pwa"
    shutil.copytree(TEST_PLAYER_ASSETS_DIR, assets)
    runtime = create_player_runtime(
        tmp_path / "player-data",
        player_assets_dir=assets,
    )
    client = TestClient(
        runtime.app,
        base_url=PLAYER_ORIGIN,
        client=("127.0.0.1", 50000),
    )

    (assets / "index.html").write_text("<script>window.compromised = true</script>")
    (assets / "assets" / "player-test-12345678.js").write_text(
        "window.compromised = true;"
    )

    shell = client.get("/")
    application = client.get("/assets/player-test-12345678.js")

    assert "Dedicated local player PWA" in shell.text
    assert "compromised" not in shell.text
    assert "__POKER_HERO_PLAYER_TEST_PWA__" in application.text
    assert "compromised" not in application.text


def test_player_runtime_rejects_missing_or_symlinked_pwa_assets(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing-player-pwa"
    with pytest.raises(PlayerAssetError, match="has not been built"):
        create_player_runtime(
            tmp_path / "missing-data",
            player_assets_dir=missing,
        )
    assert not (tmp_path / "missing-data").exists()

    symlink = tmp_path / "player-pwa-link"
    symlink.symlink_to(TEST_PLAYER_ASSETS_DIR, target_is_directory=True)
    with pytest.raises(PlayerAssetError, match="must not be a symlink"):
        create_player_runtime(
            tmp_path / "symlink-data",
            player_assets_dir=symlink,
        )


def test_player_hand_approval_publishes_reviewed_state_and_is_idempotent(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    approved_state = record.detections[0].state.model_dump(mode="json")
    approved_state["hero_player_id"] = "hero"
    payload = hand_approval_payload(
        record,
        approved_state=approved_state,
        correction_reason="Confirmed from reviewed source evidence",
    )

    unauthorized = client.post(
        f"/api/player/hands/{key}/approve",
        json=payload,
        headers={"Origin": PLAYER_ORIGIN},
    )
    missing_csrf = client.post(
        f"/api/player/hands/{key}/approve",
        json=payload,
        headers={
            "Authorization": f"Bearer {session['session_token']}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    first = client.post(
        f"/api/player/hands/{key}/approve",
        json=payload,
        headers=player_mutation_headers(session),
    )
    retry = client.post(
        f"/api/player/hands/{key}/approve",
        json=payload,
        headers=player_mutation_headers(session),
    )
    mismatched_retry = client.post(
        f"/api/player/hands/{key}/approve",
        json={
            **payload,
            "approved_state": record.detections[0].state.model_dump(mode="json"),
            "correction_reason": None,
        },
        headers=player_mutation_headers(session),
    )

    assert unauthorized.status_code == 401
    assert missing_csrf.status_code == 403
    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert mismatched_retry.status_code == 409
    assert "already bound" in mismatched_retry.json()["detail"]
    detail = first.json()
    assert detail["summary"]["lifecycle_status"] == "active"
    assert detail["summary"]["active_canonical_revision"] == 1
    assert detail["summary"]["learning_eligible"] is True
    revision = detail["canonical_revisions"][0]
    assert revision["approval_id"] == APPROVAL_REQUEST_ID
    assert revision["detection_id"] == "detection-1"
    assert revision["state"]["hero_player_id"] == "hero"
    assert revision["corrections"] == [
        {
            "field_pointer": "/hero_player_id",
            "detected_value": None,
            "approved_value": "hero",
            "corrected_at": revision["approved_at"],
            "reason": "Confirmed from reviewed source evidence",
        }
    ]
    assert RAW_TEXT not in first.text
    stored = runtime.workspace.imported_hands.get(key)
    assert stored.canonical_revisions[0].approval_id == APPROVAL_REQUEST_ID
    assert runtime.workspace.imported_hands.active_decisions(key) is not None


@pytest.mark.parametrize("source_status", ["active", "withdrawn", "rejected"])
def test_player_hand_approval_reapproves_a_retained_revision(
    tmp_path: Path,
    source_status: str,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record() if source_status == "active" else withdrawn_record()
    if source_status == "rejected":
        record = record.model_copy(
            update={
                "lifecycle": record.lifecycle.model_copy(
                    update={"status": "rejected"}
                )
            }
        )
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    approved_state = record.detections[0].state.model_dump(mode="json")
    approved_state["hero_player_id"] = "hero"

    response = client.post(
        f"/api/player/hands/{key}/approve",
        json=hand_approval_payload(
            record,
            approved_state=approved_state,
            correction_reason="Reconfirmed the hero identity",
            request_id=APPROVAL_RETRY_REQUEST_ID,
        ),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 200
    detail = response.json()
    assert detail["summary"]["lifecycle_status"] == "active"
    assert detail["summary"]["active_canonical_revision"] == 2
    assert len(detail["canonical_revisions"]) == 2
    assert detail["canonical_revisions"][0]["approval_id"] is None
    assert detail["canonical_revisions"][1]["approval_id"] == (
        APPROVAL_RETRY_REQUEST_ID
    )
    active = runtime.workspace.imported_hands.active_decisions(key)
    assert active is not None
    if active.outcome != "not_extractable":
        assert active.canonical_revision == 2


def test_player_hand_approval_refuses_missing_reason_stale_state_and_detection(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    headers = player_mutation_headers(session)
    corrected_state = record.detections[0].state.model_dump(mode="json")
    corrected_state["hero_player_id"] = "hero"

    missing_reason = client.post(
        f"/api/player/hands/{key}/approve",
        json=hand_approval_payload(
            record,
            approved_state=corrected_state,
            correction_reason=None,
        ),
        headers=headers,
    )
    missing_detection = client.post(
        f"/api/player/hands/{key}/approve",
        json=hand_approval_payload(
            record,
            approved_state=corrected_state,
            correction_reason="Reviewed",
            detection_id="missing-detection",
        ),
        headers=headers,
    )
    changed = record.model_copy(
        update={
            "lifecycle": record.lifecycle.model_copy(
                update={"reason": "Newer retained review event"}
            )
        }
    )
    runtime.workspace.imported_hands.save(key, changed)
    stale = client.post(
        f"/api/player/hands/{key}/approve",
        json=hand_approval_payload(
            record,
            approved_state=corrected_state,
            correction_reason="Reviewed",
            request_id=APPROVAL_RETRY_REQUEST_ID,
        ),
        headers=headers,
    )

    assert missing_reason.status_code == 422
    assert "requires a correction reason" in missing_reason.json()["detail"]
    assert missing_detection.status_code == 409
    assert "not retained" in missing_detection.json()["detail"]
    assert stale.status_code == 409
    assert "retained hand changed" in stale.json()["detail"]
    assert runtime.workspace.imported_hands.get(key) == changed


def test_player_hand_approval_does_not_expose_private_evidence_on_validation(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    state_payload = record.detections[0].state.model_dump()
    source_locator = {
        "raw_source_id": record.detections[0].raw_source_id,
        "line_start": 1,
        "excerpt": RAW_TEXT.rstrip("\n"),
    }
    state_payload["streets"][0]["actions"] = [
        {
            "sequence": 0,
            "actor_id": "hero",
            "action_type": "check",
            "amount": None,
            "total_committed": Decimal(0),
            "all_in": False,
            "origin": {
                "kind": "player_selected",
                "basis": "explicit_marker",
                "evidence": [source_locator],
            },
            "evidence": [source_locator],
        }
    ]
    detected_state = ImportedHandState.model_validate(state_payload)
    detection = record.detections[0].model_copy(
        update={
            "state": detected_state,
            "content_sha256": imported_hand_state_sha256(detected_state),
        }
    )
    record = record.model_copy(update={"detections": [detection]})
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    approved_state = detected_state.model_dump(mode="json")
    reviewed_action = approved_state["streets"][0]["actions"][0]
    reviewed_action["evidence"][0].pop("excerpt")
    reviewed_action["origin"]["evidence"][0].pop("excerpt")
    reviewed_action["total_committed"] = "-1"

    response = client.post(
        f"/api/player/hands/{key}/approve",
        json=hand_approval_payload(
            record,
            approved_state=approved_state,
            correction_reason="Reviewed",
        ),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Reviewed canonical state is invalid"
    assert RAW_TEXT.rstrip("\n") not in response.text


def test_player_hand_approval_keeps_a_ready_cascade_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    approved_state = record.detections[0].state.model_dump(mode="json")
    approved_state["hero_player_id"] = "hero"
    real_commit_replace = CascadeJournal._commit_replace

    def fail_record_publication(
        journal: CascadeJournal,
        record_key: str,
        relative: Path,
        staged_file: Path,
    ) -> None:
        if relative.as_posix() == "record.json":
            raise OSError("simulated approval publication failure")
        real_commit_replace(journal, record_key, relative, staged_file)

    monkeypatch.setattr(CascadeJournal, "_commit_replace", fail_record_publication)
    response = client.post(
        f"/api/player/hands/{key}/approve",
        json=hand_approval_payload(
            record,
            approved_state=approved_state,
            correction_reason="Reviewed",
        ),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 503
    assert "interrupted approval write" in response.json()["detail"]
    assert runtime.workspace.imported_hands.has_interrupted_write(key)
    detail = client.get(
        f"/api/player/hands/{key}",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert detail.status_code == 503

    monkeypatch.setattr(CascadeJournal, "_commit_replace", real_commit_replace)
    recovered = _create_player_runtime(tmp_path)
    assert recovered.workspace.imported_hand_recovery.completed
    stored = recovered.workspace.imported_hands.get(key)
    assert stored.lifecycle.status == "active"
    assert stored.canonical_revisions[-1].approval_id == APPROVAL_REQUEST_ID


@pytest.mark.parametrize(
    "payload_update",
    [
        {"request_id": "   "},
        {"detection_id": "   "},
        {"approved_state": []},
        {"correction_reason": "   "},
        {"expected_record_version": "not-a-sha256"},
        {"expected_lifecycle_status": "deleted"},
        {"expected_active_canonical_revision": 1},
        {"expected_canonical_revision_count": -1},
        {"expected_deletion_generation": -1},
        {"expected_lifecycle_changed_at": "2026-08-30T12:00:00"},
        {"unexpected": True},
    ],
)
def test_player_hand_approval_validates_the_complete_precondition(
    tmp_path: Path,
    payload_update: dict[str, object],
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)

    response = client.post(
        f"/api/player/hands/{key}/approve",
        json={
            **hand_approval_payload(
                record,
                approved_state=record.detections[0].state.model_dump(mode="json"),
                correction_reason=None,
            ),
            **payload_update,
        },
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 422
    assert runtime.workspace.imported_hands.get(key) == record


def test_player_hand_approval_reports_a_busy_process_lock(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path, write_lock_timeout_seconds=0)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    lock_index = runtime.workspace.imported_hand_lock_index(key)
    second_runtime = _create_player_runtime(tmp_path)
    process_lock = second_runtime.workspace.imported_hand_process_locks[lock_index]
    descriptor = process_lock.acquire(exclusive=True)
    try:
        response = client.post(
            f"/api/player/hands/{key}/approve",
            json=hand_approval_payload(
                record,
                approved_state=record.detections[0].state.model_dump(mode="json"),
                correction_reason=None,
            ),
            headers=player_mutation_headers(session),
        )
    finally:
        process_lock.release(descriptor)

    assert response.status_code == 409
    assert "player hand lifecycle lock" in response.json()["detail"]
    assert runtime.workspace.imported_hands.get(key) == record


@pytest.mark.parametrize(
    "missing_path",
    [
        "index.html",
        "manifest.webmanifest",
        "sw.js",
        "assets",
        "icons",
    ],
)
def test_player_runtime_rejects_an_incomplete_pwa_build(
    tmp_path: Path,
    missing_path: str,
) -> None:
    assets = tmp_path / "incomplete-player-pwa"
    shutil.copytree(TEST_PLAYER_ASSETS_DIR, assets)
    missing = assets / missing_path
    if missing.is_dir():
        shutil.rmtree(missing)
    else:
        missing.unlink()

    with pytest.raises(PlayerAssetError, match="missing"):
        create_player_runtime(
            tmp_path / "player-data",
            player_assets_dir=assets,
        )
    assert not (tmp_path / "player-data").exists()


def test_player_api_requires_a_session_and_one_use_launch_ticket(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    launch_url = runtime.issue_launch_url()
    ticket = launch_url.split("#ticket=", 1)[1]

    assert client.get("/api/player/health").status_code == 401
    assert client.get("/api/player/storage").status_code == 401
    response = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    session = response.json()
    assert session["expires_in_seconds"] == 86400

    replay = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    assert replay.status_code == 401

    health = client.get(
        "/api/player/health",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "runtime": "local-player"}

    storage = client.get(
        "/api/player/storage",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert storage.status_code == 200
    assert storage.json() == {
        "status": "ready",
        "storage": "player-local-file",
        "layout_version": PLAYER_WORKSPACE_LAYOUT_VERSION,
        "data_directory": str(tmp_path.resolve()),
        "imported_hand_record_count": 0,
        "recovery": {"completed": [], "quarantined": [], "failed": []},
    }


def test_player_storage_status_preserves_recovery_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        FileImportedHandStore,
        "has_interrupted_writes",
        lambda _self: True,
    )
    monkeypatch.setattr(
        FileImportedHandStore,
        "recover",
        lambda _self: ImportedHandRecoveryReport(
            completed=("completed-cascade",),
            quarantined=("quarantined-cascade",),
            failed=("failed-cascade",),
        ),
    )
    client, runtime = player_client(tmp_path)
    session = exchange_session(client, runtime)

    storage = client.get(
        "/api/player/storage",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )

    assert storage.status_code == 200
    assert storage.json()["status"] == "attention_required"
    assert storage.json()["recovery"] == {
        "completed": ["completed-cascade"],
        "quarantined": ["quarantined-cascade"],
        "failed": ["failed-cascade"],
    }


def test_player_api_reports_a_layout_change_as_restart_required(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    session = exchange_session(client, runtime)
    (tmp_path / PLAYER_WORKSPACE_MANIFEST_FILENAME).write_text(
        '{"layout_version":2,"schema":"poker-hero-player-workspace"}\n',
        encoding="utf-8",
    )

    response = client.get(
        "/api/player/storage",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "The player workspace layout changed while this runtime was open;"
            " restart with a compatible version"
        )
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_player_storage_waits_without_exhausting_restore_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anyio_backend: str,
) -> None:
    assert anyio_backend == "asyncio"
    runtime = _create_player_runtime(tmp_path)
    upload_started = asyncio.Event()
    allow_upload_to_finish = asyncio.Event()

    def complete_restore(*_args, **_kwargs) -> PlayerBackupRestoreResult:
        return PlayerBackupRestoreResult(
            imported_records=0,
            reused_records=0,
            skipped_stale_records=0,
            imported_decision_artifacts=0,
            reused_decision_artifacts=0,
            removed_decision_artifacts=0,
            total_records=0,
        )

    monkeypatch.setattr(
        "app.player_runtime.restore_player_backup",
        complete_restore,
    )

    async def slow_upload():
        upload_started.set()
        yield b"restore "
        await allow_upload_to_finish.wait()
        yield b"archive"

    transport = httpx.ASGITransport(
        app=runtime.app,
        client=("127.0.0.1", 50000),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=PLAYER_ORIGIN,
    ) as client:
        ticket = runtime.issue_launch_url().split("#ticket=", 1)[1]
        session_response = await client.post(
            "/api/player/session",
            headers={
                "Authorization": f"Bearer {ticket}",
                "Origin": PLAYER_ORIGIN,
            },
        )
        assert session_response.status_code == 200
        session = session_response.json()
        authorization = f"Bearer {session['session_token']}"
        restore_headers = {
            "Authorization": authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
            "Content-Type": "application/zip",
        }
        restore_task = asyncio.create_task(
            client.post(
                "/api/player/backups/restore",
                content=slow_upload(),
                headers=restore_headers,
            )
        )
        await asyncio.wait_for(upload_started.wait(), 2)

        concurrent_restore = await client.post(
            "/api/player/backups/restore",
            content=b"second restore archive",
            headers=restore_headers,
        )
        assert concurrent_restore.status_code == 409
        assert concurrent_restore.json()["detail"] == (
            "Another player restore is already in progress"
        )

        # More waiters than AnyIO's default worker limit prove that storage
        # waits on the async gate before it asks the pool for filesystem work.
        storage_tasks = [
            asyncio.create_task(
                client.get(
                    "/api/player/storage",
                    headers={"Authorization": authorization},
                )
            )
            for _ in range(50)
        ]
        await asyncio.sleep(0.1)
        assert all(not task.done() for task in storage_tasks)

        allow_upload_to_finish.set()
        restore_response = await asyncio.wait_for(restore_task, 5)
        storage_responses = await asyncio.wait_for(
            asyncio.gather(*storage_tasks),
            5,
        )

    assert restore_response.status_code == 200
    assert all(response.status_code == 200 for response in storage_responses)
    assert all(
        response.json()["imported_hand_record_count"] == 0
        for response in storage_responses
    )


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_restore_storage_failure_rejects_requests_already_waiting_on_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anyio_backend: str,
) -> None:
    assert anyio_backend == "asyncio"
    runtime = _create_player_runtime(tmp_path)
    upload_started = asyncio.Event()
    allow_upload_to_finish = asyncio.Event()

    def fail_after_partial_publication(*_args: object, **_kwargs: object) -> None:
        raise PlayerBackupStorageError(
            "Player backup restore did not complete; restart the local runtime "
            "before retrying so journal recovery can finish"
        )

    monkeypatch.setattr(
        "app.player_runtime.restore_player_backup",
        fail_after_partial_publication,
    )

    async def slow_upload():
        upload_started.set()
        yield b"restore "
        await allow_upload_to_finish.wait()
        yield b"archive"

    transport = httpx.ASGITransport(
        app=runtime.app,
        client=("127.0.0.1", 50000),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=PLAYER_ORIGIN,
    ) as client:
        ticket = runtime.issue_launch_url().split("#ticket=", 1)[1]
        session_response = await client.post(
            "/api/player/session",
            headers={
                "Authorization": f"Bearer {ticket}",
                "Origin": PLAYER_ORIGIN,
            },
        )
        assert session_response.status_code == 200
        session = session_response.json()
        authorization = f"Bearer {session['session_token']}"
        restore_task = asyncio.create_task(
            client.post(
                "/api/player/backups/restore",
                content=slow_upload(),
                headers={
                    "Authorization": authorization,
                    "Origin": PLAYER_ORIGIN,
                    "X-Poker-CSRF-Token": str(session["csrf_token"]),
                    "Content-Type": "application/zip",
                },
            )
        )
        await asyncio.wait_for(upload_started.wait(), 2)

        storage_task = asyncio.create_task(
            client.get(
                "/api/player/storage",
                headers={"Authorization": authorization},
            )
        )
        export_task = asyncio.create_task(
            client.get(
                "/api/player/backups/export",
                headers={"Authorization": authorization},
            )
        )
        await asyncio.sleep(0.1)
        assert not storage_task.done()
        assert not export_task.done()

        allow_upload_to_finish.set()
        restore_response = await asyncio.wait_for(restore_task, 5)
        storage_response, export_response = await asyncio.wait_for(
            asyncio.gather(storage_task, export_task),
            5,
        )

    assert restore_response.status_code == 503
    assert storage_response.status_code == 401
    assert export_response.status_code == 401


def test_player_storage_reports_when_a_stable_snapshot_times_out(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path, status_lock_timeout_seconds=0)
    session = exchange_session(client, runtime)
    descriptor = runtime.workspace.data_lock.acquire(exclusive=True)
    try:
        response = client.get(
            "/api/player/storage",
            headers={
                "Authorization": f"Bearer {session['session_token']}",
            },
        )
    finally:
        runtime.workspace.data_lock.release(descriptor)

    assert response.status_code == 409
    assert "waiting for an exclusive hold" in response.json()["detail"]


def test_player_hand_routes_require_auth_and_return_safe_review_projections(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)

    assert client.get("/api/player/hands").status_code == 401
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}

    listing = client.get("/api/player/hands?limit=1", headers=authorization)
    detail = client.get(f"/api/player/hands/{key}", headers=authorization)

    assert listing.status_code == 200
    assert listing.json()["items"] == [detail.json()["summary"]]
    assert listing.json()["unreadable"] == []
    assert listing.json()["next_cursor"] is None
    assert detail.status_code == 200
    assert detail.json()["summary"]["learning_eligible"] is False
    assert detail.json()["detections"][0]["warnings"] == [
        "Review hero identity"
    ]
    assert RAW_TEXT not in listing.text
    assert RAW_TEXT not in detail.text
    assert "raw_text" not in listing.text
    assert "raw_text" not in detail.text
    assert "PokerStars Hand #123456789" not in detail.text
    assert "excerpt" not in detail.text


def test_player_hand_routes_validate_pagination_and_missing_keys(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path)
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}

    invalid_limit = client.get(
        "/api/player/hands?limit=0",
        headers=authorization,
    )
    assert (
        client.get(
            "/api/player/hands?cursor=not-a-key",
            headers=authorization,
        ).status_code
        == 422
    )
    missing = client.get(f"/api/player/hands/{'a' * 64}", headers=authorization)
    malformed = client.get("/api/player/hands/not-a-key", headers=authorization)

    assert invalid_limit.status_code == 422
    assert missing.status_code == 404
    assert malformed.status_code == 404
    assert missing.json() == {"detail": "Imported hand record not found"}


def test_player_hand_routes_report_a_stable_snapshot_timeout(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path, status_lock_timeout_seconds=0)
    session = exchange_session(client, runtime)
    descriptor = runtime.workspace.data_lock.acquire(exclusive=True)
    try:
        listing = client.get(
            "/api/player/hands",
            headers={"Authorization": f"Bearer {session['session_token']}"},
        )
        detail = client.get(
            f"/api/player/hands/{'a' * 64}",
            headers={"Authorization": f"Bearer {session['session_token']}"},
        )
    finally:
        runtime.workspace.data_lock.release(descriptor)

    assert listing.status_code == 409
    assert detail.status_code == 409


def test_player_hand_routes_report_corrupt_records_explicitly(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    record_file = runtime.workspace.imported_hands.records_dir / key / "record.json"
    record_file.write_text("{not-json", encoding="utf-8")
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}

    listing = client.get("/api/player/hands", headers=authorization)
    detail = client.get(f"/api/player/hands/{key}", headers=authorization)

    assert listing.status_code == 200
    assert listing.json() == {
        "items": [],
        "unreadable": [
            {
                "record_key": key,
                "detail": "Stored imported hand record could not be read safely",
            }
        ],
        "next_cursor": None,
    }
    assert detail.status_code == 500
    assert detail.json() == {
        "detail": "Stored imported hand record could not be read safely"
    }


@pytest.mark.anyio
@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_unrelated_hand_requests_do_not_wait_for_a_lifecycle_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    anyio_backend: str,
) -> None:
    assert anyio_backend == "asyncio"
    runtime = _create_player_runtime(tmp_path)
    blocked_record = approved_record(sample_identity(hand_ordinal=31))
    unrelated_record = approved_record(sample_identity(hand_ordinal=32))
    blocked_key = imported_hand_record_key(blocked_record.identity)
    unrelated_key = imported_hand_record_key(unrelated_record.identity)
    runtime.workspace.imported_hands.save(blocked_key, blocked_record)
    runtime.workspace.imported_hands.save(unrelated_key, unrelated_record)
    blocked_write_started = Event()
    allow_blocked_write = Event()
    real_close = PlayerWorkspace.close_hand_record

    def close_with_one_blocked_record(
        workspace: PlayerWorkspace,
        record_key: str,
        *args: object,
        **kwargs: object,
    ):
        if record_key == blocked_key:
            blocked_write_started.set()
            if not allow_blocked_write.wait(2):
                raise AssertionError("blocked lifecycle write was not released")
        return real_close(workspace, record_key, *args, **kwargs)

    monkeypatch.setattr(
        PlayerWorkspace,
        "close_hand_record",
        close_with_one_blocked_record,
    )
    transport = httpx.ASGITransport(
        app=runtime.app,
        client=("127.0.0.1", 50000),
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=PLAYER_ORIGIN,
    ) as client:
        ticket = runtime.issue_launch_url().split("#ticket=", 1)[1]
        session_response = await client.post(
            "/api/player/session",
            headers={
                "Authorization": f"Bearer {ticket}",
                "Origin": PLAYER_ORIGIN,
            },
        )
        assert session_response.status_code == 200
        session = session_response.json()
        blocked_close = asyncio.create_task(
            client.post(
                f"/api/player/hands/{blocked_key}/withdraw",
                json=hand_close_payload(blocked_record, reason="Blocked review"),
                headers=player_mutation_headers(session),
            )
        )
        assert await asyncio.to_thread(blocked_write_started.wait, 2)
        try:
            unrelated_response = await asyncio.wait_for(
                client.post(
                    f"/api/player/hands/{unrelated_key}/withdraw",
                    json=hand_close_payload(
                        unrelated_record,
                        reason="Unrelated review",
                    ),
                    headers=player_mutation_headers(session),
                ),
                1,
            )
        except BaseException:
            allow_blocked_write.set()
            await blocked_close
            raise
        allow_blocked_write.set()
        blocked_response = await asyncio.wait_for(blocked_close, 2)

    assert unrelated_response.status_code == 200
    assert unrelated_response.json()["summary"]["record_key"] == unrelated_key
    assert unrelated_response.json()["lifecycle"]["status"] == "withdrawn"
    assert blocked_response.status_code == 200
    assert blocked_response.json()["lifecycle"]["status"] == "withdrawn"


@pytest.mark.parametrize(
    ("action", "expected_status"),
    [("withdraw", "withdrawn"), ("reject", "rejected")],
)
def test_player_hand_close_routes_preserve_audit_and_are_idempotent(
    tmp_path: Path,
    action: str,
    expected_status: str,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    payload = hand_close_payload(record, reason="  Player reviewed this hand  ")

    assert (
        client.post(
            f"/api/player/hands/{key}/{action}",
            json=payload,
            headers={"Origin": PLAYER_ORIGIN},
        ).status_code
        == 401
    )
    missing_csrf = client.post(
        f"/api/player/hands/{key}/{action}",
        json=payload,
        headers={
            "Authorization": f"Bearer {session['session_token']}",
            "Origin": PLAYER_ORIGIN,
        },
    )
    first = client.post(
        f"/api/player/hands/{key}/{action}",
        json=payload,
        headers=player_mutation_headers(session),
    )
    retry = client.post(
        f"/api/player/hands/{key}/{action}",
        json=payload,
        headers=player_mutation_headers(session),
    )

    assert missing_csrf.status_code == 403
    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == first.json()
    detail = first.json()
    assert detail["summary"]["lifecycle_status"] == expected_status
    assert detail["summary"]["active_canonical_revision"] is None
    assert detail["summary"]["learning_eligible"] is False
    assert detail["lifecycle"]["reason"] == "Player reviewed this hand"
    assert len(detail["canonical_revisions"]) == 1
    assert RAW_TEXT not in first.text
    stored = runtime.workspace.imported_hands.get(key)
    assert stored.lifecycle.status == expected_status
    assert stored.lifecycle.reason == "Player reviewed this hand"
    assert stored.canonical_revisions == record.canonical_revisions


def test_player_hand_close_routes_refuse_stale_or_inactive_records(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    active = approved_record()
    active_key = imported_hand_record_key(active.identity)
    pending = pending_review_record(sample_identity(hand_ordinal=2))
    pending_key = imported_hand_record_key(pending.identity)
    runtime.workspace.imported_hands.save(active_key, active)
    runtime.workspace.imported_hands.save(pending_key, pending)
    session = exchange_session(client, runtime)
    headers = player_mutation_headers(session)
    original = hand_close_payload(active, reason="No longer part of my study set")

    withdrawn = client.post(
        f"/api/player/hands/{active_key}/withdraw",
        json=original,
        headers=headers,
    )
    stale_reject = client.post(
        f"/api/player/hands/{active_key}/reject",
        json={**original, "reason": "The approved state is incorrect"},
        headers=headers,
    )
    pending_close = client.post(
        f"/api/player/hands/{pending_key}/withdraw",
        json={
            "reason": "Not approved",
            "expected_active_canonical_revision": 1,
            "expected_deletion_generation": 0,
            "expected_lifecycle_changed_at": pending.lifecycle.changed_at.isoformat(),
        },
        headers=headers,
    )

    assert withdrawn.status_code == 200
    assert stale_reject.status_code == 409
    assert "lifecycle changed" in stale_reject.json()["detail"]
    assert pending_close.status_code == 409
    assert runtime.workspace.imported_hands.get(active_key).lifecycle.status == (
        "withdrawn"
    )
    assert runtime.workspace.imported_hands.get(pending_key) == pending


def test_player_hand_delete_routes_purge_and_are_idempotent(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    runtime.workspace.imported_hands.save_decisions(
        key,
        extract_hero_decision_points(record),
    )
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}
    backup = client.get("/api/player/backups/export", headers=authorization)
    assert backup.status_code == 200
    payload = hand_delete_payload(
        record,
        reason="  Remove all retained hand evidence  ",
    )

    assert (
        client.post(
            f"/api/player/hands/{key}/delete",
            json=payload,
            headers={"Origin": PLAYER_ORIGIN},
        ).status_code
        == 401
    )
    missing_csrf = client.post(
        f"/api/player/hands/{key}/delete",
        json=payload,
        headers={**authorization, "Origin": PLAYER_ORIGIN},
    )
    first = client.post(
        f"/api/player/hands/{key}/delete",
        json=payload,
        headers=player_mutation_headers(session),
    )
    retry = client.post(
        f"/api/player/hands/{key}/delete",
        json=payload,
        headers=player_mutation_headers(session),
    )
    different_retry = client.post(
        f"/api/player/hands/{key}/delete",
        json={**payload, "request_id": DELETE_RETRY_REQUEST_ID},
        headers=player_mutation_headers(session),
    )

    assert missing_csrf.status_code == 403
    assert first.status_code == 200
    assert retry.status_code == 200
    assert retry.json() == first.json()
    assert different_retry.status_code == 409
    assert "deleted by another request" in different_retry.json()["detail"]
    detail = first.json()
    assert detail["summary"]["identity"] is None
    assert detail["summary"]["lifecycle_status"] == "deleted"
    assert detail["summary"]["deletion_generation"] == 1
    assert detail["summary"]["learning_eligible"] is False
    assert detail["raw_sources"] == []
    assert detail["detections"] == []
    assert detail["conflicts"] == []
    assert detail["canonical_revisions"] == []
    assert detail["deletion_receipt"]["receipt_id"] == DELETE_REQUEST_ID
    assert len(detail["deletion_receipt"]["tombstone_sha256"]) == 64
    assert RAW_TEXT not in first.text
    assert runtime.workspace.imported_hands.list_decision_artifacts(key) == []

    restored = client.post(
        "/api/player/backups/restore",
        content=backup.content,
        headers={
            **player_mutation_headers(session),
            "Content-Type": "application/zip",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["skipped_stale_records"] == 1
    assert runtime.workspace.imported_hands.get(key).lifecycle.status == "deleted"


def test_player_hand_delete_purges_an_unapproved_record(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = pending_review_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)

    response = client.post(
        f"/api/player/hands/{key}/delete",
        json=hand_delete_payload(
            record,
            reason="Remove this unapproved import",
        ),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 200
    assert response.json()["summary"]["lifecycle_status"] == "deleted"
    assert response.json()["summary"]["deletion_generation"] == 1
    assert response.json()["summary"]["active_canonical_revision"] is None


def test_player_hand_delete_refuses_a_stale_retained_record_version(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    payload = hand_delete_payload(record, reason="Delete retained evidence")
    changed = record.model_copy(
        update={
            "lifecycle": record.lifecycle.model_copy(
                update={"reason": "Newer retained audit event"}
            )
        }
    )
    runtime.workspace.imported_hands.save(key, changed)

    response = client.post(
        f"/api/player/hands/{key}/delete",
        json=payload,
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 409
    assert "retained hand changed" in response.json()["detail"]
    assert runtime.workspace.imported_hands.get(key) == changed


def test_player_hand_delete_retries_a_precommit_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    runtime.workspace.imported_hands.save_decisions(
        key,
        extract_hero_decision_points(record),
    )
    session = exchange_session(client, runtime)
    reason = "Remove retained evidence"
    real_purge = ImportedHandLifecycleService.purge

    def fail_before_purge_intent(*_args, **_kwargs):
        raise OSError("simulated cleanup staging failure")

    monkeypatch.setattr(
        ImportedHandLifecycleService,
        "purge",
        fail_before_purge_intent,
    )
    first = client.post(
        f"/api/player/hands/{key}/delete",
        json=hand_delete_payload(record, reason=reason),
        headers=player_mutation_headers(session),
    )

    assert first.status_code == 500
    pending = runtime.workspace.imported_hands.get(key)
    assert pending.lifecycle.status == "deletion_pending"
    assert pending.lifecycle.reason == reason
    assert pending.lifecycle.deletion_generation == 1
    assert runtime.workspace.imported_hands.active_decisions(key) is None
    assert runtime.workspace.imported_hands.list_decision_artifacts(key)

    monkeypatch.setattr(ImportedHandLifecycleService, "purge", real_purge)
    wrong_reason = client.post(
        f"/api/player/hands/{key}/delete",
        json=hand_delete_payload(
            pending,
            reason="A different deletion reason",
            request_id=DELETE_RETRY_REQUEST_ID,
        ),
        headers=player_mutation_headers(session),
    )
    assert wrong_reason.status_code == 409
    assert "retained request reason" in wrong_reason.json()["detail"]
    assert runtime.workspace.imported_hands.get(key) == pending

    retry = client.post(
        f"/api/player/hands/{key}/delete",
        json=hand_delete_payload(
            pending,
            reason=reason,
            request_id=DELETE_RETRY_REQUEST_ID,
        ),
        headers=player_mutation_headers(session),
    )

    assert retry.status_code == 200
    assert retry.json()["summary"]["lifecycle_status"] == "deleted"
    assert retry.json()["summary"]["deletion_generation"] == 1
    assert retry.json()["deletion_receipt"]["receipt_id"] == DELETE_RETRY_REQUEST_ID
    assert runtime.workspace.imported_hands.list_decision_artifacts(key) == []


def test_player_hand_delete_keeps_an_interrupted_purge_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    runtime.workspace.imported_hands.save_decisions(
        key,
        extract_hero_decision_points(record),
    )
    session = exchange_session(client, runtime)
    real_commit_delete = CascadeJournal._commit_delete

    def fail_artifact_deletion(
        journal: CascadeJournal,
        record_key: str,
        relative: Path,
    ) -> None:
        raise OSError("simulated purge publication failure")

    monkeypatch.setattr(
        CascadeJournal,
        "_commit_delete",
        fail_artifact_deletion,
    )
    response = client.post(
        f"/api/player/hands/{key}/delete",
        json=hand_delete_payload(record, reason="Remove retained evidence"),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 503
    assert "interrupted deletion write" in response.json()["detail"]
    assert runtime.workspace.imported_hands.has_interrupted_write(key)
    assert runtime.workspace.imported_hands.get(key).lifecycle.status == "deleted"
    assert runtime.workspace.imported_hands.list_decision_artifacts(key)
    detail = client.get(
        f"/api/player/hands/{key}",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert detail.status_code == 503

    monkeypatch.setattr(CascadeJournal, "_commit_delete", real_commit_delete)
    recovered = _create_player_runtime(tmp_path)
    assert recovered.workspace.imported_hand_recovery.completed
    assert recovered.workspace.imported_hands.get(key).lifecycle.status == "deleted"
    assert recovered.workspace.imported_hands.list_decision_artifacts(key) == []


@pytest.mark.parametrize(
    "payload_update",
    [
        {"request_id": "   "},
        {"request_id": "meaningful-personal-data"},
        {"reason": "   "},
        {"expected_record_version": "not-a-sha256"},
        {"expected_lifecycle_status": "deleted"},
        {"expected_active_canonical_revision": None},
        {
            "expected_lifecycle_status": "withdrawn",
            "expected_active_canonical_revision": 1,
        },
        {"expected_deletion_generation": -1},
        {"expected_lifecycle_changed_at": "2026-08-30T12:00:00"},
        {"unexpected": True},
    ],
)
def test_player_hand_delete_validates_the_complete_precondition(
    tmp_path: Path,
    payload_update: dict[str, object],
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)

    response = client.post(
        f"/api/player/hands/{key}/delete",
        json={
            **hand_delete_payload(record, reason="Delete retained evidence"),
            **payload_update,
        },
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 422
    assert runtime.workspace.imported_hands.get(key) == record


def test_player_hand_close_advances_a_future_lifecycle_timestamp(
    tmp_path: Path,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    future_changed_at = record.lifecycle.changed_at + timedelta(days=3650)
    future_record = record.model_copy(
        update={
            "lifecycle": record.lifecycle.model_copy(
                update={"changed_at": future_changed_at}
            )
        }
    )
    key = imported_hand_record_key(future_record.identity)
    runtime.workspace.imported_hands.save(key, future_record)
    runtime.workspace.imported_hands.save_decisions(
        key,
        extract_hero_decision_points(future_record),
    )
    session = exchange_session(client, runtime)
    backup = client.get(
        "/api/player/backups/export",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert backup.status_code == 200

    closed = client.post(
        f"/api/player/hands/{key}/withdraw",
        json=hand_close_payload(future_record, reason="Reviewed"),
        headers=player_mutation_headers(session),
    )

    assert closed.status_code == 200
    assert closed.json()["lifecycle"]["changed_at"] == (
        future_changed_at + timedelta(microseconds=1)
    ).isoformat().replace("+00:00", "Z")
    restored = client.post(
        "/api/player/backups/restore",
        content=backup.content,
        headers={
            **player_mutation_headers(session),
            "Content-Type": "application/zip",
        },
    )
    assert restored.status_code == 200
    assert restored.json()["skipped_stale_records"] == 1
    assert runtime.workspace.imported_hands.get(key).lifecycle.status == "withdrawn"


@pytest.mark.parametrize(
    "payload_update",
    [
        {"reason": "   "},
        {"expected_active_canonical_revision": 0},
        {"expected_deletion_generation": -1},
        {"expected_lifecycle_changed_at": "2026-08-30T12:00:00"},
        {"unexpected": True},
    ],
)
def test_player_hand_close_routes_validate_the_complete_precondition(
    tmp_path: Path,
    payload_update: dict[str, object],
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)

    response = client.post(
        f"/api/player/hands/{key}/withdraw",
        json={**hand_close_payload(record, reason="Reviewed"), **payload_update},
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 422
    assert runtime.workspace.imported_hands.get(key) == record


def test_player_hand_close_route_reports_a_busy_process_lock(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path, write_lock_timeout_seconds=0)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    lock_index = runtime.workspace.imported_hand_lock_index(key)
    second_runtime = _create_player_runtime(tmp_path)
    second_lock_index = second_runtime.workspace.imported_hand_lock_index(key)
    assert second_lock_index == lock_index
    process_lock = second_runtime.workspace.imported_hand_process_locks[
        second_lock_index
    ]
    assert process_lock.lock_path == (
        runtime.workspace.imported_hand_process_locks[lock_index].lock_path
    )
    descriptor = process_lock.acquire(exclusive=True)
    try:
        response = client.post(
            f"/api/player/hands/{key}/withdraw",
            json=hand_close_payload(record, reason="Reviewed"),
            headers=player_mutation_headers(session),
        )
    finally:
        process_lock.release(descriptor)

    assert response.status_code == 409
    assert "player hand lifecycle lock" in response.json()["detail"]
    assert runtime.workspace.imported_hands.get(key) == record


def test_player_hand_close_holds_the_volume_snapshot_through_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    transition_started = Event()
    allow_transition = Event()
    real_withdraw = ImportedHandLifecycleService.withdraw

    def delayed_withdraw(
        service: ImportedHandLifecycleService,
        record_key: str,
        *,
        reason: str,
        at,
    ):
        transition_started.set()
        assert allow_transition.wait(2)
        return real_withdraw(service, record_key, reason=reason, at=at)

    monkeypatch.setattr(ImportedHandLifecycleService, "withdraw", delayed_withdraw)
    responses = []
    request_thread = Thread(
        target=lambda: responses.append(
            client.post(
                f"/api/player/hands/{key}/withdraw",
                json=hand_close_payload(record, reason="Reviewed"),
                headers=player_mutation_headers(session),
            )
        )
    )
    request_thread.start()
    try:
        assert transition_started.wait(2)
        with pytest.raises(DataLockTimeoutError, match="exclusive hold"):
            InterprocessDataLock(tmp_path).acquire(
                exclusive=True,
                timeout_seconds=0,
            )
    finally:
        allow_transition.set()
        request_thread.join(timeout=5)

    assert not request_thread.is_alive()
    assert responses[0].status_code == 200
    assert runtime.workspace.imported_hands.get(key).lifecycle.status == "withdrawn"


def test_player_hand_close_keeps_a_ready_cascade_outcome_unresolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    real_commit_replace = CascadeJournal._commit_replace

    def fail_record_publication(
        journal: CascadeJournal,
        record_key: str,
        relative: Path,
        staged_file: Path,
    ) -> None:
        if relative.as_posix() == "record.json":
            raise OSError("simulated lifecycle publication failure")
        real_commit_replace(journal, record_key, relative, staged_file)

    monkeypatch.setattr(
        CascadeJournal,
        "_commit_replace",
        fail_record_publication,
    )
    response = client.post(
        f"/api/player/hands/{key}/withdraw",
        json=hand_close_payload(record, reason="Reviewed"),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 503
    assert "interrupted lifecycle write" in response.json()["detail"]
    assert runtime.workspace.imported_hands.has_interrupted_write(key)
    assert runtime.workspace.imported_hands.get(key).lifecycle.status == "active"
    detail = client.get(
        f"/api/player/hands/{key}",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert detail.status_code == 503

    monkeypatch.setattr(CascadeJournal, "_commit_replace", real_commit_replace)
    recovered = _create_player_runtime(tmp_path)
    assert recovered.workspace.imported_hand_recovery.completed
    assert recovered.workspace.imported_hands.get(key).lifecycle.status == "withdrawn"


def test_player_hand_close_rechecks_a_ready_cascade_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    record = approved_record()
    key = imported_hand_record_key(record.identity)
    runtime.workspace.imported_hands.save(key, record)
    session = exchange_session(client, runtime)
    real_rmtree = shutil.rmtree

    def retain_ready_cascade(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(shutil, "rmtree", retain_ready_cascade)
    response = client.post(
        f"/api/player/hands/{key}/withdraw",
        json=hand_close_payload(record, reason="Reviewed"),
        headers=player_mutation_headers(session),
    )

    assert response.status_code == 503
    assert "interrupted lifecycle write" in response.json()["detail"]
    assert runtime.workspace.imported_hands.has_interrupted_write(key)
    assert runtime.workspace.imported_hands.get(key).lifecycle.status == "withdrawn"
    detail = client.get(
        f"/api/player/hands/{key}",
        headers={"Authorization": f"Bearer {session['session_token']}"},
    )
    assert detail.status_code == 503

    monkeypatch.setattr(shutil, "rmtree", real_rmtree)
    recovered = _create_player_runtime(tmp_path)
    assert recovered.workspace.imported_hand_recovery.completed
    assert recovered.workspace.imported_hands.get(key).lifecycle.status == "withdrawn"


def test_pending_lifecycle_recovery_blocks_volume_operations_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, runtime = player_client(tmp_path)
    pending_record = approved_record(sample_identity(hand_ordinal=21))
    pending_key = imported_hand_record_key(pending_record.identity)
    unrelated_record = approved_record(sample_identity(hand_ordinal=22))
    unrelated_key = imported_hand_record_key(unrelated_record.identity)
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}
    backup = client.get("/api/player/backups/export", headers=authorization)
    assert backup.status_code == 200
    runtime.workspace.imported_hands.save(pending_key, pending_record)
    runtime.workspace.imported_hands.save(unrelated_key, unrelated_record)
    real_commit_replace = CascadeJournal._commit_replace

    def fail_pending_record(
        journal: CascadeJournal,
        record_key: str,
        relative: Path,
        staged_file: Path,
    ) -> None:
        if record_key == pending_key and relative.as_posix() == "record.json":
            raise OSError("simulated lifecycle publication failure")
        real_commit_replace(journal, record_key, relative, staged_file)

    monkeypatch.setattr(CascadeJournal, "_commit_replace", fail_pending_record)
    failed_close = client.post(
        f"/api/player/hands/{pending_key}/withdraw",
        json=hand_close_payload(pending_record, reason="Reviewed"),
        headers=player_mutation_headers(session),
    )
    assert failed_close.status_code == 503
    monkeypatch.setattr(CascadeJournal, "_commit_replace", real_commit_replace)

    listing = client.get("/api/player/hands", headers=authorization)
    storage = client.get("/api/player/storage", headers=authorization)
    blocked_export = client.get("/api/player/backups/export", headers=authorization)
    blocked_restore = client.post(
        "/api/player/backups/restore",
        content=backup.content,
        headers={
            **player_mutation_headers(session),
            "Content-Type": "application/zip",
        },
    )

    assert listing.status_code == 200
    assert [item["record_key"] for item in listing.json()["items"]] == [
        unrelated_key
    ]
    assert listing.json()["unreadable"] == [
        {
            "record_key": pending_key,
            "detail": (
                "Stored imported hand record is unavailable until lifecycle "
                "recovery finishes"
            ),
        }
    ]
    assert storage.status_code == 503
    assert "interrupted lifecycle write" in storage.json()["detail"]
    assert blocked_export.status_code == 503
    assert "startup recovery" in blocked_export.json()["detail"]
    assert blocked_restore.status_code == 503
    assert "startup recovery" in blocked_restore.json()["detail"]
    assert client.get(
        f"/api/player/hands/{unrelated_key}",
        headers=authorization,
    ).status_code == 200
    unrelated_close = client.post(
        f"/api/player/hands/{unrelated_key}/withdraw",
        json=hand_close_payload(unrelated_record, reason="Unrelated review"),
        headers=player_mutation_headers(session),
    )
    assert unrelated_close.status_code == 200


def test_player_storage_status_preserves_quarantine_across_restarts(
    tmp_path: Path,
) -> None:
    imported_hands = tmp_path / "imported-hands"
    imported_hands.mkdir(mode=0o700)
    interrupted = imported_hands / ".cascade" / "interrupted-cascade"
    interrupted.mkdir(parents=True)
    (interrupted / "ready").write_bytes(b"")

    first = _create_player_runtime(tmp_path)
    assert first.workspace.imported_hand_recovery.quarantined == (
        "interrupted-cascade",
    )
    assert first.workspace.status_payload()["status"] == "attention_required"

    second = _create_player_runtime(tmp_path)
    assert second.workspace.imported_hand_recovery == ImportedHandRecoveryReport()
    assert second.workspace.status_payload()["status"] == "attention_required"
    assert second.workspace.status_payload()["recovery"]["quarantined"] == [
        "interrupted-cascade"
    ]


def test_player_api_enforces_origin_and_csrf(tmp_path: Path) -> None:
    client, runtime = player_client(tmp_path)
    launch_url = runtime.issue_launch_url()
    ticket = launch_url.split("#ticket=", 1)[1]

    missing_origin = client.post(
        "/api/player/session",
        headers={"Authorization": f"Bearer {ticket}"},
    )
    assert missing_origin.status_code == 403
    wrong_origin = client.post(
        "/api/player/session",
        headers={
            "Authorization": f"Bearer {ticket}",
            "Origin": "https://attacker.example",
        },
    )
    assert wrong_origin.status_code == 403

    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}
    missing_csrf = client.delete(
        "/api/player/session",
        headers={**authorization, "Origin": PLAYER_ORIGIN},
    )
    assert missing_csrf.status_code == 403
    wrong_csrf = client.delete(
        "/api/player/session",
        headers={
            **authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": "wrong",
        },
    )
    assert wrong_csrf.status_code == 403
    revoked = client.delete(
        "/api/player/session",
        headers={
            **authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
        },
    )
    assert revoked.status_code == 204
    assert client.get("/api/player/health", headers=authorization).status_code == 401


def test_future_player_routes_inherit_session_and_csrf_enforcement(
    tmp_path: Path,
) -> None:
    runtime = _create_player_runtime(tmp_path)

    @runtime.api_application.post("/api/player/future-write")
    async def future_write() -> dict[str, bool]:
        return {"written": True}

    client = TestClient(
        runtime.app,
        base_url=PLAYER_ORIGIN,
        client=("127.0.0.1", 50000),
    )
    session = exchange_session(client, runtime)
    authorization = {"Authorization": f"Bearer {session['session_token']}"}

    unauthenticated = client.post(
        "/api/player/future-write",
        headers={"Origin": PLAYER_ORIGIN},
    )
    missing_csrf = client.post(
        "/api/player/future-write",
        headers={**authorization, "Origin": PLAYER_ORIGIN},
    )
    authenticated = client.post(
        "/api/player/future-write",
        headers={
            **authorization,
            "Origin": PLAYER_ORIGIN,
            "X-Poker-CSRF-Token": str(session["csrf_token"]),
        },
    )

    assert unauthenticated.status_code == 401
    assert missing_csrf.status_code == 403
    assert authenticated.status_code == 200
    assert authenticated.json() == {"written": True}


@pytest.mark.parametrize(
    ("client_address", "base_url", "headers", "status_code"),
    [
        (("192.168.1.20", 50000), PLAYER_ORIGIN, {}, 403),
        (("127.0.0.1", 50000), "http://localhost:8765", {}, 400),
        (("127.0.0.1", 50000), "http://127.0.0.1", {}, 400),
        (
            ("127.0.0.1", 50000),
            PLAYER_ORIGIN,
            {"X-Forwarded-For": "127.0.0.1"},
            400,
        ),
        (
            ("127.0.0.1", 50000),
            PLAYER_ORIGIN,
            {"Origin": "https://attacker.example"},
            403,
        ),
    ],
)
def test_player_runtime_rejects_network_boundary_bypasses(
    tmp_path: Path,
    client_address: tuple[str, int],
    base_url: str,
    headers: dict[str, str],
    status_code: int,
) -> None:
    runtime = _create_player_runtime(tmp_path)
    client = TestClient(
        runtime.app,
        base_url=base_url,
        client=client_address,
    )

    response = client.get("/", headers=headers)

    assert response.status_code == status_code
    assert response.headers["Cache-Control"] == "no-store"


def test_player_launcher_has_a_fixed_loopback_transport(tmp_path: Path) -> None:
    runtime = _create_player_runtime(tmp_path)
    server = build_player_server(runtime)

    assert server.config.host == PLAYER_HOST == "127.0.0.1"
    assert server.config.port == PLAYER_PORT == 8765
    assert server.config.proxy_headers is False
    assert server.config.forwarded_allow_ips == ""


def test_player_launcher_rejects_a_hosted_environment(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="only in the local deployment"):
        configured_player_runtime(
            Settings(data_dir=tmp_path, deployment_environment="production")
        )


def test_player_launcher_holds_the_runtime_lifetime_lease_while_serving(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "player-data"
    settings = Settings(data_dir=data_dir)
    runtime = object()
    observed: list[bool] = []

    async def observe_lease(active_runtime: object) -> None:
        assert active_runtime is runtime
        competing = player_runtime_lease(data_dir.resolve())
        with pytest.raises(DataLockTimeoutError):
            competing.acquire(exclusive=True, timeout_seconds=0)
        observed.append(True)

    monkeypatch.setattr(player_main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        player_main_module,
        "configured_player_runtime",
        lambda _settings: runtime,
    )
    monkeypatch.setattr(player_main_module, "serve_player_runtime", observe_lease)

    assert player_main_module.main([]) == 0

    assert observed == [True]
    lease = player_runtime_lease(data_dir.resolve())
    descriptor = lease.acquire(exclusive=True, timeout_seconds=0)
    lease.release(descriptor)


def test_player_launcher_dispatches_export_and_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[list[str]] = []

    def export_and_remove(arguments: list[str]) -> int:
        observed.append(arguments)
        return 7

    monkeypatch.setattr("app.player_uninstall.main", export_and_remove)

    assert (
        player_main_module.main(
            [
                "export-and-remove",
                "/private/player-backup.zip",
                "--confirm-remove-data",
            ]
        )
        == 7
    )
    assert observed == [
        ["/private/player-backup.zip", "--confirm-remove-data"]
    ]


def test_player_launcher_rejects_unknown_packaged_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert player_main_module.main(["serve-on-lan"]) == 2

    assert "Unknown player runtime command: serve-on-lan" in capsys.readouterr().err


def test_packaged_player_data_dir_uses_platform_application_data_root() -> None:
    home = Path("/private/player")

    assert packaged_player_data_dir(platform_name="darwin", home=home) == (
        home / "Library" / "Application Support" / "Poker Hero" / "data"
    )
    assert packaged_player_data_dir(
        platform_name="linux",
        home=home,
        xdg_data_home="/private/xdg",
    ) == Path("/private/xdg/poker-hero/player/data")
    assert packaged_player_data_dir(
        platform_name="linux",
        home=home,
        xdg_data_home="",
    ) == home / ".local" / "share" / "poker-hero" / "player" / "data"


def test_packaged_player_data_dir_rejects_relative_xdg_root() -> None:
    with pytest.raises(RuntimeError, match="XDG_DATA_HOME must be absolute"):
        packaged_player_data_dir(
            platform_name="linux",
            home=Path("/private/player"),
            xdg_data_home="relative-data",
        )


def test_packaged_player_data_dir_rejects_relative_home() -> None:
    with pytest.raises(RuntimeError, match="home directory must be absolute"):
        packaged_player_data_dir(
            platform_name="linux",
            home=Path("relative-home"),
            xdg_data_home="",
        )


def test_packaged_player_sets_default_data_dir_without_overriding_operator_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("POKER_DATA_DIR", raising=False)
    monkeypatch.setattr(
        player_main_module,
        "packaged_player_data_dir",
        lambda: tmp_path / "packaged-data",
    )

    player_main_module.configure_packaged_player_data_dir()

    assert os.environ["POKER_DATA_DIR"] == str(tmp_path / "packaged-data")
    monkeypatch.setenv("POKER_DATA_DIR", str(tmp_path / "operator-data"))
    player_main_module.configure_packaged_player_data_dir()
    assert os.environ["POKER_DATA_DIR"] == str(tmp_path / "operator-data")


def test_packaged_player_expands_operator_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("POKER_DATA_DIR", "~/operator-data")

    player_main_module.configure_packaged_player_data_dir()

    assert os.environ["POKER_DATA_DIR"] == str(tmp_path / "operator-data")


def test_packaged_player_rejects_relative_explicit_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("POKER_DATA_DIR", "relative-data")

    with pytest.raises(RuntimeError, match="POKER_DATA_DIR must be absolute"):
        player_main_module.configure_packaged_player_data_dir()


def _non_loopback_ipv4() -> str | None:
    candidates: set[str] = set()
    try:
        candidates.update(
            address[4][0]
            for address in socket.getaddrinfo(
                socket.gethostname(),
                None,
                family=socket.AF_INET,
            )
        )
    except OSError:
        pass
    route_probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        route_probe.connect(("192.0.2.1", 9))
        candidates.add(route_probe.getsockname()[0])
    except OSError:
        pass
    finally:
        route_probe.close()
    return next(
        (
            candidate
            for candidate in sorted(candidates)
            if not ip_address(candidate).is_loopback
        ),
        None,
    )


def test_player_server_accepts_loopback_and_refuses_the_lan_interface(
    tmp_path: Path,
) -> None:
    runtime = _create_player_runtime(tmp_path)
    server = build_player_server(runtime)
    server_thread = Thread(target=server.run, daemon=True)
    server_thread.start()
    deadline = monotonic() + 5
    while not server.started and server_thread.is_alive() and monotonic() < deadline:
        sleep(0.01)
    assert server.started

    try:
        launch_url = runtime.issue_launch_url()
        ticket = launch_url.split("#ticket=", 1)[1]
        with httpx.Client(timeout=1, trust_env=False) as client:
            response = client.post(
                f"{PLAYER_ORIGIN}/api/player/session",
                headers={
                    "Authorization": f"Bearer {ticket}",
                    "Origin": PLAYER_ORIGIN,
                },
            )
            assert response.status_code == 200

            lan_address = _non_loopback_ipv4()
            if lan_address is None:
                if sys.platform.startswith("linux"):
                    pytest.fail(
                        "Linux CI must expose a non-loopback IPv4 address for "
                        "the LAN refusal check"
                    )
                pytest.skip("No non-loopback IPv4 interface is available")
            with pytest.raises(httpx.ConnectError):
                client.get(f"http://{lan_address}:{PLAYER_PORT}/")
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)
    assert not server_thread.is_alive()


@pytest.mark.parametrize(
    "path",
    [
        "/api/player",
        "/api/player/imports",
        f"/api/player/hands/{'a' * 64}/reject",
        f"/api/player/hands/{'a' * 64}/approve",
        f"/api/player/hands/{'a' * 64}/delete",
        "/api%2Fplayer%2Fimports",
        "/%61pi/%70layer/imports",
        "/%2561pi%252Fplayer%252Fimports",
    ],
)
def test_player_namespace_matches_direct_and_encoded_paths(path: str) -> None:
    assert is_player_api_path(path)


def test_player_namespace_uses_decoded_path_when_raw_utf8_is_malformed() -> None:
    assert is_player_api_scope(
        {
            "type": "http",
            "path": "/api/player/�",
            "raw_path": b"/api%2Fplayer/%FF",
        }
    )


def test_local_player_auth_denies_malformed_encoded_path_before_body(
    tmp_path: Path,
) -> None:
    body_read = False
    sent: list[dict[str, object]] = []
    runtime = _create_player_runtime(tmp_path)

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player hand history"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        runtime.app(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/player/�",
                "raw_path": b"/api%2Fplayer/%FF",
                "headers": [(b"host", PLAYER_AUTHORITY.encode("ascii"))],
                "client": ("127.0.0.1", 50000),
            },
            receive,
            send,
        )
    )

    assert not body_read
    assert sent[0]["status"] == 401


def test_hosted_player_denial_does_not_read_the_request_body() -> None:
    inner_called = False
    body_read = False
    sent: list[dict[str, object]] = []

    async def inner(_scope, _receive, _send) -> None:
        nonlocal inner_called
        inner_called = True

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player data"}

    async def send(message) -> None:
        sent.append(message)

    middleware = DenyHostedPlayerNamespaceMiddleware(inner)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/player/imports",
                "raw_path": b"/api%2Fplayer%2Fimports",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not inner_called
    assert not body_read
    assert sent[0]["status"] == 404


def test_hosted_player_websocket_namespace_is_reserved() -> None:
    inner_called = False
    sent: list[dict[str, object]] = []

    async def inner(_scope, _receive, _send) -> None:
        nonlocal inner_called
        inner_called = True

    async def receive() -> dict[str, object]:
        return {"type": "websocket.connect"}

    async def send(message) -> None:
        sent.append(message)

    middleware = DenyHostedPlayerNamespaceMiddleware(inner)
    asyncio.run(
        middleware(
            {
                "type": "websocket",
                "path": "/api/player/events",
                "raw_path": b"/api/player/events",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not inner_called
    assert sent == [{"type": "websocket.close", "code": 1008}]


def test_hosted_v1_application_reserves_the_player_namespace(tmp_path: Path) -> None:
    hosted_app = create_app(
        Settings(
            data_dir=tmp_path,
            deployment_environment="production",
            proxy_shared_secret="worker-secret-with-at-least-32-characters",
        )
    )
    client = TestClient(hosted_app)

    response = client.post(
        "/api/player/imports",
        content=b"player hand history",
        headers={"X-Poker-Proxy-Secret": "worker-secret-with-at-least-32-characters"},
    )

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


def test_final_hosted_composition_denies_before_observability_reads_body(
    tmp_path: Path,
) -> None:
    body_read = False
    sent: list[dict[str, object]] = []
    hosted_app = create_app(Settings(data_dir=tmp_path))

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player hand history"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        hosted_app(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/player/imports",
                "raw_path": b"/api%2Fplayer%2Fimports",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not body_read
    assert sent[0]["status"] == 404


def test_final_hosted_composition_denies_malformed_player_path_before_body(
    tmp_path: Path,
) -> None:
    body_read = False
    sent: list[dict[str, object]] = []
    hosted_app = create_app(Settings(data_dir=tmp_path))

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"player hand history"}

    async def send(message) -> None:
        sent.append(message)

    asyncio.run(
        hosted_app(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/player/�",
                "raw_path": b"/api%2Fplayer/%FF",
                "headers": [],
            },
            receive,
            send,
        )
    )

    assert not body_read
    assert sent[0]["status"] == 404
