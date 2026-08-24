"""Application services for processing-job use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.hands import (
    JobQueue,
    JobRecord,
    ScreenshotMetadataRequest,
)
from app.domain.poker import CanonicalState
from app.domain.training import TrainingDecisionRequest

ListJobs = Callable[[int, int], JobQueue]
GetJob = Callable[[str], JobRecord]
GetJobImage = Callable[[str], "JobImage"]
UpdateJobMetadata = Callable[[str, ScreenshotMetadataRequest], JobRecord]
DeleteJob = Callable[[str], None]
ApproveJob = Callable[[str, CanonicalState], JobRecord]
RecordTrainingDecision = Callable[[str, TrainingDecisionRequest], JobRecord]
RecommendJob = Callable[[str, str | None], JobRecord]


@dataclass(frozen=True)
class JobImage:
    """Application result for a stored job image."""

    content: bytes
    media_type: str


class JobQueryService:
    """Dispatch processing-job reads through an application-owned boundary."""

    def __init__(
        self,
        list_jobs: ListJobs,
        get_job: GetJob,
        get_image: GetJobImage,
    ) -> None:
        self._list_jobs = list_jobs
        self._get_job = get_job
        self._get_image = get_image

    def list_jobs(self, limit: int, offset: int) -> JobQueue:
        return self._list_jobs(limit, offset)

    def get_job(self, job_id: str) -> JobRecord:
        return self._get_job(job_id)

    def get_image(self, job_id: str) -> JobImage:
        return self._get_image(job_id)


class JobMutationService:
    """Dispatch short processing-job commands through an application boundary."""

    def __init__(
        self,
        update_metadata: UpdateJobMetadata,
        delete_job: DeleteJob,
        approve_job: ApproveJob,
        record_training_decision: RecordTrainingDecision,
    ) -> None:
        self._update_metadata = update_metadata
        self._delete_job = delete_job
        self._approve_job = approve_job
        self._record_training_decision = record_training_decision

    def update_metadata(
        self,
        job_id: str,
        metadata: ScreenshotMetadataRequest,
    ) -> JobRecord:
        return self._update_metadata(job_id, metadata)

    def delete_job(self, job_id: str) -> None:
        self._delete_job(job_id)

    def approve_job(self, job_id: str, state: CanonicalState) -> JobRecord:
        return self._approve_job(job_id, state)

    def record_training_decision(
        self,
        job_id: str,
        decision: TrainingDecisionRequest,
    ) -> JobRecord:
        return self._record_training_decision(job_id, decision)


class JobRecommendationService:
    """Dispatch recommendation requests through an application boundary."""

    def __init__(self, recommend: RecommendJob) -> None:
        self._recommend = recommend

    def recommend(
        self,
        job_id: str,
        recommendation_request_id: str | None,
    ) -> JobRecord:
        return self._recommend(job_id, recommendation_request_id)
