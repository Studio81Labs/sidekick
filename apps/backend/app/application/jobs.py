"""Application services for processing-job use cases."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.domain.hands import JobQueue, JobRecord

ListJobs = Callable[[int, int], JobQueue]
GetJob = Callable[[str], JobRecord]
GetJobImage = Callable[[str], "JobImage"]


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
