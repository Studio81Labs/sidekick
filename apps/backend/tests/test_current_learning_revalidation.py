from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from threading import Event, Thread

import pytest

import app.player_workspace as player_workspace_module
from app.application.imported_hand_lifecycle import ImportedHandLifecycleService
from app.application.reference_activation import (
    ReferenceActivatedGrade,
    ReferenceActivationCatalog,
    bind_grade_to_active_reference,
)
from app.domain.imported_hands import DeletionReceipt, extract_hero_decision_points
from app.player_hands import PlayerHandCloseRequest
from app.player_workspace import PlayerHandDecisionsUnavailable, PlayerWorkspace
from app.storage.imported_hand_store import (
    GradeArtifactRetentionError,
    GRADES_DIRNAME,
    ImportedHandCascade,
    imported_hand_record_key,
)
from test_imported_hand_decisions import baseline_decision_record
from test_reference_activation import (
    activate,
    current_learning_content,
    readiness,
)


def configured_workspace(
    data_dir: Path,
) -> tuple[
    PlayerWorkspace,
    str,
    ReferenceActivatedGrade,
    ReferenceActivationCatalog,
]:
    workspace = PlayerWorkspace.open(data_dir)
    record = baseline_decision_record()
    record_key = imported_hand_record_key(record.identity)
    extraction = extract_hero_decision_points(record)
    workspace.imported_hands.save(record_key, record)
    workspace.imported_hands.save_decisions(record_key, extraction)

    content_evidence = readiness()
    assert extraction.decision_points[0] == (
        content_evidence.decision_snapshot.restore()
    )
    content_state = workspace.current_learning_content_catalog()
    content = current_learning_content(
        content_evidence,
        catalog_id=content_state.catalog.catalog_id,
    )
    workspace.publish_learning_content_catalog(
        content,
        expected_catalog_revision=content_state.catalog.catalog_revision,
        expected_catalog_sha256=content_state.catalog_sha256,
    )

    reference_state = workspace.current_reference_activation_catalog()
    catalog = activate(reference_state.catalog, content_evidence)
    workspace.publish_reference_activation_catalog(
        catalog,
        expected_catalog_revision=reference_state.catalog.catalog_revision,
        expected_catalog_sha256=reference_state.catalog_sha256,
    )
    retained = bind_grade_to_active_reference(
        catalog,
        content_evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    return workspace, record_key, retained, catalog


def test_workspace_revalidates_one_coherent_current_authority_scope(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)

    result = workspace.revalidate_reference_activated_grade(
        record_key,
        retained,
    )

    assert result == retained
    assert result.learning_eligibility == (
        "requires_current_catalog_hand_and_content"
    )


def test_workspace_persists_revalidated_grade_as_idempotent_audit_evidence(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)

    first = workspace.persist_current_reference_activated_grade(
        record_key,
        retained,
    )
    second = workspace.persist_current_reference_activated_grade(
        record_key,
        retained,
    )

    assert first == retained
    assert second == retained
    artifacts = workspace.imported_hands.list_reference_activated_grade_artifacts(
        record_key
    )
    assert len(artifacts) == 1
    revision, generation, decision_index, filename = artifacts[0]
    assert (revision, generation, decision_index) == (1, 0, 0)
    assert workspace.imported_hands.get_reference_activated_grade(
        record_key,
        filename,
    ) == retained
    assert first.learning_eligibility == (
        "requires_current_catalog_hand_and_content"
    )


def test_grade_retention_refuses_different_bytes_at_one_authority_identity(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, retained)
    *_, filename = (
        workspace.imported_hands.list_reference_activated_grade_artifacts(
            record_key
        )[0]
    )
    path = (
        workspace.imported_hands.records_dir
        / record_key
        / GRADES_DIRNAME
        / filename
    )
    path.write_bytes(
        json.dumps(json.loads(path.read_bytes()), separators=(",", ":")).encode()
    )

    with pytest.raises(GradeArtifactRetentionError):
        workspace.persist_current_reference_activated_grade(record_key, retained)

    assert workspace.imported_hands.get_reference_activated_grade(
        record_key,
        filename,
    ) == retained


def test_permanent_hand_purge_removes_retained_grade_evidence(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, retained)
    record = workspace.imported_hands.get(record_key)
    requested_at = record.lifecycle.changed_at + timedelta(minutes=1)
    deleted_at = requested_at + timedelta(minutes=1)
    lifecycle = ImportedHandLifecycleService(
        store=workspace.imported_hands,
        extract=extract_hero_decision_points,
        now=lambda: requested_at,
    )
    pending = lifecycle.request_deletion(
        record_key,
        reason="Remove all hand-linked learning evidence.",
        at=requested_at,
    )

    lifecycle.purge(
        record_key,
        receipt=DeletionReceipt(
            receipt_id="delete-grade-evidence",
            generation=pending.lifecycle.deletion_generation,
            deleted_at=deleted_at,
            tombstone_sha256="d" * 64,
        ),
    )

    assert workspace.imported_hands.list_decision_artifacts(record_key) == []
    assert (
        workspace.imported_hands.list_reference_activated_grade_artifacts(
            record_key
        )
        == []
    )


def test_workspace_refuses_to_persist_after_hand_deactivation(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    record = workspace.imported_hands.get(record_key)
    workspace.close_hand_record(
        record_key,
        action="withdraw",
        request=PlayerHandCloseRequest(
            reason="Make retained evidence stale before persistence.",
            expected_active_canonical_revision=(
                record.lifecycle.active_canonical_revision
            ),
            expected_deletion_generation=record.lifecycle.deletion_generation,
            expected_lifecycle_changed_at=record.lifecycle.changed_at,
        ),
        at=record.lifecycle.changed_at + timedelta(minutes=1),
    )

    with pytest.raises(PlayerHandDecisionsUnavailable):
        workspace.persist_current_reference_activated_grade(record_key, retained)

    assert (
        workspace.imported_hands.list_reference_activated_grade_artifacts(
            record_key
        )
        == []
    )


def test_workspace_persistence_keeps_authority_locks_through_grade_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, record_key, retained, catalog = configured_workspace(tmp_path)
    record = workspace.imported_hands.get(record_key)
    grade_staged = Event()
    release_commit = Event()
    publication_started = Event()
    publication_finished = Event()
    close_started = Event()
    close_finished = Event()
    results: list[ReferenceActivatedGrade] = []
    failures: list[Exception] = []
    real_stage = ImportedHandCascade.stage_reference_activated_grade

    def paused_stage(
        cascade: ImportedHandCascade,
        grade: ReferenceActivatedGrade,
    ) -> None:
        real_stage(cascade, grade)
        grade_staged.set()
        if not release_commit.wait(timeout=5):
            raise AssertionError("test did not release grade commit")

    monkeypatch.setattr(
        ImportedHandCascade,
        "stage_reference_activated_grade",
        paused_stage,
    )

    def persist_grade() -> None:
        try:
            results.append(
                workspace.persist_current_reference_activated_grade(
                    record_key,
                    retained,
                )
            )
        except Exception as exc:
            failures.append(exc)

    successor = activate(
        catalog,
        retained.readiness,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    def publish_successor() -> None:
        publication_started.set()
        try:
            workspace.publish_reference_activation_catalog(
                successor,
                expected_catalog_revision=catalog.catalog_revision,
                expected_catalog_sha256=catalog.semantic_digest(),
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            publication_finished.set()

    def close_hand() -> None:
        close_started.set()
        try:
            workspace.close_hand_record(
                record_key,
                action="withdraw",
                request=PlayerHandCloseRequest(
                    reason="Prove grade commit owns the complete authority scope.",
                    expected_active_canonical_revision=(
                        record.lifecycle.active_canonical_revision
                    ),
                    expected_deletion_generation=(
                        record.lifecycle.deletion_generation
                    ),
                    expected_lifecycle_changed_at=record.lifecycle.changed_at,
                ),
                at=record.lifecycle.changed_at + timedelta(minutes=1),
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            close_finished.set()

    persist_thread = Thread(target=persist_grade, daemon=True)
    publication_thread = Thread(target=publish_successor, daemon=True)
    close_thread = Thread(target=close_hand, daemon=True)
    persist_thread.start()
    assert grade_staged.wait(timeout=5)

    try:
        publication_thread.start()
        close_thread.start()
        assert publication_started.wait(timeout=5)
        assert close_started.wait(timeout=5)
        assert not publication_finished.wait(timeout=0.2)
        assert not close_finished.wait(timeout=0.2)
    finally:
        release_commit.set()

    persist_thread.join(timeout=5)
    publication_thread.join(timeout=5)
    close_thread.join(timeout=5)

    assert not persist_thread.is_alive()
    assert not publication_thread.is_alive()
    assert not close_thread.is_alive()
    assert failures == []
    assert results == [retained]
    assert workspace.imported_hands.list_reference_activated_grade_artifacts(
        record_key
    )
    assert workspace.imported_hands.get(record_key).lifecycle.status == "withdrawn"
    assert workspace.current_reference_activation_catalog().catalog == successor


def test_workspace_revalidation_excludes_catalog_and_same_hand_writers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace, record_key, retained, catalog = configured_workspace(tmp_path)
    record = workspace.imported_hands.get(record_key)
    revalidation_entered = Event()
    release_revalidation = Event()
    publication_started = Event()
    publication_finished = Event()
    close_started = Event()
    close_finished = Event()
    results: list[ReferenceActivatedGrade] = []
    failures: list[Exception] = []
    real_revalidate = player_workspace_module.revalidate_reference_grade

    def paused_revalidation(*args: object, **kwargs: object):
        revalidation_entered.set()
        if not release_revalidation.wait(timeout=5):
            raise AssertionError("test did not release revalidation")
        return real_revalidate(*args, **kwargs)

    monkeypatch.setattr(
        player_workspace_module,
        "revalidate_reference_grade",
        paused_revalidation,
    )

    def run_revalidation() -> None:
        try:
            results.append(
                workspace.revalidate_reference_activated_grade(
                    record_key,
                    retained,
                )
            )
        except Exception as exc:
            failures.append(exc)

    successor = activate(
        catalog,
        retained.readiness,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )

    def publish_successor() -> None:
        publication_started.set()
        try:
            workspace.publish_reference_activation_catalog(
                successor,
                expected_catalog_revision=catalog.catalog_revision,
                expected_catalog_sha256=catalog.semantic_digest(),
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            publication_finished.set()

    def close_hand() -> None:
        close_started.set()
        try:
            workspace.close_hand_record(
                record_key,
                action="withdraw",
                request=PlayerHandCloseRequest(
                    reason="Exercise the current-authority exclusion scope.",
                    expected_active_canonical_revision=(
                        record.lifecycle.active_canonical_revision
                    ),
                    expected_deletion_generation=(
                        record.lifecycle.deletion_generation
                    ),
                    expected_lifecycle_changed_at=record.lifecycle.changed_at,
                ),
                at=record.lifecycle.changed_at + timedelta(minutes=1),
            )
        except Exception as exc:
            failures.append(exc)
        finally:
            close_finished.set()

    revalidation_thread = Thread(target=run_revalidation, daemon=True)
    publication_thread = Thread(target=publish_successor, daemon=True)
    close_thread = Thread(target=close_hand, daemon=True)
    revalidation_thread.start()
    assert revalidation_entered.wait(timeout=5)

    try:
        publication_thread.start()
        close_thread.start()
        assert publication_started.wait(timeout=5)
        assert close_started.wait(timeout=5)
        assert not publication_finished.wait(timeout=0.2)
        assert not close_finished.wait(timeout=0.2)
    finally:
        release_revalidation.set()

    revalidation_thread.join(timeout=5)
    publication_thread.join(timeout=5)
    close_thread.join(timeout=5)

    assert not revalidation_thread.is_alive()
    assert not publication_thread.is_alive()
    assert not close_thread.is_alive()
    assert failures == []
    assert results == [retained]
    assert workspace.current_reference_activation_catalog().catalog == successor
    assert workspace.imported_hands.get(record_key).lifecycle.status == "withdrawn"
    with pytest.raises(PlayerHandDecisionsUnavailable):
        workspace.revalidate_reference_activated_grade(record_key, retained)
