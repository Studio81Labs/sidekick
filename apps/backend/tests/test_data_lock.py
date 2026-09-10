import asyncio
from pathlib import Path
from threading import Event, Thread

import pytest
from starlette.types import Message, Receive, Scope, Send

from app.bootstrap import DataMutationLockMiddleware
from app.data_lock import InterprocessDataLock


def _request_scope(method: str, path: str) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "server": ("testserver", 80),
        "client": ("testclient", 50000),
        "scheme": "http",
        "method": method,
        "root_path": "",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": [],
        "state": {},
    }


def _run_request(
    middleware: DataMutationLockMiddleware,
    *,
    method: str,
    path: str,
) -> Thread:
    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        pass

    thread = Thread(
        target=lambda: asyncio.run(
            middleware(_request_scope(method, path), receive, send)
        )
    )
    thread.start()
    return thread


def test_mutation_waits_while_snapshot_lock_is_held(tmp_path: Path) -> None:
    lock_attempted = Event()
    request_entered = Event()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request_entered.set()

    data_lock = InterprocessDataLock(tmp_path)
    middleware = DataMutationLockMiddleware(app, data_lock)
    original_acquire = data_lock.acquire

    def observed_acquire(
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> int:
        lock_attempted.set()
        return original_acquire(
            exclusive=exclusive,
            timeout_seconds=timeout_seconds,
        )

    with data_lock.hold(exclusive=True):
        data_lock.acquire = observed_acquire  # type: ignore[method-assign]
        request_thread = _run_request(
            middleware,
            method="POST",
            path="/api/jobs",
        )
        assert lock_attempted.wait(timeout=5)
        assert not request_entered.wait(timeout=0.2)

    request_thread.join(timeout=5)
    assert not request_thread.is_alive()
    assert request_entered.is_set()


def test_get_triggered_import_resume_joins_active_mutations(
    tmp_path: Path,
) -> None:
    request_entered = Event()
    release_request = Event()
    snapshot_attempted = Event()
    snapshot_acquired = Event()

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        request_entered.set()
        assert await asyncio.to_thread(release_request.wait, 5)

    data_lock = InterprocessDataLock(tmp_path)
    middleware = DataMutationLockMiddleware(app, data_lock)

    def acquire_snapshot() -> None:
        snapshot_attempted.set()
        with data_lock.hold(exclusive=True):
            snapshot_acquired.set()

    request_thread = _run_request(
        middleware,
        method="GET",
        path="/api/admin/ocr/benchmarks/imports/import-request-1",
    )
    assert request_entered.wait(timeout=5)
    snapshot_thread = Thread(target=acquire_snapshot)
    snapshot_thread.start()
    assert snapshot_attempted.wait(timeout=5)
    assert not snapshot_acquired.wait(timeout=0.2)

    release_request.set()
    request_thread.join(timeout=5)
    snapshot_thread.join(timeout=5)
    assert not request_thread.is_alive()
    assert not snapshot_thread.is_alive()
    assert snapshot_acquired.is_set()


def test_mcp_transport_does_not_join_data_mutations(tmp_path: Path) -> None:
    request_entered = False

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal request_entered
        request_entered = True

    data_lock = InterprocessDataLock(tmp_path)
    middleware = DataMutationLockMiddleware(app, data_lock)

    async def unexpected_acquire(
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> int:
        raise AssertionError("MCP transport must not acquire the data lock")

    data_lock.acquire_async = unexpected_acquire  # type: ignore[method-assign]

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        pass

    asyncio.run(middleware(_request_scope("POST", "/mcp"), receive, send))

    assert request_entered is True


def test_cancelled_async_wait_releases_eventual_lock(tmp_path: Path) -> None:
    blocker = InterprocessDataLock(tmp_path)
    waiter = InterprocessDataLock(tmp_path)
    lock_attempted = Event()
    cancelled_lock_released = Event()
    original_acquire = waiter.acquire
    original_release = waiter.release

    def observed_acquire(
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> int:
        lock_attempted.set()
        return original_acquire(
            exclusive=exclusive,
            timeout_seconds=timeout_seconds,
        )

    def observed_release(descriptor: int) -> None:
        original_release(descriptor)
        cancelled_lock_released.set()

    waiter.acquire = observed_acquire  # type: ignore[method-assign]
    waiter.release = observed_release  # type: ignore[method-assign]

    async def cancel_waiter() -> None:
        with blocker.hold(exclusive=False):
            acquisition = asyncio.create_task(
                waiter.acquire_async(exclusive=True)
            )
            assert await asyncio.to_thread(lock_attempted.wait, 5)
            acquisition.cancel()
            with pytest.raises(asyncio.CancelledError):
                await acquisition
            assert not cancelled_lock_released.is_set()

        assert await asyncio.to_thread(cancelled_lock_released.wait, 5)

    asyncio.run(cancel_waiter())


def test_async_acquire_forwards_the_timeout_budget(tmp_path: Path) -> None:
    data_lock = InterprocessDataLock(tmp_path)
    observed: list[tuple[bool, int | None]] = []
    original_acquire = data_lock.acquire

    def observed_acquire(
        *,
        exclusive: bool,
        timeout_seconds: int | None = None,
    ) -> int:
        observed.append((exclusive, timeout_seconds))
        return original_acquire(
            exclusive=exclusive,
            timeout_seconds=timeout_seconds,
        )

    data_lock.acquire = observed_acquire  # type: ignore[method-assign]

    descriptor = asyncio.run(
        data_lock.acquire_async(exclusive=True, timeout_seconds=17)
    )
    data_lock.release(descriptor)

    assert observed == [(True, 17)]
