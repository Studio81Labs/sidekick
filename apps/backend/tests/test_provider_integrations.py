import base64
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.bootstrap import create_app
from app.config import Settings
from app.storage.file_job_store import FileJobStore
from api_test_support import ADMIN_OCR_TEST_HEADERS, ADMIN_OCR_TEST_TOKEN


VALID_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR4nGNgYGBgAAAABQABpfZFQAAAAABJRU5ErkJggg=="
)


@pytest.fixture
def external_solver_service() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    requests: list[dict[str, Any]] = []

    class SolverHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers["Content-Length"])
            payload = json.loads(self.rfile.read(content_length))
            requests.append(
                {
                    "authorization": self.headers.get("Authorization"),
                    "content_type": self.headers.get("Content-Type"),
                    "path": self.path,
                    "payload": payload,
                }
            )
            response = json.dumps(
                {
                    "action": "call",
                    "sizing": None,
                    "confidence": 0.77,
                    "explanation": "Loopback external solver response",
                    "raw": {
                        "provider": "external_solver",
                        "engine": "loopback_contract_v1",
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), SolverHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/recommend", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def create_approved_job(
    client: TestClient,
    *,
    opponents_at_current_bet: int | None = None,
) -> str:
    upload = client.post(
        "/api/jobs",
        files={"file": ("table.png", VALID_PNG, "image/png")},
        headers=ADMIN_OCR_TEST_HEADERS,
    )
    assert upload.status_code == 201
    job = upload.json()
    approved_state = {
        **job["parser_result"]["state"],
        "user_approved": True,
    }
    if opponents_at_current_bet is not None:
        approved_state["opponents_at_current_bet"] = opponents_at_current_bet

    approve = client.post(
        f"/api/jobs/{job['id']}/approve",
        json=approved_state,
    )
    assert approve.status_code == 200
    return job["id"]


def test_local_solver_subprocess_completes_api_recommendation(
    tmp_path: Path,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="mock",
        recommendation_provider="local_solver",
        local_solver_engine="local_ev",
        admin_ocr_test_enabled=True,
        admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
    )

    with TestClient(create_app(settings)) as client:
        job_id = create_approved_job(client, opponents_at_current_bet=1)
        response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 200
    recommendation = response.json()["recommendation"]
    assert recommendation["raw"]["provider"] == "local_solver"
    assert recommendation["raw"]["engine"] == "local_ev_solver_v1"
    assert recommendation["raw"]["candidates"]

    persisted = FileJobStore(tmp_path).get(job_id)
    assert persisted.status == "recommended"
    assert persisted.recommendation is not None
    assert persisted.recommendation.raw["engine"] == "local_ev_solver_v1"


def test_external_solver_http_service_completes_api_recommendation(
    tmp_path: Path,
    external_solver_service: tuple[str, list[dict[str, Any]]],
) -> None:
    service_url, requests = external_solver_service
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="mock",
        recommendation_provider="external_solver",
        external_provider_url=service_url,
        external_request_timeout_seconds=5,
        admin_ocr_test_enabled=True,
        admin_ocr_test_token=ADMIN_OCR_TEST_TOKEN,
    )

    with TestClient(create_app(settings)) as client:
        job_id = create_approved_job(client)
        response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 200
    recommendation = response.json()["recommendation"]
    assert recommendation["action"] == "call"
    assert recommendation["raw"] == {
        "provider": "external_solver",
        "engine": "loopback_contract_v1",
    }
    assert len(requests) == 1
    request = requests[0]
    assert request["path"] == "/recommend"
    assert request["authorization"] is None
    assert request["content_type"] == "application/json"
    assert request["payload"]["provider"] == "external_solver"
    assert request["payload"]["state"]["hero_cards"] == [
        {"rank": "A", "suit": "hearts"},
        {"rank": "K", "suit": "diamonds"},
    ]

    persisted = FileJobStore(tmp_path).get(job_id)
    assert persisted.status == "recommended"
    assert persisted.recommendation is not None
    assert persisted.recommendation.raw["engine"] == "loopback_contract_v1"
