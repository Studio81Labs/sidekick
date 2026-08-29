from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from app.config import Settings
from app.domain.poker import CanonicalState, Card
from app.domain.recommendations import RecommendationRequest
from app.providers.registry import build_provider


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


def approved_state() -> CanonicalState:
    return CanonicalState(
        hero_cards=[Card.from_code("Ah"), Card.from_code("Kd")],
        board_cards=[Card.from_code("Qs"), Card.from_code("Jc"), Card.from_code("2h")],
        pot_size=12.5,
        current_bet=2.5,
        hero_stack=97.5,
        effective_stack=96.0,
        players_in_hand=3,
        opponents_at_current_bet=1,
        hero_position="button",
        street="flop",
        facing_action="bet",
        action_context="Cutoff bet 2.5 into 12.5",
        user_approved=True,
    )


def test_external_solver_http_service_completes_a_recommendation(
    tmp_path: Path,
    external_solver_service: tuple[str, list[dict[str, Any]]],
) -> None:
    service_url, requests = external_solver_service
    provider = build_provider(
        Settings(
            data_dir=tmp_path,
            recommendation_provider="external_solver",
            external_provider_url=service_url,
            external_request_timeout_seconds=5,
        )
    )

    result = provider.recommend(
        RecommendationRequest(state=approved_state(), provider=provider.name)
    )

    assert result.action == "call"
    assert result.raw == {
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
