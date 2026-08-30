import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import os
import time
from pathlib import Path


DATA_LOCK_FILENAME = ".poker-hero-data.lock"

# Three bounds. They are separate because they protect against different
# failures, not because the numbers differ - two of them are equal today,
# and that is a coincidence rather than a link. Anyone tuning one of these
# must be able to do it without silently moving the others.
#
# STARTUP, EXCLUSIVE side (the imported-hand recovery sweep). An exclusive
# acquire can be starved indefinitely: flock() has no writer preference,
# so a steady stream of overlapping shared holders can keep one waiting
# forever. No length of wait rescues that, so the bound is tight - fail
# fast and say which side was wanted.
DEFAULT_DATA_LOCK_TIMEOUT_SECONDS = 30

# STARTUP, SHARED side (everything else a boot does). Blocked only by
# exclusive holders, and those *drain*: the backup export finishes its
# archive and the wait ends. Waiting is the correct behaviour, so this
# bound exists only to turn a genuinely stuck system into a message
# instead of an infinite wedge with no log line, and it sits well clear of
# a legitimate export - the runbook schedules one daily, building up to a
# 100 MB archive under the exclusive side.
DEFAULT_DATA_LOCK_SHARED_TIMEOUT_SECONDS = 600

# WRITE hold (a record store cascade). Also a shared acquire, so also
# blocked only by an exclusive holder - an export, or another instance's
# recovery sweep. Unlike startup, failing fast here is the point rather
# than a hazard: this runs on a request path, where a write that gives up
# with a named error is a better answer than one that stalls a client for
# the length of an archive build. Equal to the startup exclusive bound by
# coincidence, not by connection.
DEFAULT_DATA_LOCK_WRITE_TIMEOUT_SECONDS = 30

_NANOSECONDS_PER_SECOND = 1_000_000_000
_MILLISECONDS_PER_SECOND = 1_000
_POLL_INTERVAL_MILLISECONDS = 50


class DataLockError(RuntimeError):
    pass


class DataLockTimeoutError(DataLockError):
    """A bounded acquire gave up rather than waiting indefinitely.

    flock() does not prioritise waiters, so an exclusive acquire can be
    starved indefinitely by a steady stream of overlapping shared holders.
    Anything that must not hang forever - a startup path that has to reach
    the point where a health check can answer, above all - passes a
    timeout and gets this instead of a silent wedge.
    """


class InterprocessDataLock:
    def __init__(self, data_dir: Path) -> None:
        self.lock_path = data_dir / DATA_LOCK_FILENAME

    def acquire(
        self,
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> int:
        """Acquire the lock, optionally giving up after timeout_seconds.

        timeout_seconds=None keeps the historical behaviour: block until
        the lock is granted, however long that takes.
        """
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DataLockError(
                f"Could not create data directory: {self.lock_path.parent}"
            ) from exc
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_RDONLY | os.O_CREAT,
                0o644,
            )
        except OSError as exc:
            raise DataLockError(
                f"Could not open data lock in {self.lock_path.parent}"
            ) from exc
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            if timeout_seconds is None:
                fcntl.flock(descriptor, operation)
            else:
                self._flock_before_deadline(
                    descriptor,
                    operation,
                    timeout_seconds=timeout_seconds,
                    exclusive=exclusive,
                )
        except OSError as exc:
            os.close(descriptor)
            raise DataLockError(
                f"Could not acquire data lock in {self.lock_path.parent}"
            ) from exc
        except BaseException:
            # DataLockTimeoutError is not an OSError, and neither is a
            # KeyboardInterrupt landing inside the retry loop; the
            # descriptor still has to go back.
            os.close(descriptor)
            raise
        return descriptor

    def _flock_before_deadline(
        self,
        descriptor: int,
        operation: int,
        *,
        timeout_seconds: int,
        exclusive: bool,
    ) -> None:
        # Deadline arithmetic stays in integer nanoseconds; only the sleep
        # itself needs a fractional second.
        deadline = time.monotonic_ns() + timeout_seconds * _NANOSECONDS_PER_SECOND
        while True:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                pass
            if time.monotonic_ns() >= deadline:
                raise DataLockTimeoutError(self._timeout_message(
                    timeout_seconds=timeout_seconds,
                    exclusive=exclusive,
                ))
            time.sleep(_POLL_INTERVAL_MILLISECONDS / _MILLISECONDS_PER_SECOND)

    def _timeout_message(self, *, timeout_seconds: int, exclusive: bool) -> str:
        wanted = "an exclusive" if exclusive else "a shared"
        blocker = (
            "another process holds it, either shared (an in-flight mutating "
            "request, or a backup export) or exclusively (another instance "
            "starting up)"
            if exclusive
            else "another process holds it exclusively (a startup recovery "
            "sweep, or a backup export)"
        )
        return (
            f"Timed out after {timeout_seconds}s waiting for {wanted} hold of "
            f"the data lock at {self.lock_path}: {blocker}. flock() does not "
            "prioritise waiters, so this can persist for as long as the other "
            "holders overlap. Stop the other processes using this data "
            "directory, then retry."
        )

    async def acquire_async(self, *, exclusive: bool) -> int:
        acquisition = asyncio.create_task(
            asyncio.to_thread(self.acquire, exclusive=exclusive)
        )
        try:
            return await asyncio.shield(acquisition)
        except asyncio.CancelledError:
            # Shield keeps the blocking flock alive. If it later succeeds,
            # release its otherwise-unobserved descriptor immediately.
            acquisition.add_done_callback(self._release_cancelled_acquisition)
            raise

    def _release_cancelled_acquisition(self, acquisition: asyncio.Task[int]) -> None:
        try:
            descriptor = acquisition.result()
        except asyncio.CancelledError:
            return
        except Exception:
            return
        try:
            self.release(descriptor)
        except OSError:
            # release() closes the descriptor even if explicit unlock fails.
            pass

    @staticmethod
    def release(descriptor: int) -> None:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)

    @contextmanager
    def hold(
        self,
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> Iterator[None]:
        descriptor = self.acquire(
            exclusive=exclusive,
            timeout_seconds=timeout_seconds,
        )
        try:
            yield
        finally:
            self.release(descriptor)
