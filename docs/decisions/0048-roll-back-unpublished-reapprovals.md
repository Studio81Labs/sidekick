# ADR 0048: Roll Back Unpublished Reapproval Attempts

Status: accepted

Date: 2026-08-31

## Context

ADR 0046 and the V2 product specification require correction/reapproval to
atomically supersede the derived learning state of the outgoing canonical
revision. Issue #411 described this as deactivating old decisions before a
rebuild so stale artifacts never remain active after failure. Issue #432 also
allowed a lifecycle cascade either to roll back or to leave the hand immediately
learning-ineligible. Both readings protect revision consistency, but they differ
when extraction fails before any replacement state has been staged.

The player may have attempted a correction because the active revision is wrong.
Keeping it active can therefore retain questionable learning input until the
retry succeeds. Conversely, treating an unpersisted attempt as accepted would
require a second durable failed-rebuild lifecycle state and recovery transition.
That failure marker might itself be impossible to persist during the storage
failure it is meant to describe. It would also make an exception, rather than a
committed revision, supersede previously approved canonical state.

The current cascade journal already supplies a precise durability boundary.
Extraction and validation happen before a cascade opens. Before the journal is
ready, failure leaves no publish intent. After it is ready, the per-hand key
refuses newer lifecycle writes and startup recovery completes the intent by
idempotent roll-forward.

## Decision

A correction/reapproval is accepted for eventual supersession only when the
replacement canonical revision and its derived artifacts enter the lifecycle's
durable publish boundary. The outgoing revision remains current until
roll-forward publication makes the replacement record active.

Extraction, binding validation, staging, or finalization failure before durable
publish intent rejects the attempted reapproval atomically. The prior approved
revision and the artifact derived from that exact revision remain active. The
artifact is not stale because its canonical revision was never superseded. The
caller must report that the correction was not accepted and allow the player to
retry; it must not present the attempted correction as saved.

Once publish intent is durable, the existing journal protocol applies: the hand
refuses newer lifecycle writes until recovery rolls the pending intent forward.
Superseded artifacts remain audit-only after the replacement record becomes
active. Unrelated hands continue independently throughout either failure path.

This decision clarifies ADR 0046's atomic reapproval rule. It does not change the
separate withdrawal, rejection, deletion-pending, or permanent-purge semantics.

## Consequences

No new failed-rebuild lifecycle status, backup precedence rule, or recovery API
is introduced. A failed pre-publication attempt does not silently deactivate a
previously accepted revision, and retry follows the ordinary `reapprove`
transition. The eventual player UI/API must keep the unsaved correction visible
to the player, identify the failure, and offer retry or an explicit
withdraw/reject action when the player wants the prior approval removed
immediately.

The lifecycle test contract distinguishes the two sides of the durability
boundary: extraction failure leaves revision 1 active and a later retry can
publish revision 2, while a ready interrupted cascade closes that hand to newer
writes until roll-forward recovery completes it.
