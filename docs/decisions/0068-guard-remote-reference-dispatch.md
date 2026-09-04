# ADR 0068: Guard Remote-Reference Dispatch

Status: accepted

Date: 2026-09-04

## Context

The remote-reference domain already produces a deny-by-default dispatch
candidate only after exact route, provider-policy, disclosure, rights, manifest,
and consent checks. Install-local consent is durable and revocable. A candidate
deliberately says that a fresh check is still required, however, because policy
or consent can change after preflight. Passing that candidate directly to a
future transport would create a time-of-check/time-of-use authorization bypass.

Issue #416 also requires revocation to stop new remote requests immediately and
provider, network, or response failure to remain visibly unavailable and
ungraded. No source is yet qualified for a real remote lookup, so adding an HTTP
adapter, credentials, response decoder, or runtime wiring would be premature.

## Decision

Add a transport-neutral application guard around one remote lookup attempt. The
caller supplies a prior dispatch candidate, an authority guard, an injected
transport adapter, and a clock. The guard supplies mode, provider policy,
consent, and the current active canonical decision as one snapshot and retains
its serialized authorization scope while the guarded attempt performs its one
transport call. A future composition can therefore use the same lock or
equivalent exclusion boundary as consent and hand-lifecycle mutation,
eliminating revocation, reapproval, withdrawal, rejection, and deletion races
between the reload and the call.

Immediately before every transport call or retry, the guard reloads and
validates the authority snapshot, rebuilds the closed route from the reloaded
active decision, repeats domain preflight, and requires the fresh candidate to
match every original provenance field except evaluation time. Local-only mode,
revocation, expiry, provider or disclosure drift, consent-generation change,
missing or superseded decision state, route drift, a reversed clock, or any
stale candidate makes no transport call. Only `RemoteReferenceRouteRequest` is
given to the injected callback; local
decision identity, state hashes, consent, provider policy, and learning records
are not transport arguments.

The adapter publishes a non-secret binding to its provider identity,
configuration revision, policy revision and digest, and endpoint origin. The
guard requires an exact match with fresh authority before invocation, preventing
consent for one provider or origin from authorizing a differently configured
transport.

The callback translates only explicit network and provider failures through
typed exceptions. A non-bytes return is retained separately as a transport
contract failure; other unexpected programming errors remain visible rather
than being swallowed. Network, provider, and transport-contract failures retain
the freshly checked request provenance and remain ungraded with fallback
forbidden. The adapter must
apply a 1 MiB read cap while receiving the body, and the guard independently
checks the materialized length. Empty or oversized bytes become
`response_invalid` with a digest computed locally. A bounded body becomes an
immutable response candidate
whose validation remains `pending`; it cannot contain a resolved reference or
be used for grading.

If the wall clock is invalid or moves backward after egress, the result retains
the already validated dispatch-authorization timestamp and labels it as a
fallback time basis. This preserves the request and any locally observed
response digest without pretending a later timestamp was observed.

Because dispatch now depends on exact route hashes, Decimal canonicalization is
defined from `Decimal.as_tuple()` and rendered in exact fixed-point form without
arithmetic or active-context rounding. Existing ordinary encodings remain
stable, equivalent exponents retain one digest, and distinct long values remain
distinct.

## Consequences

There is now one application seam where a future remote adapter can prove the
last-moment authorization and failure behavior required by #416. Reusing a
candidate after consent reacceptance, policy replacement, or decision change
fails closed, and every retry repeats the same guard.

No real provider is configured and no network request can occur in the packaged
runtime. This decision does not add an HTTP implementation, credentials, DNS or
redirect enforcement, response decoding, source qualification, persistence,
resolved-reference promotion, learning-content activation, mastery, or drills.
A future HTTP adapter must still pin the configured HTTPS origin after DNS
resolution, reject private/loopback/link-local destinations and redirects, and
translate its failures into the explicit transport contract. Issues #412 and
#416 therefore remain open.
