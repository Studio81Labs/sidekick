from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

import app.storage.reference_activation_catalog_store as store_module
from app.application.reference_activation import ReferenceActivationCatalog
from app.domain.learning_content import DecisionSelector
from app.player_workspace import PlayerWorkspace
from app.storage.reference_activation_catalog_store import (
    FileReferenceActivationCatalogStore,
    MAX_REFERENCE_ACTIVATION_CATALOG_BYTES,
    REFERENCE_ACTIVATION_CATALOG_FILENAME,
    REFERENCE_ACTIVATION_CATALOG_ID,
    ReferenceActivationCatalogConflict,
    ReferenceActivationCatalogStorageError,
)
from test_reference_activation import (
    activate,
    coverage_band,
    readiness,
    rewrite_activation,
)


def test_store_initializes_one_private_canonical_empty_catalog(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)

    first = store.initialize_empty()
    second = store.initialize_empty()

    assert first == second == store.load()
    assert first.catalog == ReferenceActivationCatalog.empty(
        REFERENCE_ACTIVATION_CATALOG_ID
    )
    assert first.catalog_sha256 == first.catalog.semantic_digest()
    assert store.path.stat().st_mode & 0o077 == 0
    assert json.loads(store.path.read_text(encoding="utf-8")) == (
        first.model_dump(mode="json", by_alias=True)
    )


def test_store_publishes_one_append_with_exact_compare_and_swap(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    initial = store.initialize_empty()
    successor = activate(initial.catalog, readiness())

    published = store.save(
        successor,
        expected_catalog_revision=initial.catalog.catalog_revision,
        expected_catalog_sha256=initial.catalog_sha256,
    )

    assert published == store.load()
    assert published.catalog == successor
    assert published.catalog_sha256 == successor.semantic_digest()

    retried = store.save(
        successor,
        expected_catalog_revision=initial.catalog.catalog_revision,
        expected_catalog_sha256=initial.catalog_sha256,
    )
    assert retried == published


def test_player_workspace_loads_and_publishes_current_catalog(
    tmp_path: Path,
) -> None:
    workspace = PlayerWorkspace.open(tmp_path)
    current = workspace.current_reference_activation_catalog()
    successor = activate(current.catalog, readiness())

    published = workspace.publish_reference_activation_catalog(
        successor,
        expected_catalog_revision=current.catalog.catalog_revision,
        expected_catalog_sha256=current.catalog_sha256,
    )

    assert published == workspace.current_reference_activation_catalog()
    assert published.catalog == successor


def test_store_rejects_stale_or_divergent_publication_without_overwrite(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    initial = store.initialize_empty()
    evidence = readiness()
    first = activate(initial.catalog, evidence)
    first_state = store.save(
        first,
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )
    second = activate(
        first,
        evidence,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    with pytest.raises(ReferenceActivationCatalogConflict, match="stale"):
        store.save(
            second,
            expected_catalog_revision=0,
            expected_catalog_sha256=initial.catalog_sha256,
        )
    assert store.load() == first_state

    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="publication is not canonical",
    ):
        store.save(
            second,
            expected_catalog_revision=False,
            expected_catalog_sha256=first_state.catalog_sha256,
        )
    assert store.load() == first_state

    alternate_first = activate(
        initial.catalog,
        evidence,
        activation_id="alternate-activation-1",
        mastery_series_id="alternate-mastery-series-1",
    )
    alternate_second = activate(
        alternate_first,
        evidence,
        activation_id="alternate-activation-2",
        mastery_series_id="alternate-mastery-series-2",
    )
    with pytest.raises(ReferenceActivationCatalogConflict, match="append exactly"):
        store.save(
            alternate_second,
            expected_catalog_revision=first.catalog_revision,
            expected_catalog_sha256=first_state.catalog_sha256,
        )
    assert store.load() == first_state


def test_store_rejects_reinitializing_over_published_authority(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    initial = store.initialize_empty()
    store.save(
        activate(initial.catalog, readiness()),
        expected_catalog_revision=0,
        expected_catalog_sha256=initial.catalog_sha256,
    )

    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="non-empty predecessor",
    ):
        store.initialize_empty()


def test_store_rejects_oversized_successor_without_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    initial = store.initialize_empty()
    initial_payload = store.path.read_bytes()
    successor = activate(initial.catalog, readiness())
    successor_state = store_module.ReferenceActivationCatalogState.from_catalog(
        successor
    )
    assert len(initial_payload) < len(store_module._payload(successor_state))
    monkeypatch.setattr(
        store_module,
        "MAX_REFERENCE_ACTIVATION_CATALOG_BYTES",
        len(initial_payload),
    )

    with pytest.raises(ReferenceActivationCatalogStorageError, match="size limit"):
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
    store = FileReferenceActivationCatalogStore(tmp_path)
    initial = store.initialize_empty()
    successor = activate(initial.catalog, readiness())
    real_fsync_directory = store_module._fsync_directory

    def fail_directory_fsync(_path: Path) -> None:
        raise OSError("injected directory fsync failure")

    monkeypatch.setattr(store_module, "_fsync_directory", fail_directory_fsync)
    with pytest.raises(ReferenceActivationCatalogStorageError, match="durably write"):
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


def test_store_rejects_tampered_malformed_or_oversized_state(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    store.initialize_empty()
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    payload["catalog"]["catalog_id"] = "forged-catalog"
    store.path.write_text(json.dumps(payload), encoding="utf-8")
    store.path.chmod(0o600)

    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="malformed or unsupported",
    ):
        store.load()

    store.path.write_bytes(b"not-json")
    store.path.chmod(0o600)
    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="malformed or unsupported",
    ):
        store.load()

    store.path.write_bytes(b"x" * (MAX_REFERENCE_ACTIVATION_CATALOG_BYTES + 1))
    store.path.chmod(0o600)
    with pytest.raises(ReferenceActivationCatalogStorageError, match="size limit"):
        store.load()


def test_store_rejects_self_consistent_foreign_catalog_identity(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    foreign = ReferenceActivationCatalog.empty("foreign-reference-activation")
    store.path.write_text(
        json.dumps(
            {
                "schema": store_module.REFERENCE_ACTIVATION_CATALOG_SCHEMA,
                "schema_version": (
                    store_module.REFERENCE_ACTIVATION_CATALOG_SCHEMA_VERSION
                ),
                "catalog_sha256": foreign.semantic_digest(),
                "catalog": foreign.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    store.path.chmod(0o600)

    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="malformed or unsupported",
    ):
        store.load()


def test_store_rejects_history_with_an_invalid_catalog_prefix(
    tmp_path: Path,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    evidence = readiness()
    first = activate(
        ReferenceActivationCatalog.empty(REFERENCE_ACTIVATION_CATALOG_ID),
        evidence,
    ).activations[0]
    second = rewrite_activation(
        first,
        sequence=2,
        activation_id="activation-2",
        predecessor_activation_sha256=first.activation_sha256,
        coverage_band=coverage_band(
            evidence,
            coverage_band_id="cash.preflop.bb-defense.alias",
        ),
        mastery_series_id="mastery-series-2",
    )
    third = rewrite_activation(
        second,
        sequence=3,
        activation_id="activation-3",
        predecessor_activation_sha256=second.activation_sha256,
        coverage_band=coverage_band(
            evidence,
            coverage_band_id="cash.preflop.bb-defense.alias",
            selector=DecisionSelector(street="flop"),
        ),
        mastery_series_id="mastery-series-3",
    )
    forged = ReferenceActivationCatalog.model_construct(
        catalog_id=REFERENCE_ACTIVATION_CATALOG_ID,
        catalog_revision=3,
        activations=(first, second, third),
        active_activation_ids=(first.activation_id, third.activation_id),
    )
    with pytest.raises(ValidationError, match="every catalog revision"):
        ReferenceActivationCatalog.model_validate(
            forged.model_dump(mode="python")
        )
    store.path.write_text(
        json.dumps(
            {
                "schema": store_module.REFERENCE_ACTIVATION_CATALOG_SCHEMA,
                "schema_version": (
                    store_module.REFERENCE_ACTIVATION_CATALOG_SCHEMA_VERSION
                ),
                "catalog_sha256": forged.semantic_digest(),
                "catalog": forged.model_dump(mode="json"),
            }
        ),
        encoding="utf-8",
    )
    store.path.chmod(0o600)

    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="malformed or unsupported",
    ):
        store.load()


def test_store_rejects_shared_foreign_or_symlinked_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    store.initialize_empty()

    store.path.chmod(0o644)
    with pytest.raises(
        ReferenceActivationCatalogStorageError,
        match="only by its owner",
    ):
        store.load()

    store.path.chmod(0o600)
    if hasattr(os, "getuid"):
        actual_uid = os.getuid()
        monkeypatch.setattr(store_module.os, "getuid", lambda: actual_uid + 1)
        with pytest.raises(
            ReferenceActivationCatalogStorageError,
            match="current user",
        ):
            store.load()
        monkeypatch.setattr(store_module.os, "getuid", lambda: actual_uid)

    target = tmp_path / "outside-reference-catalog"
    target.write_bytes(store.path.read_bytes())
    target.chmod(0o600)
    store.path.unlink()
    store.path.symlink_to(target)
    with pytest.raises(ReferenceActivationCatalogStorageError, match="safely open"):
        store.load()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
def test_store_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    store = FileReferenceActivationCatalogStore(tmp_path)
    os.mkfifo(store.path, mode=0o600)

    with pytest.raises(ReferenceActivationCatalogStorageError, match="regular file"):
        store.load()
