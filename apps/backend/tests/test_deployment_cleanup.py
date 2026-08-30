import json
from pathlib import Path

from app.deployment_cleanup import remove_retired_v1_jobs
from app.storage.file_job_store import FileJobStore


def _create_job(store: FileJobStore, job_id: str) -> Path:
    job = store.create_job(
        original_filename=f"{job_id}.png",
        image_bytes=b"image",
        parser_provider="mock",
        job_id=job_id,
    )
    job.status = "approved"
    store.save(job)
    return store.jobs_dir / job.id


def _replace_status(job_dir: Path, status: str) -> None:
    record_path = job_dir / "job.json"
    values = json.loads(record_path.read_text(encoding="utf-8"))
    values["status"] = status
    record_path.write_text(json.dumps(values), encoding="utf-8")


def test_remove_retired_v1_jobs_deletes_only_recommended_records(
    tmp_path: Path,
) -> None:
    store = FileJobStore(tmp_path)
    retired_job_dir = _create_job(store, "a" * 32)
    approved_job_dir = _create_job(store, "b" * 32)
    unknown_job_dir = _create_job(store, "c" * 32)
    _replace_status(retired_job_dir, "recommended")
    _replace_status(unknown_job_dir, "unknown")

    removed_job_ids = remove_retired_v1_jobs(tmp_path)

    assert removed_job_ids == ("a" * 32,)
    assert not retired_job_dir.exists()
    assert approved_job_dir.is_dir()
    assert unknown_job_dir.is_dir()


def test_remove_retired_v1_jobs_ignores_untrusted_directory_names(
    tmp_path: Path,
) -> None:
    jobs_dir = tmp_path / "jobs"
    untrusted_dir = jobs_dir / "not-a-job-id"
    untrusted_dir.mkdir(parents=True)
    (untrusted_dir / "job.json").write_text(
        json.dumps({"status": "recommended"}),
        encoding="utf-8",
    )

    removed_job_ids = remove_retired_v1_jobs(tmp_path)

    assert removed_job_ids == ()
    assert untrusted_dir.is_dir()
