from inspect import getmembers, isfunction

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
