"""The imported-hand lifecycle boundary: one cascade per transition.

Every test here is ultimately about one rule: a published record's active
revision always has an artifact ``active_decisions`` will serve, because
the record and its derived decisions move in a single cascade. The end
state of a *successful* split-into-two implementation is identical to the
end state of a single cascade, so end-state assertions alone cannot prove
the rule. Two tests therefore attack the seam directly:
``test_a_transition_opens_exactly_one_cascade_and_never_a_bare_save``
pins the shape, and
``test_nothing_commits_when_the_cascade_cannot_finish`` fails the write
after both stages are in and proves neither half survived.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from pydantic import ValidationError

from app.application.imported_hand_lifecycle import (
    ConcurrentTransitionError,
    ImportedHandLifecycleService,
    LifecycleCascadeError,
)
from app.application.imported_hand_ports import (
    ImportedHandCascadeHandle,
    ImportedHandRepository,
)
from app.domain.imported_hands import (
    CanonicalHandRevision,
    DeletionReceipt,
    DeletionRequest,
    HandDecisionExtraction,
    ImportedHandLifecycle,
    ImportedHandRecord,
    extract_hero_decision_points,
)
from app.storage.cascade_journal import CascadeJournal, PendingCascadeError
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    ImportedHandCascade,
    imported_hand_record_key,
)
from test_imported_hand_decisions import hero_fold_decision_record
from test_imported_hand_models import NOW
from test_imported_hand_store import (
    pending_review_record as bare_pending_record,
)
from test_imported_hand_store import exclusive_data_lock_is_blocked
from test_imported_hand_store import revision as bare_revision_one
from test_imported_hand_store import sample_identity as bare_identity

# Later than every timestamp either source fixture module stamps into a
# record (test_imported_hand_models.NOW is 2026-08-27,
# test_imported_hand_store.NOW is 2026-08-30), so an approval's
# lifecycle.changed_at never precedes a retained audit event.
APPROVED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CLOSED_AT = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
REAPPROVED_AT = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
PURGED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def deletion_receipt(
    *, generation: int = 1, deleted_at: datetime = PURGED_AT
) -> DeletionReceipt:
    return DeletionReceipt(
        receipt_id=f"deletion-{generation}",
        generation=generation,
        deleted_at=deleted_at,
        tombstone_sha256="b" * 64,
    )


def playable_pending_record() -> ImportedHandRecord:
    """An extraction-ready hand that has not been approved yet.

    ``hero_fold_decision_record`` is already active at revision 1; this
    strips the approval back off so the service is the thing that grants
    it. Its state really does extract (one preflop fold decision), which
    is what lets these tests assert on a bound ``canonical_revision``
    rather than only on a rejection verdict.
    """
    approved = hero_fold_decision_record()
    return ImportedHandRecord(
        identity=approved.identity,
        raw_sources=approved.raw_sources,
        detections=approved.detections,
        lifecycle=ImportedHandLifecycle(status="pending_review", changed_at=NOW),
    )


def revision_one() -> CanonicalHandRevision:
    return hero_fold_decision_record().canonical_revisions[0]


def revision_two() -> CanonicalHandRevision:
    """A second approval of the same detection, one minute later.

    Reusing revision 1's detection and state is legal (a canonical
    revision may differ from its detection only through recorded
    corrections, and there are none to record), and it keeps the hand
    extraction-ready at revision 2 -- so a failure to serve revision 2's
    decisions is the boundary's fault, never the hand's.
    """
    first = revision_one()
    return CanonicalHandRevision(
        revision=2,
        detection_id=first.detection_id,
        approved_at=first.approved_at + timedelta(minutes=1),
        state=first.state,
    )


def deletion_pending_record() -> ImportedHandRecord:
    """An approved hand whose permanent deletion the player has asked for.

    Retains its canonical revision -- the request is pending, not carried
    out -- so it is a record every verb here would otherwise happily
    transition.
    """
    approved = hero_fold_decision_record()
    return ImportedHandRecord(
        identity=approved.identity,
        raw_sources=approved.raw_sources,
        detections=approved.detections,
        canonical_revisions=approved.canonical_revisions,
        lifecycle=ImportedHandLifecycle(
            status="deletion_pending",
            deletion_generation=1,
            changed_at=CLOSED_AT,
            deletion_request=DeletionRequest(generation=1, requested_at=CLOSED_AT),
        ),
    )


def lifecycle_fixture(
    tmp_path: Path,
    *,
    record: ImportedHandRecord | None = None,
    now: Callable[[], datetime] = lambda: APPROVED_AT,
) -> tuple[ImportedHandLifecycleService, FileImportedHandStore, str]:
    store = FileImportedHandStore(tmp_path)
    pending = record if record is not None else playable_pending_record()
    assert pending.identity is not None
    key = imported_hand_record_key(pending.identity)
    store.save(key, pending)
    service = ImportedHandLifecycleService(
        store=store,
        extract=extract_hero_decision_points,
        now=now,
    )
    return service, store, key


@contextmanager
def recorded_cascades(opened: list[str]) -> Iterator[None]:
    """Record the operation label of every cascade opened in the block."""
    real_begin_cascade = FileImportedHandStore.begin_cascade

    @contextmanager
    def recording(
        self: FileImportedHandStore, record_key: str, *, operation: str
    ) -> Any:
        opened.append(operation)
        with real_begin_cascade(self, record_key, operation=operation) as cascade:
            yield cascade

    with mock.patch.object(FileImportedHandStore, "begin_cascade", recording):
        yield


def unextractable_fixture(
    tmp_path: Path,
) -> tuple[ImportedHandLifecycleService, FileImportedHandStore, str]:
    """The same boundary over a hand extraction refuses outright.

    The store tests' bare fixture has no hero cards and no played street,
    so a real extraction of it rejects with ``incomplete_hand_state``
    however it is approved.
    """
    return lifecycle_fixture(tmp_path, record=bare_pending_record(bare_identity()))


def artifact_keys(store: FileImportedHandStore, key: str) -> list[tuple[int, int]]:
    """The ``(revision, generation)`` half of every retained artifact."""
    return [artifact[:2] for artifact in store.list_decision_artifacts(key)]


def assert_published_invariant(store: FileImportedHandStore, key: str) -> None:
    """The rule this whole module exists for, checked against disk.

    A learning-eligible record must have an artifact ``active_decisions``
    will serve, and that artifact must describe this record's own
    revision and generation. A rejection is exempt from the revision half
    only because the domain forbids a ``not_extractable`` outcome from
    binding a canonical revision at all -- that it is served *as* the
    active artifact is itself proof it was filed under the record's
    current revision, since that is the only name ``active_decisions``
    looks under.
    """
    record = store.get(key)
    active = store.active_decisions(key)
    if not record.lifecycle.learning_eligible:
        assert active is None, "an inactive record must serve no decisions"
        return
    assert active is not None, (
        "a published active record has no decisions at its active revision"
    )
    assert active.deletion_generation == record.lifecycle.deletion_generation
    if active.outcome != "not_extractable":
        assert active.canonical_revision == record.lifecycle.active_canonical_revision


# ---------------------------------------------------------------------------
# The brief's own tests
# ---------------------------------------------------------------------------


def test_reapproval_publishes_the_new_revision_and_its_decisions_together(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    service.reapprove(key, revision_two())

    record = store.get(key)
    assert record.lifecycle.active_canonical_revision == 2
    active = store.active_decisions(key)
    assert active is not None
    assert active.canonical_revision == 2
    assert active.outcome == "decisions"
    assert sorted(artifact_keys(store, key)) == [(1, 0), (2, 0)]


def test_failed_reapproval_extraction_keeps_prior_approval_and_can_retry(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)

    with mock.patch.object(service, "_extract", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            service.reapprove(key, revision_two())

    assert store.get(key) == before
    active = store.active_decisions(key)
    assert active is not None
    assert active.canonical_revision == 1
    assert artifact_keys(store, key) == [(1, 0)]

    retried = service.reapprove(key, revision_two())

    assert retried.lifecycle.active_canonical_revision == 2
    active = store.active_decisions(key)
    assert active is not None
    assert active.canonical_revision == 2
    assert sorted(artifact_keys(store, key)) == [(1, 0), (2, 0)]


def test_withdrawal_deactivates_derived_decisions(tmp_path: Path) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())

    service.withdraw(key, reason="player withdrew approval", at=CLOSED_AT)

    record = store.get(key)
    assert record.lifecycle.status == "withdrawn"
    assert record.lifecycle.active_canonical_revision is None
    assert record.lifecycle.reason == "player withdrew approval"
    assert record.lifecycle.changed_at == CLOSED_AT
    assert store.active_decisions(key) is None
    assert artifact_keys(store, key) == [(1, 0)]  # audit retained
    assert store.get_decisions(key, revision=1, generation=0) is not None


def test_rejection_after_approval_deactivates_derived_decisions(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())

    service.reject(key, reason="not the hand I meant to import", at=CLOSED_AT)

    record = store.get(key)
    assert record.lifecycle.status == "rejected"
    assert record.lifecycle.active_canonical_revision is None
    assert record.lifecycle.reason == "not the hand I meant to import"
    assert record.lifecycle.changed_at == CLOSED_AT
    assert store.active_decisions(key) is None
    assert artifact_keys(store, key) == [(1, 0)]  # audit retained
    assert store.get_decisions(key, revision=1, generation=0) is not None


def test_deletion_request_deactivates_decisions_and_retains_audit(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    opened: list[str] = []

    with recorded_cascades(opened):
        pending = service.request_deletion(
            key,
            reason="player requested permanent deletion",
            at=CLOSED_AT,
        )

    assert opened == ["request_deletion"]
    assert pending.lifecycle.status == "deletion_pending"
    assert pending.lifecycle.active_canonical_revision is None
    assert pending.lifecycle.deletion_generation == 1
    assert pending.lifecycle.changed_at == CLOSED_AT
    assert pending.lifecycle.reason == "player requested permanent deletion"
    assert pending.lifecycle.deletion_request == DeletionRequest(
        generation=1,
        requested_at=CLOSED_AT,
    )
    assert store.active_decisions(key) is None
    assert store.list_decision_artifacts(key) == [(1, 0, "r1-g0.json")]
    assert store.get(key) == pending


def test_retrying_a_published_deletion_request_is_idempotent(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    first = service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )
    opened: list[str] = []

    with recorded_cascades(opened):
        retried = service.request_deletion(
            key,
            reason="a retry must not replace retained audit",
            at=REAPPROVED_AT,
        )

    assert opened == []
    assert retried == first
    assert retried.lifecycle.deletion_generation == 1
    assert retried.lifecycle.changed_at == CLOSED_AT
    assert store.get(key) == first


def test_purge_replaces_the_hand_with_a_receipt_and_deletes_exact_artifacts(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    # Prove the application boundary uses the exact names returned by storage,
    # rather than reconstructing just the canonical spelling from (1, 0).
    extraction = store.get_decisions(key, revision=1, generation=0)
    assert extraction is not None
    decisions_dir = store.records_dir / key / "decisions"
    (decisions_dir / "r01-g0.json").write_bytes(
        extraction.model_dump_json(indent=2).encode("utf-8")
    )
    service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )
    receipt = deletion_receipt()
    opened: list[str] = []

    with recorded_cascades(opened):
        deleted = service.purge(key, receipt=receipt)

    assert opened == ["purge"]
    assert deleted.identity is None
    assert deleted.raw_sources == []
    assert deleted.detections == []
    assert deleted.conflicts == []
    assert deleted.canonical_revisions == []
    assert deleted.lifecycle.status == "deleted"
    assert deleted.lifecycle.deletion_generation == 1
    assert deleted.lifecycle.changed_at == PURGED_AT
    assert deleted.deletion_receipt == receipt
    assert store.get(key) == deleted
    assert store.active_decisions(key) is None
    assert store.list_decision_artifacts(key) == []


def test_retrying_a_completed_purge_with_its_receipt_is_idempotent(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )
    receipt = deletion_receipt()
    first = service.purge(key, receipt=receipt)
    opened: list[str] = []

    with recorded_cascades(opened):
        retried = service.purge(key, receipt=receipt)

    assert opened == []
    assert retried == first
    assert store.get(key) == first


def test_purge_requires_matching_pending_generation_and_chronology(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )
    before = store.get(key)

    with pytest.raises(ValidationError, match="generation"):
        service.purge(key, receipt=deletion_receipt(generation=2))
    with pytest.raises(LifecycleCascadeError, match="backwards"):
        service.purge(
            key,
            receipt=deletion_receipt(
                deleted_at=CLOSED_AT - timedelta(seconds=1)
            ),
        )

    assert store.get(key) == before
    assert store.get(key).lifecycle.status == "deletion_pending"


def test_purge_refuses_a_hand_that_was_not_logically_deactivated(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)
    opened: list[str] = []

    with recorded_cascades(opened):
        with pytest.raises(LifecycleCascadeError, match="logical deactivation"):
            service.purge(key, receipt=deletion_receipt())

    assert opened == []
    assert store.get(key) == before
    assert store.active_decisions(key) is not None


def test_failed_purge_staging_leaves_the_complete_pending_hand_and_audit(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    pending = service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )

    with mock.patch.object(
        ImportedHandCascade,
        "stage_decisions_delete",
        side_effect=OSError("simulated cleanup failure"),
    ):
        with pytest.raises(OSError, match="cleanup failure"):
            service.purge(key, receipt=deletion_receipt())

    assert store.get(key) == pending
    assert store.get(key).lifecycle.status == "deletion_pending"
    assert store.active_decisions(key) is None
    assert store.list_decision_artifacts(key) == [(1, 0, "r1-g0.json")]


def test_interrupted_purge_stays_ineligible_and_recovery_finishes_cleanup(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )
    fail_once = [True]
    real_commit_delete = CascadeJournal._commit_delete

    def flaky_delete(
        journal: CascadeJournal, record_key: str, relative: Any
    ) -> None:
        if fail_once:
            fail_once.clear()
            raise OSError("simulated disk failure during artifact cleanup")
        real_commit_delete(journal, record_key, relative)

    with mock.patch.object(CascadeJournal, "_commit_delete", flaky_delete):
        with pytest.raises(OSError, match="artifact cleanup"):
            service.purge(key, receipt=deletion_receipt())

    # Content publishes before deletion markers. Even in that torn state the
    # record is already a tombstone, so no retained artifact can become active.
    assert store.get(key).lifecycle.status == "deleted"
    assert store.active_decisions(key) is None
    assert store.list_decision_artifacts(key) == [(1, 0, "r1-g0.json")]

    with pytest.raises(PendingCascadeError, match="restart"):
        service.purge(key, receipt=deletion_receipt())

    # The stranded cascade closes only its own key. A different imported hand
    # can still be persisted and approved while cleanup waits for recovery.
    other_identity = bare_identity(hand_ordinal=2)
    other_key = imported_hand_record_key(other_identity)
    store.save(other_key, bare_pending_record(other_identity))
    other = service.approve(other_key, bare_revision_one(other_identity))
    assert other.lifecycle.status == "active"
    assert store.active_decisions(other_key) is not None

    report = store.recover()

    assert len(report.completed) == 1
    assert report.quarantined == () and report.failed == ()
    assert store.get(key).lifecycle.status == "deleted"
    assert store.list_decision_artifacts(key) == []
    assert store.get(other_key) == other
    assert store.active_decisions(other_key) is not None


def test_never_publishes_a_record_whose_active_revision_has_no_decisions(
    tmp_path: Path,
) -> None:
    """The invariant behind the whole task, asserted directly.

    Asserted after every verb rather than only after reapproval, and
    without the brief's ``if learning_eligible`` guard around the
    approved cases, which would let the assertions pass vacuously against
    an implementation that simply failed to publish anything.
    """
    service, store, key = lifecycle_fixture(tmp_path)

    service.approve(key, revision_one())
    assert store.get(key).lifecycle.learning_eligible
    assert_published_invariant(store, key)

    service.reapprove(key, revision_two())
    record = store.get(key)
    assert record.lifecycle.learning_eligible
    active = store.active_decisions(key)
    assert active is not None
    assert active.canonical_revision == record.lifecycle.active_canonical_revision
    assert active.deletion_generation == record.lifecycle.deletion_generation

    service.withdraw(key, reason="player withdrew approval", at=CLOSED_AT)
    assert not store.get(key).lifecycle.learning_eligible
    assert_published_invariant(store, key)


# ---------------------------------------------------------------------------
# The seam: one cascade, not two
# ---------------------------------------------------------------------------


def test_a_transition_opens_exactly_one_cascade_and_never_a_bare_save(
    tmp_path: Path,
) -> None:
    """Every verb moves everything it moves through one cascade.

    ``save``/``save_decisions`` each open a cascade of their own, so a
    boundary built from them publishes the record in one durable unit and
    its decisions in another -- exactly the window this task exists to
    close. Patching both to raise makes that construction impossible
    rather than merely unlikely, and counting the cascades proves the
    remaining route did not simply open two.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    opened: list[str] = []

    def no_bare_write(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a lifecycle transition must stage through one cascade, never "
            "through the store's single-operation write wrappers"
        )

    with (
        recorded_cascades(opened),
        mock.patch.object(FileImportedHandStore, "save", no_bare_write),
        mock.patch.object(FileImportedHandStore, "save_decisions", no_bare_write),
    ):
        service.approve(key, revision_one())
        service.reapprove(key, revision_two())
        service.withdraw(key, reason="player withdrew approval", at=CLOSED_AT)

    assert opened == ["approve", "reapprove", "withdraw"]


def test_a_rejection_transition_is_journalled_under_its_own_operation(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    opened: list[str] = []

    with recorded_cascades(opened):
        service.reject(key, reason="not mine", at=CLOSED_AT)

    assert opened == ["reject"]


def test_nothing_commits_when_the_cascade_cannot_finish(tmp_path: Path) -> None:
    """A write that dies after both stages leaves neither behind.

    ``_decision_revision_for`` runs inside the cascade's own finalizer,
    after the record and the extraction have both been staged, so failing
    it is the closest a test can get to losing power mid-write. A
    boundary that published the record in its own cascade first would
    have committed revision 2 by the time this fires; a single cascade
    discards the whole scratch tree and revision 1 is still current.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)

    with mock.patch.object(
        FileImportedHandStore,
        "_decision_revision_for",
        side_effect=OSError("cascade interrupted"),
    ):
        with pytest.raises(OSError):
            service.reapprove(key, revision_two())

    assert store.get(key) == before
    active = store.active_decisions(key)
    assert active is not None
    assert active.canonical_revision == 1
    assert artifact_keys(store, key) == [(1, 0)]


# ---------------------------------------------------------------------------
# What the boundary refuses
# ---------------------------------------------------------------------------


def test_an_extraction_bound_to_the_outgoing_revision_is_refused(
    tmp_path: Path,
) -> None:
    """The one input the service does not compute is the one it checks.

    ``extract`` is injected, so nothing about this service guarantees it
    describes the record being published. Handing back the outgoing
    revision's artifact is the exact mistake a boundary that extracted
    from the *stored* record instead of the one it is about to publish
    would make, and it must be refused before anything is staged rather
    than discovered afterwards as a revision 2 record with only revision
    1 decisions on disk.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)
    outgoing = store.active_decisions(key)
    assert outgoing is not None
    assert outgoing.canonical_revision == 1

    with mock.patch.object(service, "_extract", return_value=outgoing):
        with pytest.raises(LifecycleCascadeError):
            service.reapprove(key, revision_two())

    assert store.get(key) == before
    assert artifact_keys(store, key) == [(1, 0)]


def test_an_extraction_from_another_deletion_generation_is_refused(
    tmp_path: Path,
) -> None:
    """An artifact naming the right revision of the wrong incarnation.

    The generation is half of an artifact's name, so an extraction
    computed against a purged-and-reimported incarnation files itself
    under a name the published record never looks under, and the hand is
    left active with no decisions -- broken by an artifact that was in
    the right cascade and named the right revision.

    Deliberately correct in every other respect, including the canonical
    revision: an extraction that got the revision wrong too would be
    refused by the revision check whether the generation were inspected
    or not, and this test would then pass against a boundary that never
    looked at the generation at all.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)
    other_incarnation = ImportedHandRecord(
        identity=before.identity,
        raw_sources=before.raw_sources,
        detections=before.detections,
        conflicts=before.conflicts,
        canonical_revisions=[*before.canonical_revisions, revision_two()],
        lifecycle=ImportedHandLifecycle(
            status="active",
            active_canonical_revision=2,
            deletion_generation=1,
            changed_at=APPROVED_AT,
        ),
    )
    stale_generation = extract_hero_decision_points(other_incarnation)
    assert stale_generation.canonical_revision == 2
    assert stale_generation.deletion_generation == 1

    with mock.patch.object(service, "_extract", return_value=stale_generation):
        with pytest.raises(LifecycleCascadeError):
            service.reapprove(key, revision_two())

    assert store.get(key) == before
    assert artifact_keys(store, key) == [(1, 0)]


def test_a_not_active_rejection_for_an_active_record_is_refused(
    tmp_path: Path,
) -> None:
    """A ``not_active`` verdict always takes the store's sentinel slot.

    The domain only produces it for a record that is not learning
    eligible, so it can never describe the record an approval publishes.
    Staging one anyway would file it at the sentinel and leave the
    active revision with no artifact at all.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)
    not_active = HandDecisionExtraction(
        identity=before.identity,
        chronology=None,
        provenance=None,
        canonical_revision=None,
        deletion_generation=0,
        outcome="not_extractable",
        rejection="not_active",
        decision_points=[],
        excluded_actions=[],
    )

    with mock.patch.object(service, "_extract", return_value=not_active):
        with pytest.raises(LifecycleCascadeError):
            service.reapprove(key, revision_two())

    assert store.get(key) == before
    assert artifact_keys(store, key) == [(1, 0)]


def test_approve_refuses_a_hand_that_has_already_been_approved(
    tmp_path: Path,
) -> None:
    """The journal's operation label has to describe what happened.

    A stranded cascade directory is read by a human, and ``approve`` on a
    hand that already carries a canonical revision would tell them a
    first approval was in flight when a supersession was.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)

    with pytest.raises(LifecycleCascadeError):
        service.approve(key, revision_two())

    assert store.get(key) == before
    assert artifact_keys(store, key) == [(1, 0)]


def test_reapprove_refuses_a_hand_that_was_never_approved(tmp_path: Path) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    before = store.get(key)

    with pytest.raises(LifecycleCascadeError):
        service.reapprove(key, revision_one())

    assert store.get(key) == before
    assert store.list_decision_artifacts(key) == []


def test_a_lifecycle_the_domain_refuses_publishes_nothing(tmp_path: Path) -> None:
    """No hand-built lifecycle state: ``validate_aggregate`` is the judge.

    A hand with no canonical revision has no approval to withdraw, and
    the aggregate says so. The service does not re-implement that rule,
    so the ``ValidationError`` reaches the caller and nothing is written.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    before = store.get(key)

    with pytest.raises(ValidationError):
        service.withdraw(key, reason="never approved", at=CLOSED_AT)

    assert store.get(key) == before
    assert store.list_decision_artifacts(key) == []


def test_an_empty_reason_is_refused_by_the_domain(tmp_path: Path) -> None:
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    before = store.get(key)

    with pytest.raises(ValidationError):
        service.withdraw(key, reason="", at=CLOSED_AT)

    assert store.get(key) == before


# ---------------------------------------------------------------------------
# A hand extraction refuses is still a lifecycle transition
# ---------------------------------------------------------------------------


def test_an_unextractable_hand_stores_its_rejection_and_stays_approved(
    tmp_path: Path,
) -> None:
    """A rejected extraction is a stored verdict, not a cascade failure."""
    service, store, key = unextractable_fixture(tmp_path)

    published = service.approve(key, bare_revision_one(bare_identity()))

    assert published.lifecycle.active_canonical_revision == 1
    record = store.get(key)
    assert record.lifecycle.status == "active"
    active = store.active_decisions(key)
    assert active is not None
    assert active.outcome == "not_extractable"
    assert active.rejection == "incomplete_hand_state"
    assert active.canonical_revision is None
    assert artifact_keys(store, key) == [(1, 0)]
    assert_published_invariant(store, key)


def test_a_still_unextractable_reapproval_supersedes_without_deleting(
    tmp_path: Path,
) -> None:
    """Reapproving a hand that still will not extract keeps both verdicts.

    Superseded artifacts are retained for audit; only permanent purge may
    remove one. Two rejections that both carry no canonical revision must
    therefore land under different names, which is what the store's
    fallback to the *cascade's own* record gives them.
    """
    service, store, key = unextractable_fixture(tmp_path)
    identity = bare_identity()
    first = bare_revision_one(identity)
    service.approve(key, first)
    second = CanonicalHandRevision(
        revision=2,
        detection_id=first.detection_id,
        approved_at=first.approved_at,
        state=first.state,
        corrections=list(first.corrections),
    )

    service.reapprove(key, second)

    assert store.get(key).lifecycle.active_canonical_revision == 2
    assert sorted(artifact_keys(store, key)) == [(1, 0), (2, 0)]
    assert store.get_decisions(key, revision=1, generation=0) is not None
    assert_published_invariant(store, key)


# ---------------------------------------------------------------------------
# Layering
# ---------------------------------------------------------------------------


class PortOnlyCascade:
    """Exposes exactly the members ``ImportedHandCascadeHandle`` declares.

    Restricting the repository alone leaves a hole: ``begin_cascade`` hands
    back the adapter's own concrete cascade, so every method the port never
    declared remains reachable through an annotation that is never evaluated
    under ``from __future__ import annotations``. The handle is where purge
    stages exact artifact deletion, so its declared boundary has to hold too.
    """

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        if name.startswith("_") or name not in vars(ImportedHandCascadeHandle):
            raise AttributeError(
                f"{name!r} is not declared by ImportedHandCascadeHandle"
            )
        return getattr(self._inner, name)


class PortOnlyRepository:
    """Exposes exactly the members ``ImportedHandRepository`` declares.

    The service is annotated against the port, but no type checker runs
    here, so an undeclared store method would be reached at runtime with
    nothing to stop it. This makes the annotation load-bearing: anything
    the port does not declare is simply absent, including on the cascade
    handle ``begin_cascade`` yields.
    """

    def __init__(self, inner: FileImportedHandStore) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        if name.startswith("_") or name not in vars(ImportedHandRepository):
            raise AttributeError(
                f"{name!r} is not declared by ImportedHandRepository"
            )
        return getattr(self._inner, name)

    @contextmanager
    def begin_cascade(self, record_key: str, *, operation: str) -> Any:
        with self._inner.begin_cascade(record_key, operation=operation) as cascade:
            yield PortOnlyCascade(cascade)


def port_only_service(
    store: FileImportedHandStore, *, now: Callable[[], datetime] = lambda: APPROVED_AT
) -> ImportedHandLifecycleService:
    return ImportedHandLifecycleService(
        store=PortOnlyRepository(store),
        extract=extract_hero_decision_points,
        now=now,
    )


def test_the_service_needs_only_what_the_repository_port_declares(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    pending = playable_pending_record()
    assert pending.identity is not None
    key = imported_hand_record_key(pending.identity)
    store.save(key, pending)
    service = port_only_service(store)

    service.approve(key, revision_one())
    service.reapprove(key, revision_two())
    service.withdraw(key, reason="player withdrew approval", at=CLOSED_AT)

    assert store.get(key).lifecycle.status == "withdrawn"
    assert sorted(artifact_keys(store, key)) == [(1, 0), (2, 0)]


def test_deletion_and_purge_need_only_what_the_repository_port_declares(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    pending = playable_pending_record()
    assert pending.identity is not None
    key = imported_hand_record_key(pending.identity)
    store.save(key, pending)
    service = port_only_service(store)

    service.approve(key, revision_one())
    service.request_deletion(
        key,
        reason="player requested permanent deletion",
        at=CLOSED_AT,
    )
    deleted = service.purge(key, receipt=deletion_receipt())

    assert deleted.lifecycle.status == "deleted"
    assert store.get(key) == deleted
    assert store.list_decision_artifacts(key) == []


def test_rejection_and_an_unextractable_hand_also_stay_within_the_port(
    tmp_path: Path,
) -> None:
    """The two paths the port-only run above never reaches.

    ``reject`` has its own ``_close`` call site, and a hand whose
    extraction is refused takes the branch where the artifact carries no
    canonical revision -- the one whose filename the adapter has to
    resolve by rereading the record.
    """
    store = FileImportedHandStore(tmp_path)
    identity = bare_identity()
    pending = bare_pending_record(identity)
    key = imported_hand_record_key(identity)
    store.save(key, pending)
    service = port_only_service(store)

    service.approve(key, bare_revision_one(identity))
    service.reject(key, reason="not the hand I meant to import", at=CLOSED_AT)

    record = store.get(key)
    assert record.lifecycle.status == "rejected"
    assert store.active_decisions(key) is None
    assert artifact_keys(store, key) == [(1, 0)]
    retained = store.get_decisions(key, revision=1, generation=0)
    assert retained is not None
    assert retained.outcome == "not_extractable"


def test_the_cascade_the_port_yields_exposes_the_purge_only_stage(
    tmp_path: Path,
) -> None:
    """Permanent purge reaches deletion only through the declared port."""
    store = FileImportedHandStore(tmp_path)
    record = playable_pending_record()
    assert record.identity is not None
    key = imported_hand_record_key(record.identity)
    store.save(key, record)
    repository = PortOnlyRepository(store)

    with repository.begin_cascade(key, operation="save") as cascade:
        assert not isinstance(cascade, ImportedHandCascade)
        cascade.stage_decisions_delete("r1-g0.json")
        cascade.stage_record(record)

    assert store.get(key) == record


# ---------------------------------------------------------------------------
# A pending deletion is not something a transition may quietly undo
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transition",
    [
        pytest.param(
            lambda service, key: service.approve(key, revision_two()), id="approve"
        ),
        pytest.param(
            lambda service, key: service.reapprove(key, revision_two()),
            id="reapprove",
        ),
        pytest.param(
            lambda service, key: service.withdraw(key, reason="changed my mind", at=REAPPROVED_AT),
            id="withdraw",
        ),
        pytest.param(
            lambda service, key: service.reject(key, reason="not mine", at=REAPPROVED_AT),
            id="reject",
        ),
    ],
)
def test_every_verb_refuses_a_record_whose_deletion_is_pending(
    tmp_path: Path,
    transition: Callable[[ImportedHandLifecycleService, str], object],
) -> None:
    """A deletion request may only be retained by a deletion_pending record.

    The domain says so outright, so any verb here that rebuilt the
    lifecycle around a new status would have to drop the request to
    validate at all -- cancelling a player's pending deletion as an
    invisible side effect of an unrelated transition, with nothing left
    on the record to show it ever existed. Cancelling a deletion is its
    own transition (the journal reserves ``restore`` for it) and has to
    be asked for.

    Matched on the message because the deletion guard has to fire ahead
    of each verb's own precondition -- ``approve`` would otherwise refuse
    this record for having been approved already, and ``reapprove``
    accept it -- and both raise the same error type.
    """
    service, store, key = lifecycle_fixture(tmp_path, record=deletion_pending_record())
    before = store.get(key)
    assert before.lifecycle.deletion_request is not None

    with pytest.raises(LifecycleCascadeError, match="deletion"):
        transition(service, key)

    after = store.get(key)
    assert after == before
    assert after.lifecycle.deletion_request is not None
    assert after.lifecycle.status == "deletion_pending"


def test_a_refused_deletion_pending_transition_opens_no_cascade(
    tmp_path: Path,
) -> None:
    service, store, key = lifecycle_fixture(tmp_path, record=deletion_pending_record())
    opened: list[str] = []

    with recorded_cascades(opened):
        with pytest.raises(LifecycleCascadeError):
            service.withdraw(key, reason="changed my mind", at=REAPPROVED_AT)

    assert opened == []


# ---------------------------------------------------------------------------
# approve vs reapprove: the path where the two candidate predicates differ
# ---------------------------------------------------------------------------


def test_approving_a_withdrawn_hand_again_is_a_reapproval(tmp_path: Path) -> None:
    """The only path on which the two candidate predicates disagree.

    "Has this hand ever been approved" and "is it currently active" agree
    everywhere except here: a withdrawn hand carries a canonical revision
    but is not eligible. The ruling is the former -- the journal's
    operation label is read by a human, and a hand that was approved
    before is being approved *again* whatever its status in between --
    so ``approve`` must refuse this and ``reapprove`` must take it.
    Without this test either predicate passes the whole suite.
    """
    clock = [APPROVED_AT]
    service, store, key = lifecycle_fixture(tmp_path, now=lambda: clock[0])
    service.approve(key, revision_one())
    service.withdraw(key, reason="player withdrew approval", at=CLOSED_AT)
    assert not store.get(key).lifecycle.learning_eligible

    with pytest.raises(LifecycleCascadeError, match="already been approved"):
        service.approve(key, revision_two())

    clock[0] = REAPPROVED_AT
    opened: list[str] = []
    with recorded_cascades(opened):
        service.reapprove(key, revision_two())

    assert opened == ["reapprove"]
    record = store.get(key)
    assert record.lifecycle.active_canonical_revision == 2
    assert record.lifecycle.changed_at == REAPPROVED_AT
    assert sorted(artifact_keys(store, key)) == [(1, 0), (2, 0)]
    active = store.active_decisions(key)
    assert active is not None
    assert active.canonical_revision == 2
    assert_published_invariant(store, key)


# ---------------------------------------------------------------------------
# The clock, and the two properties _publish's docstring claims
# ---------------------------------------------------------------------------


def test_an_approval_stamps_the_injected_clock(tmp_path: Path) -> None:
    """``now`` is the only thing that may date a lifecycle change here.

    Every other timestamp within reach -- the revision's own
    ``approved_at``, the record's previous ``changed_at`` -- is close
    enough to be substituted for it without any assertion noticing, and
    they are all consistent with the aggregate's ordering rules, so
    ``validate_aggregate`` would not catch the substitution either.
    """
    clock = [APPROVED_AT]
    service, store, key = lifecycle_fixture(tmp_path, now=lambda: clock[0])
    assert revision_one().approved_at != APPROVED_AT

    service.approve(key, revision_one())
    assert store.get(key).lifecycle.changed_at == APPROVED_AT

    clock[0] = REAPPROVED_AT
    service.reapprove(key, revision_two())
    assert store.get(key).lifecycle.changed_at == REAPPROVED_AT


def test_the_extraction_is_computed_before_the_cascade_takes_any_lock(
    tmp_path: Path,
) -> None:
    """``extract`` is injected, so it may block for as long as it likes.

    Running it inside the cascade would hold the interprocess data lock
    across a callable this service does not control, and the store's own
    contract is that the hold starts and ends inside the call. Both the
    ordering and the lock itself are asserted: ordering alone would stay
    green if the lock were ever taken earlier for some other reason.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    events: list[str] = []
    real_extract = extract_hero_decision_points

    def recording_extract(record: ImportedHandRecord) -> HandDecisionExtraction:
        events.append("extract")
        assert not exclusive_data_lock_is_blocked(tmp_path), (
            "the data lock is already held while the extraction runs"
        )
        return real_extract(record)

    with (
        mock.patch.object(service, "_extract", recording_extract),
        recorded_cascades(events),
    ):
        service.reapprove(key, revision_two())

    assert events == ["extract", "reapprove"]


def test_a_refused_extraction_never_opens_a_cascade(tmp_path: Path) -> None:
    """The guard runs before staging, not merely before commit.

    Checking it after staging would leave the same end state -- the
    exception still escapes the ``with`` block and the journal still
    discards -- so nothing on disk can tell the two apart. What differs
    is whether a lock was taken and a scratch tree built for a write
    that was never going to be allowed.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    outgoing = store.active_decisions(key)
    assert outgoing is not None
    opened: list[str] = []

    with recorded_cascades(opened), mock.patch.object(
        service, "_extract", return_value=outgoing
    ):
        with pytest.raises(LifecycleCascadeError):
            service.reapprove(key, revision_two())

    assert opened == []


def test_a_stale_transition_is_refused_rather_than_overwriting_a_committed_one(
    tmp_path: Path,
) -> None:
    """The probed interleaving: read revision 1, withdraw, then reapprove.

    Both reviewers reached this independently. Without the compare-and-swap
    the reapproval republishes the state it built from the pre-withdrawal
    snapshot, so the withdrawal is erased and the record ends `active` at
    revision 2 -- while its own `canonical_revisions` and the surviving
    `r2-g0.json` artifact describe an approval the player had already
    retracted. Nothing downstream detects it.

    The interleaving is forced deterministically rather than raced: the
    competing withdrawal is committed from inside the reapproval's own
    extract step, which runs after `_current` has taken its snapshot and
    before the cascade opens.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    snapshot = store.get(key)

    competing_committed: list[bool] = []
    real_extract = extract_hero_decision_points

    def extract_then_let_a_withdrawal_land(
        record: ImportedHandRecord,
    ) -> HandDecisionExtraction:
        if not competing_committed:
            competing_committed.append(True)
            service.withdraw(key, reason="player retracted it", at=CLOSED_AT)
        return real_extract(record)

    racing = ImportedHandLifecycleService(
        store=store,
        extract=extract_then_let_a_withdrawal_land,
        now=lambda: REAPPROVED_AT,
    )

    with pytest.raises(ConcurrentTransitionError, match="changed after this"):
        racing.reapprove(key, revision_two())

    assert competing_committed == [True], "the competing withdrawal never landed"
    published = store.get(key)
    assert published.lifecycle.status == "withdrawn"
    assert published.lifecycle.active_canonical_revision is None
    assert [item.revision for item in published.canonical_revisions] == [1]
    assert published != snapshot
    # And the stale transition wrote nothing at all - no artifact for the
    # revision the record now denies ever approving.
    assert store.get_decisions(key, revision=2, generation=0) is None
    assert store.active_decisions(key) is None


def test_an_unchanged_record_publishes_normally(tmp_path: Path) -> None:
    """The compare-and-swap must not refuse the ordinary case.

    A transition that reads, builds, and publishes with nothing else
    touching the record in between is every real transition today.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())

    reapproved = service.reapprove(key, revision_two())

    assert reapproved.lifecycle.active_canonical_revision == 2
    assert store.get(key).lifecycle.active_canonical_revision == 2
    assert store.active_decisions(key) is not None


def commit_failing_once_on(relative_name: str) -> Any:
    """Fail one _commit_replace for a named file, as a torn disk write would.

    A cascade's content files publish in sorted path order, so
    `decisions/...` lands before `record.json`: failing on the record
    leaves the artifact committed, the record not, and the cascade sitting
    ready to be replayed.
    """
    fail_once = [True]
    real_commit_replace = CascadeJournal._commit_replace

    def flaky(
        journal: CascadeJournal, record_key: str, relative: Any, staged_file: Any
    ) -> None:
        if fail_once and relative.as_posix() == relative_name:
            fail_once.clear()
            raise OSError("simulated disk failure mid-commit")
        real_commit_replace(journal, record_key, relative, staged_file)

    return mock.patch.object(CascadeJournal, "_commit_replace", flaky)


def test_a_key_is_closed_to_writes_while_a_cascade_waits_to_replay(
    tmp_path: Path,
) -> None:
    """Roll-forward assumes nothing newer happened; this makes that true.

    Reproduced before it was closed: a reapproval's commit publishes the
    decision artifact and then fails on record.json, so the cascade is left
    ready. A withdrawal then committed cleanly over the half-applied state
    -- and the next startup sweep replayed the older staged record on top,
    erasing the withdrawal while reporting the sweep `completed`. The
    compare-and-swap cannot see it: it runs at transition time, and the
    overwrite happens later, during recovery.

    So the key stays closed from the moment its cascade is left pending
    until recovery deals with it. The refusal names the cascade and says
    the remedy is a restart, because recovery needs an exclusive
    interprocess hold that a request path must not take.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())

    with commit_failing_once_on("record.json"):
        with pytest.raises(OSError):
            service.reapprove(key, revision_two())

    # Half applied: the new artifact is on disk, the record is not.
    assert store.list_decision_artifacts(key) == [
        (1, 0, "r1-g0.json"),
        (2, 0, "r2-g0.json"),
    ]
    assert store.get(key).lifecycle.active_canonical_revision == 1

    with pytest.raises(PendingCascadeError) as refusal:
        service.withdraw(key, reason="player retracted it", at=CLOSED_AT)

    message = str(refusal.value)
    assert key in message
    assert "restart" in message
    # Nothing was written by the refused transition.
    assert store.get(key).lifecycle.active_canonical_revision == 1


def test_recovery_reopens_the_key_it_closed(tmp_path: Path) -> None:
    """The block is temporary and a restart is the whole remedy.

    Recovery finishes the pending cascade, so the record reaches the state
    that write intended, and the transition that was refused then applies
    on top of it -- against the correct state rather than over it.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    with commit_failing_once_on("record.json"):
        with pytest.raises(OSError):
            service.reapprove(key, revision_two())

    report = store.recover()

    assert len(report.completed) == 1
    assert report.quarantined == () and report.failed == ()
    assert store.get(key).lifecycle.active_canonical_revision == 2

    withdrawn = service.withdraw(key, reason="player retracted it", at=CLOSED_AT)

    assert withdrawn.lifecycle.status == "withdrawn"
    assert store.get(key).lifecycle.status == "withdrawn"


def test_a_transition_cannot_move_the_lifecycle_marker_backwards(
    tmp_path: Path,
) -> None:
    """A delayed withdrawal must not regress lifecycle.changed_at.

    The aggregate accepts it: it compares changed_at only against the
    audit events the record retains, and this instant is later than all of
    them. But classify_restore compares the two records' markers directly
    to decide which is newer, so a regressed marker makes a real
    withdrawal look `stale_record` beside the approval it replaced, and a
    restore would discard it as out of date.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    approved = service.approve(key, revision_one())
    assert approved.lifecycle.changed_at == APPROVED_AT
    before_the_approval = APPROVED_AT - timedelta(seconds=1)
    # Later than every retained audit event, so the domain is content.
    assert before_the_approval > revision_one().approved_at

    with pytest.raises(LifecycleCascadeError, match="backwards"):
        service.withdraw(key, reason="player retracted it", at=before_the_approval)

    assert store.get(key).lifecycle.status == "active"
    assert store.get(key).lifecycle.changed_at == APPROVED_AT


@pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=1)])
def test_a_transition_at_or_after_the_current_marker_is_accepted(
    tmp_path: Path, offset: timedelta
) -> None:
    """Equal is allowed: two transitions may share an instant."""
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())

    withdrawn = service.withdraw(
        key, reason="player retracted it", at=APPROVED_AT + offset
    )

    assert withdrawn.lifecycle.status == "withdrawn"
    assert store.get(key).lifecycle.changed_at == APPROVED_AT + offset


def test_an_accepted_write_is_never_erased_by_a_stale_replay(tmp_path: Path) -> None:
    """The end state the refusal exists to protect, asserted as an invariant.

    Two outcomes are legitimate for a transition arriving behind a
    half-applied cascade: refuse it now, or accept it and have it survive.
    The one outcome that is not is accepting it and then silently erasing
    it, which is what roll-forward did before the refusal existed -- the
    boot sweep replayed the older staged record over the committed
    withdrawal and reported itself `completed`.

    Written as "whatever was accepted must still be there afterwards" so
    the failure is that erasure rather than a missing exception, and so
    the test keeps its meaning if the refusal is ever replaced by a
    different mechanism.
    """
    service, store, key = lifecycle_fixture(tmp_path)
    service.approve(key, revision_one())
    with commit_failing_once_on("record.json"):
        with pytest.raises(OSError):
            service.reapprove(key, revision_two())

    try:
        service.withdraw(key, reason="player retracted it", at=CLOSED_AT)
    except PendingCascadeError:
        accepted = False
    else:
        accepted = True

    store.recover()

    if accepted:
        assert store.get(key).lifecycle.status == "withdrawn", (
            "a withdrawal that committed successfully was erased by startup "
            "recovery replaying an older staged record over it"
        )
    else:
        # Refused instead, so the pending cascade is what recovery lands.
        assert store.get(key).lifecycle.active_canonical_revision == 2
