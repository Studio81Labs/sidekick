#!/usr/bin/env python3
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Lock


class ProviderState:
    def __init__(self) -> None:
        self._fail_next_parser = False
        self._lock = Lock()

    def arm_parser_failure(self) -> None:
        with self._lock:
            self._fail_next_parser = True

    def consume_parser_failure(self) -> bool:
        with self._lock:
            should_fail = self._fail_next_parser
            self._fail_next_parser = False
            return should_fail


def build_handler(state: ProviderState) -> type[BaseHTTPRequestHandler]:
    class ProviderHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/health":
                self.send_error(404)
                return
            self._send_json(200, {"status": "ok"})

        def do_POST(self) -> None:
            if self.path == "/control/fail-next-parser":
                state.arm_parser_failure()
                self._send_json(200, {"armed": True})
                return
            if self.path == "/parse":
                self._handle_parser_request()
                return
            self.send_error(404)

        def _handle_parser_request(self) -> None:
            content_type = self.headers.get("Content-Type", "")
            body = self._read_body()
            if (
                "multipart/form-data" not in content_type
                or b'name="image"' not in body
                or b'name="layout_profile"' not in body
            ):
                self._send_json(400, {"detail": "Invalid parser request"})
                return
            if state.consume_parser_failure():
                self._send_json(503, {"detail": "Temporary parser outage"})
                return
            self._send_json(
                200,
                {
                    "state": {
                        "hero_cards": [
                            {"rank": "A", "suit": "hearts"},
                            {"rank": "K", "suit": "diamonds"},
                        ],
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
                    },
                    "confidences": {
                        "hero_cards": 0.99,
                        "board_cards": 0.98,
                        "pot_size": 0.96,
                        "current_bet": 0.9,
                        "hero_stack": 0.89,
                        "effective_stack": 0.88,
                        "players_in_hand": 0.93,
                        "hero_position": 0.87,
                        "street": 1.0,
                        "facing_action": 0.9,
                    },
                    "warnings": [],
                    "raw": {
                        "provider": "llm_vision",
                        "engine": "e2e_provider_stub",
                    },
                },
            )

        def _read_body(self) -> bytes:
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                content_length = 0
            if content_length <= 0:
                return b""
            return self.rfile.read(content_length)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_json(self, status: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ProviderHandler


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(ProviderState()),
    )
    server.daemon_threads = True
    args.ready_file.touch()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
