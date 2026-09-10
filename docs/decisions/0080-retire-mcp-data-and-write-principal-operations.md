# ADR 0080: Retire MCP Data and Write Principal Operations

Status: accepted

Date: 2026-09-09

Supersedes: the read/write scope, write enablement, write rate limiting, and
data-tool portions of ADR 0018

## Context

ADR 0079 and C3 of #517 make the hosted OCR application an explicit
administrator-only operator surface. The former MCP data and mutation tools
would duplicate that surface and retain removed route contracts. They are not a
required V2 player, OCR, review, benchmark, backup, or administrator capability.

The optional trusted-developer MCP transport remains useful for verifying the
configured staging or production environment. That narrow status operation does
not need a write scope, a write enablement setting, a write rate limit, or
access to operator data.

## Decision

Both local stdio and optional hosted `/mcp` expose exactly one read-only tool:
`get_environment_status`. It reports only bounded deployment health and
environment identity. It does not expose job, image, history, approval,
upload, archive, backup, dataset, benchmark, parser, or player data.

MCP principals have exactly the persisted `read` scope. Principal creation,
rotation, revocation, expiry, hashed opaque-token storage, environment binding,
the disabled-by-default `POKER_MCP_ENABLED` gate, and the separate
`MCP_ADMIN_TOKEN` administration boundary remain as defined in ADR 0018.
`POKER_MCP_ALLOW_WRITES`, write scopes, write rate-limit configuration, and all
write or data-oriented MCP tools are retired without a compatibility reader or
forwarding path.

Operator data and mutations remain solely on `/admin/ocr` and
`/api/admin/ocr/...`, protected by the OCR administrator authorization boundary.
An MCP principal is never an operator credential.

## Consequences

- Deployment smoke checks may issue an ephemeral read principal and call only
  `get_environment_status`.
- Current `principals.json` records with a scope other than exactly `read` are
  rejected without rewrite, normalization, or deletion; operators create fresh
  principals in an empty current development data directory.
- Future implementation must not add MCP data or mutation tools, write scopes,
  or a write-enable switch without a new architecture decision and an explicit
  product/security review.
