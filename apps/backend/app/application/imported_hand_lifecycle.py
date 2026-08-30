"""The one boundary an imported hand's lifecycle transitions cross.

A hand's stored state and the decision artifacts derived from it are two
things on disk that must never disagree about which canonical revision is
current. ``active_decisions`` decides that from the record's live
lifecycle, so the moment a record publishes revision 2 the artifact for
revision 1 stops being served -- and if nothing published an artifact for
revision 2 in that same instant, the hand goes silently unlearnable while
still reporting itself as approved and eligible. Nothing later notices:
the artifact for revision 1 is still on disk, retained for audit, looking
exactly like a healthy one.

So every transition here publishes the record's new lifecycle state and
the artifacts derived from it in a single cascade. The journal is
roll-forward, which means "deactivate the outgoing artifact *before*
publishing the new state" cannot be expressed as an earlier write -- an
earlier write is just an earlier commit, with its own window. It is
expressed instead as one intent: both changes staged through one handle
and committed together, so there is no instant between them to observe.
For a withdrawal or a rejection the same rule needs no second stage at
all, because the record ceasing to be learning eligible is itself what
deactivates every artifact it had.

Two things this service deliberately does not do.

It does not compose lifecycle states by hand. Each verb builds the whole
``ImportedHandRecord`` it intends to publish and lets
``validate_aggregate`` accept or reject it: whether a withdrawal needs a
prior approval, whether an active pointer may name a given revision,
whether a reason may be blank, are all the aggregate's rules, and
re-deciding any of them here would put a second, drifting copy of the
domain in the application layer. A ``ValidationError`` propagates to the
caller and nothing is written.

It does not reach the store except through
``ImportedHandRepository``. The cascade is a port method that yields a
staging handle, so this layer composes a durable multi-file write while
knowing nothing about files -- which is what lets the rule above be
stated in terms of one intent rather than one directory.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.application.imported_hand_ports import (
    ImportedHandCascadeHandle,
    ImportedHandRepository,
)
from app.domain.imported_hands import (
    CanonicalHandRevision,
    HandDecisionExtraction,
    ImportedHandLifecycle,
    ImportedHandRecord,
)


class LifecycleCascadeError(RuntimeError):
    """A transition cannot be published as asked, before anything is staged.

    Reserved for the two things the domain cannot judge on its own: that
    the verb the caller named describes what is actually happening to
    this record, and that the extraction handed back describes the record
    about to be published rather than some other moment in its life.
    Everything the aggregate *can* judge raises ``ValidationError``
    instead, and everything the store can judge raises its own error --
    neither is wrapped, because a caller that cannot tell "you asked for
    the wrong thing" apart from "the disk is full" cannot respond to
    either.
    """


class ImportedHandLifecycleService:
    """Approve, reapprove, withdraw, and reject one imported hand.

    ``extract`` is injected rather than imported so this service can be
    given the domain's real extractor in production and something
    narrower in a test. That also means its result is untrusted input:
    see ``_require_bound_extraction``.

    ``now`` stamps an approval's ``lifecycle.changed_at``. Withdrawal and
    rejection take their instant from the caller instead, because those
    two record a decision a player made at a time the caller already
    knows and this service does not.
    """

    def __init__(
        self,
        *,
        store: ImportedHandRepository,
        extract: Callable[[ImportedHandRecord], HandDecisionExtraction],
        now: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._extract = extract
        self._now = now

    def approve(
        self, record_key: str, revision: CanonicalHandRevision
    ) -> ImportedHandRecord:
        """Publish this hand's first approval, with its decisions.

        Refuses a hand that already carries a canonical revision. That is
        a reapproval however it is spelled, and the cascade's operation
        label is the one thing an operator reading a write interrupted by
        a crash has to go on, so it must not say "first approval" when a
        supersession was in flight.
        """
        record = self._store.get(record_key)
        if record.canonical_revisions:
            raise LifecycleCascadeError(
                f"record {record_key} has already been approved at revision "
                f"{record.canonical_revisions[-1].revision}; approving it "
                "again supersedes that revision and must be published as a "
                "reapproval"
            )
        return self._publish(
            record_key,
            self._approved(record, revision),
            operation="approve",
        )

    def reapprove(
        self, record_key: str, revision: CanonicalHandRevision
    ) -> ImportedHandRecord:
        """Supersede this hand's current approval, with its decisions.

        The transition this whole module exists for: the outgoing
        revision's artifact stops being served the instant the new
        lifecycle state is visible, so the new revision's artifact has to
        become visible in that same instant.
        """
        record = self._store.get(record_key)
        if not record.canonical_revisions:
            raise LifecycleCascadeError(
                f"record {record_key} has never been approved; there is no "
                "revision to supersede, so this is a first approval"
            )
        return self._publish(
            record_key,
            self._approved(record, revision),
            operation="reapprove",
        )

    def withdraw(
        self, record_key: str, *, reason: str, at: datetime
    ) -> ImportedHandRecord:
        """Retire this hand's approval at the player's own request."""
        return self._close(
            record_key,
            status="withdrawn",
            operation="withdraw",
            reason=reason,
            at=at,
        )

    def reject(
        self, record_key: str, *, reason: str, at: datetime
    ) -> ImportedHandRecord:
        """Retire this hand's approval as wrong rather than unwanted."""
        return self._close(
            record_key,
            status="rejected",
            operation="reject",
            reason=reason,
            at=at,
        )

    def _close(
        self,
        record_key: str,
        *,
        status: str,
        operation: str,
        reason: str,
        at: datetime,
    ) -> ImportedHandRecord:
        """Publish a record that is no longer learning eligible.

        Nothing derived is staged, and nothing derived is deleted. The
        record losing its active revision is what stops every artifact it
        had from being served, and issue #432 keeps those artifacts on
        disk for audit -- removing one is only ever a purge's business.
        Staging a fresh "this hand is not active" verdict here would be
        worse than useless: it describes a record that is by definition
        not learning eligible, so nothing would ever serve it, and it
        would sit beside the real artifacts looking like one of them.
        """
        record = self._store.get(record_key)
        return self._publish(
            record_key,
            ImportedHandRecord(
                identity=record.identity,
                raw_sources=record.raw_sources,
                detections=record.detections,
                conflicts=record.conflicts,
                canonical_revisions=record.canonical_revisions,
                lifecycle=ImportedHandLifecycle(
                    status=status,
                    active_canonical_revision=None,
                    deletion_generation=record.lifecycle.deletion_generation,
                    changed_at=at,
                    reason=reason,
                ),
            ),
            operation=operation,
        )

    def _approved(
        self, record: ImportedHandRecord, revision: CanonicalHandRevision
    ) -> ImportedHandRecord:
        """Build the record this approval intends to publish.

        Deliberately assembled and handed straight to the aggregate's own
        validator: whether ``revision`` may follow the ones already
        retained, and whether the active pointer may name it, are the
        aggregate's rules and are not restated here.
        """
        return ImportedHandRecord(
            identity=record.identity,
            raw_sources=record.raw_sources,
            detections=record.detections,
            conflicts=record.conflicts,
            canonical_revisions=[*record.canonical_revisions, revision],
            lifecycle=ImportedHandLifecycle(
                status="active",
                active_canonical_revision=revision.revision,
                deletion_generation=record.lifecycle.deletion_generation,
                changed_at=self._now(),
            ),
        )

    def _publish(
        self,
        record_key: str,
        record: ImportedHandRecord,
        *,
        operation: str,
    ) -> ImportedHandRecord:
        """Commit ``record`` and everything derived from it as one change.

        The extraction is computed before the cascade opens, so a failure
        there costs nothing and holds no lock: there is no half-written
        state to unwind because nothing has been staged. Once the cascade
        is open, both stages go through the one handle.

        Whether to derive anything at all is decided from the record
        being published, never from which verb asked. That is what makes
        this boundary closed rather than a list of four special cases: a
        transition that leaves a hand learning eligible always republishes
        its decisions, so any future verb routed through here -- one that
        records a conflict, resolves one, or restores a purged hand --
        inherits the guarantee instead of having to remember it. The gap
        ``active_decisions`` documents (a record that stays active and
        stops being extractable without its revision moving) is exactly
        the gap this closes, and it closes only for transitions that come
        through here.

        One thing a future verb routed through here has to know, because
        the four below cannot reach it: every verb here either appends a
        canonical revision or ends the hand's eligibility, so a
        republished artifact always lands under a name nothing occupies.
        A verb that left the active revision *and* generation where they
        are -- recording a conflict against an already-approved hand is
        the obvious one -- would republish over the retained artifact at
        that same name rather than beside it, which is the one way this
        boundary could destroy audit history. Such a verb needs a ruling
        on that before it is written, not a fix here.

        The two stages are not ordered. "Deactivate before publish" is
        satisfied by there being one commit, not by which line runs
        first; the adapter resolves a staged artifact against the record
        staged beside it whichever way round they arrive.
        """
        extraction: HandDecisionExtraction | None = None
        if record.lifecycle.learning_eligible:
            extraction = self._extract(record)
            self._require_bound_extraction(extraction, record)

        cascade: ImportedHandCascadeHandle
        with self._store.begin_cascade(record_key, operation=operation) as cascade:
            cascade.stage_record(record)
            if extraction is not None:
                cascade.stage_decisions(extraction)
        return record

    @staticmethod
    def _require_bound_extraction(
        extraction: HandDecisionExtraction, record: ImportedHandRecord
    ) -> None:
        """Refuse an artifact that does not describe ``record``.

        ``extract`` is a constructor argument, so nothing structural
        guarantees its result belongs to the record about to be
        published; and a wrong one does not fail loudly downstream. The
        store files an artifact under the revision and generation it
        resolves for it, and each mismatch below resolves to a name the
        published record will never look under -- leaving an active hand
        with no decisions at all, which is the one outcome this whole
        module exists to prevent. Checked before the cascade opens, since
        the point is that it is never staged.

        A rejection is exempt from the revision check because the domain
        forbids a ``not_extractable`` outcome from binding a canonical
        revision at all; the store files it under the record's own active
        revision instead. Except a ``not_active`` rejection, which asserts
        from its own content that the record was not learning eligible
        when it was computed -- it can only be describing some other
        moment than the approval being published here, and the store
        always sends it to a slot no active record reads.
        """
        lifecycle = record.lifecycle
        if extraction.deletion_generation != lifecycle.deletion_generation:
            raise LifecycleCascadeError(
                "the extraction was computed at deletion generation "
                f"{extraction.deletion_generation}, but this record "
                f"publishes generation {lifecycle.deletion_generation}"
            )
        if extraction.outcome == "not_extractable":
            if extraction.rejection == "not_active":
                raise LifecycleCascadeError(
                    "a not_active rejection cannot describe a record being "
                    "published as learning eligible"
                )
            return
        if extraction.canonical_revision != lifecycle.active_canonical_revision:
            raise LifecycleCascadeError(
                "the extraction is bound to canonical revision "
                f"{extraction.canonical_revision}, but this record publishes "
                f"revision {lifecycle.active_canonical_revision} as active"
            )


__all__ = ["ImportedHandLifecycleService", "LifecycleCascadeError"]
