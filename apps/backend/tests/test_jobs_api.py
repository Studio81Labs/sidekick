from pathlib import Path
from threading import Event, Lock as ThreadLock, Thread

import pytest

from app.storage.file_benchmark_store import FileBenchmarkStore
from app.storage.file_job_store import FileJobStore
from app.storage.persistence import JobNotFoundError
from api_test_support import (
    APPROVED_STATE,
    VALID_PNG,
    approve_job,
    load_only_job,
    make_client,
    upload_job,
)


def test_upload_persists_client_request_identity(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    request_id = "08b8ce83-8423-4fe6-8aa1-966d6710ad74"

    response = upload_job(client, upload_request_id=request_id)

    assert response.status_code == 201
    assert response.json()["upload_request_id"] == request_id
    assert "recommendation_provider" not in response.json()
    assert load_only_job(tmp_path).upload_request_id == request_id


def test_processing_queue_pages_unarchived_jobs_in_stable_order(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_ids = [
        upload_job(client, filename=f"queue-{index}.png").json()["id"]
        for index in range(4)
    ]
    approve_job(client, job_ids[1])
    client.put("/api/history", json={"job_ids": [job_ids[1]]})
    benchmark_only_id = upload_job(
        client,
        filename="benchmark-only.png",
    ).json()["id"]
    store = FileJobStore(tmp_path)
    benchmark_only = store.get(benchmark_only_id)
    benchmark_only.parser_result = None
    benchmark_only.approved_state = APPROVED_STATE
    benchmark_only.benchmark_included = True
    benchmark_only.status = "approved"
    store.save(benchmark_only)

    first_page = client.get("/api/jobs?limit=2")
    second_page = client.get("/api/jobs?limit=2&offset=2")
    changed_job = store.get(job_ids[2])
    changed_job.error = "Needs another look"
    store.save(changed_job)
    changed_page = client.get("/api/jobs?limit=2")

    assert first_page.status_code == 200
    assert second_page.status_code == 200
    assert first_page.json()["total"] == 3
    assert [job["id"] for job in first_page.json()["jobs"]] == [
        job_ids[0],
        job_ids[2],
    ]
    assert [job["id"] for job in second_page.json()["jobs"]] == [job_ids[3]]
    assert first_page.json()["snapshot_version"] == second_page.json()["snapshot_version"]
    assert changed_page.json()["snapshot_version"] != first_page.json()["snapshot_version"]
    assert client.get("/api/jobs?offset=-1").status_code == 422


def test_processing_queue_keeps_mutated_benchmark_imports(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    pristine_id = upload_job(client, filename="pristine-import.png").json()["id"]
    reparsed_id = upload_job(client, filename="reparsed-import.png").json()["id"]
    failed_id = upload_job(client, filename="failed-import.png").json()["id"]
    store = FileJobStore(tmp_path)
    parser_result = store.get(reparsed_id).parser_result
    for job_id in (pristine_id, reparsed_id, failed_id):
        approve_job(client, job_id)
        imported_job = store.get(job_id)
        imported_job.parser_result = None
        imported_job.benchmark_included = True
        store.save(imported_job)

    reparsed_job = store.get(reparsed_id)
    reparsed_job.parser_result = parser_result
    store.save(reparsed_job)
    failed_job = store.get(failed_id)
    failed_job.status = "error"
    failed_job.error = "parser exploded"
    store.save(failed_job)

    queue = client.get("/api/jobs")

    assert queue.status_code == 200
    assert queue.json()["total"] == 2
    assert [job["id"] for job in queue.json()["jobs"]] == [reparsed_id, failed_id]
    assert queue.json()["jobs"][0]["parser_result"] is not None
    assert queue.json()["jobs"][1]["status"] == "error"
    assert queue.json()["jobs"][1]["error"] == "parser exploded"


def test_job_metadata_is_normalized_persisted_and_searchable(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client, filename="anonymous-table.png").json()["id"]

    updated = client.put(
        f"/api/jobs/{job_id}/metadata",
        json={
            "title": "  Tricky turn decision  ",
            "notes": "  Villain had been playing aggressively.  ",
            "tags": [" Turn ", "Study", "turn", ""],
        },
    )

    assert updated.status_code == 200
    assert updated.json()["title"] == "Tricky turn decision"
    assert updated.json()["notes"] == "Villain had been playing aggressively."
    assert updated.json()["tags"] == ["Turn", "Study"]
    persisted = FileJobStore(tmp_path).get(job_id)
    assert persisted.title == "Tricky turn decision"
    assert persisted.notes == "Villain had been playing aggressively."
    assert persisted.tags == ["Turn", "Study"]

    approve_job(client, job_id)
    client.put("/api/history", json={"job_ids": [job_id]})
    for query in ("tricky decision", "aggressively", "study"):
        result = client.get("/api/history", params={"query": query})
        assert result.status_code == 200
        assert [job["id"] for job in result.json()["jobs"]] == [job_id]

    cleared = client.put(
        f"/api/jobs/{job_id}/metadata",
        json={"title": " ", "notes": "", "tags": []},
    )
    assert cleared.status_code == 200
    assert cleared.json()["title"] is None
    assert cleared.json()["notes"] is None
    assert cleared.json()["tags"] == []


def test_job_metadata_rejects_oversized_excess_or_ambiguous_tags(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]

    oversized = client.put(
        f"/api/jobs/{job_id}/metadata",
        json={"title": None, "notes": None, "tags": ["x" * 33]},
    )
    excessive = client.put(
        f"/api/jobs/{job_id}/metadata",
        json={
            "title": None,
            "notes": None,
            "tags": [f"tag-{index}" for index in range(11)],
        },
    )
    comma_separated = client.put(
        f"/api/jobs/{job_id}/metadata",
        json={"title": None, "notes": None, "tags": ["turn,river"]},
    )

    assert oversized.status_code == 422
    assert excessive.status_code == 422
    assert comma_separated.status_code == 422
    assert FileJobStore(tmp_path).get(job_id).tags == []


def test_delete_removes_unarchivable_job_and_image(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client, filename="incomplete-table.png").json()["id"]
    job_dir = tmp_path / "jobs" / job_id

    deleted = client.delete(f"/api/jobs/{job_id}")

    assert deleted.status_code == 204
    assert deleted.content == b""
    assert not job_dir.exists()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/image").status_code == 404
    assert client.get("/api/jobs").json()["total"] == 0
    assert client.delete(f"/api/jobs/{job_id}").status_code == 404


def test_delete_removes_archived_job_from_history(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)
    client.put("/api/history", json={"job_ids": [job_id]})

    deleted = client.delete(f"/api/jobs/{job_id}")

    assert deleted.status_code == 204
    assert client.get("/api/history").json()["total"] == 0


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("pot_size", True),
        ("pot_size", "12.5"),
        ("players_in_hand", True),
        ("players_in_hand", "3"),
        ("players_in_hand", 3.0),
    ],
)
def test_approval_rejects_coerced_numeric_state(
    tmp_path: Path,
    field_name: str,
    value: object,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]

    response = approve_job(
        client,
        job_id,
        {**APPROVED_STATE, field_name: value},
    )

    assert response.status_code == 422
    job = FileJobStore(tmp_path).get(job_id)
    assert job.status == "parsed"
    assert job.approved_state is None


def test_reapproval_replaces_the_previous_approved_state(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    corrected_state = {**APPROVED_STATE, "pot_size": 18.0}
    response = approve_job(client, job_id, corrected_state)

    assert response.status_code == 200
    job = response.json()
    assert job["status"] == "approved"
    assert job["approved_state"]["pot_size"] == 18.0
    assert job["error"] is None
    assert FileJobStore(tmp_path).get(job_id).approved_state.pot_size == 18.0


def test_job_image_endpoint_returns_upload(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    upload = upload_job(client)
    job_id = upload.json()["id"]

    image_response = client.get(f"/api/jobs/{job_id}/image")

    assert image_response.status_code == 200
    assert image_response.content == VALID_PNG


def test_job_read_completes_before_concurrent_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    record_path = tmp_path / "jobs" / job_id / "job.json"
    read_started = Event()
    release_read = Event()
    delete_started = Event()
    delete_finished = Event()
    responses: dict[str, object] = {}
    original_read_bytes = Path.read_bytes
    paused = False

    def pause_record_read(path: Path) -> bytes:
        nonlocal paused
        if path == record_path and not paused:
            paused = True
            read_started.set()
            assert release_read.wait(timeout=5)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", pause_record_read)

    read_thread = Thread(
        target=lambda: responses.update(read=client.get(f"/api/jobs/{job_id}")),
    )

    def delete_job() -> None:
        delete_started.set()
        responses["delete"] = client.delete(f"/api/jobs/{job_id}")
        delete_finished.set()

    delete_thread = Thread(target=delete_job)
    read_thread.start()
    assert read_started.wait(timeout=2)
    delete_thread.start()
    try:
        assert delete_started.wait(timeout=2)
        assert not delete_finished.wait(timeout=0.1)
    finally:
        release_read.set()
        read_thread.join(timeout=5)
        delete_thread.join(timeout=5)

    assert not read_thread.is_alive()
    assert not delete_thread.is_alive()
    assert responses["read"].status_code == 200
    assert responses["read"].json()["id"] == job_id
    assert responses["delete"].status_code == 204


def test_job_image_read_completes_before_concurrent_delete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    store = FileJobStore(tmp_path)
    image_path = store.image_path(store.get(job_id))
    read_started = Event()
    release_read = Event()
    delete_started = Event()
    delete_finished = Event()
    responses: dict[str, object] = {}
    original_read_bytes = Path.read_bytes
    paused = False

    def pause_image_read(path: Path) -> bytes:
        nonlocal paused
        if path == image_path and not paused:
            paused = True
            read_started.set()
            assert release_read.wait(timeout=5)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", pause_image_read)

    read_thread = Thread(
        target=lambda: responses.update(
            read=client.get(f"/api/jobs/{job_id}/image"),
        ),
    )

    def delete_job() -> None:
        delete_started.set()
        responses["delete"] = client.delete(f"/api/jobs/{job_id}")
        delete_finished.set()

    delete_thread = Thread(target=delete_job)
    read_thread.start()
    assert read_started.wait(timeout=2)
    delete_thread.start()
    try:
        assert delete_started.wait(timeout=2)
        assert not delete_finished.wait(timeout=0.1)
    finally:
        release_read.set()
        read_thread.join(timeout=5)
        delete_thread.join(timeout=5)

    assert not read_thread.is_alive()
    assert not delete_thread.is_alive()
    assert responses["read"].status_code == 200
    assert responses["read"].content == VALID_PNG
    assert responses["delete"].status_code == 204


def test_delete_rejects_while_benchmark_import_is_pending(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    FileBenchmarkStore(tmp_path).begin_import(
        "pending-import-before-delete",
        b"pending archive",
    )

    response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == "A benchmark dataset import is still pending"
    assert client.get(f"/api/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}/image").content == VALID_PNG


def test_store_persists_jobs_and_rejects_invalid_job_ids(tmp_path: Path) -> None:
    store = FileJobStore(tmp_path)
    job = store.create_job(
        original_filename="table.png",
        image_bytes=VALID_PNG,
        parser_provider="mock",
    )

    reloaded = FileJobStore(tmp_path).get(job.id)

    assert reloaded.id == job.id
    assert reloaded.image_filename == "original.png"
    for invalid_job_id in ["../job", f"{job.id}/../{job.id}", "." * 32, "g" * 32, "abc"]:
        with pytest.raises(JobNotFoundError):
            store.get(invalid_job_id)


def test_invalid_job_id_returns_not_found(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/jobs/not-a-valid-job-id")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_missing_job_mutations_do_not_allocate_per_job_locks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_locks = []

    def counting_lock():
        lock = ThreadLock()
        created_locks.append(lock)
        return lock

    monkeypatch.setattr("app.bootstrap.Lock", counting_lock)
    client = make_client(tmp_path)
    initial_lock_count = len(created_locks)

    for index in range(20):
        job_id = f"{index:032x}"
        responses = (
            client.post(f"/api/jobs/{job_id}/approve", json=APPROVED_STATE),
            client.put(f"/api/jobs/{job_id}/benchmark", json={"included": False}),
        )
        assert all(response.status_code == 404 for response in responses)

    assert initial_lock_count > 0
    assert len(created_locks) == initial_lock_count


def test_image_endpoint_rejects_tampered_image_filename(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    store = FileJobStore(tmp_path)
    job = store.get(job_id)
    job.image_filename = "../outside.png"
    store.save(job)

    response = client.get(f"/api/jobs/{job_id}/image")

    assert response.status_code == 404
    with pytest.raises(JobNotFoundError):
        store.image_path(job)


def test_image_endpoint_returns_not_found_when_image_file_is_missing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    store = FileJobStore(tmp_path)
    job = store.get(job_id)
    store.image_path(job).unlink()

    response = client.get(f"/api/jobs/{job_id}/image")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job image not found"
