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

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from pydantic import ValidationError

from app.application.imported_hand_lifecycle import (
    ImportedHandLifecycleService,
    LifecycleCascadeError,
)
from app.application.imported_hand_ports import ImportedHandRepository
from app.domain.imported_hands import (
    CanonicalHandRevision,
    HandDecisionExtraction,
    ImportedHandLifecycle,
    ImportedHandRecord,
    extract_hero_decision_points,
)
from app.storage.imported_hand_store import (
    FileImportedHandStore,
    imported_hand_record_key,
)
from test_imported_hand_decisions import hero_fold_decision_record
from test_imported_hand_models import NOW
from test_imported_hand_store import (
    pending_review_record as bare_pending_record,
)
from test_imported_hand_store import revision as bare_revision_one
from test_imported_hand_store import sample_identity as bare_identity

# Later than every timestamp either source fixture module stamps into a
# record (test_imported_hand_models.NOW is 2026-08-27,
# test_imported_hand_store.NOW is 2026-08-30), so an approval's
# lifecycle.changed_at never precedes a retained audit event.
APPROVED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
CLOSED_AT = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)


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


def lifecycle_fixture(
    tmp_path: Path,
    *,
    record: ImportedHandRecord | None = None,
) -> tuple[ImportedHandLifecycleService, FileImportedHandStore, str]:
    store = FileImportedHandStore(tmp_path)
    pending = record if record is not None else playable_pending_record()
    assert pending.identity is not None
    key = imported_hand_record_key(pending.identity)
    store.save(key, pending)
    service = ImportedHandLifecycleService(
        store=store,
        extract=extract_hero_decision_points,
        now=lambda: APPROVED_AT,
    )
    return service, store, key


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


def test_a_failure_mid_cascade_leaves_the_record_untouched(tmp_path: Path) -> None:
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
    assert store.active_decisions(key) is None
    assert artifact_keys(store, key) == [(1, 0)]  # audit retained
    assert store.get_decisions(key, revision=1, generation=0) is not None


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
    real_begin_cascade = FileImportedHandStore.begin_cascade

    @contextmanager
    def recording_begin_cascade(
        self: FileImportedHandStore, record_key: str, *, operation: str
    ) -> Any:
        opened.append(operation)
        with real_begin_cascade(self, record_key, operation=operation) as cascade:
            yield cascade

    def no_bare_write(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "a lifecycle transition must stage through one cascade, never "
            "through the store's single-operation write wrappers"
        )

    with (
        mock.patch.object(
            FileImportedHandStore, "begin_cascade", recording_begin_cascade
        ),
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
    real_begin_cascade = FileImportedHandStore.begin_cascade

    @contextmanager
    def recording_begin_cascade(
        self: FileImportedHandStore, record_key: str, *, operation: str
    ) -> Any:
        opened.append(operation)
        with real_begin_cascade(self, record_key, operation=operation) as cascade:
            yield cascade

    with mock.patch.object(
        FileImportedHandStore, "begin_cascade", recording_begin_cascade
    ):
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

    Superseded artifacts are retained for audit; only Task 6's purge may
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


class PortOnlyRepository:
    """Exposes exactly the members ``ImportedHandRepository`` declares.

    The service is annotated against the port, but no type checker runs
    here, so an undeclared store method would be reached at runtime with
    nothing to stop it. This makes the annotation load-bearing: anything
    the port does not declare is simply absent.
    """

    def __init__(self, inner: FileImportedHandStore) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        if name.startswith("_") or name not in vars(ImportedHandRepository):
            raise AttributeError(
                f"{name!r} is not declared by ImportedHandRepository"
            )
        return getattr(self._inner, name)


def test_the_service_needs_only_what_the_repository_port_declares(
    tmp_path: Path,
) -> None:
    store = FileImportedHandStore(tmp_path)
    pending = playable_pending_record()
    assert pending.identity is not None
    key = imported_hand_record_key(pending.identity)
    store.save(key, pending)
    service = ImportedHandLifecycleService(
        store=PortOnlyRepository(store),
        extract=extract_hero_decision_points,
        now=lambda: APPROVED_AT,
    )

    service.approve(key, revision_one())
    service.reapprove(key, revision_two())
    service.withdraw(key, reason="player withdrew approval", at=CLOSED_AT)

    assert store.get(key).lifecycle.status == "withdrawn"
    assert sorted(artifact_keys(store, key)) == [(1, 0), (2, 0)]
