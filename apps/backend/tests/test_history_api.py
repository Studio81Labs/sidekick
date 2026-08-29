from pathlib import Path
from threading import Event, Thread

import pytest

from app.storage.file_job_store import FileJobStore
from api_test_support import (
    APPROVED_STATE,
    approve_job,
    make_client,
    mark_legacy_player,
    upload_job,
)


def test_history_persists_only_explicitly_archived_ready_jobs(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    parsed_id = upload_job(client, filename="parsed.png").json()["id"]
    first_id = upload_job(client, filename="first.png").json()["id"]
    second_id = upload_job(client, filename="second.png").json()["id"]
    mark_legacy_player(tmp_path, second_id)
    approve_job(client, first_id)
    approve_job(client, second_id)
    client.post(f"/api/jobs/{second_id}/recommend")

    empty_history = client.get("/api/history")
    rejected = client.put("/api/history", json={"job_ids": [parsed_id]})
    archived = client.put(
        "/api/history",
        json={"job_ids": [first_id, second_id]},
    )

    assert empty_history.status_code == 200
    assert empty_history.json()["total"] == 0
    assert empty_history.json()["jobs"] == []
    assert empty_history.json()["snapshot_version"]
    assert rejected.status_code == 409
    assert rejected.json()["detail"] == (
        "Only successful approved or recommended jobs can be moved to history"
    )
    assert FileJobStore(tmp_path).get(parsed_id).archived_at is None
    assert archived.status_code == 200
    history = archived.json()
    assert history["total"] == 2
    assert [job["id"] for job in history["jobs"]] == [second_id, first_id]
    assert all(job["archived_at"] for job in history["jobs"])

    store = FileJobStore(tmp_path)
    replayed_job = store.get(first_id)
    persisted_at = replayed_job.archived_at
    replayed_job.status = "error"
    replayed_job.error = "Later archived review failed"
    store.save(replayed_job)
    repeated = client.put("/api/history?limit=1", json={"job_ids": [first_id]})

    assert repeated.status_code == 200
    assert repeated.json()["total"] == 2
    assert len(repeated.json()["jobs"]) == 1
    assert store.get(first_id).archived_at == persisted_at


def test_history_archive_is_atomic_when_a_job_is_missing(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        "/api/history",
        json={"job_ids": [job_id, "f" * 32]},
    )

    assert response.status_code == 404
    empty_history = client.get("/api/history").json()
    assert empty_history["total"] == 0
    assert empty_history["jobs"] == []
    assert FileJobStore(tmp_path).get(job_id).archived_at is None


def test_processing_queue_waits_for_batch_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    job_ids = [
        upload_job(client, filename=f"archive-{index}.png").json()["id"]
        for index in range(2)
    ]
    for job_id in job_ids:
        approve_job(client, job_id)

    first_archive_saved = Event()
    release_archive = Event()
    processing_finished = Event()
    responses: dict[str, object] = {}
    original_save = FileJobStore.save

    def paused_save(store: FileJobStore, job):
        saved = original_save(store, job)
        if job.archived_at is not None and not first_archive_saved.is_set():
            first_archive_saved.set()
            assert release_archive.wait(timeout=2)
        return saved

    monkeypatch.setattr(FileJobStore, "save", paused_save)
    archive_thread = Thread(
        target=lambda: responses.update(
            archive=client.put("/api/history", json={"job_ids": job_ids}),
        ),
    )

    def read_processing_queue() -> None:
        responses["processing"] = client.get("/api/jobs")
        processing_finished.set()

    processing_thread = Thread(target=read_processing_queue)
    archive_thread.start()
    try:
        assert first_archive_saved.wait(timeout=2)
        processing_thread.start()
        assert not processing_finished.wait(timeout=0.1)
    finally:
        release_archive.set()
        archive_thread.join(timeout=2)
        processing_thread.join(timeout=2)

    assert not archive_thread.is_alive()
    assert not processing_thread.is_alive()
    assert responses["archive"].status_code == 200
    assert responses["processing"].status_code == 200
    assert responses["processing"].json()["total"] == 0
    assert responses["processing"].json()["jobs"] == []


def test_history_pages_archived_jobs_in_stable_newest_first_order(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    job_ids = [
        upload_job(client, filename=f"history-{index}.png").json()["id"]
        for index in range(4)
    ]
    for job_id in job_ids:
        approve_job(client, job_id)
    archived = client.put("/api/history", json={"job_ids": job_ids})

    first_page = client.get("/api/history?limit=2")
    page = client.get("/api/history?limit=2&offset=1")
    store = FileJobStore(tmp_path)
    changed_job = store.get(job_ids[0])
    changed_job.training_review_note = "Snapshot content changed."
    store.save(changed_job)
    changed_page = client.get("/api/history?limit=2")

    assert archived.status_code == 200
    assert first_page.status_code == 200
    assert page.status_code == 200
    assert page.json()["total"] == 4
    assert first_page.json()["snapshot_version"] == page.json()["snapshot_version"]
    assert [job["id"] for job in page.json()["jobs"]] == [
        job_ids[2],
        job_ids[1],
    ]
    assert changed_page.json()["snapshot_version"] != page.json()["snapshot_version"]
    assert client.get("/api/history?offset=-1").status_code == 422


def test_history_scan_does_not_block_an_unarchived_job_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    archived_id = upload_job(client, filename="archived.png").json()["id"]
    active_id = upload_job(client, filename="active.png").json()["id"]
    approve_job(client, archived_id)
    client.put("/api/history", json={"job_ids": [archived_id]})

    history_started = Event()
    release_history = Event()
    approval_finished = Event()
    responses: dict[str, object] = {}
    original_list = FileJobStore.list

    def paused_list(store: FileJobStore):
        jobs = original_list(store)
        history_started.set()
        assert release_history.wait(timeout=2)
        return jobs

    monkeypatch.setattr(FileJobStore, "list", paused_list)

    history_thread = Thread(
        target=lambda: responses.update(history=client.get("/api/history")),
    )

    def run_approval() -> None:
        responses["approval"] = approve_job(client, active_id)
        approval_finished.set()

    approval_thread = Thread(target=run_approval)
    history_thread.start()
    try:
        assert history_started.wait(timeout=2)
        approval_thread.start()
        assert approval_finished.wait(timeout=1)
    finally:
        release_history.set()
        history_thread.join(timeout=2)
        approval_thread.join(timeout=2)

    assert not history_thread.is_alive()
    assert not approval_thread.is_alive()
    assert responses["history"].status_code == 200
    assert responses["approval"].status_code == 200


def test_history_scan_serializes_an_archived_job_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client, filename="archived.png").json()["id"]
    approve_job(client, job_id)
    client.put("/api/history", json={"job_ids": [job_id]})

    history_started = Event()
    release_history = Event()
    approval_started = Event()
    approval_finished = Event()
    responses: dict[str, object] = {}
    original_list = FileJobStore.list

    def paused_list(store: FileJobStore):
        jobs = original_list(store)
        history_started.set()
        assert release_history.wait(timeout=2)
        return jobs

    monkeypatch.setattr(FileJobStore, "list", paused_list)

    history_thread = Thread(
        target=lambda: responses.update(history=client.get("/api/history")),
    )
    corrected_state = {**APPROVED_STATE, "pot_size": 21.0}

    def run_approval() -> None:
        approval_started.set()
        responses["approval"] = approve_job(client, job_id, corrected_state)
        approval_finished.set()

    approval_thread = Thread(target=run_approval)
    history_thread.start()
    try:
        assert history_started.wait(timeout=2)
        approval_thread.start()
        assert approval_started.wait(timeout=2)
        assert not approval_finished.wait(timeout=0.1)
    finally:
        release_history.set()
        history_thread.join(timeout=2)
        approval_thread.join(timeout=2)

    assert not history_thread.is_alive()
    assert not approval_thread.is_alive()
    assert responses["history"].status_code == 200
    assert responses["history"].json()["jobs"][0]["approved_state"]["pot_size"] == 12.5
    assert responses["approval"].status_code == 200
    assert responses["approval"].json()["approved_state"]["pot_size"] == 21


def test_history_searches_archived_poker_context_before_paging(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    matching_id = upload_job(client, filename="river-bluff.png").json()["id"]
    other_id = upload_job(client, filename="value-line.png").json()["id"]
    mark_legacy_player(tmp_path, matching_id)
    mark_legacy_player(tmp_path, other_id)
    matching_state = {
        **APPROVED_STATE,
        "hero_cards": [
            {"rank": "7", "suit": "diamonds"},
            {"rank": "A", "suit": "hearts"},
        ],
        "street": "turn",
    }
    approve_job(client, matching_id, matching_state)
    approve_job(client, other_id)
    client.post(f"/api/jobs/{matching_id}/recommend")
    client.post(f"/api/jobs/{other_id}/recommend")
    client.put(
        "/api/history",
        json={"job_ids": [matching_id, other_id]},
    )

    poker_terms = client.get(
        "/api/history",
        params={"query": "7♦ TURN call", "limit": 1},
    )
    filename = client.get(
        "/api/history",
        params={"query": "RIVER-BLUFF"},
    )
    no_match = client.get(
        "/api/history",
        params={"query": "river raise"},
    )
    separator_only = client.get(
        "/api/history",
        params={"query": ", ,"},
    )

    assert poker_terms.status_code == 200
    assert poker_terms.json()["total"] == 1
    assert [job["id"] for job in poker_terms.json()["jobs"]] == [matching_id]
    assert [job["id"] for job in filename.json()["jobs"]] == [matching_id]
    assert no_match.json()["total"] == 0
    assert no_match.json()["jobs"] == []
    assert separator_only.status_code == 200
    assert separator_only.json()["total"] == 0
    assert separator_only.json()["jobs"] == []
    assert client.get(
        "/api/history",
        params={"query": "x" * 101},
    ).status_code == 422


def test_history_card_queries_do_not_match_recommendation_prose(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, recommendation_provider="rule_based")
    ace_spades_id = upload_job(client, filename="ace-spades.png").json()["id"]
    other_id = upload_job(client, filename="other-hand.png").json()["id"]
    mark_legacy_player(tmp_path, ace_spades_id)
    mark_legacy_player(tmp_path, other_id)
    ace_spades_state = {
        **APPROVED_STATE,
        "hero_cards": [
            {"rank": "A", "suit": "spades"},
            {"rank": "K", "suit": "diamonds"},
        ],
    }
    other_state = {
        **APPROVED_STATE,
        "hero_cards": [
            {"rank": "Q", "suit": "clubs"},
            {"rank": "K", "suit": "diamonds"},
        ],
    }
    approve_job(client, ace_spades_id, ace_spades_state)
    approve_job(client, other_id, other_state)
    client.post(f"/api/jobs/{ace_spades_id}/recommend")
    client.post(f"/api/jobs/{other_id}/recommend")
    store = FileJobStore(tmp_path)
    other_job = store.get(other_id)
    other_job.training_review_note = (
        "Play as bluff when blockers support it. Ah, I missed the draw."
    )
    store.save(other_job)
    client.put(
        "/api/history",
        json={"job_ids": [ace_spades_id, other_id]},
    )

    for card_query in (
        "A♠",
        "a♠",
        "A♠︎",
        "A♠️",
        "As",
        "AsKd",
        "askd",
        "A♠K♦",
        "As,Kd",
        "as,kd",
        "A♠,K♦",
    ):
        response = client.get("/api/history", params={"query": card_query})

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert [job["id"] for job in response.json()["jobs"]] == [ace_spades_id]

    prose_response = client.get(
        "/api/history",
        params={"query": "play as bluff"},
    )

    assert prose_response.status_code == 200
    assert prose_response.json()["total"] == 1
    assert [job["id"] for job in prose_response.json()["jobs"]] == [other_id]

    lowercase_prose_response = client.get(
        "/api/history",
        params={"query": "ah"},
    )
    canonical_card_response = client.get(
        "/api/history",
        params={"query": "Ah"},
    )

    assert lowercase_prose_response.status_code == 200
    assert lowercase_prose_response.json()["total"] == 1
    assert [job["id"] for job in lowercase_prose_response.json()["jobs"]] == [
        other_id
    ]
    assert canonical_card_response.status_code == 200
    assert canonical_card_response.json()["total"] == 0


def test_history_card_queries_match_screenshot_metadata_only(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    metadata_id = upload_job(
        client,
        filename="metadata-card-terms.png",
    ).json()["id"]
    prose_id = upload_job(
        client,
        filename="prose-card-terms.png",
    ).json()["id"]
    state_without_metadata_cards = {
        **APPROVED_STATE,
        "hero_cards": [
            {"rank": "Q", "suit": "clubs"},
            {"rank": "J", "suit": "spades"},
        ],
        "board_cards": [
            {"rank": "2", "suit": "hearts"},
            {"rank": "3", "suit": "diamonds"},
            {"rank": "4", "suit": "clubs"},
        ],
    }
    approve_job(client, metadata_id, state_without_metadata_cards)
    approve_job(client, prose_id, state_without_metadata_cards)
    metadata = client.put(
        f"/api/jobs/{metadata_id}/metadata",
        json={
            "title": "Ah bluff Th",
            "notes": "Review the Kd blocker with 10s",
            "tags": ["Qs study"],
        },
    )
    store = FileJobStore(tmp_path)
    prose_job = store.get(prose_id)
    prose_job.training_review_note = "Ah Kd Qs appeared only in review prose."
    store.save(prose_job)
    client.put(
        "/api/history",
        json={"job_ids": [metadata_id, prose_id]},
    )

    assert metadata.status_code == 200
    for query in (
        "Ah",
        "Kd",
        "Qs",
        "Ah bluff",
        "Kd blocker",
        "Qs study",
        "Th",
        "10h",
        "10h bluff",
        "10s",
        "Ts",
        "Ts blocker",
    ):
        response = client.get("/api/history", params={"query": query})

        assert response.status_code == 200
        assert response.json()["total"] == 1
        assert [job["id"] for job in response.json()["jobs"]] == [metadata_id]


def test_history_rejects_duplicate_job_ids(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    job_id = upload_job(client).json()["id"]
    approve_job(client, job_id)

    response = client.put(
        "/api/history",
        json={"job_ids": [job_id, job_id]},
    )

    assert response.status_code == 422
    empty_history = client.get("/api/history").json()
    assert empty_history["total"] == 0
    assert empty_history["jobs"] == []
