# ADR 0067: Require Independent Reference-Source Qualification

Status: accepted

Date: 2026-09-04

## Context

The grading domain can already compare one approved canonical decision with a
complete, route-bound `ResolvedReferencePolicy`. It preserves policy, engine,
economics, utility, tolerance, and EV-unit provenance and keeps every result
behind the later teaching-content activation gate. The comparison previously
trusted the caller-supplied `solved` policy label, however, because source
rights, independent-solved evidence, benchmark results, and coverage approval
were explicitly left upstream.

Issues #412 and #416 require those upstream claims to fail closed. The retained
V1 chart must remain heuristic, a source license must match its actual delivery
mode, and benchmark or coverage evidence from one revision must not authorize a
different policy, engine, economic model, utility, or support tolerance.
Remote-source qualification must also remain distinct from consent and from
proof that one response came through an authorized minimized request.

## Decision

`grade_decision` requires an independent `ReferenceSourceQualification` beside
every supplied reference policy. The qualification is a strict, immutable
evidence snapshot. It records an assessment revision, assessor and time, source
and configuration identities, independent-solved evidence, the coverage
manifest, delivery-mode-specific rights, benchmark suite and threshold outcome,
and an exact `ReferencePolicyQualificationBinding`.

The binding covers the reference, policy, tolerance, evidence, artifact,
domain-computed canonical policy content, coverage, route, exact decision
context, engine, economics, utility, EV unit, and support-threshold identity
used by the resolved policy. Any mismatch returns heuristic,
reference-unavailable, mastery-ineligible output while retaining the attempted
reference and qualification for audit. Missing, staged, rejected, or
non-passing qualification also remains heuristic and ungraded. Policy
completeness and action support are evaluated only after this source gate.

A shipped static lookup requires explicit commercial-use, embedding,
redistribution, and update rights. A server-side feed requires commercial-use,
commercial-serving, and derived-output rights, but source qualification does
not authorize a lookup. Until a later application boundary supplies exact
provider, consent, request, response, and failure provenance for one delivered
reference, a server-side qualification returns `reference_delivery_unverified`
and cannot produce a solved grade.

The qualification contract does not fetch legal evidence, execute a benchmark,
select a source, persist an assessment, configure a provider, send a network
request, activate a reference, approve teaching content, update mastery, or
schedule drills. No production composition constructs a qualified reference in
this decision.

## Consequences

A complete policy object is no longer sufficient to create gradeable evidence.
All future source adapters must obtain a reviewed, exact qualification from an
independent application authority, and remote adapters must additionally prove
per-lookup delivery authorization before the grading boundary is widened for
them. Existing fictional grading fixtures carry explicit qualification evidence
so mixed-policy, legality, and EV behavior remain testable without claiming a
real source exists.

This closes a structural bypass in issue #416 but does not complete the external
source acquisition and Phase 0 evidence work in #412, the gate decision in
#414, remote transport, reference activation, grade persistence, mastery, or
drill scheduling.
