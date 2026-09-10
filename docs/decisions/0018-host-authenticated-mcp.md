# ADR 0018: Host an Authenticated MCP Endpoint

Status: superseded in part by ADR 0080

The hosted transport, per-environment principal identity, opaque-token storage,
independent administration boundary, and disabled-by-default deployment gate
remain current. ADR 0080 replaces this ADR's `read + write` principal scope,
write-enable setting, separate write-rate-limit, and data-tool decisions with
the current permanent read-only environment-status capability.

## Context

ADR 0017 deliberately shipped the first gateway as local stdio because Poker
Hero did not yet have an agent authentication boundary. That requires every
developer machine to run and configure a gateway process even though the
gateway ultimately operates on one deployed environment. The Nexcue developer
workflow demonstrates the desired operator experience: an environment URL,
an opaque bearer token created by the application's admin surface, and a Codex
`bearer_token_env_var` setting.

The Worker-to-backend shared secret cannot be used as agent identity. Sharing
it would grant every holder the backend proxy's authority and would make
individual rotation and revocation impossible. A hosted gateway also cannot
accept local screenshot paths because those paths belong to the agent machine,
not the server.

## Decision

Each existing FastAPI deployment may host a stateless Streamable HTTP MCP route
at the exact path `/mcp`. `POKER_MCP_ENABLED=false` remains the default global
kill switch. When enabled, `POKER_MCP_PUBLIC_URL` fixes the endpoint and the
deployment's existing `POKER_DEPLOYMENT_ENVIRONMENT` fixes its environment.

Operators create named MCP principals from the protected application
information/admin surface. Credentials use a random `phmcp_` opaque token,
are displayed only once, and are persisted under `POKER_DATA_DIR/mcp` only as
a SHA-256 hash plus a non-secret lookup prefix. Each principal is bound to the
deployment environment and can expire, rotate, or be revoked independently.
MCP responses and token-issuance responses are non-cacheable.

Principals have `read` or `read + write` scope. Server authorization is
independent of Codex's client approval setting. Writes additionally require
`POKER_MCP_ALLOW_WRITES=true`, which configuration permits only in staging.
Production therefore remains read-only even if a stored principal contains a
legacy write scope. Read and write requests have separate per-principal
in-memory rate limits.

The hosted gateway invokes the same FastAPI contract through an in-process
ASGI HTTP client. It retains the environment health check before each data
operation, including the existing proxy-secret boundary for internal API
calls. Hosted discovery omits `submit_screenshot`; screenshots continue to be
uploaded through the browser. The local stdio gateway remains supported and
retains its explicitly rooted local screenshot tool.

Administrative backups, imports, benchmark execution, and bulk archive tools
remain outside both MCP transports.

## Consequences

- Codex can connect directly with a URL and environment-injected bearer token.
- Compromise containment can revoke one principal or disable the complete MCP
  route without rotating the Worker credential.
- Staging and production credentials are not interchangeable.
- The credential file is deployment state and is intentionally excluded from
  portable application backups.
- The existing protected app/Cloudflare Access boundary is the operator
  authorization boundary for principal-management endpoints; Poker Hero does
  not introduce a second user-role system in this decision.
- A future customer-facing MCP requires OAuth, consent, and a separate threat
  model. These developer credentials must not be extended to customers.
