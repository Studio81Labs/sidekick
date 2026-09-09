import base64
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.bootstrap import create_app
from app.config import Settings
from app.storage.file_job_store import FileJobStore


VALID_PNG = (
    base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
        "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
    )
)

ADMIN_OCR_TEST_TOKEN = "test-administrative-ocr-token-0123456789abcdef"
ADMIN_OCR_TEST_HEADERS = {"Authorization": f"Bearer {ADMIN_OCR_TEST_TOKEN}"}

APPROVED_STATE = {
    "hero_cards": [{"rank": "A", "suit": "hearts"}, {"rank": "K", "suit": "diamonds"}],
    "board_cards": [
        {"rank": "Q", "suit": "spades"},
        {"rank": "J", "suit": "clubs"},
        {"rank": "2", "suit": "hearts"},
    ],
    "pot_size": 12.5,
    "current_bet": 2.5,
    "hero_stack": 97.5,
    "effective_stack": 96.0,
    "players_in_hand": 3,
    "hero_position": "button",
    "street": "flop",
    "facing_action": "bet",
    "action_context": "Cutoff bet 2.5 into 12.5",
    "user_approved": True,
}


class CurrentAdminOcrTestClient(TestClient):
    """Keep behavioral fixtures on the current admin contract during C3 migration.

    Individual feature tests exercise application behavior, not URL migration. Their
    historical paths are rewritten only inside this test client and receive the
    test administrator credential. Dedicated transport tests use an ordinary
    ``TestClient`` to prove the removed paths remain unregistered.
    """

    _legacy_prefixes = (
        ("/api/admin/ocr-test/session", "/api/admin/ocr/session"),
        ("/api/benchmarks", "/api/admin/ocr/benchmarks"),
        ("/api/backups", "/api/admin/ocr/backups"),
        ("/api/history", "/api/admin/ocr/history"),
        ("/api/jobs", "/api/admin/ocr/jobs"),
    )

    def request(self, method: str, url: object, *args: object, **kwargs: object):
        path = str(url)
        for legacy_prefix, current_prefix in self._legacy_prefixes:
            if path == legacy_prefix or path.startswith(f"{legacy_prefix}/") or path.startswith(
                f"{legacy_prefix}?"
            ):
                path = f"{current_prefix}{path[len(legacy_prefix):]}"
                break
        if path == "/api/admin/ocr" or path.startswith("/api/admin/ocr/"):
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("Authorization", ADMIN_OCR_TEST_HEADERS["Authorization"])
            kwargs["headers"] = headers
        return super().request(method, path, *args, **kwargs)


def make_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    settings_values = {
        "data_dir": tmp_path,
        "parser_provider": "mock",
        "admin_ocr_test_enabled": True,
        "admin_ocr_test_token": ADMIN_OCR_TEST_TOKEN,
    }
    settings_values.update(settings_overrides)
    app = create_app(Settings(**settings_values))
    return CurrentAdminOcrTestClient(app)


def make_transport_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    """Build an unwrapped client for authentication and route-contract checks."""

    settings_values = {
        "data_dir": tmp_path,
        "parser_provider": "mock",
        "admin_ocr_test_enabled": True,
        "admin_ocr_test_token": ADMIN_OCR_TEST_TOKEN,
    }
    settings_values.update(settings_overrides)
    return TestClient(create_app(Settings(**settings_values)))


def upload_job(
    client: TestClient,
    content: bytes = VALID_PNG,
    content_type: str = "image/png",
    filename: str = "table.png",
    upload_request_id: str | None = None,
):
    data = (
        {"upload_request_id": upload_request_id}
        if upload_request_id is not None
        else None
    )
    return client.post(
        "/api/admin/ocr/jobs",
        files={"file": (filename, content, content_type)},
        data=data,
        headers=ADMIN_OCR_TEST_HEADERS,
    )


def upload_job_with_pipeline(
    client: TestClient,
    *,
    parser_provider: str,
    parser_layout_profile: str,
):
    data = {
        "parser_provider": parser_provider,
        "parser_layout_profile": parser_layout_profile,
    }
    return client.post(
        "/api/admin/ocr/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        data=data,
        headers=ADMIN_OCR_TEST_HEADERS,
    )


def approve_job(client: TestClient, job_id: str, state: dict[str, object] | None = None):
    return client.post(
        f"/api/admin/ocr/jobs/{job_id}/approve",
        json=state or APPROVED_STATE,
        headers=ADMIN_OCR_TEST_HEADERS,
    )


def import_benchmark_dataset(
    client: TestClient,
    archive_bytes: bytes,
    *,
    request_id: str | None = None,
    headers: dict[str, str] | None = None,
):
    """Post a parser dataset archive with the administrator credential.

    Dataset import mints administrative test jobs, so it shares the upload
    boundary's bearer. Pass `headers={}` to exercise the unauthenticated path.
    """
    request_headers = dict(ADMIN_OCR_TEST_HEADERS if headers is None else headers)
    if request_id is not None:
        request_headers["X-Benchmark-Import-Request-ID"] = request_id
    return client.post(
        "/api/admin/ocr/benchmarks/import",
        files={"file": ("dataset.zip", archive_bytes, "application/zip")},
        headers=request_headers,
    )


def restore_application_backup(
    client: TestClient,
    archive_bytes: bytes,
    *,
    headers: dict[str, str] | None = None,
):
    """Post an application backup archive with the administrator credential.

    Restore can re-persist screenshots captured before the boundary, so it
    shares the upload bearer. Pass `headers={}` for the unauthenticated path.
    """
    return client.post(
        "/api/admin/ocr/backups/restore",
        files={"file": ("backup.zip", archive_bytes, "application/zip")},
        headers=dict(ADMIN_OCR_TEST_HEADERS if headers is None else headers),
    )


def load_only_job(tmp_path: Path):
    job_dirs = list((tmp_path / "jobs").iterdir())
    assert len(job_dirs) == 1
    return FileJobStore(tmp_path).get(job_dirs[0].name)


def archive_with_unsupported_compression(archive_bytes: bytes) -> bytes:
    payload = bytearray(archive_bytes)
    for signature, compression_offset in (
        (b"PK\x03\x04", 8),
        (b"PK\x01\x02", 10),
    ):
        header_offset = payload.find(signature)
        assert header_offset >= 0
        payload[
            header_offset + compression_offset:
            header_offset + compression_offset + 2
        ] = (99).to_bytes(2, "little")
    return bytes(payload)


def rebuild_zip_archive(
    archive_bytes: bytes,
    replacements: dict[str, bytes],
) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(archive_bytes)) as source:
        with ZipFile(output, "w") as target:
            for info in source.infolist():
                target.writestr(
                    info,
                    replacements.get(info.filename, source.read(info)),
                )
    return output.getvalue()
