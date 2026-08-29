import json
from inspect import getmembers, isfunction
from pathlib import Path

import pytest

from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.file_benchmark_store import FileBenchmarkStore as DirectFileBenchmarkStore
from app.storage.file_job_store import FileJobStore as DirectFileJobStore
from app.storage.ports import BenchmarkRepository, JobRepository


def _public_protocol_methods(protocol: type[object]) -> set[str]:
    return {
        name
        for name, member in getmembers(protocol, isfunction)
        if not name.startswith("_")
    }


def test_storage_facade_preserves_file_adapter_identity() -> None:
    assert FileJobStore is DirectFileJobStore
    assert FileBenchmarkStore is DirectFileBenchmarkStore


def test_file_job_store_implements_job_repository_surface() -> None:
    assert _public_protocol_methods(JobRepository) <= set(dir(FileJobStore))


def test_file_benchmark_store_implements_benchmark_repository_surface() -> None:
    assert _public_protocol_methods(BenchmarkRepository) <= set(dir(FileBenchmarkStore))


def test_file_job_store_persists_explicit_input_context(tmp_path: Path) -> None:
    store = FileJobStore(tmp_path)

    job = store.create_job(
        original_filename="table.png",
        image_bytes=b"png",
        parser_provider="mock",
        recommendation_provider="mock",
        input_context="administrative_test",
    )

    assert store.get(job.id).input_context == "administrative_test"
    assert (
        json.loads((tmp_path / "jobs" / job.id / "job.json").read_text())["input_context"]
        == "administrative_test"
    )


def test_file_job_store_requires_input_context(tmp_path: Path) -> None:
    store = FileJobStore(tmp_path)

    with pytest.raises(TypeError):
        store.create_job(  # type: ignore[call-arg]
            original_filename="table.png",
            image_bytes=b"png",
            parser_provider="mock",
            recommendation_provider="mock",
        )


def test_file_job_store_loads_records_persisted_without_input_context(tmp_path: Path) -> None:
    store = FileJobStore(tmp_path)
    job = store.create_job(
        original_filename="table.png",
        image_bytes=b"png",
        parser_provider="mock",
        recommendation_provider="mock",
        input_context="administrative_test",
    )
    record_path = tmp_path / "jobs" / job.id / "job.json"
    payload = json.loads(record_path.read_text())
    del payload["input_context"]
    record_path.write_text(json.dumps(payload))

    assert store.get(job.id).input_context == "legacy_player"
