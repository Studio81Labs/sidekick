from pathlib import Path

import pytest

from app.domain.hands import JobRecord
from app.storage.file_job_store import FileJobStore
from app.workspace import (
    INTERRUPTED_PARSER_ERROR,
    WorkspaceCoordinator,
)


def create_job(store: FileJobStore, filename: str) -> JobRecord:
    return store.create_job(
        original_filename=filename,
        image_bytes=b"image",
        parser_provider="mock",
    )


def test_open_recovers_interrupted_jobs(tmp_path: Path) -> None:
    store = FileJobStore(tmp_path)
    parsing_job = create_job(store, "parsing.png")
    approved_job = create_job(store, "approved.png")
    approved_job.status = "approved"
    store.save(approved_job)

    workspace = WorkspaceCoordinator.open(tmp_path)

    recovered_parsing_job = workspace.jobs.get(parsing_job.id)
    assert recovered_parsing_job.status == "error"
    assert recovered_parsing_job.error == INTERRUPTED_PARSER_ERROR

    untouched_job = workspace.jobs.get(approved_job.id)
    assert untouched_job.status == "approved"
    assert untouched_job.error is None


def test_dataset_import_lock_reports_transaction_state(tmp_path: Path) -> None:
    workspace = WorkspaceCoordinator.open(tmp_path)

    assert not workspace.dataset_import_lock.locked()
    with workspace.dataset_import_lock:
        assert workspace.dataset_import_lock.locked()
    assert not workspace.dataset_import_lock.locked()


def test_coordinator_rejects_empty_job_lock_pool(tmp_path: Path) -> None:
    workspace = WorkspaceCoordinator.open(tmp_path)

    with pytest.raises(ValueError, match="job_lock_stripes must be positive"):
        WorkspaceCoordinator(
            jobs=workspace.jobs,
            benchmarks=workspace.benchmarks,
            data_lock=workspace.data_lock,
            job_lock_stripes=0,
        )
