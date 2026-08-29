"""Storage utilities shared by file-backed repository adapters."""

from __future__ import annotations

import os
import re
import tempfile
from hashlib import sha256
from pathlib import Path

from app.domain.benchmarks import BENCHMARK_IMPORT_REQUEST_ID_PATTERN
from app.domain.hands import JobRecord

JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
BENCHMARK_ID_PATTERN = JOB_ID_PATTERN
BENCHMARK_IMPORT_REQUEST_ID_RE = re.compile(BENCHMARK_IMPORT_REQUEST_ID_PATTERN)

DATA_VOLUME_MARKER_FILENAME = ".poker-hero-data-volume"
DATA_VOLUME_MARKER_PREFIX = "poker-hero-data-volume-v1:"


class DataVolumeError(RuntimeError):
    pass


class JobNotFoundError(KeyError):
    pass


class BenchmarkNotFoundError(KeyError):
    pass


class BenchmarkImportNotFoundError(KeyError):
    pass


def initialize_data_volume(data_dir: Path, volume_id: str) -> None:
    required_store_dirs = (data_dir / "jobs", data_dir / "benchmarks")
    try:
        stores_are_initialized = data_dir.is_dir() and all(
            path.is_dir() for path in required_store_dirs
        )
    except OSError as exc:
        raise DataVolumeError(
            f"Could not inspect data directory: {data_dir}"
        ) from exc
    if not stores_are_initialized:
        raise DataVolumeError(
            f"Data directory was not initialized by the backend: {data_dir}"
        )

    marker_path = data_dir / DATA_VOLUME_MARKER_FILENAME
    if marker_path.exists():
        _require_durable_data_volume_marker(data_dir, volume_id)
        return

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=data_dir,
            encoding="utf-8",
            prefix=".poker-hero-data-volume.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(_data_volume_marker_content(volume_id))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        temp_path.chmod(0o644)
        try:
            os.link(temp_path, marker_path)
        except FileExistsError:
            pass
    except OSError as exc:
        raise DataVolumeError(
            f"Could not initialize data directory: {data_dir}"
        ) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
    _require_durable_data_volume_marker(data_dir, volume_id)


def require_initialized_data_volume(data_dir: Path, volume_id: str) -> None:
    marker_path = data_dir / DATA_VOLUME_MARKER_FILENAME
    try:
        marker_content = marker_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise DataVolumeError(
            f"Data volume marker is missing from {data_dir}; refusing backup export"
        ) from exc
    except OSError as exc:
        raise DataVolumeError(
            f"Could not verify data volume marker in {data_dir}"
        ) from exc
    if marker_content != _data_volume_marker_content(volume_id):
        raise DataVolumeError(
            f"Data volume marker does not match {data_dir}; refusing backup export"
        )


def require_initialized_data_stores(data_dir: Path) -> None:
    required_store_dirs = (data_dir / "jobs", data_dir / "benchmarks")
    try:
        missing_stores = [
            path.name for path in required_store_dirs if not path.is_dir()
        ]
    except OSError as exc:
        raise DataVolumeError(
            f"Could not verify data stores in {data_dir}"
        ) from exc
    if missing_stores:
        missing = ", ".join(missing_stores)
        raise DataVolumeError(
            f"Required data store directories are missing from {data_dir}: {missing}; "
            "refusing backup export"
        )


def _data_volume_marker_content(volume_id: str) -> str:
    return f"{DATA_VOLUME_MARKER_PREFIX}{volume_id}\n"


def _require_durable_data_volume_marker(data_dir: Path, volume_id: str) -> None:
    require_initialized_data_volume(data_dir, volume_id)
    try:
        _fsync_directory(data_dir)
    except OSError as exc:
        raise DataVolumeError(
            f"Could not make data volume marker durable: {data_dir}"
        ) from exc


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def load_persisted_job_record(payload: str | bytes) -> JobRecord:
    return JobRecord.model_validate_json(payload)
