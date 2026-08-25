import json
from pathlib import Path
from threading import Event, Lock as ThreadLock, Thread

import pytest
from fastapi.testclient import TestClient

import app.bootstrap as bootstrap_module
from app.bootstrap import create_app
from app.config import Settings
from app.providers.base import ProviderError
from app.providers.mock import MockRecommendationProvider
from app.storage.file_job_store import FileJobStore
from api_test_support import (
    APPROVED_STATE,
    approve_job,
    make_client,
    upload_job,
    upload_job_with_pipeline,
)


def test_upload_parse_approve_and_recommend(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    recommendation_request_id = "recommendation-request-123"

    upload = upload_job(client)

    assert upload.status_code == 201
    job = upload.json()
    assert job["status"] == "parsed"
    assert job["parser_result"]["state"]["hero_cards"][0]["rank"] == "A"
    assert job["parser_result"]["confidences"]["hero_cards"] == 0.99

    approve = approve_job(client, job["id"])

    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    recommend = client.post(
        f"/api/jobs/{job['id']}/recommend",
        headers={"X-Recommendation-Request-ID": recommendation_request_id},
    )

    assert recommend.status_code == 200
    result = recommend.json()
    assert result["status"] == "recommended"
    assert result["recommendation_request_id"] == recommendation_request_id
    assert result["recommendation"]["action"] == "call"
    assert result["recommendation"]["sizing"] is None
    assert (
        FileJobStore(tmp_path).get(job["id"]).recommendation_request_id
        == recommendation_request_id
    )


def test_recommendation_uses_provider_selected_when_job_was_uploaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_settings: list[Settings] = []

    def capture_provider(settings: Settings):
        selected_settings.append(settings)
        return MockRecommendationProvider()

    monkeypatch.setattr(bootstrap_module, "build_provider", capture_provider)
    client = make_client(
        tmp_path,
        recommendation_enabled_providers=["rule_based"],
    )
    upload = upload_job_with_pipeline(
        client,
        parser_provider="mock",
        parser_layout_profile="generic",
        recommendation_provider="rule_based",
    )
    job_id = upload.json()["id"]
    approve_job(client, job_id)

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 200
    assert len(selected_settings) == 1
    assert selected_settings[0].recommendation_provider == "rule_based"


def test_recommendation_does_not_require_a_completed_job_parser_to_remain_enabled(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    store = FileJobStore(tmp_path)
    job = store.get(job_id)
    job.parser_provider = "llm_vision"
    job.parser_layout_profile = "generic"
    store.save(job)
    approve_job(client, job_id)

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 200
    assert response.json()["status"] == "recommended"


def test_recommendation_does_not_require_a_persisted_provider_to_remain_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        parser_provider="mock",
        recommendation_provider="mock",
        recommendation_enabled_providers=["rule_based"],
    )
    client = TestClient(create_app(settings))
    upload = upload_job_with_pipeline(
        client,
        parser_provider="mock",
        parser_layout_profile="generic",
        recommendation_provider="rule_based",
    )
    job_id = upload.json()["id"]
    approve_job(client, job_id)
    settings.recommendation_enabled_providers = []
    monkeypatch.setattr(
        bootstrap_module,
        "build_provider",
        lambda _settings: MockRecommendationProvider(),
    )

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 200
    assert response.json()["status"] == "recommended"


def test_recommendation_preserves_decision_recorded_while_provider_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_started = Event()
    release_provider = Event()

    class SlowRecommendationProvider(MockRecommendationProvider):
        def recommend(self, request):
            provider_started.set()
            if not release_provider.wait(timeout=5):
                raise ProviderError("test provider timed out")
            return super().recommend(request)

    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    imported_job = FileJobStore(tmp_path).get(job_id)
    imported_job.parser_result = None
    imported_job.benchmark_included = True
    FileJobStore(tmp_path).save(imported_job)
    monkeypatch.setattr(
        "app.bootstrap.build_provider",
        lambda settings: SlowRecommendationProvider(),
    )
    recommendation_responses = []
    recommendation_thread = Thread(
        target=lambda: recommendation_responses.append(
            client.post(f"/api/jobs/{job_id}/recommend")
        )
    )

    recommendation_thread.start()
    try:
        assert provider_started.wait(timeout=2)
        in_progress_job = client.get(f"/api/jobs/{job_id}")
        assert in_progress_job.status_code == 200
        assert in_progress_job.json()["recommendation_pending"] is True
        processing_jobs = client.get("/api/jobs")
        assert processing_jobs.status_code == 200
        assert processing_jobs.json()["total"] == 1
        assert processing_jobs.json()["jobs"][0]["id"] == job_id
        assert processing_jobs.json()["jobs"][0]["recommendation_pending"] is True
        duplicate_response = client.post(f"/api/jobs/{job_id}/recommend")
        assert duplicate_response.status_code == 409
        assert duplicate_response.json()["detail"] == "Recommendation is already running"
        reapproval_response = approve_job(client, job_id)
        assert reapproval_response.status_code == 409
        assert reapproval_response.json()["detail"] == "Recommendation is already running"
        assert FileJobStore(tmp_path).get(job_id).recommendation_pending is True
        decision_response = client.put(
            f"/api/jobs/{job_id}/decision",
            json={"action": "raise", "sizing": 7.5},
        )
        assert decision_response.status_code == 200
        assert decision_response.json()["recommendation_pending"] is True
    finally:
        release_provider.set()
        recommendation_thread.join(timeout=5)

    assert not recommendation_thread.is_alive()
    assert len(recommendation_responses) == 1
    recommendation_response = recommendation_responses[0]
    assert recommendation_response.status_code == 200
    job = recommendation_response.json()
    assert job["status"] == "recommended"
    assert job["recommendation_pending"] is False
    assert job["training_decision"]["action"] == "raise"
    assert job["training_decision"]["sizing"] == 7.5
    persisted_job = FileJobStore(tmp_path).get(job_id)
    assert persisted_job.training_decision.action == "raise"
    assert persisted_job.recommendation is not None


def test_superseded_recommendation_cannot_overwrite_newer_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_provider_started = Event()
    release_first_provider = Event()
    provider_calls = 0
    provider_calls_lock = ThreadLock()

    class SupersededRecommendationProvider(MockRecommendationProvider):
        def recommend(self, request):
            nonlocal provider_calls
            with provider_calls_lock:
                provider_calls += 1
                call_number = provider_calls
            if call_number == 1:
                first_provider_started.set()
                if not release_first_provider.wait(timeout=5):
                    raise ProviderError("test provider timed out")
            return super().recommend(request)

    provider = SupersededRecommendationProvider()
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    monkeypatch.setattr("app.bootstrap.build_provider", lambda settings: provider)
    first_responses = []
    first_thread = Thread(
        target=lambda: first_responses.append(client.post(
            f"/api/jobs/{job_id}/recommend",
            headers={"X-Recommendation-Request-ID": "first-attempt"},
        ))
    )

    first_thread.start()
    try:
        assert first_provider_started.wait(timeout=2)
        store = FileJobStore(tmp_path)
        recovered_job = store.get(job_id)
        recovered_job.recommendation_pending = False
        recovered_job.status = "error"
        recovered_job.error = "Recommendation was recovered elsewhere"
        store.save(recovered_job)

        newer_response = client.post(
            f"/api/jobs/{job_id}/recommend",
            headers={"X-Recommendation-Request-ID": "newer-attempt"},
        )
        assert newer_response.status_code == 200
        assert newer_response.json()["recommendation_request_id"] == "newer-attempt"
    finally:
        release_first_provider.set()
        first_thread.join(timeout=5)

    assert not first_thread.is_alive()
    assert len(first_responses) == 1
    assert first_responses[0].status_code == 409
    assert first_responses[0].json()["detail"] == (
        "A newer recommendation request replaced this attempt"
    )
    persisted_job = FileJobStore(tmp_path).get(job_id)
    assert persisted_job.recommendation_request_id == "newer-attempt"
    assert persisted_job.recommendation_pending is False
    assert persisted_job.status == "recommended"
    assert persisted_job.recommendation is not None


def test_app_startup_recovers_interrupted_recommendation(tmp_path: Path) -> None:
    initial_client = make_client(tmp_path)
    job_id = upload_job(initial_client).json()["id"]
    approve_job(initial_client, job_id)
    store = FileJobStore(tmp_path)
    interrupted_job = store.get(job_id)
    interrupted_job.recommendation_pending = True
    store.save(interrupted_job)

    restarted_client = make_client(tmp_path)

    recovered_response = restarted_client.get(f"/api/jobs/{job_id}")
    assert recovered_response.status_code == 200
    recovered_job = recovered_response.json()
    assert recovered_job["recommendation_pending"] is False
    assert recovered_job["status"] == "error"
    assert recovered_job["error"] == (
        "Recommendation was interrupted by a backend restart; request it again"
    )

    retry_response = restarted_client.post(f"/api/jobs/{job_id}/recommend")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == "recommended"


def test_app_startup_loads_legacy_non_actionable_recommendation_sizing(
    tmp_path: Path,
) -> None:
    initial_client = make_client(tmp_path)
    job_id = upload_job(initial_client).json()["id"]
    approve_job(initial_client, job_id)
    recommendation_response = initial_client.post(f"/api/jobs/{job_id}/recommend")
    assert recommendation_response.status_code == 200
    assert recommendation_response.json()["recommendation"]["action"] == "call"

    record_path = tmp_path / "jobs" / job_id / "job.json"
    legacy_record = json.loads(record_path.read_text())
    legacy_record["recommendation"]["sizing"] = 2.5
    record_path.write_text(json.dumps(legacy_record))

    restarted_client = make_client(tmp_path)

    recovered_response = restarted_client.get(f"/api/jobs/{job_id}")
    assert recovered_response.status_code == 200
    assert recovered_response.json()["recommendation"]["sizing"] is None
    listed_response = restarted_client.get("/api/jobs")
    assert listed_response.status_code == 200
    assert listed_response.json()["jobs"][0]["recommendation"]["sizing"] is None


def test_app_startup_loads_legacy_zero_wager_sizing(tmp_path: Path) -> None:
    initial_client = make_client(tmp_path)
    job_id = upload_job(initial_client).json()["id"]
    approve_job(initial_client, job_id)
    decision_response = initial_client.put(
        f"/api/jobs/{job_id}/decision",
        json={"action": "raise", "sizing": 7.5},
    )
    assert decision_response.status_code == 200
    recommendation_response = initial_client.post(f"/api/jobs/{job_id}/recommend")
    assert recommendation_response.status_code == 200

    record_path = tmp_path / "jobs" / job_id / "job.json"
    legacy_record = json.loads(record_path.read_text())
    legacy_record["training_decision"]["sizing"] = 0
    legacy_record["recommendation"]["action"] = "raise"
    legacy_record["recommendation"]["sizing"] = 0
    record_path.write_text(json.dumps(legacy_record))

    restarted_client = make_client(tmp_path)

    recovered_response = restarted_client.get(f"/api/jobs/{job_id}")
    assert recovered_response.status_code == 200
    recovered_job = recovered_response.json()
    assert recovered_job["training_decision"]["sizing"] is None
    assert recovered_job["recommendation"]["sizing"] is None


def test_recommend_requires_approval(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    upload = upload_job(client)
    job_id = upload.json()["id"]

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 409
    assert response.json()["detail"] == "Approve corrected state before requesting recommendation"


def test_provider_configuration_errors_are_http_errors_and_stored(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, recommendation_provider="missing")
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "Provider configuration error: Unknown recommendation provider: missing"
    )
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "error"
    assert job.error == "Unknown recommendation provider: missing"
    assert job.recommendation_pending is False


def test_provider_runtime_errors_are_stored_retryable_and_not_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingProvider:
        name = "failing"
        required_fields = ["hero_cards", "street"]

        def required_fields_for(self, state: object):
            return self.required_fields

        def recommend(self, request: object):
            raise ProviderError("provider exploded")

    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    monkeypatch.setattr("app.bootstrap.build_provider", lambda settings: FailingProvider())

    response = client.post(f"/api/jobs/{job_id}/recommend")
    rejected_archive = client.put(
        "/api/history",
        json={"job_ids": [job_id]},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "provider exploded"
    assert rejected_archive.status_code == 409
    assert rejected_archive.json()["detail"] == (
        "Only successful approved or recommended jobs can be moved to history"
    )
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "error"
    assert job.error == "provider exploded"
    assert job.recommendation_pending is False
    assert job.archived_at is None
    queue = client.get("/api/jobs").json()
    assert [queued_job["id"] for queued_job in queue["jobs"]] == [job_id]


@pytest.mark.parametrize(
    "failure_stage",
    ["build_provider", "required_fields", "validation"],
)
def test_unexpected_provider_setup_errors_clear_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    class SetupProvider(MockRecommendationProvider):
        def required_fields_for(self, state):
            if failure_stage == "required_fields":
                raise RuntimeError("required fields exploded")
            return super().required_fields_for(state)

    def build_setup_provider(settings):
        if failure_stage == "build_provider":
            raise RuntimeError("provider construction exploded")
        return SetupProvider()

    def fail_required_field_validation(state, required_fields):
        raise RuntimeError("required field validation exploded")

    monkeypatch.setattr("app.bootstrap.build_provider", build_setup_provider)
    if failure_stage == "validation":
        monkeypatch.setattr(
            "app.bootstrap.missing_required_fields",
            fail_required_field_validation,
        )
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    with pytest.raises(RuntimeError, match="exploded"):
        client.post(f"/api/jobs/{job_id}/recommend")

    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "error"
    assert job.error is not None
    assert job.error.startswith("Unexpected provider error:")
    assert job.recommendation_pending is False


def test_recommend_reports_missing_required_fields(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id, {"street": "flop", "user_approved": True})

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 422
    assert response.json()["detail"] == {"missing_fields": ["hero_cards"]}
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "approved"
    assert job.recommendation_pending is False


def test_multiway_ev_recommendation_requires_committed_opponent_count(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        recommendation_provider="local_solver",
    )
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "missing_fields": ["opponents_at_current_bet"]
    }
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "approved"
    assert job.error is None
    assert job.recommendation_pending is False


def test_local_ev_requires_total_opponent_wager_when_not_derivable(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        recommendation_provider="local_solver",
        local_solver_engine="local_ev",
    )
    job_id = upload_job(client).json()["id"]
    approve_job(
        client,
        job_id,
        {
            "hero_cards": [
                {"rank": "A", "suit": "hearts"},
                {"rank": "K", "suit": "diamonds"},
            ],
            "board_cards": [],
            "pot_size": 4,
            "current_bet": 1.5,
            "hero_stack": 99,
            "effective_stack": 99,
            "players_in_hand": 2,
            "hero_position": "big_blind",
            "street": "preflop",
            "facing_action": "raise",
            "action_context": "",
            "user_approved": True,
        },
    )

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 422
    assert response.json()["detail"] == {"missing_fields": ["opponent_wager"]}
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "approved"
    assert job.error is None
    assert job.recommendation_pending is False


def test_local_ev_requires_aggregate_multiway_commitments(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        recommendation_provider="local_solver",
        local_solver_engine="local_ev",
    )
    job_id = upload_job(client).json()["id"]
    approve_job(
        client,
        job_id,
        {
            **APPROVED_STATE,
            "pot_size": 30,
            "current_bet": 15,
            "effective_stack": 85,
            "opponents_at_current_bet": 1,
            "opponent_wager": 15,
            "facing_action": "raise",
        },
    )

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "missing_fields": ["opponent_commitment_total"]
    }
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "approved"
    assert job.error is None
    assert job.recommendation_pending is False


@pytest.mark.parametrize(
    ("missing_field", "value"),
    [
        ("hero_position", None),
        ("facing_action", None),
        ("hero_stack", None),
    ],
)
def test_cfr_only_recommend_reports_missing_postflop_fields(
    tmp_path: Path, missing_field: str, value: object
) -> None:
    client = make_client(
        tmp_path,
        recommendation_provider="local_solver",
        local_solver_engine="postflop_solver",
        postflop_solver_fallback_enabled=False,
    )
    job_id = upload_job(client).json()["id"]
    state = {**APPROVED_STATE, "players_in_hand": 2, missing_field: value}
    approve_job(client, job_id, state)

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 422
    assert response.json()["detail"] == {"missing_fields": [missing_field]}
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "approved"
    assert job.error is None


def test_cfr_only_unsupported_state_is_user_correctable(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        recommendation_provider="local_solver",
        local_solver_engine="postflop_solver",
        postflop_solver_fallback_enabled=False,
    )
    job_id = upload_job(client).json()["id"]
    approve_job(
        client,
        job_id,
        {**APPROVED_STATE, "players_in_hand": 2, "facing_action": "raise"},
    )

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "missing_fields": ["opponent_stack", "postflop_action_history"]
    }
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "approved"
    assert job.error is None


def test_provider_configuration_errors_are_http_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MisconfiguredProvider:
        name = "misconfigured"
        required_fields = ["missing_field"]

        def required_fields_for(self, state: object):
            return self.required_fields

    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    monkeypatch.setattr("app.bootstrap.build_provider", lambda settings: MisconfiguredProvider())

    response = client.post(f"/api/jobs/{job_id}/recommend")

    assert response.status_code == 500
    assert response.json()["detail"] == "Provider configuration error: Unknown required field: missing_field"
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "error"
    assert job.error == "Unknown required field: missing_field"
    assert job.recommendation_pending is False
