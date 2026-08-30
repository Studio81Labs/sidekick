"""Workspace repositories, recovery, and lock coordination."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from threading import Lock, RLock
from typing import Self

from app.application.imported_hand_ports import (
    ImportedHandRecoveryReport,
    ImportedHandRepository,
)
from app.data_lock import (
    DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    InterprocessDataLock,
)
from app.domain.hands import JobRecord
from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.imported_hand_store import FileImportedHandStore
from app.storage.ports import BenchmarkRepository, JobRepository

DEFAULT_JOB_LOCK_STRIPES = 64
DEFAULT_IMPORTED_HAND_LOCK_STRIPES = 64
INTERRUPTED_PARSER_ERROR = (
    "Parsing was interrupted by a backend restart; upload the screenshot again"
)


class WorkspaceCoordinator:
    """Own persistence adapters and serialize compound workspace operations."""

    def __init__(
        self,
        *,
        jobs: JobRepository,
        benchmarks: BenchmarkRepository,
        imported_hands: ImportedHandRepository,
        data_lock: InterprocessDataLock,
        job_lock_stripes: int = DEFAULT_JOB_LOCK_STRIPES,
        job_lock_factory: Callable[[], LockType] = Lock,
        imported_hand_lock_stripes: int = DEFAULT_IMPORTED_HAND_LOCK_STRIPES,
        imported_hand_lock_factory: Callable[[], LockType] = Lock,
    ) -> None:
        if job_lock_stripes <= 0:
            raise ValueError("job_lock_stripes must be positive")
        if imported_hand_lock_stripes <= 0:
            raise ValueError("imported_hand_lock_stripes must be positive")
        self.jobs = jobs
        self.benchmarks = benchmarks
        self.imported_hands = imported_hands
        self.data_lock = data_lock
        self.job_locks = tuple(job_lock_factory() for _ in range(job_lock_stripes))
        self.imported_hand_locks = tuple(
            imported_hand_lock_factory()
            for _ in range(imported_hand_lock_stripes)
        )
        self.history_lock = RLock()
        self.dataset_import_lock = Lock()
        self.benchmark_corpus_lock = Lock()
        self.application_backup_lock = Lock()
        # What open()'s record-store recovery sweep found. Retained rather
        # than discarded so the quarantined and failed buckets stay
        # available to whoever eventually surfaces them; nothing acts on
        # them yet.
        self.imported_hand_recovery = ImportedHandRecoveryReport()

    @classmethod
    def open(
        cls,
        data_dir: Path,
        *,
        job_lock_stripes: int = DEFAULT_JOB_LOCK_STRIPES,
        job_lock_factory: Callable[[], LockType] = Lock,
        imported_hand_lock_stripes: int = DEFAULT_IMPORTED_HAND_LOCK_STRIPES,
        imported_hand_lock_factory: Callable[[], LockType] = Lock,
        recovery_lock_timeout_seconds: int = DEFAULT_DATA_LOCK_TIMEOUT_SECONDS,
    ) -> Self:
        data_lock = InterprocessDataLock(data_dir)
        imported_hands = FileImportedHandStore(data_dir)
        # The record store's recovery sweep needs an EXCLUSIVE hold: it
        # replays or discards write-journal scratch directories, and can
        # only tell a crashed cascade from a live one if no other process
        # can have a live one. The journal serialises begin() against
        # recover() within a process and enforces nothing across them.
        #
        # The hold is kept as narrow as the requirement allows - the sweep
        # scans .cascade and nothing else - and is BOUNDED. flock() does
        # not prioritise waiters, so overlapping shared holders can starve
        # an exclusive acquire indefinitely, and this runs at import time
        # (app/main.py -> bootstrap.create_app), before uvicorn binds and
        # before /api/health can answer. An unbounded wait here means a
        # rolling deploy against a shared data volume hangs silently and
        # never turns healthy. A loud startup failure is far better, so
        # the timeout raises DataLockTimeoutError and it is deliberately
        # not caught: a stranded half-applied cascade must not be served
        # around quietly.
        with data_lock.hold(
            exclusive=True,
            timeout_seconds=recovery_lock_timeout_seconds,
        ):
            recovery = imported_hands.recover()
        # Everything else keeps the shared hold it has always had.
        # recover_interrupted_jobs() reads and validates every job record
        # on disk, which is the dominant cost here and has no business
        # inside an exclusive hold taken for the sweep. It does write job
        # records under a shared lock, which is a real race - but a
        # pre-existing one, tracked separately, and not fixed by widening
        # a lock introduced for something else.
        with data_lock.hold(exclusive=False):
            workspace = cls(
                jobs=FileJobStore(data_dir),
                benchmarks=FileBenchmarkStore(data_dir),
                imported_hands=imported_hands,
                data_lock=data_lock,
                job_lock_stripes=job_lock_stripes,
                job_lock_factory=job_lock_factory,
                imported_hand_lock_stripes=imported_hand_lock_stripes,
                imported_hand_lock_factory=imported_hand_lock_factory,
            )
            workspace.imported_hand_recovery = recovery
            workspace.recover_interrupted_jobs()
        return workspace

    def recover_interrupted_jobs(self) -> None:
        for job in self.jobs.list():
            if job.status == "created":
                job.status = "error"
                job.error = INTERRUPTED_PARSER_ERROR
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

    def imported_hand_lock_index(self, record_key: str) -> int:
        return hash(record_key) % len(self.imported_hand_locks)

    def imported_hand_lock_for(self, record_key: str) -> LockType:
        return self.imported_hand_locks[self.imported_hand_lock_index(record_key)]

    @contextmanager
    def hold_imported_hands(self, record_keys: Iterable[str]) -> Iterator[None]:
        """Serialize compound work on a set of imported-hand records.

        Stripes are entered in sorted index order so two callers naming
        overlapping sets can never take them in opposite orders.

        This must wrap a record-store write, never the other way round.
        The store's write journal holds its own lock for the whole of a
        save and treats it as a leaf lock, so a stripe taken from inside
        an open cascade inverts the ordering this class establishes
        (benchmark_corpus_lock -> job_locks -> history_lock, with the
        journal below all of them) into an ABBA deadlock.
        """
        lock_indexes = sorted(
            {self.imported_hand_lock_index(record_key) for record_key in record_keys}
        )
        with ExitStack() as stack:
            for lock_index in lock_indexes:
                stack.enter_context(self.imported_hand_locks[lock_index])
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
