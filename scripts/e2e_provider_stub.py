#!/usr/bin/env python3
from argparse import ArgumentParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from threading import Event, Lock


# Keep the gate beyond Playwright's 30-second test timeout.
RECOMMENDATION_BLOCK_TIMEOUT_SECONDS = 35
RECOMMENDATION_FALLBACK_REASON = "E2E fallback: unsupported postflop tree"


class ProviderState:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir
        self._fail_next_parser = False
        self._fail_next_recommendation = False
        self._next_recommendation_variant: str | None = None
        self._block_next_recommendation = False
        self._recommendation_started = Event()
        self._recommendation_release = Event()
        self._lock = Lock()

    def arm_parser_failure(self) -> None:
        with self._lock:
            self._fail_next_parser = True

    def arm_recommendation_failure(self) -> None:
        with self._lock:
            self._fail_next_recommendation = True

    def arm_recommendation_fallback(self) -> None:
        with self._lock:
            self._next_recommendation_variant = "fallback"

    def arm_recommendation_evidence(self, variant: str = "evidence") -> None:
        with self._lock:
            self._next_recommendation_variant = variant

    def arm_recommendation_block(self) -> None:
        with self._lock:
            self._block_next_recommendation = True
            self._recommendation_started.clear()
            self._recommendation_release.clear()

    def consume_parser_failure(self) -> bool:
        with self._lock:
            should_fail = self._fail_next_parser
            self._fail_next_parser = False
            return should_fail

    def consume_recommendation_failure(self) -> bool:
        with self._lock:
            should_fail = self._fail_next_recommendation
            self._fail_next_recommendation = False
            return should_fail

    def consume_recommendation_variant(self) -> str | None:
        with self._lock:
            variant = self._next_recommendation_variant
            self._next_recommendation_variant = None
            return variant

    def begin_recommendation(self) -> bool:
        with self._lock:
            should_block = self._block_next_recommendation
            self._block_next_recommendation = False
        if should_block:
            self._recommendation_started.set()
        return should_block

    def recommendation_started(self) -> bool:
        return self._recommendation_started.is_set()

    def release_recommendation(self) -> None:
        self._recommendation_release.set()

    def wait_for_recommendation_release(self) -> bool:
        return self._recommendation_release.wait(
            RECOMMENDATION_BLOCK_TIMEOUT_SECONDS,
        )


def build_handler(state: ProviderState) -> type[BaseHTTPRequestHandler]:
    class ProviderHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/control/recommendation-state":
                self._send_json(
                    200,
                    {"started": state.recommendation_started()},
                )
                return
            if self.path != "/health":
                self.send_error(404)
                return
            self._send_json(200, {"status": "ok"})

        def do_POST(self) -> None:
            if self.path == "/control/fail-next-recommendation":
                state.arm_recommendation_failure()
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/invalid-headline-sizing-next-recommendation":
                state.arm_recommendation_evidence("invalid_headline_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/nonfinite-headline-sizing-next-recommendation":
                state.arm_recommendation_evidence("nonfinite_headline_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/zero-headline-sizing-next-recommendation":
                state.arm_recommendation_evidence("zero_headline_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/coerced-headline-sizing-next-recommendation":
                state.arm_recommendation_evidence("coerced_headline_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/coerced-confidence-next-recommendation":
                state.arm_recommendation_evidence("coerced_confidence")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/fail-next-parser":
                state.arm_parser_failure()
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/fallback-next-recommendation":
                state.arm_recommendation_fallback()
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/evidence-next-recommendation":
                state.arm_recommendation_evidence()
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/lower-evidence-next-recommendation":
                state.arm_recommendation_evidence("lower_evidence")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/pattern-evidence-next-recommendation":
                state.arm_recommendation_evidence("pattern_evidence")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/sizing-evidence-next-recommendation":
                state.arm_recommendation_evidence("sizing_evidence")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/frequency-boundary-next-recommendation":
                state.arm_recommendation_evidence("frequency_boundary")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/below-frequency-boundary-next-recommendation":
                state.arm_recommendation_evidence("below_frequency_boundary")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/above-frequency-maximum-next-recommendation":
                state.arm_recommendation_evidence("above_frequency_maximum")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/maximum-frequency-boundary-next-recommendation":
                state.arm_recommendation_evidence("maximum_frequency_boundary")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/malformed-policy-next-recommendation":
                state.arm_recommendation_evidence("malformed_policy")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/malformed-policy-frequency-next-recommendation":
                state.arm_recommendation_evidence("malformed_policy_frequency")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/missing-policy-frequency-next-recommendation":
                state.arm_recommendation_evidence("missing_policy_frequency")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/missing-recommended-frequency-next-recommendation":
                state.arm_recommendation_evidence("missing_recommended_frequency")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/malformed-recommended-frequency-next-recommendation":
                state.arm_recommendation_evidence("malformed_recommended_frequency")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/missing-recommended-line-next-recommendation":
                state.arm_recommendation_evidence("missing_recommended_line")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/missing-recommended-sizing-next-recommendation":
                state.arm_recommendation_evidence("missing_recommended_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/invalid-recommended-sizing-next-recommendation":
                state.arm_recommendation_evidence("invalid_recommended_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/nonnumeric-ev-next-recommendation":
                state.arm_recommendation_evidence("nonnumeric_ev")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/nonnumeric-recommended-ev-next-recommendation":
                state.arm_recommendation_evidence("nonnumeric_recommended_ev")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/unrelated-nonnumeric-ev-next-recommendation":
                state.arm_recommendation_evidence("unrelated_nonnumeric_ev")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/unrelated-invalid-sizing-next-recommendation":
                state.arm_recommendation_evidence("unrelated_invalid_sizing")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/unrelated-invalid-action-next-recommendation":
                state.arm_recommendation_evidence("unrelated_invalid_action")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/ev-candidate-invalid-frequency-next-recommendation":
                state.arm_recommendation_evidence("ev_candidate_invalid_frequency")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/single-line-evidence-next-recommendation":
                state.arm_recommendation_evidence("single_line_evidence")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/duplicate-line-evidence-next-recommendation":
                state.arm_recommendation_evidence("duplicate_line_evidence")
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/block-next-recommendation":
                state.arm_recommendation_block()
                self._send_json(200, {"armed": True})
                return
            if self.path == "/control/release-recommendation":
                state.release_recommendation()
                self._send_json(200, {"released": True})
                return
            if self.path == "/control/legacy-jobs":
                if state.data_dir is None:
                    self._send_json(400, {"detail": "data directory unavailable"})
                    return
                payload = json.loads(self._read_body() or b"{}")
                job_ids = payload.get("job_ids")
                if not isinstance(job_ids, list) or not all(
                    isinstance(job_id, str) and re.fullmatch(r"[0-9a-f]{32}", job_id)
                    for job_id in job_ids
                ):
                    self._send_json(400, {"detail": "job_ids must be 32-hex identifiers"})
                    return
                for job_id in job_ids:
                    record_path = state.data_dir / "jobs" / job_id / "job.json"
                    if not record_path.is_file():
                        self._send_json(404, {"detail": f"unknown job {job_id}"})
                        return
                    record = json.loads(record_path.read_text())
                    record.pop("input_context", None)
                    temporary = record_path.with_suffix(".json.tmp")
                    temporary.write_text(json.dumps(record))
                    os.replace(temporary, record_path)
                self._send_json(200, {"legacy_job_ids": job_ids})
                return
            if self.path == "/parse":
                self._handle_parser_request()
                return
            if self.path == "/recommend":
                self._handle_recommendation_request()
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

        def _handle_recommendation_request(self) -> None:
            body = self._read_body()
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
            if content_type != "application/json":
                self._send_json(400, {"detail": "Invalid recommendation request"})
                return
            try:
                payload = json.loads(body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                self._send_json(400, {"detail": "Invalid recommendation request"})
                return
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("state"), dict)
                or payload.get("provider") != "external_solver"
            ):
                self._send_json(400, {"detail": "Invalid recommendation request"})
                return
            if state.consume_recommendation_failure():
                self._send_json(503, {"detail": "Temporary solver outage"})
                return
            if (
                state.begin_recommendation()
                and not state.wait_for_recommendation_release()
            ):
                self._send_json(504, {"detail": "Recommendation gate timed out"})
                return
            raw = {
                "provider": "external_solver",
                "engine": "e2e_provider_stub",
            }
            recommendation_action = "call"
            recommendation_sizing = None
            recommendation_confidence: float | str = 0.78
            recommendation_variant = state.consume_recommendation_variant()
            if recommendation_variant == "invalid_headline_sizing":
                recommendation_sizing = 2.5
            elif recommendation_variant == "nonfinite_headline_sizing":
                recommendation_action = "raise"
                recommendation_sizing = float("inf")
            elif recommendation_variant == "zero_headline_sizing":
                recommendation_action = "raise"
                recommendation_sizing = 0
            elif recommendation_variant == "coerced_headline_sizing":
                recommendation_action = "raise"
                recommendation_sizing = "7.5"
            elif recommendation_variant == "coerced_confidence":
                recommendation_confidence = "0.78"
            elif recommendation_variant == "fallback":
                raw.update(
                    {
                        "requested_engine": "postflop_solver",
                        "fallback_reason": RECOMMENDATION_FALLBACK_REASON,
                    },
                )
            elif recommendation_variant in {
                "evidence",
                "lower_evidence",
                "pattern_evidence",
                "sizing_evidence",
                "frequency_boundary",
                "below_frequency_boundary",
                "above_frequency_maximum",
                "maximum_frequency_boundary",
                "malformed_policy",
                "malformed_policy_frequency",
                "missing_policy_frequency",
                "missing_recommended_frequency",
                "malformed_recommended_frequency",
                "missing_recommended_line",
                "missing_recommended_sizing",
                "invalid_recommended_sizing",
                "nonnumeric_ev",
                "nonnumeric_recommended_ev",
                "unrelated_nonnumeric_ev",
                "unrelated_invalid_sizing",
                "unrelated_invalid_action",
                "ev_candidate_invalid_frequency",
                "single_line_evidence",
                "duplicate_line_evidence",
            }:
                if recommendation_variant == "pattern_evidence":
                    call_ev, raise_ev = 2.4, 0.2
                    call_frequency = 0.96
                    raise_frequency = 0.02
                    fold_frequency = 0.02
                elif recommendation_variant == "frequency_boundary":
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.93
                    raise_frequency = 0.05
                    fold_frequency = 0.02
                elif recommendation_variant == "below_frequency_boundary":
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.930001
                    raise_frequency = 0.049999
                    fold_frequency = 0.02
                elif recommendation_variant == "above_frequency_maximum":
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.78
                    raise_frequency = 1.000001
                    fold_frequency = 0.02
                elif recommendation_variant == "maximum_frequency_boundary":
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.78
                    raise_frequency = 1.0
                    fold_frequency = 0.02
                elif recommendation_variant == "malformed_policy_frequency":
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.78
                    raise_frequency = "20%"
                    fold_frequency = 0.02
                elif recommendation_variant == "missing_recommended_line":
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.0
                    raise_frequency = 0.2
                    fold_frequency = 0.8
                elif recommendation_variant == "nonnumeric_ev":
                    call_ev, raise_ev = 1.4, "1.1"
                    call_frequency = 0.78
                    raise_frequency = 0.2
                    fold_frequency = 0.02
                elif recommendation_variant == "nonnumeric_recommended_ev":
                    call_ev, raise_ev = "1.4", 1.1
                    call_frequency = 0.78
                    raise_frequency = 0.2
                    fold_frequency = 0.02
                elif recommendation_variant in {
                    "single_line_evidence",
                    "duplicate_line_evidence",
                }:
                    call_ev, raise_ev = 0.0, 1.4
                    call_frequency = 0.0
                    raise_frequency = 1.0
                    fold_frequency = 0.0
                    recommendation_action = "raise"
                    recommendation_sizing = 8
                elif recommendation_variant == "sizing_evidence":
                    call_ev, raise_ev = 0.8, 1.4
                    call_frequency = 0.3
                    raise_frequency = 0.7
                    fold_frequency = 0.0
                    recommendation_action = "raise"
                    recommendation_sizing = 8
                elif recommendation_variant == "lower_evidence":
                    call_ev, raise_ev = 0.4, 0.3
                    call_frequency = 0.78
                    raise_frequency = 0.2
                    fold_frequency = 0.02
                else:
                    call_ev, raise_ev = 1.4, 1.1
                    call_frequency = 0.78
                    raise_frequency = 0.2
                    fold_frequency = 0.02
                raise_candidate = {
                    "action": "raise",
                    "ev": raise_ev,
                    "frequency": raise_frequency,
                }
                if recommendation_variant == "missing_policy_frequency":
                    raise_candidate.pop("frequency")
                if recommendation_variant != "malformed_policy":
                    raise_candidate["sizing"] = 8
                call_candidate = {
                    "action": "call",
                    "sizing": None,
                    "ev": call_ev,
                    "frequency": call_frequency,
                }
                if recommendation_variant == "missing_recommended_sizing":
                    call_candidate.pop("sizing")
                elif recommendation_variant == "invalid_recommended_sizing":
                    call_candidate["sizing"] = 2.5
                if recommendation_variant == "missing_recommended_frequency":
                    call_candidate.pop("frequency")
                elif recommendation_variant == "malformed_recommended_frequency":
                    call_candidate["frequency"] = "78%"
                third_action = "fold"
                third_sizing = None
                third_ev: int | str = 0
                third_frequency: float | str = fold_frequency
                if recommendation_variant == "unrelated_invalid_sizing":
                    third_action = "bet"
                    third_sizing = -1
                    third_ev = 99
                elif recommendation_variant == "unrelated_invalid_action":
                    third_action = "jam"
                    third_ev = 99
                elif recommendation_variant == "ev_candidate_invalid_frequency":
                    third_action = "bet"
                    third_sizing = 6
                    third_ev = 2.0
                    third_frequency = "20%"
                elif recommendation_variant == "unrelated_nonnumeric_ev":
                    third_ev = "99"
                third_candidate = {
                    "action": third_action,
                    "sizing": third_sizing,
                    "ev": third_ev,
                    "frequency": third_frequency,
                }
                if recommendation_variant == "single_line_evidence":
                    policy_candidates = [raise_candidate]
                elif recommendation_variant == "duplicate_line_evidence":
                    policy_candidates = [
                        raise_candidate,
                        {
                            "action": "raise",
                            "sizing": 8.001,
                            "ev": 1.3,
                            "frequency": 0.0,
                        },
                    ]
                else:
                    policy_candidates = [raise_candidate, third_candidate]
                    if recommendation_variant != "missing_recommended_line":
                        policy_candidates.insert(0, call_candidate)
                raw.update(
                    {
                        "equity": {"equity": 0.61},
                        "realized_equity": 0.55,
                        "required_equity": 0.2,
                        "candidates": policy_candidates,
                    },
                )
            self._send_json(
                200,
                {
                    "action": recommendation_action,
                    "sizing": recommendation_sizing,
                    "confidence": recommendation_confidence,
                    "explanation": "E2E solver compared the available actions.",
                    "raw": raw,
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
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--ready-file", type=Path, required=True)
    args = parser.parse_args()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(ProviderState(args.data_dir)),
    )
    server.daemon_threads = True
    args.ready_file.touch()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
