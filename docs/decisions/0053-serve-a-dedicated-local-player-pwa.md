# ADR 0053: Serve a Dedicated Local Player PWA

Status: accepted

Date: 2026-08-31

## Context

The loopback player runtime has an authenticated API, isolated imported-hand
store, and conflict-safe backup/restore, but it still serves an inline readiness
document. The existing React application is the hosted V1 and administrative
OCR control panel. Serving that build locally would expose player navigation to
screenshot capture and hosted API assumptions, while extending the inline
document would create an unbuilt second frontend outside the PWA package.

The first useful player UI can remain deliberately narrower than import and
learning. Storage/recovery status and the existing backup endpoints already form
one complete local recovery workflow, and they do not require an unfinished
hand-history adapter or lifecycle transport contract.

## Decision

`apps/pwa/player` is a dedicated Vite/React entry for the local player runtime.
It has its own document, manifest, service worker, styles, API adapter, and build
output at `apps/pwa/dist-player`. It does not import the hosted application,
routes, API adapters, browser projections, administrative tools, error
reporting, or Worker configuration. It may share only generic PWA cache-policy
and service-worker runtime primitives.

The player application exchanges the existing one-use fragment ticket, erases
the fragment before the network request, and keeps the returned bearer session
and CSRF token in browser `sessionStorage`. It displays local data/recovery
status, downloads a player backup, restores a selected player-backup ZIP with
the CSRF token, and revokes the current session. It does not add import,
per-record, lifecycle, grading, learning, screenshot, or remote-provider paths.

The player service worker precaches only `/` and content-addressed build assets.
It treats every `/api` path and encoded equivalent as network-only, never writes
API responses to Cache Storage, and uses a player-specific versioned cache
namespace. Restore registers unload protection for the duration of its
non-replayable request. If the browser loses a restore response, it clears the
selected archive and treats the outcome as potentially committed. The runtime
holds storage-status reads behind that restore from request-body handling
through completion. Status waits on that gate asynchronously before using a
worker, then takes the shared data-volume lock for its snapshot, so follow-up
refreshes cannot exhaust the restore worker pool or be mistaken for a stable
pre-commit view. If refresh fails, the PWA hides stale status and backup actions
until restart. A restore storage failure can follow durable journal intent or
partial publication, so the runtime revokes that browser session and the player
clears its local credentials on an explicit `503`. A reload therefore cannot
resume ordinary work before process-start recovery; restart is required before
export or retry.

`pnpm player:start` builds and verifies the player PWA before starting Python.
The loopback FastAPI composition refuses to start when `index.html`, the
manifest, the service worker, or required static directories are absent or
symlinked. It loads the verified document, manifest, service worker, hashed
assets, and icons into an immutable process snapshot before opening the player
workspace, then serves only that snapshot. Later filesystem replacement
therefore cannot change code on the authenticated origin. All player API routes
are registered separately and remain behind the Host, Origin, session, and CSRF
middleware from ADR 0050. The hosted Worker and V1 FastAPI composition do not
serve this build.

## Consequences

The supported workspace command now delivers a co-located installable recovery
PWA and API from the exact loopback origin. Player backup controls no longer
require direct API use, and recovery attention remains visible without exposing
record contents. The build verifier rejects missing install metadata, mutable
precache entries, hosted/admin endpoint leakage, and icon drift.

This is not an operating-system installer or a completed player workflow.
Hand-history import, record review, lifecycle writes, migration/upgrade policy,
uninstall behavior, later learning stores, optional remote solved lookup, and
the complete Phase 1 network evidence remain open under issues #432 and #415.
