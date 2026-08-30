"""Remove persisted records retired from the deployed application."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from app.data_lock import DEFAULT_DATA_LOCK_TIMEOUT_SECONDS, InterprocessDataLock
from app.storage.persistence import JOB_ID_PATTERN, _fsync_directory

RETIRED_V1_JOB_STATUS = "recommended"
RECOVERY_TIMEOUT_ENV = "POKER_DATA_LOCK_RECOVERY_TIMEOUT_SECONDS"


def remove_retired_v1_jobs(
    data_dir: Path,
    *,
    timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
) -> tuple[str, ...]:
    """Delete V1 recommendation jobs without accepting them into current state."""
    jobs_dir = data_dir / "jobs"
    if not _retired_job_directories(jobs_dir):
        return ()

    removed_job_ids: list[str] = []
    with InterprocessDataLock(data_dir).hold(
        exclusive=True,
        timeout_seconds=timeout_seconds,
    ):
        for job_dir in _retired_job_directories(jobs_dir):
            try:
                shutil.rmtree(job_dir)
            except FileNotFoundError:
                continue
            removed_job_ids.append(job_dir.name)
        if removed_job_ids:
            _fsync_directory(jobs_dir)
    return tuple(removed_job_ids)


def _retired_job_directories(jobs_dir: Path) -> tuple[Path, ...]:
    if not jobs_dir.exists():
        return ()
    if jobs_dir.is_symlink() or not jobs_dir.is_dir():
        raise RuntimeError(f"Job store is not a directory: {jobs_dir}")

    retired: list[Path] = []
    for record_path in sorted(jobs_dir.glob("*/job.json")):
        job_dir = record_path.parent
        if (
            JOB_ID_PATTERN.fullmatch(job_dir.name) is None
            or job_dir.is_symlink()
            or record_path.is_symlink()
            or not record_path.is_file()
        ):
            continue
        try:
            values = json.loads(record_path.read_bytes())
        except FileNotFoundError:
            continue
        except json.JSONDecodeError:
            continue
        if isinstance(values, dict) and values.get("status") == RETIRED_V1_JOB_STATUS:
            retired.append(job_dir)
    return tuple(retired)


def main() -> None:
    data_dir = Path(os.environ.get("POKER_DATA_DIR", "/app/data"))
    timeout_seconds = int(
        os.environ.get(
            RECOVERY_TIMEOUT_ENV,
            str(DEFAULT_DATA_LOCK_TIMEOUT_SECONDS),
        )
    )
    removed_job_ids = remove_retired_v1_jobs(
        data_dir,
        timeout_seconds=timeout_seconds,
    )
    if removed_job_ids:
        print(
            "Deployment cleanup removed "
            f"{len(removed_job_ids)} retired V1 screenshot job(s).",
            flush=True,
        )


if __name__ == "__main__":
    main()
