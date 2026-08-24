from app.application.jobs import JobImage, JobQueryService
from app.domain.hands import JobQueue, JobRecord


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
