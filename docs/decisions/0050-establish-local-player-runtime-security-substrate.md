# ADR 0050: Establish Local Player Runtime Security Substrate

Status: accepted

Date: 2026-08-31

## Context

ADR 0046 requires the V2 player UI, API, and writable store to run together on
the player machine. Loopback binding is necessary but insufficient: a browser
can still be induced to contact a loopback service, DNS rebinding can manipulate
the `Host` header, and proxy-header trust can manufacture a local peer. Reusing
the hosted V1 FastAPI composition would also make its administrative screenshot
and legacy routes reachable from the player runtime.

No V2 import or learning route is ready to expose. The security boundary must
therefore exist before those routes land, and the deployed Worker and hosted V1
backend must reserve the player namespace before it carries sensitive payloads.

## Decision

The player runtime uses a separate allowlist-composed FastAPI application. It
does not wrap or mount the V1 application. Its launcher has a fixed
`127.0.0.1:8765` listener, disables proxy-header interpretation, and offers no
LAN or hosted-mode switch.

The runtime creates a 256-bit per-installation secret in the configured local
data directory. The secret is a regular, current-user-owned file with no group
or world permissions and never enters the browser. At launch, the server mints
a short-lived one-use bootstrap ticket and opens it in the URL fragment. The
bootstrap shell removes the fragment before exchanging the ticket for a
process-local bearer session and independent CSRF token held in browser session
storage. The server retains only keyed token digests in memory, so a restart
invalidates every browser session.

Every request must have a loopback socket peer and the exact configured local
`Host`; forwarded/proxy headers are rejected. Supplied origins must match the
local origin, and player API mutations require that exact `Origin`. Every player
API read and write requires the bearer session. Mutations other than the
one-use bootstrap exchange also require the session's CSRF token. Player shell
and API responses are non-cacheable and carry a restrictive browser policy.

`/api/player` is the reserved V2 player namespace. The Cloudflare Worker and
the hosted V1 ASGI composition reject direct and repeatedly encoded forms of
that namespace before proxying, static-asset fallback, or request-body reads.

This decision ships only the boundary substrate and authenticated readiness
shell. It does not add imported-hand, approval, grading, learning, backup, or
lifecycle routes, and it does not make the Phase 1 runtime gate pass.

## Consequences

Future V2 player routes have one explicit application composition and security
contract to enter. They cannot accidentally inherit V1 administrative routes,
CORS, proxy secrets, or hosted deployment behavior. Local callers cannot treat
loopback reachability as authorization, and the permanent installation secret
is not copied into browser storage, URLs, command arguments, or logs.

The bootstrap ticket is briefly present in a browser URL fragment. Fragments
are not sent in HTTP requests, and the shell erases it before the network
exchange; browser or endpoint compromise remains outside the threat boundary.
Session state is intentionally lost on browser or server restart and is renewed
by launching the runtime again.

The readiness shell is not the V2 player product. Issue #432 remains open until
the dedicated PWA, writable lifecycle-safe store, backup/restore and migration
behavior, optional remote-provider consent boundary, packaging, and complete
direct-network evidence are implemented.
