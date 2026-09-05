from __future__ import annotations

from datetime import timedelta
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.application.imported_hand_lifecycle import ImportedHandLifecycleService
from app.application.reference_activation import bind_grade_to_active_reference
from app.domain.imported_hands import DeletionReceipt, extract_hero_decision_points
from app.player_grade_audit import (
    PlayerGradeAuditCursorError,
    select_grade_audit_page,
)
from app.player_hands import PlayerHandApprovalRequest, PlayerHandCloseRequest
from app.storage.imported_hand_store import GRADES_DIRNAME
from test_current_learning_revalidation import configured_workspace
from test_reference_activation import activate, readiness


def test_workspace_projects_retained_grade_as_redacted_historical_evidence(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, retained)

    page = workspace.list_retained_grade_audits(
        record_key,
        limit=25,
        cursor=None,
    )

    assert page.schema_name == "player-retained-grade-audits/v1"
    assert page.next_cursor is None
    assert len(page.items) == 1
    audit = page.items[0]
    grade = retained.readiness.grade
    assert audit.audit_status == "historical_only"
    assert audit.decision == grade.decision
    assert audit.classification == grade.classification
    assert audit.supported_policy_lines == grade.supported_policy_lines
    assert audit.matched_policy_line == grade.matched_policy_line
    assert audit.ev_cost == grade.ev_cost
    assert audit.ev_unit == grade.ev_unit
    assert audit.reference.binding.policy_content_sha256 == (
        grade.reference.policy_content_sha256()
    )
    assert audit.qualification.source_id == grade.source_qualification.source_id
    assert audit.content.concept_id == retained.readiness.tagging.tag.concept_id
    assert audit.activation.activation_id == retained.activation_id
    assert audit.activation.mastery_series_id == retained.mastery_series_id
    assert audit.learning_eligibility == (
        "requires_current_catalog_hand_and_content"
    )

    serialized = json.dumps(page.model_dump(mode="json", by_alias=True))
    raw_text = workspace.imported_hands.get(record_key).raw_sources[0].raw_text
    principle = retained.readiness.approved_principles[0].principle
    assert "canonical_json" not in serialized
    assert "pointer" not in serialized
    assert raw_text not in serialized
    assert principle.content not in serialized


def test_workspace_grade_audit_pages_use_opaque_snapshot_cursors(
    tmp_path: Path,
) -> None:
    workspace, record_key, first_grade, first_catalog = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, first_grade)
    evidence = readiness()
    second_catalog = activate(
        first_catalog,
        evidence,
        activation_id="activation-2",
        mastery_series_id="mastery-series-2",
    )
    reference_state = workspace.current_reference_activation_catalog()
    workspace.publish_reference_activation_catalog(
        second_catalog,
        expected_catalog_revision=reference_state.catalog.catalog_revision,
        expected_catalog_sha256=reference_state.catalog_sha256,
    )
    second_grade = bind_grade_to_active_reference(
        second_catalog,
        evidence,
        coverage_band_id="cash.preflop.bb-defense.100bb",
    )
    workspace.persist_current_reference_activated_grade(record_key, second_grade)

    first_page = workspace.list_retained_grade_audits(
        record_key,
        limit=1,
        cursor=None,
    )
    second_page = workspace.list_retained_grade_audits(
        record_key,
        limit=1,
        cursor=first_page.next_cursor,
    )

    assert first_page.next_cursor != first_page.items[0].audit_id
    assert second_page.next_cursor is None
    assert second_page.items[0].audit_id != first_page.items[0].audit_id
    filenames = {
        item[3]
        for item in workspace.imported_hands
        .list_reference_activated_grade_artifacts(record_key)
    }
    assert first_page.next_cursor not in filenames
    unknown_cursor = (
        "0" * 64
        if first_page.items[0].audit_id != "0" * 64
        else "1" * 64
    )
    with pytest.raises(PlayerGradeAuditCursorError):
        workspace.list_retained_grade_audits(
            record_key,
            limit=1,
            cursor=unknown_cursor,
        )


def test_grade_audit_cursor_rejects_a_changed_snapshot_before_its_position() -> None:
    original = [
        (1, 0, 0, f"r1-g0-d0-{'b' * 64}.json"),
        (1, 0, 0, f"r1-g0-d0-{'c' * 64}.json"),
    ]
    _, cursor = select_grade_audit_page(
        "1" * 64,
        original,
        limit=1,
        cursor=None,
    )
    assert cursor is not None

    changed = [
        (1, 0, 0, f"r1-g0-d0-{'a' * 64}.json"),
        *original,
    ]
    with pytest.raises(PlayerGradeAuditCursorError):
        select_grade_audit_page(
            "1" * 64,
            changed,
            limit=1,
            cursor=cursor,
        )


def test_grade_audit_remains_historical_through_withdrawal_and_reapproval(
    tmp_path: Path,
) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, retained)
    record = workspace.imported_hands.get(record_key)
    workspace.close_hand_record(
        record_key,
        action="withdraw",
        request=PlayerHandCloseRequest(
            reason="Retain the old grade only for audit.",
            expected_active_canonical_revision=(
                record.lifecycle.active_canonical_revision
            ),
            expected_deletion_generation=record.lifecycle.deletion_generation,
            expected_lifecycle_changed_at=record.lifecycle.changed_at,
        ),
        at=record.lifecycle.changed_at + timedelta(minutes=1),
    )

    withdrawn_page = workspace.list_retained_grade_audits(
        record_key,
        limit=25,
        cursor=None,
    )
    assert withdrawn_page.items[0].audit_status == "historical_only"
    withdrawn = workspace.imported_hands.get(record_key)
    withdrawn_detail = workspace.get_hand_record(record_key)
    workspace.approve_hand_record(
        record_key,
        request=PlayerHandApprovalRequest(
            request_id="99999999-9999-4999-8999-999999999999",
            detection_id=withdrawn.detections[-1].detection_id,
            approved_state=withdrawn_detail.canonical_revisions[-1].state,
            expected_record_version=withdrawn_detail.summary.record_version,
            expected_lifecycle_status="withdrawn",
            expected_active_canonical_revision=None,
            expected_canonical_revision_count=len(withdrawn.canonical_revisions),
            expected_deletion_generation=withdrawn.lifecycle.deletion_generation,
            expected_lifecycle_changed_at=withdrawn.lifecycle.changed_at,
        ),
        at=withdrawn.lifecycle.changed_at + timedelta(minutes=1),
    )

    reapproved_page = workspace.list_retained_grade_audits(
        record_key,
        limit=25,
        cursor=None,
    )
    assert reapproved_page.items[0].decision.canonical_revision == 1
    assert reapproved_page.items[0].audit_status == "historical_only"
    assert reapproved_page.record_version != withdrawn_page.record_version


def test_grade_audit_is_empty_after_permanent_purge(tmp_path: Path) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, retained)
    record = workspace.imported_hands.get(record_key)
    requested_at = record.lifecycle.changed_at + timedelta(minutes=1)
    lifecycle = ImportedHandLifecycleService(
        store=workspace.imported_hands,
        extract=extract_hero_decision_points,
        now=lambda: requested_at,
    )
    pending = lifecycle.request_deletion(
        record_key,
        reason="Remove retained grade evidence.",
        at=requested_at,
    )
    lifecycle.purge(
        record_key,
        receipt=DeletionReceipt(
            receipt_id="delete-grade-audit-evidence",
            generation=pending.lifecycle.deletion_generation,
            deleted_at=requested_at + timedelta(minutes=1),
            tombstone_sha256="d" * 64,
        ),
    )

    page = workspace.list_retained_grade_audits(
        record_key,
        limit=25,
        cursor=None,
    )
    assert page.items == ()
    assert page.next_cursor is None


def test_grade_audit_refuses_malformed_retained_evidence(tmp_path: Path) -> None:
    workspace, record_key, retained, _ = configured_workspace(tmp_path)
    workspace.persist_current_reference_activated_grade(record_key, retained)
    *_, filename = (
        workspace.imported_hands.list_reference_activated_grade_artifacts(
            record_key
        )[0]
    )
    artifact = (
        workspace.imported_hands.records_dir
        / record_key
        / GRADES_DIRNAME
        / filename
    )
    artifact.write_text("{}")

    with pytest.raises(ValidationError):
        workspace.list_retained_grade_audits(
            record_key,
            limit=25,
            cursor=None,
        )
