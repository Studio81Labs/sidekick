import json

import pytest
from pydantic import ValidationError

from app.domain.hands import (
    ArchiveJobsRequest,
    JobHistory,
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
)
from app.storage.persistence import load_persisted_job_record


def test_screenshot_metadata_request_normalizes_text_and_tags() -> None:
    request = ScreenshotMetadataRequest(
        title="  Hero flop play  ",
        notes="\n  check bluff sizing \n",
        tags=["river", "river", "Turn ", "  ", " flop ", "river  ", "button"],
    )

    assert request.title == "Hero flop play"
    assert request.notes == "check bluff sizing"
    assert request.tags == ["river", "Turn", "flop", "button"]


def test_archive_jobs_request_rejects_duplicates_and_empty_batch() -> None:
    with pytest.raises(ValidationError):
        ArchiveJobsRequest(job_ids=[])

    with pytest.raises(ValidationError):
        ArchiveJobsRequest(job_ids=["a" * 32, "a" * 32])

    ArchiveJobsRequest(job_ids=["a" * 32, "b" * 32])


def test_job_record_json_round_trip_and_snapshot_fields() -> None:
    record = JobRecord(
        original_filename="hero-turn.png",
        image_filename="original.png",
        parser_provider="ocr_cv",
        recommendation_provider="rule_based",
        title="   Turn decision  ",
        notes="  Check river sizing.   ",
        tags=["river", "  river", "button"],
    )

    persisted = load_persisted_job_record(record.model_dump_json())

    assert persisted == record
    assert persisted.title == "Turn decision"
    assert persisted.notes == "Check river sizing."
    assert persisted.tags == ["river", "button"]


def test_job_record_json_round_trip_rejects_legacy_sizing_values_only_after_normalization() -> None:
    legacy_payload = {
        "original_filename": "legacy.png",
        "image_filename": "original.png",
        "parser_provider": "ocr_cv",
        "recommendation_provider": "rule_based",
        "recommendation": {
            "action": "call",
            "sizing": 2.5,
            "confidence": 0.82,
            "explanation": "legacy check action",
        },
        "training_decision": {
            "action": "raise",
            "sizing": 0,
            "certainty": "medium",
        },
    }

    legacy_job = load_persisted_job_record(json.dumps(legacy_payload))

    assert legacy_job.recommendation is not None
    assert legacy_job.recommendation.sizing is None
    assert legacy_job.training_decision is not None
    assert legacy_job.training_decision.sizing is None


def test_job_history_and_queue_contracts_round_trip() -> None:
    job = JobRecord(
        original_filename="history-turn.png",
        image_filename="history.png",
        parser_provider="mock",
        recommendation_provider="rule_based",
    )

    history = JobHistory(total=1, jobs=[job], snapshot_version="history-v1")
    queue = JobQueue(total=1, jobs=[job], snapshot_version="queue-v1")

    reloaded_history = JobHistory.model_validate(history.model_dump())
    reloaded_queue = JobQueue.model_validate(queue.model_dump())

    assert reloaded_history == history
    assert reloaded_queue == queue
    assert reloaded_history.total == 1
    assert reloaded_queue.total == 1
