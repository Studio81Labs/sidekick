from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.application.admin_ocr_test import AdminOcrTestAccessPolicy
from app.bootstrap import create_app
from app.config import Settings
from api_test_support import (
    ADMIN_OCR_TEST_HEADERS,
    ADMIN_OCR_TEST_TOKEN,
    VALID_PNG,
    make_client,
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
