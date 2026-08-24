from __future__ import annotations

import os
import re
import shutil
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

import ijson
from pydantic import TypeAdapter, ValidationError

from app.domain.poker import CanonicalState
from app.domain.benchmarks import (
    BENCHMARK_IMPORT_REQUEST_ID_PATTERN,
    BenchmarkDatasetImportReceipt,
    BenchmarkDatasetImportResult,
    BenchmarkReport,
    BenchmarkReportSummary,
)
from app.domain.hands import JobRecord

JOB_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
BENCHMARK_ID_PATTERN = JOB_ID_PATTERN
BENCHMARK_SUMMARY_SUFFIX = ".summary.json"
BENCHMARK_SUMMARY_SCALAR_FIELDS = frozenset({
    "id",
    "parser_provider",
    "layout_profile",
    "created_at",
    "total_cases",
    "failed_cases",
    "accuracy",
})
BENCHMARK_SUMMARY_OPTIONAL_SCALAR_FIELDS = frozenset({"corpus_fingerprint"})
BENCHMARK_SUMMARY_METADATA_FIELDS = (
    BENCHMARK_SUMMARY_SCALAR_FIELDS | BENCHMARK_SUMMARY_OPTIONAL_SCALAR_FIELDS
)
BENCHMARK_IMPORT_REQUEST_ID_RE = re.compile(BENCHMARK_IMPORT_REQUEST_ID_PATTERN)
JOB_RECORD_PAYLOAD_ADAPTER = TypeAdapter(dict[str, Any])
LEGACY_ACTIONS_WITHOUT_SIZING = frozenset({"fold", "check", "call"})
LEGACY_WAGER_ACTIONS = frozenset({"bet", "raise"})
DATA_VOLUME_MARKER_FILENAME = ".poker-hero-data-volume"
DATA_VOLUME_MARKER_PREFIX = "poker-hero-data-volume-v1:"


class DataVolumeError(RuntimeError):
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


def _normalize_legacy_action_sizing(
    value: Any,
    *,
    normalize_non_wager: bool,
) -> None:
    if not isinstance(value, dict):
        return
    action = value.get("action")
    sizing = value.get("sizing")
    if action in LEGACY_WAGER_ACTIONS and sizing == 0:
        value["sizing"] = None
    elif (
        normalize_non_wager
        and action in LEGACY_ACTIONS_WITHOUT_SIZING
        and sizing is not None
    ):
        value["sizing"] = None


def load_persisted_job_record(payload: str | bytes) -> JobRecord:
    values = JOB_RECORD_PAYLOAD_ADAPTER.validate_json(payload)
    _normalize_legacy_action_sizing(
        values.get("recommendation"),
        normalize_non_wager=True,
    )
    _normalize_legacy_action_sizing(
        values.get("training_decision"),
        normalize_non_wager=False,
    )
    return JobRecord.model_validate(values)


class JobNotFoundError(KeyError):
    pass


class BenchmarkNotFoundError(KeyError):
    pass


class BenchmarkImportNotFoundError(KeyError):
    pass


class FileJobStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.jobs_dir = (self.data_dir / "jobs").resolve()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def create_job(
        self,
        original_filename: str,
        image_bytes: bytes,
        parser_provider: str,
        recommendation_provider: str,
        parser_layout_profile: str | None = None,
        recommendation_engine: str | None = None,
        job_id: str | None = None,
        upload_request_id: str | None = None,
    ) -> JobRecord:
        image_suffix = Path(original_filename).suffix or ".png"
        job_values = {
            "original_filename": original_filename,
            "image_filename": f"original{image_suffix}",
            "parser_provider": parser_provider,
            "parser_layout_profile": parser_layout_profile,
            "recommendation_provider": recommendation_provider,
            "recommendation_engine": recommendation_engine,
            "upload_request_id": upload_request_id,
        }
        if job_id is not None:
            job_values["id"] = job_id
        job = JobRecord.model_validate(job_values)
        job_dir = self._job_dir(job.id)
        job_dir.mkdir(parents=True, exist_ok=False)
        self.image_path(job).write_bytes(image_bytes)
        self.save(job)
        return job

    def create_benchmark_import_job(
        self,
        *,
        job_id: str,
        original_filename: str,
        image_bytes: bytes,
        parser_provider: str,
        recommendation_provider: str,
        parser_layout_profile: str | None = None,
        recommendation_engine: str | None = None,
        approved_state: CanonicalState,
        import_request_id: str,
    ) -> JobRecord:
        image_suffix = Path(original_filename).suffix or ".png"
        job = JobRecord(
            id=job_id,
            status="approved",
            original_filename=original_filename,
            image_filename=f"original{image_suffix}",
            parser_provider=parser_provider,
            parser_layout_profile=parser_layout_profile,
            recommendation_provider=recommendation_provider,
            recommendation_engine=recommendation_engine,
            approved_state=approved_state,
            benchmark_included=True,
            benchmark_import_request_id=import_request_id,
        )
        job_dir = self._job_dir(job.id)
        job_dir.mkdir(parents=True, exist_ok=True)
        if self._job_path(job.id).exists():
            raise FileExistsError(job.id)
        self.save(job)
        self.write_image(job, image_bytes)
        return job

    def write_image(self, job: JobRecord, image_bytes: bytes) -> None:
        self._atomic_write_bytes(self.image_path(job), image_bytes)

    def image_path(self, job: JobRecord) -> Path:
        job_dir = self._job_dir(job.id)
        return self._resolve_under(job_dir, job_dir / job.image_filename)

    def get(self, job_id: str) -> JobRecord:
        path = self._job_path(job_id)
        if not path.exists():
            raise JobNotFoundError(job_id)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise JobNotFoundError(job_id) from exc
        return load_persisted_job_record(payload)

    def list(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for path in self.jobs_dir.glob("*/job.json"):
            try:
                payload = path.read_bytes()
            except FileNotFoundError:
                # A concurrent delete may remove a job after the directory scan.
                continue
            jobs.append(load_persisted_job_record(payload))
        return sorted(jobs, key=lambda job: job.created_at)

    def save(self, job: JobRecord) -> JobRecord:
        job.touch()
        path = self._job_path(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=path.parent,
                encoding="utf-8",
                prefix="job.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(job.model_dump_json(indent=2))
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
        return job

    def restore(self, job: JobRecord, image_bytes: bytes) -> JobRecord:
        job_dir = self._job_dir(job.id)
        if job_dir.exists():
            raise FileExistsError(job.id)
        if (
            not job.image_filename
            or Path(job.image_filename).name != job.image_filename
            or "\\" in job.image_filename
        ):
            raise ValueError("job image filename must not contain a path")
        temp_dir = Path(tempfile.mkdtemp(
            dir=self.jobs_dir,
            prefix=".backup-restore.",
        ))
        try:
            self._write_file(
                temp_dir / job.image_filename,
                image_bytes,
            )
            self._write_file(
                temp_dir / "job.json",
                job.model_dump_json(indent=2).encode(),
            )
            os.replace(temp_dir, job_dir)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        return job

    def delete(self, job_id: str) -> None:
        job_dir = self._job_dir(job_id)
        if not self._job_path(job_id).is_file():
            raise JobNotFoundError(job_id)
        try:
            shutil.rmtree(job_dir)
            _fsync_directory(self.jobs_dir)
        except FileNotFoundError as exc:
            raise JobNotFoundError(job_id) from exc

    def _job_dir(self, job_id: str) -> Path:
        self._validate_job_id(job_id)
        return self._resolve_under(self.jobs_dir, self.jobs_dir / job_id)

    def _job_path(self, job_id: str) -> Path:
        return self._resolve_under(self.jobs_dir, self._job_dir(job_id) / "job.json")

    def _validate_job_id(self, job_id: str) -> None:
        if JOB_ID_PATTERN.fullmatch(job_id) is None:
            raise JobNotFoundError(job_id)

    def _resolve_under(self, base_dir: Path, candidate: Path) -> Path:
        base = base_dir.resolve()
        path = candidate.resolve(strict=False)
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise JobNotFoundError(str(candidate)) from exc
        return path

    def _atomic_write_bytes(self, path: Path, payload: bytes) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=path.parent,
                prefix="image.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()

    def _write_file(self, path: Path, payload: bytes) -> None:
        with path.open("xb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())


class FileBenchmarkStore:
    def __init__(self, data_dir: Path) -> None:
        self.benchmarks_dir = (data_dir / "benchmarks").resolve()
        self.benchmarks_dir.mkdir(parents=True, exist_ok=True)
        self.imports_dir = (self.benchmarks_dir / "imports").resolve()
        self.imports_dir.mkdir(parents=True, exist_ok=True)

    def get_latest(self) -> BenchmarkReport | None:
        path = self.benchmarks_dir / "latest.json"
        if not path.exists():
            return None
        return BenchmarkReport.model_validate_json(path.read_text())

    def get(self, report_id: str) -> BenchmarkReport:
        path = self._report_path(report_id)
        if not path.exists():
            raise BenchmarkNotFoundError(report_id)
        return BenchmarkReport.model_validate_json(path.read_text())

    def list(self, limit: int | None = 10) -> list[BenchmarkReport]:
        if limit is not None and limit <= 0:
            return []

        report_paths = sorted(
            (
                path
                for path in self.benchmarks_dir.glob("*.json")
                if BENCHMARK_ID_PATTERN.fullmatch(path.stem) is not None
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if limit is not None:
            report_paths = report_paths[:limit]
        reports = [
            BenchmarkReport.model_validate_json(path.read_text())
            for path in report_paths
        ]
        return sorted(reports, key=lambda report: report.created_at, reverse=True)

    def list_summaries(
        self,
        limit: int | None = 10,
        *,
        parser_provider: str | None = None,
        layout_profile: str | None = None,
    ) -> list[BenchmarkReportSummary]:
        if limit is not None and limit <= 0:
            return []

        summaries = self._list_report_summaries(
            parser_provider=parser_provider,
            layout_profile=layout_profile,
        )
        summaries.sort(
            key=lambda summary: (summary.created_at, summary.id),
            reverse=True,
        )
        if limit is None:
            matching_limit = None
            modified_since_ns = None
        elif len(summaries) < limit:
            matching_limit = limit - len(summaries)
            modified_since_ns = None
        else:
            matching_limit = None
            modified_since_ns = int(
                summaries[limit - 1].created_at.timestamp() * 1_000_000_000
            )

        if matching_limit != 0:
            self._backfill_report_summaries(
                parser_provider=parser_provider,
                layout_profile=layout_profile,
                matching_limit=matching_limit,
                modified_since_ns=modified_since_ns,
            )
            summaries = self._list_report_summaries(
                parser_provider=parser_provider,
                layout_profile=layout_profile,
            )
        summaries.sort(
            key=lambda summary: (summary.created_at, summary.id),
            reverse=True,
        )
        return summaries[:limit] if limit is not None else summaries

    def find_previous_comparable_summary(
        self,
        latest: BenchmarkReportSummary,
    ) -> BenchmarkReportSummary | None:
        if latest.corpus_fingerprint is None:
            return None
        latest_key = (latest.created_at, latest.id)
        previous: BenchmarkReportSummary | None = None
        for path in self.benchmarks_dir.glob(f"*{BENCHMARK_SUMMARY_SUFFIX}"):
            report_id = path.name.removesuffix(BENCHMARK_SUMMARY_SUFFIX)
            if (
                BENCHMARK_ID_PATTERN.fullmatch(report_id) is None
                or not self._report_path(report_id).exists()
            ):
                continue
            summary = self._read_report_summary(report_id, path)
            if (
                summary.parser_provider != latest.parser_provider
                or summary.layout_profile != latest.layout_profile
                or summary.corpus_fingerprint != latest.corpus_fingerprint
                or (summary.created_at, summary.id) >= latest_key
            ):
                continue
            if previous is None or (
                summary.created_at,
                summary.id,
            ) > (
                previous.created_at,
                previous.id,
            ):
                previous = summary
        for path in self.benchmarks_dir.glob("*.json"):
            if (
                BENCHMARK_ID_PATTERN.fullmatch(path.stem) is None
                or self._report_summary_path(path.stem).exists()
            ):
                continue
            summary = self._read_report_summary_metadata(path)
            if (
                summary.parser_provider != latest.parser_provider
                or summary.layout_profile != latest.layout_profile
                or summary.corpus_fingerprint != latest.corpus_fingerprint
                or (summary.created_at, summary.id) >= latest_key
            ):
                continue
            if previous is None or (
                summary.created_at,
                summary.id,
            ) > (
                previous.created_at,
                previous.id,
            ):
                previous = summary
        return previous

    def _list_report_summaries(
        self,
        *,
        parser_provider: str | None,
        layout_profile: str | None,
    ) -> list[BenchmarkReportSummary]:
        summaries: list[BenchmarkReportSummary] = []
        for path in self.benchmarks_dir.glob(f"*{BENCHMARK_SUMMARY_SUFFIX}"):
            report_id = path.name.removesuffix(BENCHMARK_SUMMARY_SUFFIX)
            if BENCHMARK_ID_PATTERN.fullmatch(report_id) is None:
                continue
            if not self._report_path(report_id).exists():
                continue
            summary = self._read_report_summary(report_id, path)
            if parser_provider is not None and summary.parser_provider != parser_provider:
                continue
            if layout_profile is not None and summary.layout_profile != layout_profile:
                continue
            summaries.append(summary)
        return summaries

    def save(self, report: BenchmarkReport) -> BenchmarkReport:
        payload = report.model_dump_json(indent=2)
        self._atomic_write(self.benchmarks_dir / f"{report.id}.json", payload)
        self._write_report_summary(report)
        self._atomic_write(self.benchmarks_dir / "latest.json", payload)
        return report

    def restore(self, report: BenchmarkReport) -> BenchmarkReport:
        path = self._report_path(report.id)
        if path.exists():
            raise FileExistsError(report.id)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=path.parent,
                encoding="utf-8",
                prefix=".backup-report.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(report.model_dump_json(indent=2))
                temp_file.flush()
                os.fsync(temp_file.fileno())
            report_timestamp_ns = int(
                report.created_at.timestamp() * 1_000_000_000
            )
            os.utime(
                temp_path,
                ns=(report_timestamp_ns, report_timestamp_ns),
            )
            os.link(temp_path, path)
            try:
                self._write_report_summary(report)
            except OSError:
                path.unlink(missing_ok=True)
                self._report_summary_path(report.id).unlink(missing_ok=True)
                raise
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    # The final hard link may already be published. A hidden
                    # cleanup file is safer than reporting a partial restore.
                    pass
        return report

    def delete(self, report_id: str) -> None:
        self._report_path(report_id).unlink(missing_ok=True)
        self._report_summary_path(report_id).unlink(missing_ok=True)

    def refresh_latest(self) -> None:
        summaries = self.list_summaries(limit=None)
        latest_path = self.benchmarks_dir / "latest.json"
        if not summaries:
            latest_path.unlink(missing_ok=True)
            return
        latest_summary = max(
            summaries,
            key=lambda summary: (summary.created_at, summary.id),
        )
        latest = self.get(latest_summary.id)
        self._atomic_write(latest_path, latest.model_dump_json(indent=2))

    def get_import(self, request_id: str) -> BenchmarkDatasetImportReceipt:
        path = self._import_receipt_path(request_id)
        if not path.exists():
            raise BenchmarkImportNotFoundError(request_id)
        return BenchmarkDatasetImportReceipt.model_validate_json(path.read_text())

    def has_pending_import(self) -> bool:
        for request_dir in self.imports_dir.iterdir():
            if (
                not request_dir.is_dir()
                or BENCHMARK_IMPORT_REQUEST_ID_RE.fullmatch(request_dir.name) is None
            ):
                continue
            try:
                receipt = self.get_import(request_dir.name)
            except BenchmarkImportNotFoundError:
                continue
            if receipt.status == "pending":
                return True
        return False

    def begin_import(
        self,
        request_id: str,
        archive_bytes: bytes,
    ) -> BenchmarkDatasetImportReceipt:
        request_dir = self._import_dir(request_id)
        if request_dir.exists():
            return self.get_import(request_id)
        receipt = BenchmarkDatasetImportReceipt(
            request_id=request_id,
            archive_sha256=sha256(archive_bytes).hexdigest(),
            status="pending",
        )
        temp_dir = Path(tempfile.mkdtemp(
            dir=self.imports_dir,
            prefix=".benchmark-import.",
        ))
        try:
            self._write_file(
                temp_dir / "dataset.zip",
                archive_bytes,
            )
            self._write_file(
                temp_dir / "receipt.json",
                receipt.model_dump_json(indent=2).encode(),
            )
            os.replace(temp_dir, request_dir)
        finally:
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        return receipt

    def complete_import(
        self,
        request_id: str,
        result: BenchmarkDatasetImportResult,
    ) -> BenchmarkDatasetImportReceipt:
        receipt = self.get_import(request_id)
        completed = receipt.model_copy(update={
            "status": "completed",
            "result": result,
        })
        self._atomic_write(
            self._import_receipt_path(request_id),
            completed.model_dump_json(indent=2),
        )
        self._remove_import_archive(request_id)
        return completed

    def fail_import(
        self,
        request_id: str,
        error: str,
        status_code: int,
    ) -> BenchmarkDatasetImportReceipt:
        receipt = self.get_import(request_id)
        failed = receipt.model_copy(update={
            "status": "failed",
            "result": None,
            "error": error,
            "error_status": status_code,
        })
        self._atomic_write(
            self._import_receipt_path(request_id),
            failed.model_dump_json(indent=2),
        )
        self._remove_import_archive(request_id)
        return failed

    def get_import_archive(self, request_id: str) -> bytes:
        path = self._import_archive_path(request_id)
        if not path.exists():
            raise BenchmarkImportNotFoundError(request_id)
        return path.read_bytes()

    def _report_path(self, report_id: str) -> Path:
        if BENCHMARK_ID_PATTERN.fullmatch(report_id) is None:
            raise BenchmarkNotFoundError(report_id)
        return self.benchmarks_dir / f"{report_id}.json"

    def _report_summary_path(self, report_id: str) -> Path:
        if BENCHMARK_ID_PATTERN.fullmatch(report_id) is None:
            raise BenchmarkNotFoundError(report_id)
        return self.benchmarks_dir / f"{report_id}{BENCHMARK_SUMMARY_SUFFIX}"

    def _write_report_summary(self, report: BenchmarkReport) -> None:
        self._write_summary(BenchmarkReportSummary.from_report(report))

    def _write_summary(self, summary: BenchmarkReportSummary) -> None:
        self._atomic_write(
            self._report_summary_path(summary.id),
            summary.model_dump_json(indent=2),
        )

    def _read_report_summary(
        self,
        report_id: str,
        path: Path,
    ) -> BenchmarkReportSummary:
        try:
            summary = BenchmarkReportSummary.model_validate_json(path.read_text())
        except ValidationError:
            summary = None
        if summary is not None and summary.id == report_id:
            return summary

        report = self.get(report_id)
        self._write_report_summary(report)
        return BenchmarkReportSummary.from_report(report)

    def _backfill_report_summaries(
        self,
        *,
        parser_provider: str | None,
        layout_profile: str | None,
        matching_limit: int | None,
        modified_since_ns: int | None,
    ) -> None:
        if matching_limit == 0:
            return
        report_candidates: list[tuple[int, Path]] = []
        for path in self.benchmarks_dir.glob("*.json"):
            if (
                BENCHMARK_ID_PATTERN.fullmatch(path.stem) is None
                or self._report_summary_path(path.stem).exists()
            ):
                continue
            try:
                modified_at_ns = path.stat().st_mtime_ns
            except FileNotFoundError:
                continue
            if (
                modified_since_ns is not None
                and modified_at_ns < modified_since_ns
            ):
                continue
            report_candidates.append((modified_at_ns, path))

        report_candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        matching_count = 0
        for _, report_path in report_candidates:
            summary = self._read_report_summary_metadata(report_path)
            self._write_summary(summary)
            if (
                (parser_provider is None or summary.parser_provider == parser_provider)
                and (layout_profile is None or summary.layout_profile == layout_profile)
            ):
                matching_count += 1
                if (
                    matching_limit is not None
                    and matching_count >= matching_limit
                ):
                    break

    def _read_report_summary_metadata(self, path: Path) -> BenchmarkReportSummary:
        payload: dict[str, Any] = {"field_metrics": []}
        current_metric: dict[str, Any] | None = None
        field_metrics_complete = False
        with path.open("rb") as report_file:
            for prefix, event, value in ijson.parse(report_file):
                if (
                    prefix in BENCHMARK_SUMMARY_METADATA_FIELDS
                    and event in {"string", "number"}
                ):
                    payload[prefix] = value
                elif prefix == "field_metrics.item" and event == "start_map":
                    current_metric = {}
                elif (
                    current_metric is not None
                    and prefix.startswith("field_metrics.item.")
                    and event in {"string", "number"}
                ):
                    current_metric[prefix.removeprefix("field_metrics.item.")] = value
                elif (
                    current_metric is not None
                    and prefix == "field_metrics.item"
                    and event == "end_map"
                ):
                    payload["field_metrics"].append(current_metric)
                    current_metric = None
                elif prefix == "field_metrics" and event == "end_array":
                    field_metrics_complete = True
                elif (
                    prefix == "cases"
                    and event == "start_array"
                    and field_metrics_complete
                    and BENCHMARK_SUMMARY_SCALAR_FIELDS.issubset(payload)
                ):
                    break
        summary = BenchmarkReportSummary.model_validate(payload)
        if summary.id != path.stem:
            raise ValueError("Benchmark report ID does not match its filename")
        return summary

    def _import_dir(self, request_id: str) -> Path:
        if (
            len(request_id) > 128
            or BENCHMARK_IMPORT_REQUEST_ID_RE.fullmatch(request_id) is None
        ):
            raise BenchmarkImportNotFoundError(request_id)
        request_dir = (self.imports_dir / request_id).resolve(strict=False)
        if request_dir.parent != self.imports_dir:
            raise BenchmarkImportNotFoundError(request_id)
        return request_dir

    def _import_receipt_path(self, request_id: str) -> Path:
        return self._import_dir(request_id) / "receipt.json"

    def _import_archive_path(self, request_id: str) -> Path:
        return self._import_dir(request_id) / "dataset.zip"

    def _write_file(self, path: Path, payload: bytes) -> None:
        with path.open("xb") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())

    def _remove_import_archive(self, request_id: str) -> None:
        try:
            self._import_archive_path(request_id).unlink(missing_ok=True)
        except OSError:
            # The terminal receipt remains authoritative if best-effort cleanup fails.
            pass

    def _atomic_write(self, path: Path, payload: str) -> None:
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=path.parent,
                encoding="utf-8",
                prefix="benchmark.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                temp_file.write(payload)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
