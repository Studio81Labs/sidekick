from typing import cast

from app.application.jobs import (
    JobImage,
    JobMutationService,
    JobQueryService,
    JobRecommendationService,
)
from app.domain.hands import JobQueue, JobRecord, ScreenshotMetadataRequest
from app.domain.poker import CanonicalState
from app.domain.training import TrainingDecisionRequest


def test_job_query_service_dispatches_job_reads() -> None:
    calls: list[tuple[object, ...]] = []
    queue = JobQueue(total=0, jobs=[], snapshot_version="empty")
    job = JobRecord(
        original_filename="table.png",
        image_filename="image.png",
        parser_provider="mock",
        recommendation_provider="mock",
    )
    image = JobImage(content=b"image", media_type="image/png")

    def list_jobs(limit: int, offset: int) -> JobQueue:
        calls.append(("list", limit, offset))
        return queue

    def get_job(job_id: str) -> JobRecord:
        calls.append(("get", job_id))
        return job

    def get_image(job_id: str) -> JobImage:
        calls.append(("image", job_id))
        return image

    service = JobQueryService(list_jobs, get_job, get_image)

    assert service.list_jobs(25, 50) is queue
    assert service.get_job(job.id) is job
    assert service.get_image(job.id) is image
    assert calls == [
        ("list", 25, 50),
        ("get", job.id),
        ("image", job.id),
    ]


def test_job_mutation_service_dispatches_short_commands() -> None:
    calls: list[tuple[object, ...]] = []
    job = JobRecord(
        original_filename="table.png",
        image_filename="image.png",
        parser_provider="mock",
        recommendation_provider="mock",
    )
    metadata = ScreenshotMetadataRequest(title="Button bluff")
    state = cast(CanonicalState, object())
    decision = cast(TrainingDecisionRequest, object())

    def update_metadata(
        job_id: str,
        request: ScreenshotMetadataRequest,
    ) -> JobRecord:
        calls.append(("metadata", job_id, request))
        return job

    def delete_job(job_id: str) -> None:
        calls.append(("delete", job_id))

    def approve_job(job_id: str, approved_state: CanonicalState) -> JobRecord:
        calls.append(("approve", job_id, approved_state))
        return job

    def record_training_decision(
        job_id: str,
        request: TrainingDecisionRequest,
    ) -> JobRecord:
        calls.append(("decision", job_id, request))
        return job

    service = JobMutationService(
        update_metadata,
        delete_job,
        approve_job,
        record_training_decision,
    )

    assert service.update_metadata(job.id, metadata) is job
    assert service.delete_job(job.id) is None
    assert service.approve_job(job.id, state) is job
    assert service.record_training_decision(job.id, decision) is job
    assert calls == [
        ("metadata", job.id, metadata),
        ("delete", job.id),
        ("approve", job.id, state),
        ("decision", job.id, decision),
    ]


def test_job_recommendation_service_dispatches_request_ids() -> None:
    calls: list[tuple[str, str | None]] = []
    job = JobRecord(
        original_filename="table.png",
        image_filename="image.png",
        parser_provider="mock",
        recommendation_provider="mock",
    )

    def recommend(job_id: str, request_id: str | None) -> JobRecord:
        calls.append((job_id, request_id))
        return job

    service = JobRecommendationService(recommend)

    assert service.recommend(job.id, "recommend-1") is job
    assert service.recommend(job.id, None) is job
    assert calls == [(job.id, "recommend-1"), (job.id, None)]
