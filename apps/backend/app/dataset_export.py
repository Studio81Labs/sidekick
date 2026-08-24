import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import SpooledTemporaryFile
from typing import BinaryIO
from zipfile import ZIP_DEFLATED, ZipFile

from app.domain.poker import CanonicalState
from app.domain.hands import JobRecord


DATASET_SCHEMA = "poker-hero-parser-dataset"
DATASET_SCHEMA_VERSION = 1
MAX_DATASET_CASES = 250
MAX_DATASET_EXPANSION_RATIO = 4
ARCHIVE_MEMORY_LIMIT = 8 * 1024 * 1024
ARCHIVE_SIZE_RESERVE_BYTES = 64 * 1024
STREAM_CHUNK_SIZE = 1024 * 1024


class DatasetExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParserDatasetArchiveCase:
    job_id: str
    original_filename: str
    image_suffix: str
    image_source: Path | bytes
    expected_state: CanonicalState


def dataset_case_limit_message(limit: int) -> str:
    unit = "case" if limit == 1 else "cases"
    return f"Parser datasets support at most {limit} {unit}"


def dataset_archive_limit_message(limit: int) -> str:
    return f"Parser dataset exceeds the configured {limit}-byte archive limit"


def _archive_output_limit(max_archive_bytes: int) -> int:
    reserve = min(ARCHIVE_SIZE_RESERVE_BYTES, max_archive_bytes // 100)
    return max_archive_bytes - reserve


def parser_dataset_archive_case(
    job: JobRecord,
    image_path_for: Callable[[JobRecord], Path],
) -> ParserDatasetArchiveCase:
    if job.approved_state is None or not job.approved_state.user_approved:
        raise DatasetExportError(
            f"{job.original_filename} does not have approved ground truth"
        )
    try:
        image_path = image_path_for(job)
    except (KeyError, OSError, ValueError) as exc:
        raise DatasetExportError(
            f"Image is unavailable for {job.original_filename}"
        ) from exc
    if not image_path.is_file():
        raise DatasetExportError(
            f"Image is unavailable for {job.original_filename}"
        )
    return ParserDatasetArchiveCase(
        job_id=job.id,
        original_filename=job.original_filename,
        image_suffix=image_path.suffix.lower() or ".png",
        image_source=image_path,
        expected_state=job.approved_state,
    )


def build_parser_dataset_archive(
    jobs: list[JobRecord],
    image_path_for: Callable[[JobRecord], Path],
    parser_provider: str,
    layout_profile: str,
    max_archive_bytes: int,
) -> BinaryIO:
    cases = [
        parser_dataset_archive_case(job, image_path_for)
        for job in sorted(
            jobs,
            key=lambda candidate: (candidate.created_at, candidate.id),
        )
    ]
    return build_parser_dataset_archive_from_cases(
        cases,
        parser_provider=parser_provider,
        layout_profile=layout_profile,
        max_archive_bytes=max_archive_bytes,
    )


def build_parser_dataset_archive_from_cases(
    archive_cases: list[ParserDatasetArchiveCase],
    parser_provider: str,
    layout_profile: str,
    max_archive_bytes: int,
) -> BinaryIO:
    if len(archive_cases) > MAX_DATASET_CASES:
        raise DatasetExportError(dataset_case_limit_message(MAX_DATASET_CASES))
    if max_archive_bytes <= 0:
        raise DatasetExportError(dataset_archive_limit_message(max_archive_bytes))
    archive_output_limit = _archive_output_limit(max_archive_bytes)

    archive_file = SpooledTemporaryFile(max_size=ARCHIVE_MEMORY_LIMIT, mode="w+b")
    cases: list[dict[str, object]] = []
    try:
        image_sizes: list[int] = []
        for case in archive_cases:
            try:
                image_sizes.append(
                    case.image_source.stat().st_size
                    if isinstance(case.image_source, Path)
                    else len(case.image_source)
                )
            except OSError as exc:
                raise DatasetExportError(
                    f"Image is unavailable for {case.original_filename}"
                ) from exc

            image_name = f"images/{case.job_id}{case.image_suffix}"
            expected_state = case.expected_state.model_dump(
                mode="json",
                exclude={"user_approved"},
                exclude_none=True,
            )
            for history_field in (
                "preflop_action_history",
                "postflop_action_history",
                "completed_postflop_streets",
            ):
                if not expected_state.get(history_field):
                    expected_state.pop(history_field, None)
            cases.append(
                {
                    "job_id": case.job_id,
                    "original_filename": case.original_filename,
                    "image_file": image_name,
                    "expected_state": expected_state,
                }
            )

        manifest = {
            "schema": DATASET_SCHEMA,
            "schema_version": DATASET_SCHEMA_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "parser_provider": parser_provider,
            "layout_profile": layout_profile,
            "case_count": len(cases),
            "cases": cases,
        }
        manifest_bytes = (
            json.dumps(manifest, indent=2, ensure_ascii=True) + "\n"
        ).encode()
        if sum(image_sizes) + len(manifest_bytes) > (
            max_archive_bytes * MAX_DATASET_EXPANSION_RATIO
        ):
            raise DatasetExportError(dataset_archive_limit_message(max_archive_bytes))

        with ZipFile(archive_file, mode="w", compression=ZIP_DEFLATED) as archive:
            for case, manifest_case in zip(archive_cases, cases, strict=True):
                image_name = str(manifest_case["image_file"])
                if isinstance(case.image_source, Path):
                    archive.write(case.image_source, arcname=image_name)
                else:
                    archive.writestr(image_name, case.image_source)
                if archive_file.tell() > archive_output_limit:
                    raise DatasetExportError(
                        dataset_archive_limit_message(max_archive_bytes)
                    )

            archive.writestr("manifest.json", manifest_bytes)
            if archive_file.tell() > archive_output_limit:
                raise DatasetExportError(
                    dataset_archive_limit_message(max_archive_bytes)
                )

        if archive_file.tell() > archive_output_limit:
            raise DatasetExportError(
                dataset_archive_limit_message(max_archive_bytes)
            )
        archive_file.seek(0)
        return archive_file
    except Exception:
        archive_file.close()
        raise


def stream_archive(archive_file: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := archive_file.read(STREAM_CHUNK_SIZE):
            yield chunk
    finally:
        archive_file.close()
