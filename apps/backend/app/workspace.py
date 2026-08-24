"""Workspace repositories, recovery, and lock coordination."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Lock, RLock
from typing import Self

from app.data_lock import InterprocessDataLock
from app.domain.hands import JobRecord
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.ports import BenchmarkRepository, JobRepository

DEFAULT_JOB_LOCK_STRIPES = 64
INTERRUPTED_PARSER_ERROR = (
    "Parsing was interrupted by a backend restart; upload the screenshot again"
)
INTERRUPTED_RECOMMENDATION_ERROR = (
    "Recommendation was interrupted by a backend restart; request it again"
)


class WorkspaceCoordinator:
    """Own persistence adapters and serialize compound workspace operations."""

    def __init__(
        self,
        *,
        jobs: JobRepository,
        benchmarks: BenchmarkRepository,
        data_lock: InterprocessDataLock,
        job_lock_stripes: int = DEFAULT_JOB_LOCK_STRIPES,
        job_lock_factory: Callable[[], LockType] = Lock,
    ) -> None:
        if job_lock_stripes <= 0:
            raise ValueError("job_lock_stripes must be positive")
        self.jobs = jobs
        self.benchmarks = benchmarks
        self.data_lock = data_lock
        self.job_locks = tuple(job_lock_factory() for _ in range(job_lock_stripes))
        self.history_lock = RLock()
        self.dataset_import_lock = Lock()
        self.benchmark_corpus_lock = Lock()
        self.application_backup_lock = Lock()

    @classmethod
    def open(
        cls,
        data_dir: Path,
        *,
        job_lock_stripes: int = DEFAULT_JOB_LOCK_STRIPES,
        job_lock_factory: Callable[[], LockType] = Lock,
    ) -> Self:
        data_lock = InterprocessDataLock(data_dir)
        with data_lock.hold(exclusive=False):
            workspace = cls(
                jobs=FileJobStore(data_dir),
                benchmarks=FileBenchmarkStore(data_dir),
                data_lock=data_lock,
                job_lock_stripes=job_lock_stripes,
                job_lock_factory=job_lock_factory,
            )
            workspace.recover_interrupted_jobs()
        return workspace

    def recover_interrupted_jobs(self) -> None:
        for job in self.jobs.list():
            if job.status == "created":
                job.recommendation_pending = False
                job.status = "error"
                job.error = INTERRUPTED_PARSER_ERROR
                self.jobs.save(job)
                continue
            if job.recommendation_pending:
                job.recommendation_pending = False
                job.status = "error"
                job.error = INTERRUPTED_RECOMMENDATION_ERROR
                self.jobs.save(job)

    def save_job(self, job: JobRecord) -> JobRecord:
        if job.archived_at is None:
            return self.jobs.save(job)
        with self.history_lock:
            return self.jobs.save(job)

    def job_lock_index(self, job_id: str) -> int:
        return hash(job_id) % len(self.job_locks)

    def job_lock_for(self, job_id: str) -> LockType:
        return self.job_locks[self.job_lock_index(job_id)]

    @contextmanager
    def hold_jobs(self, job_ids: Iterable[str]) -> Iterator[None]:
        lock_indexes = sorted({self.job_lock_index(job_id) for job_id in job_ids})
        with ExitStack() as stack:
            for lock_index in lock_indexes:
                stack.enter_context(self.job_locks[lock_index])
            yield

    @contextmanager
    def hold_benchmark_import(self, job_ids: Iterable[str]) -> Iterator[None]:
        with self.benchmark_corpus_lock, self.hold_jobs(job_ids), self.history_lock:
            yield

    @contextmanager
    def hold_backup_transaction(self) -> Iterator[None]:
        with (
            self.application_backup_lock,
            self.dataset_import_lock,
            self.benchmark_corpus_lock,
            ExitStack() as stack,
        ):
            for job_lock in self.job_locks:
                stack.enter_context(job_lock)
            with self.history_lock:
                yield
