"""Repository protocol definitions for persistence boundaries."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.domain.benchmarks import (
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkReport,
    BenchmarkReportSummary,
)
from app.domain.poker import CanonicalState
from app.domain.hands import JobRecord


class JobRepository(Protocol):
    def create_job(
        self,
        original_filename: str,
        image_bytes: bytes,
        parser_provider: str,
        parser_layout_profile: str | None = ...,
        job_id: str | None = ...,
        upload_request_id: str | None = ...,
    ) -> JobRecord: ...

    def create_benchmark_import_job(
        self,
        *,
        job_id: str,
        original_filename: str,
        image_bytes: bytes,
        parser_provider: str,
        approved_state: CanonicalState,
        import_request_id: str,
        parser_layout_profile: str | None = ...,
    ) -> JobRecord: ...

    def write_image(self, job: JobRecord, image_bytes: bytes) -> None: ...

    def image_path(self, job: JobRecord) -> Path: ...

    def get(self, job_id: str) -> JobRecord: ...

    def list(self) -> list[JobRecord]: ...

    def save(self, job: JobRecord) -> JobRecord: ...

    def restore(self, job: JobRecord, image_bytes: bytes) -> JobRecord: ...

    def delete(self, job_id: str) -> None: ...


class BenchmarkRepository(Protocol):
    def get_latest(self) -> BenchmarkReport | None: ...

    def get(self, report_id: str) -> BenchmarkReport: ...

    def list(self, limit: int | None = ...) -> list[BenchmarkReport]: ...

    def list_summaries(
        self,
        limit: int | None = ...,
        *,
        parser_provider: str | None = ...,
        layout_profile: str | None = ...,
    ) -> list[BenchmarkReportSummary]: ...

    def find_previous_comparable_summary(
        self,
        latest: BenchmarkReportSummary,
    ) -> BenchmarkReportSummary | None: ...

    def save(self, report: BenchmarkReport) -> BenchmarkReport: ...

    def restore(self, report: BenchmarkReport) -> BenchmarkReport: ...

    def delete(self, report_id: str) -> None: ...

    def refresh_latest(self) -> None: ...

    def get_import(self, request_id: str) -> BenchmarkDatasetImportReceipt: ...

    def has_pending_import(self) -> bool: ...

    def begin_import(self, request_id: str, archive_bytes: bytes) -> BenchmarkDatasetImportReceipt: ...

    def complete_import(
        self,
        request_id: str,
        result: BenchmarkDatasetImportResult,
    ) -> BenchmarkDatasetImportReceipt: ...

    def fail_import(
        self,
        request_id: str,
        error: str,
        status_code: int,
    ) -> BenchmarkDatasetImportReceipt: ...

    def get_import_archive(self, request_id: str) -> bytes: ...
