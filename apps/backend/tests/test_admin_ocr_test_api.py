import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.application.admin_ocr_test import AdminOcrTestAccessPolicy
from app.bootstrap import create_app
from app.config import Settings
from app.storage.file_job_store import FileJobStore
from api_test_support import (
    ADMIN_OCR_TEST_HEADERS,
    ADMIN_OCR_TEST_TOKEN,
    VALID_PNG,
    approve_job,
    make_client,
    upload_job,
)


def _post_upload(client: TestClient, headers: dict[str, str] | None = None):
    return client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers=headers,
    )


def test_upload_is_forbidden_when_administrative_mode_is_disabled(tmp_path: Path) -> None:
    client = make_client(tmp_path, admin_ocr_test_enabled=False, admin_ocr_test_token=None)

    without_credential = _post_upload(client)
    with_credential = _post_upload(client, ADMIN_OCR_TEST_HEADERS)

    assert without_credential.status_code == 403
    assert without_credential.json()["detail"] == "Administrative OCR test mode is disabled"
    assert with_credential.status_code == 403
    assert not (tmp_path / "jobs").exists() or not any((tmp_path / "jobs").iterdir())


def test_upload_requires_a_valid_administrator_bearer(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    missing = _post_upload(client)
    wrong_scheme = _post_upload(client, {"Authorization": f"Basic {ADMIN_OCR_TEST_TOKEN}"})
    wrong_token = _post_upload(client, {"Authorization": f"Bearer {ADMIN_OCR_TEST_TOKEN}x"})

    for response in (missing, wrong_scheme, wrong_token):
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"
        assert response.json()["detail"] == "Administrative OCR test authorization is required"
    assert not (tmp_path / "jobs").exists() or not any((tmp_path / "jobs").iterdir())


def test_authorized_upload_creates_an_administrative_test_job(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = _post_upload(client, ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 201
    job = response.json()
    assert job["input_context"] == "administrative_test"
    assert client.get(f"/api/jobs/{job['id']}").json()["input_context"] == "administrative_test"


def test_disabled_deployment_ignores_configured_token(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
            recommendation_provider="mock",
            admin_ocr_test_enabled=False,
            admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
        )
    )

    response = _post_upload(TestClient(app), ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 403


def test_upload_fails_closed_on_an_unexpected_authorization_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only an explicit "authorized" decision may proceed: a future decision member
    # must deny rather than fall through and open the upload surface. The policy is
    # patched before the app is built because bootstrap binds `authorize` once.
    monkeypatch.setattr(
        AdminOcrTestAccessPolicy,
        "authorize",
        lambda _self, _authorization_header: "expired",
    )
    client = make_client(tmp_path)

    response = _post_upload(client, ADMIN_OCR_TEST_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test authorization was refused"
    )
    assert not (tmp_path / "jobs").exists() or not any((tmp_path / "jobs").iterdir())


def _persisted_record_path(tmp_path: Path, job_id: str) -> Path:
    return tmp_path / "jobs" / job_id / "job.json"


def _set_input_context(tmp_path: Path, job_id: str, value: str | None) -> None:
    path = _persisted_record_path(tmp_path, job_id)
    payload = json.loads(path.read_text())
    if value is None:
        payload.pop("input_context", None)
    else:
        payload["input_context"] = value
    path.write_text(json.dumps(payload))


def test_administrative_test_job_cannot_request_a_recommendation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    assert approve_job(client, job_id).status_code == 200

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test inputs cannot request recommendations"
    )
    stored = FileJobStore(tmp_path).get(job_id)
    assert stored.status == "approved"
    assert stored.recommendation is None
    assert stored.recommendation_pending is False
    assert stored.recommendation_request_id is None


def test_administrative_test_job_cannot_record_training_decision(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 7.5, "certainty": "high"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Administrative OCR test inputs cannot record training decisions"
    )
    assert FileJobStore(tmp_path).get(job_id).training_decision is None


def test_administrative_test_job_cannot_enter_training_review(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    complete = client.put(f"/api/jobs/{job_id}/training-review", json={"note": "x"})
    reopen = client.delete(f"/api/jobs/{job_id}/training-review")

    assert complete.status_code == 403
    assert reopen.status_code == 403
    assert complete.json()["detail"] == (
        "Administrative OCR test inputs cannot enter training review"
    )


def test_legacy_player_jobs_keep_recommendation_and_training_paths(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    _set_input_context(tmp_path, job_id, None)  # record persisted before #413

    assert client.get(f"/api/jobs/{job_id}").json()["input_context"] == "legacy_player"
    decision = client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None, "certainty": "medium"},
    )
    recommend = client.post(f"/api/jobs/{job_id}/recommend")

    assert decision.status_code == 200
    assert recommend.status_code == 200
    assert recommend.json()["status"] == "recommended"


def test_training_progress_excludes_administrative_test_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    _set_input_context(tmp_path, job_id, "legacy_player")
    assert client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "call", "sizing": None, "certainty": "medium"},
    ).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/recommend").status_code == 200
    assert client.get("/api/training/progress").json()["reviewed_hands"] == 1

    _set_input_context(tmp_path, job_id, "administrative_test")

    progress = client.get("/api/training/progress").json()
    assert progress["reviewed_hands"] == 0
    assert progress["unrated_hands"] == 0


def test_lesson_export_excludes_administrative_test_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    _set_input_context(tmp_path, job_id, "legacy_player")
    assert client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 7.5, "certainty": "medium"},
    ).status_code == 200
    assert client.post(f"/api/jobs/{job_id}/recommend").status_code == 200
    assert client.put(
        f"/api/jobs/{job_id}/training-review",
        json={"note": "Watch the call price."},
    ).status_code == 200
    exported = client.get("/api/training/lessons/export")
    assert exported.status_code == 200
    assert "Watch the call price." in exported.text

    _set_input_context(tmp_path, job_id, "administrative_test")

    excluded = client.get("/api/training/lessons/export")
    assert excluded.status_code == 409
    assert excluded.json()["detail"] == (
        "No saved lesson notes match the selected filters"
    )
