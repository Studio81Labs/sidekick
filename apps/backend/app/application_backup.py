import json
import lzma
import zlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Literal, Self
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError
from pydantic import (
    BaseModel,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from app.dataset_export import MAX_DATASET_CASES
from app.domain.hands import JobRecord
from app.models import ApplicationBackupRestoreResult, BenchmarkReport
from app.storage import (
    FileBenchmarkStore,
    FileJobStore,
    JobNotFoundError,
    load_persisted_job_record,
)


BACKUP_SCHEMA = "poker-hero-application-backup"
BACKUP_SCHEMA_VERSION = 1
BACKUP_ARCHIVE_MEMORY_LIMIT = 8 * 1024 * 1024
BACKUP_ARCHIVE_SIZE_RESERVE_BYTES = 64 * 1024
BACKUP_STREAM_CHUNK_SIZE = 1024 * 1024
MAX_BACKUP_ENTRIES = 20_000
MAX_BACKUP_JOBS = 5_000
MAX_BACKUP_REPORTS = 5_000
MAX_BACKUP_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_BACKUP_RECORD_BYTES = 2 * 1024 * 1024
MAX_BACKUP_REPORT_BYTES = 4 * 1024 * 1024
MAX_BACKUP_EXPANSION_RATIO = 4
SUPPORTED_IMAGE_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}


class ApplicationBackupError(RuntimeError):
    status_code = 400


class ApplicationBackupConflictError(ApplicationBackupError):
    status_code = 409


class ApplicationBackupExportError(ApplicationBackupError):
    status_code = 409


class _BackupJobManifest(BaseModel):
    job_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    record_file: str = Field(min_length=1, max_length=512)
    record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_file: str = Field(min_length=1, max_length=512)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_size: int = Field(ge=1, strict=True)


class _BackupReportManifest(BaseModel):
    report_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    report_file: str = Field(min_length=1, max_length=512)
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class _ApplicationBackupManifest(BaseModel):
    schema_name: Literal[BACKUP_SCHEMA] = Field(alias="schema")
    schema_version: Literal[BACKUP_SCHEMA_VERSION]
    exported_at: datetime
    job_count: int = Field(ge=0, le=MAX_BACKUP_JOBS, strict=True)
    benchmark_report_count: int = Field(
        ge=0,
        le=MAX_BACKUP_REPORTS,
        strict=True,
    )
    jobs: list[_BackupJobManifest] = Field(max_length=MAX_BACKUP_JOBS)
    benchmark_reports: list[_BackupReportManifest] = Field(
        max_length=MAX_BACKUP_REPORTS
    )

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, value: object) -> object:
        if type(value) is not int:
            raise ValueError("Schema version must be a JSON integer")
        return value

    @model_validator(mode="after")
    def validate_entries(self) -> Self:
        if self.job_count != len(self.jobs):
            raise ValueError("job_count does not match jobs")
        if self.benchmark_report_count != len(self.benchmark_reports):
            raise ValueError(
                "benchmark_report_count does not match benchmark_reports"
            )
        job_ids = [job.job_id for job in self.jobs]
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("job IDs must be unique")
        report_ids = [report.report_id for report in self.benchmark_reports]
        if len(report_ids) != len(set(report_ids)):
            raise ValueError("benchmark report IDs must be unique")
        member_paths = [
            *(job.record_file for job in self.jobs),
            *(job.image_file for job in self.jobs),
            *(report.report_file for report in self.benchmark_reports),
        ]
        if len(member_paths) != len(set(member_paths)):
            raise ValueError("archive member paths must be unique")
        return self


@dataclass(frozen=True)
class ParsedApplicationBackup:
    jobs: tuple[tuple[JobRecord, bytes], ...]
    benchmark_reports: tuple[BenchmarkReport, ...]


def application_backup_limit_message(limit: int) -> str:
    return f"Application backup exceeds the configured {limit}-byte archive limit"


def build_application_backup_archive(
    *,
    jobs: list[JobRecord],
    benchmark_reports: list[BenchmarkReport],
    image_path_for: Callable[[JobRecord], Path],
    max_archive_bytes: int,
    max_image_bytes: int,
) -> BinaryIO:
    if len(jobs) > MAX_BACKUP_JOBS:
        raise ApplicationBackupExportError(
            f"Application backups support at most {MAX_BACKUP_JOBS} jobs"
        )
    if len(benchmark_reports) > MAX_BACKUP_REPORTS:
        raise ApplicationBackupExportError(
            "Application backups support at most "
            f"{MAX_BACKUP_REPORTS} benchmark reports"
        )
    if max_archive_bytes <= 0:
        raise ApplicationBackupExportError(
            application_backup_limit_message(max_archive_bytes)
        )

    sorted_jobs = sorted(jobs, key=lambda job: (job.created_at, job.id))
    sorted_reports = sorted(
        benchmark_reports,
        key=lambda report: (report.created_at, report.id),
    )
    if any(job.status == "created" or job.recommendation_pending for job in sorted_jobs):
        raise ApplicationBackupExportError(
            "Wait for active parsing and recommendations before creating a backup"
        )

    archive_file = SpooledTemporaryFile(
        max_size=BACKUP_ARCHIVE_MEMORY_LIMIT,
        mode="w+b",
    )
    output_limit = _archive_output_limit(max_archive_bytes)
    try:
        job_entries: list[
            tuple[JobRecord, Path, bytes, _BackupJobManifest]
        ] = []
        uncompressed_size = 0
        for job in sorted_jobs:
            image_path = _validated_job_image_path(job, image_path_for)
            try:
                image_size = image_path.stat().st_size
                image_digest = _hash_file(image_path)
            except OSError as exc:
                raise ApplicationBackupExportError(
                    f"Image is unavailable for {job.original_filename}"
                ) from exc
            if image_size <= 0:
                raise ApplicationBackupExportError(
                    f"Image is unavailable for {job.original_filename}"
                )
            if image_size > max_image_bytes:
                raise ApplicationBackupExportError(
                    f"Image exceeds the allowed size: {job.original_filename}"
                )
            record_bytes = _json_bytes(job)
            if len(record_bytes) > MAX_BACKUP_RECORD_BYTES:
                raise ApplicationBackupExportError(
                    f"Job record is too large for {job.original_filename}"
                )
            record_file = f"jobs/{job.id}/job.json"
            image_file = f"jobs/{job.id}/{job.image_filename}"
            entry = _BackupJobManifest(
                job_id=job.id,
                record_file=record_file,
                record_sha256=sha256(record_bytes).hexdigest(),
                image_file=image_file,
                image_sha256=image_digest,
                image_size=image_size,
            )
            uncompressed_size += len(record_bytes) + image_size
            job_entries.append((job, image_path, record_bytes, entry))

        report_entries: list[
            tuple[bytes, _BackupReportManifest]
        ] = []
        for report in sorted_reports:
            report_bytes = _json_bytes(report)
            if len(report_bytes) > MAX_BACKUP_REPORT_BYTES:
                raise ApplicationBackupExportError(
                    f"Benchmark report {report.id} is too large"
                )
            entry = _BackupReportManifest(
                report_id=report.id,
                report_file=f"benchmarks/{report.id}.json",
                report_sha256=sha256(report_bytes).hexdigest(),
            )
            uncompressed_size += len(report_bytes)
            report_entries.append((report_bytes, entry))

        manifest = {
            "schema": BACKUP_SCHEMA,
            "schema_version": BACKUP_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "job_count": len(job_entries),
            "benchmark_report_count": len(report_entries),
            "jobs": [entry.model_dump(mode="json") for *_, entry in job_entries],
            "benchmark_reports": [
                entry.model_dump(mode="json") for _, entry in report_entries
            ],
        }
        manifest_bytes = (
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
        ).encode()
        if len(manifest_bytes) > MAX_BACKUP_MANIFEST_BYTES:
            raise ApplicationBackupExportError(
                "Application backup manifest exceeds the allowed size"
            )
        uncompressed_size += len(manifest_bytes)
        if uncompressed_size > max_archive_bytes * MAX_BACKUP_EXPANSION_RATIO:
            raise ApplicationBackupExportError(
                application_backup_limit_message(max_archive_bytes)
            )

        with ZipFile(archive_file, mode="w", compression=ZIP_DEFLATED) as archive:
            for _, image_path, record_bytes, entry in job_entries:
                archive.writestr(entry.record_file, record_bytes)
                archive.write(image_path, arcname=entry.image_file)
                _ensure_archive_size(archive_file, output_limit, max_archive_bytes)
            for report_bytes, entry in report_entries:
                archive.writestr(entry.report_file, report_bytes)
                _ensure_archive_size(archive_file, output_limit, max_archive_bytes)
            archive.writestr("manifest.json", manifest_bytes)
            _ensure_archive_size(archive_file, output_limit, max_archive_bytes)

        _ensure_archive_size(archive_file, output_limit, max_archive_bytes)
        archive_file.seek(0)
        return archive_file
    except Exception:
        archive_file.close()
        raise


def parse_application_backup_archive(
    archive_bytes: bytes,
    *,
    max_image_bytes: int,
    max_uncompressed_bytes: int,
) -> ParsedApplicationBackup:
    if not archive_bytes:
        raise ApplicationBackupError("Application backup ZIP is empty")
    try:
        with ZipFile(BytesIO(archive_bytes)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_BACKUP_ENTRIES:
                raise ApplicationBackupError(
                    "Application backup contains too many files"
                )
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ApplicationBackupError(
                    "Application backup contains duplicate paths"
                )
            if any(info.is_dir() for info in infos):
                raise ApplicationBackupError(
                    "Application backup must not contain directory entries"
                )
            if any(info.flag_bits & 0x1 for info in infos):
                raise ApplicationBackupError(
                    "Encrypted application backups are not supported"
                )
            if sum(info.file_size for info in infos) > max_uncompressed_bytes:
                raise ApplicationBackupError(
                    "Application backup expands beyond the allowed size"
                )
            try:
                manifest_info = archive.getinfo("manifest.json")
            except KeyError as exc:
                raise ApplicationBackupError(
                    "Application backup is missing manifest.json"
                ) from exc
            if manifest_info.file_size > MAX_BACKUP_MANIFEST_BYTES:
                raise ApplicationBackupError(
                    "Application backup manifest exceeds the allowed size"
                )
            try:
                manifest = _ApplicationBackupManifest.model_validate_json(
                    _read_archive_member(archive, manifest_info)
                )
            except ValidationError as exc:
                first_error = exc.errors(include_url=False)[0]
                location = ".".join(str(part) for part in first_error["loc"])
                raise ApplicationBackupError(
                    "Application backup manifest is invalid at "
                    f"{location}: {first_error['msg']}"
                ) from exc
            _require_timezone_aware(
                manifest.exported_at,
                "manifest exported_at",
            )

            expected_paths = {
                "manifest.json",
                *(job.record_file for job in manifest.jobs),
                *(job.image_file for job in manifest.jobs),
                *(report.report_file for report in manifest.benchmark_reports),
            }
            if set(names) != expected_paths:
                raise ApplicationBackupError(
                    "Application backup contains missing or unexpected files"
                )

            jobs = tuple(
                _read_backup_job(archive, entry, max_image_bytes)
                for entry in manifest.jobs
            )
            reports = tuple(
                _read_backup_report(archive, entry)
                for entry in manifest.benchmark_reports
            )
            job_ids = {job.id for job, _ in jobs}
            for report in reports:
                if any(case.job_id not in job_ids for case in report.cases):
                    raise ApplicationBackupError(
                        f"Benchmark report {report.id} references an unknown job"
                    )
            return ParsedApplicationBackup(
                jobs=jobs,
                benchmark_reports=reports,
            )
    except BadZipFile as exc:
        raise ApplicationBackupError(
            "Upload must be a valid application backup ZIP"
        ) from exc


def restore_application_backup(
    backup: ParsedApplicationBackup,
    *,
    job_store: FileJobStore,
    benchmark_store: FileBenchmarkStore,
) -> ApplicationBackupRestoreResult:
    current_jobs = {job.id: job for job in job_store.list()}
    current_reports = {
        report.id: report for report in benchmark_store.list(limit=None)
    }
    resulting_job_ids = current_jobs.keys() | {
        job.id for job, _ in backup.jobs
    }
    if len(resulting_job_ids) > MAX_BACKUP_JOBS:
        raise ApplicationBackupConflictError(
            f"Application backups support at most {MAX_BACKUP_JOBS} jobs"
        )
    resulting_report_ids = current_reports.keys() | {
        report.id for report in backup.benchmark_reports
    }
    if len(resulting_report_ids) > MAX_BACKUP_REPORTS:
        raise ApplicationBackupConflictError(
            "Application backups support at most "
            f"{MAX_BACKUP_REPORTS} benchmark reports"
        )
    included_job_ids = {
        job.id for job in current_jobs.values() if job.benchmark_included
    } | {
        job.id for job, _ in backup.jobs if job.benchmark_included
    }
    if len(included_job_ids) > MAX_DATASET_CASES:
        raise ApplicationBackupConflictError(
            "Restoring this backup would exceed the parser benchmark "
            f"limit of {MAX_DATASET_CASES} hands"
        )
    jobs_to_import: list[tuple[JobRecord, bytes]] = []
    reused_jobs = 0
    for job, image_bytes in backup.jobs:
        existing = current_jobs.get(job.id)
        if existing is None:
            jobs_to_import.append((job, image_bytes))
            continue
        try:
            existing_image_path = job_store.image_path(existing)
            existing_image_size = existing_image_path.stat().st_size
            existing_image_digest = _hash_file(existing_image_path)
        except (JobNotFoundError, OSError) as exc:
            raise ApplicationBackupConflictError(
                f"Existing job {job.id} does not have its source image"
            ) from exc
        if (
            existing != job
            or existing_image_size != len(image_bytes)
            or existing_image_digest != sha256(image_bytes).hexdigest()
        ):
            raise ApplicationBackupConflictError(
                f"Backup job {job.id} conflicts with existing data"
            )
        reused_jobs += 1

    reports_to_import: list[BenchmarkReport] = []
    reused_reports = 0
    for report in backup.benchmark_reports:
        existing = current_reports.get(report.id)
        if existing is None:
            reports_to_import.append(report)
            continue
        if existing != report:
            raise ApplicationBackupConflictError(
                f"Backup report {report.id} conflicts with existing data"
            )
        reused_reports += 1

    imported_job_ids: list[str] = []
    imported_report_ids: list[str] = []
    try:
        for job, image_bytes in jobs_to_import:
            job_store.restore(job, image_bytes)
            imported_job_ids.append(job.id)
        for report in reports_to_import:
            benchmark_store.restore(report)
            imported_report_ids.append(report.id)
        benchmark_store.refresh_latest()
    except (FileExistsError, OSError) as exc:
        for report_id in reversed(imported_report_ids):
            benchmark_store.delete(report_id)
        for job_id in reversed(imported_job_ids):
            job_store.delete(job_id)
        benchmark_store.refresh_latest()
        raise ApplicationBackupConflictError(
            "Application backup could not be restored without changing existing data"
        ) from exc

    return ApplicationBackupRestoreResult(
        imported_jobs=len(imported_job_ids),
        reused_jobs=reused_jobs,
        imported_benchmark_reports=len(imported_report_ids),
        reused_benchmark_reports=reused_reports,
        total_jobs=len(current_jobs) + len(imported_job_ids),
        total_benchmark_reports=len(current_reports) + len(imported_report_ids),
    )


def stream_application_backup(archive_file: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := archive_file.read(BACKUP_STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        archive_file.close()


def _read_backup_job(
    archive: ZipFile,
    entry: _BackupJobManifest,
    max_image_bytes: int,
) -> tuple[JobRecord, bytes]:
    expected_record_file = f"jobs/{entry.job_id}/job.json"
    if entry.record_file != expected_record_file:
        raise ApplicationBackupError(
            f"Application backup record path is invalid for job {entry.job_id}"
        )
    record_info = _member_info(
        archive,
        entry.record_file,
        MAX_BACKUP_RECORD_BYTES,
        "job record",
    )
    record_bytes = _read_archive_member(archive, record_info)
    if sha256(record_bytes).hexdigest() != entry.record_sha256:
        raise ApplicationBackupError(
            f"Application backup checksum failed for job {entry.job_id}"
        )
    try:
        job = load_persisted_job_record(record_bytes)
    except ValidationError as exc:
        raise ApplicationBackupError(
            f"Application backup job {entry.job_id} is invalid"
        ) from exc
    if job.id != entry.job_id:
        raise ApplicationBackupError(
            f"Application backup job ID does not match {entry.job_id}"
        )
    if job.status == "created" or job.recommendation_pending:
        raise ApplicationBackupError(
            f"Application backup job {entry.job_id} contains an active operation"
        )
    _validate_job_timestamps(job)
    if not _is_plain_filename(job.image_filename):
        raise ApplicationBackupError(
            f"Application backup image filename is invalid for job {entry.job_id}"
        )
    expected_image_file = f"jobs/{entry.job_id}/{job.image_filename}"
    if entry.image_file != expected_image_file:
        raise ApplicationBackupError(
            f"Application backup image path is invalid for job {entry.job_id}"
        )
    image_info = _member_info(
        archive,
        entry.image_file,
        max_image_bytes,
        "job image",
    )
    if image_info.file_size != entry.image_size:
        raise ApplicationBackupError(
            f"Application backup image size does not match for job {entry.job_id}"
        )
    image_bytes = _read_archive_member(archive, image_info)
    if sha256(image_bytes).hexdigest() != entry.image_sha256:
        raise ApplicationBackupError(
            f"Application backup image checksum failed for job {entry.job_id}"
        )
    if not _is_supported_image(image_bytes):
        raise ApplicationBackupError(
            f"Application backup image is invalid for job {entry.job_id}"
        )
    return job, image_bytes


def _read_backup_report(
    archive: ZipFile,
    entry: _BackupReportManifest,
) -> BenchmarkReport:
    expected_report_file = f"benchmarks/{entry.report_id}.json"
    if entry.report_file != expected_report_file:
        raise ApplicationBackupError(
            "Application backup report path is invalid for "
            f"{entry.report_id}"
        )
    report_info = _member_info(
        archive,
        entry.report_file,
        MAX_BACKUP_REPORT_BYTES,
        "benchmark report",
    )
    report_bytes = _read_archive_member(archive, report_info)
    if sha256(report_bytes).hexdigest() != entry.report_sha256:
        raise ApplicationBackupError(
            f"Application backup checksum failed for report {entry.report_id}"
        )
    try:
        report = BenchmarkReport.model_validate_json(report_bytes)
    except ValidationError as exc:
        raise ApplicationBackupError(
            f"Application backup report {entry.report_id} is invalid"
        ) from exc
    if report.id != entry.report_id:
        raise ApplicationBackupError(
            f"Application backup report ID does not match {entry.report_id}"
        )
    _require_timezone_aware(
        report.created_at,
        f"report {entry.report_id} created_at",
    )
    return report


def _member_info(
    archive: ZipFile,
    member_name: str,
    size_limit: int,
    label: str,
) -> ZipInfo:
    if not _is_safe_archive_path(member_name):
        raise ApplicationBackupError(
            f"Application backup {label} path is invalid"
        )
    try:
        info = archive.getinfo(member_name)
    except KeyError as exc:
        raise ApplicationBackupError(
            f"Application backup is missing {label}: {member_name}"
        ) from exc
    if info.file_size > size_limit:
        raise ApplicationBackupError(
            f"Application backup {label} exceeds the allowed size"
        )
    return info


def _read_archive_member(archive: ZipFile, info: ZipInfo) -> bytes:
    try:
        return archive.read(info)
    except (NotImplementedError, RuntimeError) as exc:
        raise ApplicationBackupError(
            "Application backup uses an unsupported compression method"
        ) from exc
    except (
        BadZipFile,
        EOFError,
        OSError,
        lzma.LZMAError,
        zlib.error,
    ) as exc:
        raise ApplicationBackupError(
            f"Application backup entry could not be read: {info.filename}"
        ) from exc


def _archive_output_limit(max_archive_bytes: int) -> int:
    reserve = min(
        BACKUP_ARCHIVE_SIZE_RESERVE_BYTES,
        max_archive_bytes // 100,
    )
    return max_archive_bytes - reserve


def _ensure_archive_size(
    archive_file: BinaryIO,
    output_limit: int,
    max_archive_bytes: int,
) -> None:
    if archive_file.tell() > output_limit:
        raise ApplicationBackupExportError(
            application_backup_limit_message(max_archive_bytes)
        )


def _validated_job_image_path(
    job: JobRecord,
    image_path_for: Callable[[JobRecord], Path],
) -> Path:
    if not _is_plain_filename(job.image_filename):
        raise ApplicationBackupExportError(
            f"Image filename is invalid for {job.original_filename}"
        )
    try:
        image_path = image_path_for(job)
    except (KeyError, OSError, ValueError) as exc:
        raise ApplicationBackupExportError(
            f"Image is unavailable for {job.original_filename}"
        ) from exc
    if not image_path.is_file():
        raise ApplicationBackupExportError(
            f"Image is unavailable for {job.original_filename}"
        )
    try:
        with Image.open(image_path) as image:
            image_format = image.format
            image.verify()
    except (
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        raise ApplicationBackupExportError(
            f"Image is invalid for {job.original_filename}"
        ) from exc
    if image_format not in SUPPORTED_IMAGE_FORMATS:
        raise ApplicationBackupExportError(
            f"Image is invalid for {job.original_filename}"
        )
    return image_path


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as file:
        while chunk := file.read(BACKUP_STREAM_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(model: BaseModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode()


def _is_plain_filename(value: str) -> bool:
    return bool(value) and PurePosixPath(value).name == value and "\\" not in value


def _is_safe_archive_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and "\\" not in value
        and path.as_posix() == value
    )


def _is_supported_image(image_bytes: bytes) -> bool:
    if not image_bytes:
        return False
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image_format = image.format
            image.verify()
            return image_format in SUPPORTED_IMAGE_FORMATS
    except (
        Image.DecompressionBombError,
        OSError,
        SyntaxError,
        UnidentifiedImageError,
        ValueError,
    ):
        return False


def _validate_job_timestamps(job: JobRecord) -> None:
    timestamps = (
        ("created_at", job.created_at),
        ("updated_at", job.updated_at),
        ("training_reviewed_at", job.training_reviewed_at),
        ("archived_at", job.archived_at),
        (
            "training_decision.recorded_at",
            job.training_decision.recorded_at if job.training_decision else None,
        ),
    )
    for field_name, value in timestamps:
        if value is not None:
            _require_timezone_aware(
                value,
                f"job {job.id} {field_name}",
            )


def _require_timezone_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ApplicationBackupError(
            f"Application backup {label} must include a timezone"
        )
