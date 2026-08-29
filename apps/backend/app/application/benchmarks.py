"""Application services for parser benchmark use cases."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from app.application.admin_ocr_test import AuthorizeAdministrator
from app.domain.benchmarks import (
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkOverview,
    BenchmarkReport,
    BenchmarkRunRequest,
    BenchmarkSelectionRequest,
)
from app.domain.hands import JobRecord


@dataclass(frozen=True)
class BenchmarkDatasetExport:
    """A prepared parser dataset archive ready for transport."""

    content: Iterator[bytes]
    filename: str


@dataclass(frozen=True)
class BenchmarkImportStatus:
    """A persisted import receipt plus its recovery scheduling state."""

    receipt: BenchmarkDatasetImportReceipt
    should_resume: bool


UpdateBenchmarkInclusion = Callable[[str, BenchmarkSelectionRequest], JobRecord]
GetBenchmarkOverview = Callable[[str | None, str | None], BenchmarkOverview]
ExportBenchmarkDataset = Callable[
    [str | None, str | None],
    BenchmarkDatasetExport,
]
ImportBenchmarkDataset = Callable[[bytes, str | None], BenchmarkDatasetImportResult]
GetBenchmarkImport = Callable[[str], BenchmarkImportStatus]
ResumeBenchmarkImport = Callable[[str], None]
GetBenchmarkReport = Callable[[str], BenchmarkReport]
RunBenchmark = Callable[[BenchmarkRunRequest | None], BenchmarkReport]


@dataclass(frozen=True)
class BenchmarkService:
    """Dispatch parser benchmark use cases through application callbacks."""

    update_inclusion: UpdateBenchmarkInclusion
    get_overview: GetBenchmarkOverview
    export_dataset: ExportBenchmarkDataset
    max_dataset_upload_bytes: int
    import_dataset: ImportBenchmarkDataset
    get_import: GetBenchmarkImport
    resume_import: ResumeBenchmarkImport
    get_report: GetBenchmarkReport
    run: RunBenchmark
    authorize_administrator: AuthorizeAdministrator
