import asyncio
import json
import logging
import re
from pathlib import Path
from threading import Event, Thread

import pytest
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

import app.bootstrap as bootstrap_module
from app.bootstrap import create_app
from app.config import Settings
from app.storage.file_benchmark_store import FileBenchmarkStore
from api_test_support import make_client

CORS_EXPOSED_HEADERS = (
    "X-Request-ID, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining"
)


@pytest.fixture
def access_log_records(
    monkeypatch: pytest.MonkeyPatch,
) -> list[logging.LogRecord]:
    records: list[logging.LogRecord] = []

    class RecordHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    monkeypatch.setattr(bootstrap_module.LOGGER, "handlers", [RecordHandler()])
    monkeypatch.setattr(bootstrap_module.LOGGER, "propagate", False)
    return records


def test_default_access_log_level_suppresses_health_event(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    response = make_client(tmp_path).get("/api/health")

    assert response.status_code == 200
    assert access_log_records == []


def test_debug_access_log_level_emits_health_event(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    client = make_client(tmp_path, access_log_level="debug")

    response = client.get(
        "/api/health",
        headers={"X-Request-ID": "health-request-123"},
    )

    assert response.status_code == 200
    access_events = [
        json.loads(record.message)
        for record in access_log_records
        if record.name == "poker.access"
    ]
    assert access_events == [
        {
            "duration_ms": access_events[0]["duration_ms"],
            "event": "http_request",
            "level": "debug",
            "method": "GET",
            "outcome": "completed",
            "path": "/api/health",
            "request_id": "health-request-123",
            "status_code": 200,
        }
    ]
    assert access_log_records[0].levelno == logging.DEBUG


def test_request_id_is_returned_and_access_log_is_structured(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    client = make_client(tmp_path)

    response = client.get(
        "/api/admin/ocr/jobs?limit=1",
        headers={"X-Request-ID": "worker-request-123"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "worker-request-123"
    messages = [
        json.loads(record.message)
        for record in access_log_records
        if record.name == "poker.access"
    ]
    assert len(messages) == 1
    assert messages == [
        {
            "duration_ms": messages[0]["duration_ms"],
            "event": "http_request",
            "level": "info",
            "method": "GET",
            "outcome": "completed",
            "path": "/api/admin/ocr/jobs",
            "request_id": "worker-request-123",
            "status_code": 200,
        }
    ]
    assert isinstance(messages[0]["duration_ms"], float)
    assert messages[0]["duration_ms"] >= 0


def test_invalid_request_id_is_replaced(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get(
        "/api/admin/ocr/jobs",
        headers={"X-Request-ID": "invalid request id"},
    )

    assert response.status_code == 200
    generated_request_id = response.headers["X-Request-ID"]
    assert generated_request_id != "invalid request id"
    assert re.fullmatch(r"[0-9a-f]{32}", generated_request_id)


def test_unhandled_error_response_keeps_request_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    access_log_records: list[logging.LogRecord],
) -> None:
    request_id = "08b8ce83-8423-4fe6-8aa1-966d6710ad74"
    captured: list[tuple[Exception, dict[str, str | None]]] = []
    monkeypatch.setattr(
        bootstrap_module,
        "capture_unhandled_exception",
        lambda error, **context: captured.append((error, context)),
    )
    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
        )
    )

    @app.api_application.get("/api/test-crash")
    def crash() -> None:
        raise RuntimeError("test crash")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/api/test-crash",
        headers={
            "Origin": "http://localhost:5173",
            "X-Request-ID": request_id,
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert response.headers["X-Request-ID"] == request_id
    assert response.headers["Access-Control-Allow-Origin"] == (
        "http://localhost:5173"
    )
    assert response.headers["Access-Control-Expose-Headers"] == CORS_EXPOSED_HEADERS
    access_events = [
        json.loads(record.message)
        for record in access_log_records
        if record.name == "poker.access"
    ]
    assert len(access_events) == 1
    assert access_events[0]["request_id"] == request_id
    assert access_events[0]["status_code"] == 500
    assert access_events[0]["outcome"] == "failed"
    assert len(captured) == 1
    assert str(captured[0][0]) == "test crash"
    assert captured[0][1] == {
        "request_id": request_id,
        "method": "GET",
        "route": "/api/test-crash",
    }


def test_stream_failure_is_logged_after_response_start(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
        )
    )

    def stream_chunks():
        yield b"partial"
        assert not [
            record
            for record in access_log_records
            if record.name == "poker.access"
        ]
        raise RuntimeError("stream failed")

    @app.api_application.get("/api/test-stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(stream_chunks())

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get(
        "/api/test-stream",
        headers={"X-Request-ID": "failed-stream-123"},
    )

    assert response.status_code == 200
    access_events = [
        json.loads(record.message)
        for record in access_log_records
        if record.name == "poker.access"
    ]
    assert len(access_events) == 1
    assert access_events[0]["request_id"] == "failed-stream-123"
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "failed"


def test_client_disconnect_marks_file_response_failed(
    access_log_records: list[logging.LogRecord],
) -> None:
    received_messages = iter([
        {"type": "http.request", "body": b"", "more_body": False},
        {"type": "http.disconnect"},
    ])
    sent_messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        await asyncio.sleep(0)
        return next(received_messages)

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)
        await asyncio.sleep(0)

    async def file_response(
        _scope: dict[str, object],
        _receive,
        send_response,
    ) -> None:
        await asyncio.sleep(0)
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send_response({
            "type": "http.response.body",
            "body": b"partial",
            "more_body": True,
        })
        await asyncio.sleep(0)
        await send_response({
            "type": "http.response.body",
            "body": b"complete",
            "more_body": False,
        })

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs/example/image",
        "raw_path": b"/api/admin/ocr/jobs/example/image",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(
        bootstrap_module.RequestObservabilityMiddleware(file_response)(
            scope,
            receive,
            send,
        )
    )

    response_headers = dict(sent_messages[0]["headers"])
    assert b"x-request-id" in response_headers
    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "failed"


def test_client_disconnect_during_pathsend_marks_response_failed(
    access_log_records: list[logging.LogRecord],
) -> None:
    pathsend_started = asyncio.Event()
    disconnect_delivered = asyncio.Event()
    receive_count = 0

    async def receive() -> dict[str, object]:
        nonlocal receive_count
        receive_count += 1
        if receive_count == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await pathsend_started.wait()
        disconnect_delivered.set()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.pathsend":
            pathsend_started.set()
            await disconnect_delivered.wait()
            await asyncio.sleep(0)

    async def file_response(
        _scope: dict[str, object],
        _receive,
        send_response,
    ) -> None:
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send_response({
            "type": "http.response.pathsend",
            "path": "/tmp/example.png",
        })

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "extensions": {"http.response.pathsend": {}},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs/example/image",
        "raw_path": b"/api/admin/ocr/jobs/example/image",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(
        bootstrap_module.RequestObservabilityMiddleware(file_response)(
            scope,
            receive,
            send,
        )
    )

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "failed"


def test_client_disconnect_during_final_body_send_marks_response_failed(
    access_log_records: list[logging.LogRecord],
) -> None:
    final_send_started = asyncio.Event()
    disconnect_delivered = asyncio.Event()
    receive_count = 0

    async def receive() -> dict[str, object]:
        nonlocal receive_count
        receive_count += 1
        if receive_count == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await final_send_started.wait()
        disconnect_delivered.set()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        if (
            message["type"] == "http.response.body"
            and not message.get("more_body", False)
        ):
            final_send_started.set()
            await disconnect_delivered.wait()
            await asyncio.sleep(0)

    async def file_response(
        _scope: dict[str, object],
        _receive,
        send_response,
    ) -> None:
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send_response({
            "type": "http.response.body",
            "body": b"complete",
            "more_body": False,
        })

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs/example/image",
        "raw_path": b"/api/admin/ocr/jobs/example/image",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(
        bootstrap_module.RequestObservabilityMiddleware(file_response)(
            scope,
            receive,
            send,
        )
    )

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "failed"


def test_rejected_upload_monitors_receive_only_after_response_start(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    receive_calls = 0
    sent_messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        nonlocal receive_calls
        assert sent_messages
        assert sent_messages[0]["type"] == "http.response.start"
        receive_calls += 1
        await asyncio.Event().wait()
        raise AssertionError("receive monitor should be cancelled")

    async def send(message: dict[str, object]) -> None:
        sent_messages.append(message)
        await asyncio.sleep(0)

    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
            proxy_shared_secret="worker-to-backend-secret-value-123",
        )
    )

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs",
        "raw_path": b"/api/admin/ocr/jobs",
        "query_string": b"",
        "headers": [
            (b"content-length", b"1048576"),
            (b"content-type", b"multipart/form-data; boundary=unread"),
            (b"expect", b"100-continue"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(app(scope, receive, send))

    assert receive_calls == 1
    assert sent_messages[0]["type"] == "http.response.start"
    assert sent_messages[0]["status"] == 401
    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 401
    assert access_events[0]["outcome"] == "completed"


def test_disconnect_during_rejected_upload_response_is_logged_as_failed(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    response_started = asyncio.Event()
    final_send_started = asyncio.Event()
    disconnect_delivered = asyncio.Event()
    received_messages = iter([
        {
            "type": "http.request",
            "body": b"first unread upload frame",
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b"second unread upload frame",
            "more_body": True,
        },
        {"type": "http.disconnect"},
    ])

    async def receive() -> dict[str, object]:
        assert response_started.is_set()
        await final_send_started.wait()
        message = next(received_messages)
        if message["type"] == "http.disconnect":
            disconnect_delivered.set()
        return message

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            response_started.set()
        elif (
            message["type"] == "http.response.body"
            and not message.get("more_body", False)
        ):
            final_send_started.set()
            await disconnect_delivered.wait()

    app = create_app(
        Settings(
            data_dir=tmp_path,
            parser_provider="mock",
            proxy_shared_secret="worker-to-backend-secret-value-123",
        )
    )
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs",
        "raw_path": b"/api/admin/ocr/jobs",
        "query_string": b"",
        "headers": [
            (b"content-length", b"1048576"),
            (b"content-type", b"multipart/form-data; boundary=unread"),
            (b"expect", b"100-continue"),
        ],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(app(scope, receive, send))

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 401
    assert access_events[0]["outcome"] == "failed"


def test_disconnect_during_successful_unread_body_response_is_logged_as_failed(
    access_log_records: list[logging.LogRecord],
) -> None:
    response_started = asyncio.Event()
    final_send_started = asyncio.Event()
    disconnect_delivered = asyncio.Event()
    received_messages = iter([
        {
            "type": "http.request",
            "body": b"first unread request frame",
            "more_body": True,
        },
        {
            "type": "http.request",
            "body": b"second unread request frame",
            "more_body": True,
        },
        {"type": "http.disconnect"},
    ])

    async def receive() -> dict[str, object]:
        assert response_started.is_set()
        await final_send_started.wait()
        message = next(received_messages)
        if message["type"] == "http.disconnect":
            disconnect_delivered.set()
        return message

    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.start":
            response_started.set()
        elif (
            message["type"] == "http.response.body"
            and not message.get("more_body", False)
        ):
            final_send_started.set()
            await disconnect_delivered.wait()

    async def successful_short_circuit(
        _scope: dict[str, object],
        _receive,
        send_response,
    ) -> None:
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send_response({
            "type": "http.response.body",
            "body": b"complete",
            "more_body": False,
        })

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs",
        "raw_path": b"/api/admin/ocr/jobs",
        "query_string": b"",
        "headers": [(b"content-length", b"1048576")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(
        bootstrap_module.RequestObservabilityMiddleware(successful_short_circuit)(
            scope,
            receive,
            send,
        )
    )

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "failed"


def test_response_start_does_not_create_concurrent_receive_calls(
    access_log_records: list[logging.LogRecord],
) -> None:
    first_receive_started = asyncio.Event()
    release_first_receive = asyncio.Event()
    disconnect_delivered = asyncio.Event()
    receive_calls = 0
    active_receive_calls = 0
    maximum_active_receive_calls = 0

    async def receive() -> dict[str, object]:
        nonlocal active_receive_calls, maximum_active_receive_calls
        nonlocal receive_calls
        receive_calls += 1
        active_receive_calls += 1
        maximum_active_receive_calls = max(
            maximum_active_receive_calls,
            active_receive_calls,
        )
        try:
            if receive_calls == 1:
                first_receive_started.set()
                await release_first_receive.wait()
                return {
                    "type": "http.request",
                    "body": b"partial request",
                    "more_body": True,
                }
            disconnect_delivered.set()
            return {"type": "http.disconnect"}
        finally:
            active_receive_calls -= 1

    async def send(_message: dict[str, object]) -> None:
        await asyncio.sleep(0)

    async def overlapping_response(
        _scope: dict[str, object],
        receive_request,
        send_response,
    ) -> None:
        first_receive = asyncio.create_task(receive_request())
        await first_receive_started.wait()
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        release_first_receive.set()
        await first_receive
        await disconnect_delivered.wait()
        await send_response({
            "type": "http.response.body",
            "body": b"complete",
            "more_body": False,
        })

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs",
        "raw_path": b"/api/admin/ocr/jobs",
        "query_string": b"",
        "headers": [(b"content-length", b"1024")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(
        bootstrap_module.RequestObservabilityMiddleware(overlapping_response)(
            scope,
            receive,
            send,
        )
    )

    assert receive_calls == 2
    assert maximum_active_receive_calls == 1
    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["outcome"] == "failed"


def test_preexisting_disconnect_is_seen_before_synchronous_final_send(
    access_log_records: list[logging.LogRecord],
) -> None:
    response_started = False

    async def receive() -> dict[str, object]:
        assert response_started
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        nonlocal response_started
        if message["type"] == "http.response.start":
            response_started = True

    async def synchronous_response(
        _scope: dict[str, object],
        _receive,
        send_response,
    ) -> None:
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send_response({
            "type": "http.response.body",
            "body": b"complete",
            "more_body": False,
        })

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/admin/ocr/jobs",
        "raw_path": b"/api/admin/ocr/jobs",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {},
    }

    asyncio.run(
        bootstrap_module.RequestObservabilityMiddleware(synchronous_response)(
            scope,
            receive,
            send,
        )
    )

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "failed"


def test_completed_response_is_logged_before_post_response_failure(
    access_log_records: list[logging.LogRecord],
) -> None:
    async def receive() -> dict[str, object]:
        await asyncio.Event().wait()
        raise AssertionError("receive should be cancelled")

    async def send(_message: dict[str, object]) -> None:
        await asyncio.sleep(0)

    async def response_then_fail(
        _scope: dict[str, object],
        _receive,
        send_response,
    ) -> None:
        await send_response({
            "type": "http.response.start",
            "status": 200,
            "headers": [],
        })
        await send_response({
            "type": "http.response.body",
            "body": b"complete",
            "more_body": False,
        })
        access_events = [
            json.loads(record.message) for record in access_log_records
        ]
        assert len(access_events) == 1
        assert access_events[0]["outcome"] == "completed"
        raise RuntimeError("background task failed")

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/admin/ocr/benchmarks/imports/example",
        "raw_path": b"/api/admin/ocr/benchmarks/imports/example",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
        "state": {bootstrap_module.BACKGROUND_TASK_STATE_KEY: True},
    }

    with pytest.raises(RuntimeError, match="background task failed"):
        asyncio.run(
            bootstrap_module.RequestObservabilityMiddleware(response_then_fail)(
                scope,
                receive,
                send,
            )
        )

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "completed"


def test_benchmark_recovery_poll_logs_before_background_import_finishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    access_log_records: list[logging.LogRecord],
) -> None:
    request_id = "observed-background-import"
    FileBenchmarkStore(tmp_path).begin_import(request_id, b"test archive")
    import_started = Event()
    release_import = Event()

    def block_import_parse(*_args: object, **_kwargs: object):
        import_started.set()
        assert release_import.wait(timeout=2)
        raise OSError("simulated interrupted background import")

    monkeypatch.setattr(
        bootstrap_module,
        "parse_parser_dataset_archive",
        block_import_parse,
    )
    client = make_client(tmp_path)
    responses: list[object] = []

    def poll_import() -> None:
        responses.append(client.get(f"/api/admin/ocr/benchmarks/imports/{request_id}"))

    poll_thread = Thread(target=poll_import)
    poll_thread.start()
    assert import_started.wait(timeout=2)

    access_events = [json.loads(record.message) for record in access_log_records]
    assert len(access_events) == 1
    assert access_events[0]["path"] == (
        f"/api/admin/ocr/benchmarks/imports/{request_id}"
    )
    assert access_events[0]["status_code"] == 200
    assert access_events[0]["outcome"] == "completed"
    assert poll_thread.is_alive()

    release_import.set()
    poll_thread.join(timeout=2)
    assert not poll_thread.is_alive()
    assert len(responses) == 1
    assert responses[0].status_code == 200


def test_cors_preflight_is_observed(
    tmp_path: Path,
    access_log_records: list[logging.LogRecord],
) -> None:
    client = make_client(tmp_path)

    response = client.options(
        "/api/admin/ocr/jobs",
        headers={
            "Access-Control-Request-Headers": "X-Benchmark-Import-Request-ID",
            "Access-Control-Request-Method": "POST",
            "Origin": "http://localhost:5173",
            "X-Request-ID": "preflight-request-123",
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "preflight-request-123"
    access_events = [
        json.loads(record.message)
        for record in access_log_records
        if record.name == "poker.access"
    ]
    assert len(access_events) == 1
    assert access_events[0]["method"] == "OPTIONS"
    assert access_events[0]["request_id"] == "preflight-request-123"
    assert access_events[0]["outcome"] == "completed"


def test_access_logger_formats_events_as_plain_json() -> None:
    handler = next(
        handler
        for handler in bootstrap_module.LOGGER.handlers
        if handler.get_name() == bootstrap_module.ACCESS_LOG_HANDLER_NAME
    )
    message = '{"event":"http_request","level":"info"}'
    record = bootstrap_module.LOGGER.makeRecord(
        bootstrap_module.LOGGER.name,
        logging.INFO,
        __file__,
        1,
        message,
        (),
        None,
    )

    assert bootstrap_module.LOGGER.propagate is False
    assert handler.format(record) == message


def test_cors_exposes_request_id_header(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get(
        "/api/admin/ocr/jobs",
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Expose-Headers"] == CORS_EXPOSED_HEADERS


def test_proxy_shared_secret_protects_api_but_not_health(tmp_path: Path) -> None:
    proxy_secret = "worker-to-backend-secret-value-123"
    client = make_client(tmp_path, proxy_shared_secret=proxy_secret)

    assert client.get("/api/health").status_code == 200
    rejected = client.get(
        "/api/admin/ocr/jobs",
        headers={
            "Origin": "http://localhost:5173",
            "X-Request-ID": "rejected-request-123",
        },
    )
    assert rejected.status_code == 401
    assert rejected.headers["X-Request-ID"] == "rejected-request-123"
    assert rejected.headers["Access-Control-Allow-Origin"] == (
        "http://localhost:5173"
    )
    assert rejected.headers["Access-Control-Expose-Headers"] == CORS_EXPOSED_HEADERS
    assert client.get(
        "/api/admin/ocr/jobs",
        headers={"X-Poker-Proxy-Secret": "incorrect-secret-value-123456789"},
    ).status_code == 401

    authorized = client.get(
        "/api/admin/ocr/jobs",
        headers={"X-Poker-Proxy-Secret": proxy_secret},
    )

    assert authorized.status_code == 200
    assert authorized.json()["jobs"] == []
