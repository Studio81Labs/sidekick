"""Storage compatibility facade.

The storage domain is split into protocol definitions and dedicated file-backed
adapters under `app.storage`, while this module preserves historical import
paths for production modules and tests.
"""

from app.storage.file_benchmark_store import (
    BENCHMARK_SUMMARY_METADATA_FIELDS,
    BENCHMARK_SUMMARY_OPTIONAL_SCALAR_FIELDS,
    BENCHMARK_SUMMARY_SCALAR_FIELDS,
    BENCHMARK_SUMMARY_SUFFIX,
    FileBenchmarkStore,
)
from app.storage.file_job_store import FileJobStore
from app.storage.persistence import (
    BENCHMARK_ID_PATTERN,
    BENCHMARK_IMPORT_REQUEST_ID_RE,
    DATA_VOLUME_MARKER_FILENAME,
    DATA_VOLUME_MARKER_PREFIX,
    JOB_ID_PATTERN,
    JOB_RECORD_PAYLOAD_ADAPTER,
    LEGACY_ACTIONS_WITHOUT_SIZING,
    LEGACY_WAGER_ACTIONS,
    BenchmarkImportNotFoundError,
    BenchmarkNotFoundError,
    DataVolumeError,
    JobNotFoundError,
    _data_volume_marker_content,
    _fsync_directory,
    _normalize_legacy_action_sizing,
    _require_durable_data_volume_marker,
    initialize_data_volume,
    load_persisted_job_record,
    require_initialized_data_stores,
    require_initialized_data_volume,
)

__all__ = [
    "BENCHMARK_ID_PATTERN",
    "BENCHMARK_IMPORT_REQUEST_ID_RE",
    "BENCHMARK_SUMMARY_METADATA_FIELDS",
    "BENCHMARK_SUMMARY_OPTIONAL_SCALAR_FIELDS",
    "BENCHMARK_SUMMARY_SCALAR_FIELDS",
    "BENCHMARK_SUMMARY_SUFFIX",
    "DATA_VOLUME_MARKER_FILENAME",
    "DATA_VOLUME_MARKER_PREFIX",
    "DataVolumeError",
    "JOB_ID_PATTERN",
    "JOB_RECORD_PAYLOAD_ADAPTER",
    "LEGACY_ACTIONS_WITHOUT_SIZING",
    "LEGACY_WAGER_ACTIONS",
    "JobNotFoundError",
    "BenchmarkImportNotFoundError",
    "BenchmarkNotFoundError",
    "FileBenchmarkStore",
    "FileJobStore",
    "initialize_data_volume",
    "require_initialized_data_stores",
    "require_initialized_data_volume",
    "load_persisted_job_record",
    "_data_volume_marker_content",
    "_require_durable_data_volume_marker",
    "_normalize_legacy_action_sizing",
    "_fsync_directory",
]
