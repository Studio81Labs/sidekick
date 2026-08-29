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


def make_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    settings_values = {
        "data_dir": tmp_path,
        "parser_provider": "mock",
        "recommendation_provider": "mock",
        "admin_ocr_test_enabled": True,
        "admin_ocr_test_token": ADMIN_OCR_TEST_TOKEN,
    }
    settings_values.update(settings_overrides)
    app = create_app(Settings(**settings_values))
    return TestClient(app)


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
        "/api/jobs",
        files={"file": (filename, content, content_type)},
        data=data,
        headers=ADMIN_OCR_TEST_HEADERS,
    )


def upload_job_with_pipeline(
    client: TestClient,
    *,
    parser_provider: str,
    parser_layout_profile: str,
    recommendation_provider: str,
    recommendation_engine: str | None = None,
):
    data = {
        "parser_provider": parser_provider,
        "parser_layout_profile": parser_layout_profile,
        "recommendation_provider": recommendation_provider,
    }
    if recommendation_engine is not None:
        data["recommendation_engine"] = recommendation_engine
    return client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        data=data,
        headers=ADMIN_OCR_TEST_HEADERS,
    )


def approve_job(client: TestClient, job_id: str, state: dict[str, object] | None = None):
    return client.post(f"/api/jobs/{job_id}/approve", json=state or APPROVED_STATE)


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
