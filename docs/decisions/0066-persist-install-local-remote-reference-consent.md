# ADR 0066: Persist Install-Local Remote-Reference Consent

Status: accepted

Date: 2026-09-04

## Context

The remote-reference domain already defines a deny-by-default preflight,
immutable provider-policy and disclosure snapshots, minimized outbound route
state, and consent generations. It intentionally has no networking or
persistence. Issue #416 requires explicit, revocable consent before any future
remote solved-feed request, while #432 requires player state to remain in the
local runtime and backup/restore to preserve privacy and lifecycle guarantees.

Persisting a provider transport before issue #412 qualifies a real source would
cross the current architecture boundary. Leaving consent only in memory would
make revocation and restart behavior unauditable and would not provide an
authoritative state for the future immediate pre-dispatch recheck.

## Decision

Workspace layout version 2 adds an owner-only regular file named
`.poker-hero-remote-reference-consent.json`. It stores a strict versioned
envelope containing either no consent or one current immutable
`RemoteReferenceConsent` snapshot. It contains no credential, route binding,
outbound request, response, player record, or learning state.

Fresh and manifestless workspaces create empty consent state before publishing
the version 2 manifest. An existing version 1 workspace is upgraded under the
exclusive data-volume lock. The migration validates the private imported-hand
store, durably creates empty consent state with create-only publication, and
only then atomically replaces and syncs the workspace manifest. A retry reuses
and validates any consent file left by an interrupted migration. Version 2
startup requires the file to be an owner-only regular file and rejects missing,
symlinked, oversized, malformed, or unsupported state.

The player runtime remains local-only because this decision adds no transport.
Consent is available only when its embedding application supplies a fully
validated active `RemoteReferenceProviderPolicy`; the default packaged
composition supplies none. Authenticated local routes expose the non-secret
policy/disclosure required for an informed UI, accept consent, and revoke it.
Mutation routes retain the runtime's Origin and CSRF enforcement.

The offer includes the exact UTF-8 terms, privacy, retention, training-use, and
logging policy text. Every document must match its declared SHA-256, and all
text and hashes are covered by the displayed complete provider-policy digest.
Clients acknowledge that digest and the policy/disclosure revisions and affirm
the disclosure, network dependency, and retention/use terms. They cannot choose
provider identity, endpoint, outbound categories, consent ID, or timestamps.
The server checks the complete policy digest and derives the persisted values
from its policy snapshot. Acceptance
compare-and-sets the current generation and creates the next one. Revocation
compare-and-sets the current generation, changes it to `revoked` without
changing that acceptance generation, and is idempotent for retries. Both
mutations hold the exclusive data-volume lock and durably replace the state
before returning success. An idempotent revocation retry re-saves the revoked
snapshot so it re-proves directory durability if a preceding attempt replaced
the file but failed its final directory sync.

Consent state is installation authorization, not portable hand data. Player
backup export excludes it and restore never changes it. This prevents an older
archive from reactivating consent after revocation. A future portable consent
audit would need a separate monotonic, revocation-safe schema.

## Consequences

The application now has restart-stable, fail-closed consent state and an API
boundary suitable for a future explicit player control. No remote provider is
configured, no network request is sent, and no reference result can become
solved or mastery-gradeable through this change. A future dispatch adapter must
still atomically reread current provider status, consent status, and consent
generation immediately before every request or retry, enforce the resolved
origin allowlist, and retain request/response provenance. This change advances
issues #416 and #432 but closes neither issue nor the source gate in #412.
