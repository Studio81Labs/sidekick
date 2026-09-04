from __future__ import annotations

from datetime import timedelta
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.storage.learning_content_catalog_store as store_module
from app.application.learning_content_catalog import LearningContentCatalog
from app.domain.learning_content import (
    PrincipleLifecycleEvent,
    append_principle_lifecycle_event,
)
from app.player_workspace import PlayerWorkspace
from app.storage.learning_content_catalog_store import (
    FileLearningContentCatalogStore,
    LEARNING_CONTENT_CATALOG_ID,
    MAX_LEARNING_CONTENT_CATALOG_BYTES,
    LearningContentCatalogConflict,
    LearningContentCatalogStorageError,
)
from test_learning_content import (
    NOW,
    approved_record,
    mapping,
    matching_rule,
    taxonomy,
)


def initial_catalog(empty: LearningContentCatalog) -> LearningContentCatalog:
    return LearningContentCatalog(
        catalog_id=empty.catalog_id,
        catalog_revision=1,
        predecessor_catalog_sha256=empty.semantic_digest(),
        taxonomy_lineage=(taxonomy(),),
        mapping_lineage=(mapping(matching_rule()),),
        principles=(approved_record(),),
    )


def test_catalog_retains_current_content_and_complete_lineages() -> None:
    empty = LearningContentCatalog.empty(LEARNING_CONTENT_CATALOG_ID)
    first = initial_catalog(empty)
    second_taxonomy = taxonomy(
        revision="taxonomy-v2",
        predecessor="taxonomy-v1",
        definition_revision="definition-v2",
        definition="A separately versioned current definition.",
    )
    second_mapping = mapping(
        matching_rule(),
        revision="mapping-v2",
        taxonomy_revision="taxonomy-v2",
        predecessor="mapping-v1",
    )
    second = LearningContentCatalog(
        catalog_id=first.catalog_id,
        catalog_revision=2,
        predecessor_catalog_sha256=first.semantic_digest(),
        taxonomy_lineage=(*first.taxonomy_lineage, second_taxonomy),
        mapping_lineage=(*first.mapping_lineage, second_mapping),
        principles=first.principles,
    )

    assert second.current_taxonomy == second_taxonomy
    assert second.current_mapping == second_mapping
    assert second.taxonomy_lineage[0] == first.taxonomy_lineage[0]
    assert second.mapping_lineage[0] == first.mapping_lineage[0]
    assert second.principles == first.principles


def test_catalog_rejects_incomplete_or_incompatible_current_content() -> None:
    empty = LearningContentCatalog.empty(LEARNING_CONTENT_CATALOG_ID)
    with pytest.raises(ValidationError, match="taxonomy and mapping"):
        LearningContentCatalog(
            catalog_id=empty.catalog_id,
            catalog_revision=1,
            predecessor_catalog_sha256=empty.semantic_digest(),
            taxonomy_lineage=(taxonomy(),),
        )

    with pytest.raises(ValidationError, match="current mapping"):
        LearningContentCatalog(
            catalog_id=empty.catalog_id,
            catalog_revision=1,
            predecessor_catalog_sha256=empty.semantic_digest(),
            taxonomy_lineage=(
                taxonomy(),
                taxonomy(
                    revision="taxonomy-v2",
                    predecessor="taxonomy-v1",
                    definition_revision="definition-v2",
                ),
            ),
            mapping_lineage=(mapping(matching_rule()),),
        )

    incompatible = approved_record(definition_revision="unknown-definition")
    with pytest.raises(ValidationError, match="unknown concept definition"):
        LearningContentCatalog(
            catalog_id=empty.catalog_id,
            catalog_revision=1,
            predecessor_catalog_sha256=empty.semantic_digest(),
            taxonomy_lineage=(taxonomy(),),
            mapping_lineage=(mapping(matching_rule()),),
            principles=(incompatible,),
        )

    with pytest.raises(ValidationError, match="taxonomy lineage must begin"):
        LearningContentCatalog(
            catalog_id=empty.catalog_id,
            catalog_revision=1,
            predecessor_catalog_sha256=empty.semantic_digest(),
            taxonomy_lineage=(
                taxonomy(revision="taxonomy-v2", predecessor="taxonomy-v1"),
            ),
            mapping_lineage=(
                mapping(
                    matching_rule(),
                    taxonomy_revision="taxonomy-v2",
                ),
            ),
        )

    approved = approved_record()
    dangling_superseded = append_principle_lifecycle_event(
        approved,
        PrincipleLifecycleEvent(
            sequence=2,
            status="superseded",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=NOW + timedelta(minutes=10),
        ),
    )
    with pytest.raises(ValidationError, match="requires its retained successor"):
        LearningContentCatalog(
            catalog_id=empty.catalog_id,
            catalog_revision=1,
            predecessor_catalog_sha256=empty.semantic_digest(),
            taxonomy_lineage=(taxonomy(),),
            mapping_lineage=(mapping(matching_rule()),),
            principles=(dangling_superseded,),
        )


def test_store_initializes_one_private_fixed_identity_authority(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)

    first = store.initialize_empty()
    second = store.initialize_empty()

    assert first == second == store.load()
    assert first.catalog == LearningContentCatalog.empty(
        LEARNING_CONTENT_CATALOG_ID
    )
    assert first.catalog_sha256 == first.catalog.semantic_digest()
    assert store.path.stat().st_mode & 0o077 == 0
    assert json.loads(store.path.read_text(encoding="utf-8")) == (
        first.model_dump(mode="json", by_alias=True)
    )


def test_store_publishes_append_only_content_with_exact_cas_and_retry(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    successor = initial_catalog(initial.catalog)

    published = store.save(
        successor,
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )
    retried = store.save(
        successor,
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )

    assert published == retried == store.load()
    assert published.catalog == successor
    assert published.catalog_sha256 == successor.semantic_digest()


def test_store_rejects_reinitializing_over_published_authority(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    store.save(
        initial_catalog(initial.catalog),
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )

    with pytest.raises(
        LearningContentCatalogStorageError,
        match="non-empty predecessor",
    ):
        store.initialize_empty()


def test_store_rejects_oversized_successor_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    initial_payload = store.path.read_bytes()
    successor = initial_catalog(initial.catalog)
    successor_state = store_module.LearningContentCatalogState.from_catalog(
        successor
    )
    assert len(initial_payload) < len(store_module._payload(successor_state))
    monkeypatch.setattr(
        store_module,
        "MAX_LEARNING_CONTENT_CATALOG_BYTES",
        len(initial_payload),
    )

    with pytest.raises(LearningContentCatalogStorageError, match="size limit"):
        store.save(
            successor,
            expected_catalog_revision=0,
            expected_catalog_sha256=initial.catalog_sha256,
        )

    assert store.path.read_bytes() == initial_payload


def test_store_retry_makes_a_replaced_successor_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    successor = initial_catalog(initial.catalog)
    real_fsync_directory = store_module._fsync_directory

    def fail_directory_fsync(_path: Path) -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(store_module, "_fsync_directory", fail_directory_fsync)
    with pytest.raises(LearningContentCatalogStorageError, match="durably write"):
        store.save(
            successor,
            expected_catalog_revision=0,
            expected_catalog_sha256=initial.catalog_sha256,
        )
    assert store.load().catalog == successor

    monkeypatch.setattr(store_module, "_fsync_directory", real_fsync_directory)
    assert (
        store.save(
            successor,
            expected_catalog_revision=0,
            expected_catalog_sha256=initial.catalog_sha256,
        ).catalog
        == successor
    )


def test_player_workspace_loads_and_publishes_current_content(
    tmp_path: Path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    current = workspace.current_learning_content_catalog()
    successor = initial_catalog(current.catalog)

    published = workspace.publish_learning_content_catalog(
        successor,
        expected_catalog_revision=current.catalog.catalog_revision,
        expected_catalog_sha256=current.catalog_sha256,
    )

    assert published == workspace.current_learning_content_catalog()
    assert published.catalog.current_taxonomy == taxonomy()


def test_store_rejects_stale_or_rewritten_history_without_overwrite(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    first = initial_catalog(initial.catalog)
    first_state = store.save(
        first,
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )
    retired = append_principle_lifecycle_event(
        first.principles[0],
        PrincipleLifecycleEvent(
            sequence=2,
            status="retired",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=NOW + timedelta(minutes=10),
        ),
    )
    second = first.model_copy(
        update={
            "catalog_revision": 2,
            "predecessor_catalog_sha256": first.semantic_digest(),
            "principles": (retired,),
        }
    )

    with pytest.raises(LearningContentCatalogConflict, match="stale"):
        store.save(
            second,
            expected_catalog_revision=0,
            expected_catalog_sha256=initial.catalog_sha256,
        )
    assert store.load() == first_state

    rewritten_root = taxonomy(definition="Rewritten under the same identity.")
    rewritten = LearningContentCatalog(
        catalog_id=first.catalog_id,
        catalog_revision=2,
        predecessor_catalog_sha256=first.semantic_digest(),
        taxonomy_lineage=(rewritten_root,),
        mapping_lineage=first.mapping_lineage,
        principles=(),
    )
    with pytest.raises(LearningContentCatalogConflict, match="revision history"):
        store.save(
            rewritten,
            expected_catalog_revision=1,
            expected_catalog_sha256=first_state.catalog_sha256,
        )
    assert store.load() == first_state


def test_store_publishes_current_principle_lifecycle_without_rewriting_content(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    first = initial_catalog(initial.catalog)
    first_state = store.save(
        first,
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )
    retired = append_principle_lifecycle_event(
        first.principles[0],
        PrincipleLifecycleEvent(
            sequence=2,
            status="retired",
            actor_kind="human",
            actor_id="reviewer-1",
            occurred_at=NOW + timedelta(minutes=10),
        ),
    )
    second = LearningContentCatalog(
        catalog_id=first.catalog_id,
        catalog_revision=2,
        predecessor_catalog_sha256=first.semantic_digest(),
        taxonomy_lineage=first.taxonomy_lineage,
        mapping_lineage=first.mapping_lineage,
        principles=(retired,),
    )

    published = store.save(
        second,
        expected_catalog_revision=1,
        expected_catalog_sha256=first_state.catalog_sha256,
    )

    assert published.catalog.principles[0].principle == (
        first.principles[0].principle
    )
    assert published.catalog.principles[0].lifecycle[:-1] == (
        first.principles[0].lifecycle
    )
    assert published.catalog.principles[0].current_status == "retired"


def test_store_rejects_principle_lifecycle_rewrite_or_removal(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    initial = store.initialize_empty()
    first = initial_catalog(initial.catalog)
    first_state = store.save(
        first,
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )
    rewritten = approved_record()
    rewritten_event = rewritten.lifecycle[1].model_copy(
        update={"actor_id": "different-reviewer"}
    )
    rewritten = rewritten.model_copy(
        update={"lifecycle": (rewritten.lifecycle[0], rewritten_event)}
    )
    successor = LearningContentCatalog(
        catalog_id=first.catalog_id,
        catalog_revision=2,
        predecessor_catalog_sha256=first.semantic_digest(),
        taxonomy_lineage=first.taxonomy_lineage,
        mapping_lineage=first.mapping_lineage,
        principles=(rewritten,),
    )

    with pytest.raises(LearningContentCatalogConflict, match="principle history"):
        store.save(
            successor,
            expected_catalog_revision=1,
            expected_catalog_sha256=first_state.catalog_sha256,
        )

    removed = successor.model_copy(update={"principles": ()})
    with pytest.raises(LearningContentCatalogConflict, match="principle history"):
        store.save(
            removed,
            expected_catalog_revision=1,
            expected_catalog_sha256=first_state.catalog_sha256,
        )
    assert store.load() == first_state


def test_store_rejects_foreign_tampered_or_oversized_state(
    tmp_path: Path,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    state = store.initialize_empty()
    payload = state.model_dump(mode="json", by_alias=True)
    payload["catalog"]["catalog_id"] = "foreign-learning-content"
    foreign = LearningContentCatalog.empty("foreign-learning-content")
    payload["catalog_sha256"] = foreign.semantic_digest()
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    store.path.chmod(0o600)
    with pytest.raises(
        LearningContentCatalogStorageError,
        match="malformed or unsupported",
    ):
        store.load()

    store.path.write_bytes(b"not-json")
    store.path.chmod(0o600)
    with pytest.raises(
        LearningContentCatalogStorageError,
        match="malformed or unsupported",
    ):
        store.load()

    store.path.write_bytes(b"x" * (MAX_LEARNING_CONTENT_CATALOG_BYTES + 1))
    store.path.chmod(0o600)
    with pytest.raises(LearningContentCatalogStorageError, match="size limit"):
        store.load()


def test_store_rejects_shared_foreign_or_symlinked_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    store.initialize_empty()

    store.path.chmod(0o644)
    with pytest.raises(LearningContentCatalogStorageError, match="only by its owner"):
        store.load()
    store.path.chmod(0o600)

    if hasattr(os, "getuid"):
        actual_uid = os.getuid()
        monkeypatch.setattr(store_module.os, "getuid", lambda: actual_uid + 1)
        with pytest.raises(LearningContentCatalogStorageError, match="current user"):
            store.load()
        monkeypatch.setattr(store_module.os, "getuid", lambda: actual_uid)

    target = tmp_path / "outside-learning-content"
    target.write_bytes(store.path.read_bytes())
    target.chmod(0o600)
    store.path.unlink()
    store.path.symlink_to(target)
    with pytest.raises(LearningContentCatalogStorageError, match="safely open"):
        store.load()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
def test_store_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    store = FileLearningContentCatalogStore(tmp_path)
    os.mkfifo(store.path, mode=0o600)

    with pytest.raises(LearningContentCatalogStorageError, match="regular file"):
        store.load()
