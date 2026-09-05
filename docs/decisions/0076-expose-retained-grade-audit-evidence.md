# ADR 0076: Expose Retained Grades as Historical Audit Evidence

Status: accepted

Date: 2026-09-05

## Context

ADR 0074 retains complete `ReferenceActivatedGrade` artifacts beneath each
imported hand, but deliberately added no active-grade reader. Those artifacts
are useful review evidence: they preserve the solved policy, qualification,
economics, content, activation, and hand revision that produced a historical
classification.

Serializing the retained model directly is unsafe. Its content-ready evidence
contains a canonical decision snapshot, source evidence pointers, and reviewed
principle content that are not needed by the player audit surface. Conversely,
filtering artifacts through current hand and catalog revalidation would erase
the distinction between immutable history and present learning authority.

## Decision

Add an authenticated local-player read endpoint at
`GET /api/player/hands/{record_key}/grade-audits`. The player workspace reads one
bounded page under the hand's in-process stripe, shared interprocess stripe,
and shared data-volume lock. It requires a final hand record and uses the
imported-hand store's existing artifact loader so each returned artifact is
validated against its storage identity, hand identity, named canonical
revision, deletion generation, decision index, and re-derived decision.

Pages retain storage order but expose only SHA-256-derived opaque audit IDs and
cursors, never artifact filenames or paths. An unknown cursor fails closed. A
missing, malformed, or mismatched artifact fails the requested page with one
redacted error rather than returning a partial or apparently complete history.

Return a purpose-built immutable projection. It includes the decision binding,
classification, policy candidates and match, EV cost/unit, reference and policy
revisions, route and engine identities, economics and utility models, source
qualification and redacted evidence identities, content revision bindings,
coverage-band digest, catalog snapshot, activation, and mastery-series identity.
It excludes raw hand history, the canonical decision snapshot, evidence
pointers, principle text, provider credentials, and storage details.

Every item is labeled `historical_only` and preserves
`requires_current_catalog_hand_and_content`. The reader intentionally does not
call the current-authority revalidation boundary from ADR 0073. It performs no
reference lookup, remote dispatch, catalog publication, persistence, mastery
mutation, or drill scheduling. Any future learning consumer must still reload
and revalidate current hand, reference, and content authority inside its own
mutation scope.

Withdrawal and reapproval leave prior audit items visible with their immutable
revision bindings. Permanent purge and authorized reimport continue removing
them atomically with the hand-derived artifacts.

## Consequences

Players and future review UI can inspect why a retained historical grade was
produced without granting that artifact present learning authority or exposing
private retained inputs. The endpoint is read-only, loopback-only, session
authenticated, origin/host constrained by the existing runtime middleware, and
served with `Cache-Control: no-store`.

The packaged reference and learning-content catalogs remain empty. This does
not supply a production solved reference, close the Phase 0 gate, calculate
mastery, analyze aggregate mixing, schedule drills, or add a PWA consumer.
