"""File-backed job store adapter."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from app.domain.poker import CanonicalState
from app.domain.hands import JobInputContext, JobRecord
from app.storage.persistence import (
    JOB_ID_PATTERN,
    _fsync_directory,
    JobNotFoundError,
    load_persisted_job_record,
)


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
        *,
        input_context: JobInputContext,
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
            "input_context": input_context,
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
        input_context: JobInputContext,
    ) -> JobRecord:
        image_suffix = Path(original_filename).suffix or ".png"
        job = JobRecord(
            id=job_id,
            status="approved",
            input_context=input_context,
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
