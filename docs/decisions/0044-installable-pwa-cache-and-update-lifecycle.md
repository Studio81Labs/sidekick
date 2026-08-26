# ADR 0044: Installable PWA Cache And Update Lifecycle

Status: accepted

Date: 2026-08-26

## Context

Poker Hero's browser application must be installable and able to open a
recognizable shell after connectivity is lost. Its screenshots, detected poker
state, user corrections, training answers, lesson notes, recommendations,
history, benchmarks, backups, and MCP traffic are private and can change on the
server. Serving any of those responses from a service-worker cache could present
stale analysis as current or retain sensitive data outside the existing bounded
browser projections.

A newly deployed worker can also replace the active application while a user is
editing or while a mutation is in flight. The application already has several
independent draft and operation owners, so update safety cannot depend on one
page-local `beforeunload` flag.

## Decision

The Vite production build generates one root-scoped service worker. Its owned
cache name is `poker-hero-shell-<build digest>`, where the digest covers the
worker policy, emitted navigation shell, and content-addressed application
assets. The worker may delete only older caches with the
`poker-hero-shell-` prefix.

The install cache contains only:

- `/`, the minimum navigation shell; and
- exact emitted, content-addressed files below `/assets/`.

Installation fetches the complete version before writing it, requires an HTML
shell and non-HTML successful asset responses, and deletes the version cache if
validation or a cache write fails. A successful SPA fallback therefore cannot
stand in for a missing bundle.

Those asset URLs are cache-first because their content hashes make them
immutable. Navigations are network-first; a successful navigation is returned
without mutating the active worker's install cache, and a network failure falls
back to that worker's install-time shell. This keeps the HTML paired with the
hashed assets and policy from the same build until the waiting worker is
explicitly activated. Cross-origin requests are never intercepted.

Every request at `/api`, below `/api/`, or at the exact `/mcp` path is
network-only. The path check fails closed for encoded equivalents. This excludes
screenshot and upload bodies, detected and approved state, history,
recommendations, training data, benchmark imports and reports, backups, health
data, and MCP messages without relying on each endpoint's current spelling. No
runtime response outside the emitted asset allowlist is added to Cache Storage.
Offline mode therefore opens the application chrome but does not offer offline
analysis or queued mutations. The UI displays a persistent offline notice and
network operations retain their visible failure and retry behavior; browser
projections must not be described as freshly synchronized while offline.

The worker does not call `skipWaiting()` during installation. The application
owns activation through one update coordinator and a centralized safety
registry. Every unsaved form or active operation registers a named reason. The
initial registry covers:

- detected-state corrections;
- selected screenshot files and screenshot title, notes, and tags;
- unlocked training action, sizing, and certainty answers;
- edited lesson notes;
- MCP administration drafts and an unacknowledged one-time credential;
- active screen capture, upload, approval, recommendation, screenshot mutation,
  backup restore, training-review mutation, MCP mutation, and benchmark
  operations.

New local drafts and non-replayable operations must register before they ship.
The same aggregate state guards browser unloads. When a worker is waiting, the
UI announces the update but never activates it while an operation is active.
With dirty state, activation requires an explicit discard confirmation. With no
dirty or busy reason, the user may explicitly activate and reload. The
confirmation is bound to the registered dirty revision, so an edit made while
activation is pending requires fresh confirmation. The coordinator rechecks
safety on `controllerchange`; if state became unsafe after activation began, the
new worker may take control but reload remains deferred.

The deployed edge Worker runs before static assets so it can apply response
headers consistently. `/sw.js` is revalidated on every load and receives
`Service-Worker-Allowed: /`; HTML and other stable-name metadata are revalidated;
successful non-HTML content-addressed `/assets/` files receive a one-year
immutable cache policy. Missing asset responses, including successful HTML SPA
fallbacks, remain revalidatable so a later rollback can restore that hash. The
Nginx image applies the same header contract for its static deployment path.

## Threat Boundaries

The service worker is not an authorization, durability, or synchronization
boundary. Cloudflare Access, the same-origin API Worker, backend authentication,
and server persistence remain authoritative. Cache Storage is readable by any
successful same-origin script, so it intentionally contains no poker data,
credentials, API responses, screenshots, source captures, or user-authored
drafts. An XSS compromise can still read the live page and make authorized
requests; limiting the cache prevents the worker from increasing that exposure.

The offline shell can render bounded browser projections that already exist for
recovery, but the offline notice makes their disconnected status explicit and
no service-worker response claims that analysis is current.

## Consequences

Installed users can launch the application shell without a network connection,
and immutable bundles avoid redundant downloads. All private and mutable
features still require the network and fail visibly when it is unavailable.
Updates wait for an explicit safe handoff instead of silently replacing an
active workspace. Adding a form or long-running operation now includes a safety
registry obligation and corresponding update-lifecycle test.

A small generated worker is preferred over a general runtime-caching framework.
That keeps the cache allowlist reviewable and makes an accidental private-route
strategy harder to introduce. Background Sync and offline mutation replay are
out of scope.

## Rollout And Rollback

Rollout requires manifest and icon validation, desktop and mobile worker-scope
tests, an online-to-offline shell test, Cache Storage inspection for private
routes, and dirty/busy update tests before deployment.

Normal rollback redeploys the last known-good application build. Its distinct
worker digest installs beside the current worker and follows the same safe update
prompt. For an emergency client-side reset, unregister the Poker Hero service
worker, delete only cache names beginning with `poker-hero-shell-`, and reload
while online. The next successful production load registers the deployed worker
again. Rollback must not delete unrelated origin caches or browser projections.
