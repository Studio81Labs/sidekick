import json
from collections import Counter
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path

from app.domain.hands import JobRecord
from app.models import BENCHMARK_FIELDS


def benchmark_layout_profile(
    job: JobRecord,
    default_layout_profile: str,
) -> str:
    return job.parser_layout_profile or default_layout_profile


def benchmark_jobs_for_layout(
    jobs: list[JobRecord],
    layout_profile: str,
    default_layout_profile: str,
) -> list[JobRecord]:
    return [
        job
        for job in jobs
        if job.benchmark_included
        and benchmark_layout_profile(job, default_layout_profile) == layout_profile
    ]


def benchmark_layout_counts(
    jobs: list[JobRecord],
    default_layout_profile: str,
) -> dict[str, int]:
    return dict(
        sorted(
            Counter(
                benchmark_layout_profile(job, default_layout_profile)
                for job in jobs
                if job.benchmark_included
            ).items()
        )
    )


def benchmark_corpus_fingerprint(
    jobs: list[JobRecord],
    image_path_for: Callable[[JobRecord], Path],
) -> str:
    cases = [
        {
            "approved_state": job.approved_state.model_dump(
                mode="json",
                include=set(BENCHMARK_FIELDS),
            ),
            "source_image": _source_image_identity(job, image_path_for),
            "job_id": job.id,
        }
        for job in sorted(jobs, key=lambda candidate: candidate.id)
        if job.benchmark_included and job.approved_state is not None
    ]
    payload = json.dumps(
        cases,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as image_file:
        while chunk := image_file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _source_image_identity(
    job: JobRecord,
    image_path_for: Callable[[JobRecord], Path],
) -> dict[str, str | bool]:
    try:
        return {"sha256": _file_sha256(image_path_for(job))}
    except (KeyError, OSError, ValueError):
        return {
            "available": False,
            "image_filename": job.image_filename,
        }
