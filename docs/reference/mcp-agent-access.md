# MCP Agent Access

Poker Hero's hosted MCP endpoint is for trusted developer agents performing
post-hand training and review. It is not a customer API and does not provide
live-play assistance.

## Security model

Access has three independent gates:

1. `POKER_MCP_ENABLED=true` exposes `/mcp`; otherwise the route is absent.
2. Every request needs an active, unexpired bearer credential created by the
   same deployment environment.
3. Every write needs both a credential with `write` scope and
   `POKER_MCP_ALLOW_WRITES=true`. The latter is valid only in staging.

Credential administration has an additional operator boundary: the public
Worker requires its per-environment `MCP_ADMIN_TOKEN` on
`/api/mcp/principals` and all descendant routes. This is not an MCP agent token.

The server stores a token hash and short display prefix, never the plaintext
token. Rotation immediately invalidates the previous token. Revocation is
immediate and safe to repeat. MCP and issuance responses use `Cache-Control:
no-store`.

## Deployment configuration

Configure the staging Coolify application with:

```dotenv
POKER_MCP_ENABLED=true
POKER_MCP_PUBLIC_URL=https://<staging-agent-origin>/mcp
POKER_MCP_ALLOW_WRITES=true
POKER_MCP_READ_CALLS_PER_MINUTE=60
POKER_MCP_WRITE_CALLS_PER_MINUTE=10
POKER_MCP_ALLOWED_ORIGINS=[]
```

The public URL must use HTTPS and the exact `/mcp` path. CLI clients normally
omit `Origin`, so an empty origin list is appropriate. Add only exact HTTPS
origins if a browser MCP client is required; wildcards are not supported.

Leave production unconfigured for now. When production read access is later
approved, configure its own URL and enable the route while keeping
`POKER_MCP_ALLOW_WRITES=false`.

In the GitHub `staging` environment, configure a separate high-entropy
`MCP_ADMIN_TOKEN` secret. The PWA deployment publishes it only as an
encrypted Worker binding. Never reuse `API_PROXY_SECRET` or an agent principal
token. The Worker rejects administration when this binding is absent and strips
the operator bearer header before proxying an authorized request to FastAPI.

Set the `MCP_SMOKE_URL` environment variable to the same exact public HTTPS
`/mcp` URL. After each PWA deployment, the workflow uses the admin
boundary to issue an ephemeral read-only principal, initializes the MCP server,
calls `get_environment_status`, and revokes the principal. The smoke principal
also expires after one hour so a failed cleanup cannot leave durable access.

## Principal lifecycle

Open the app information dialog and find **Agent access**.

- Enter the staging `MCP_ADMIN_TOKEN` and unlock credential management. The
  value stays only in browser component memory and is cleared by locking,
  closing, or reloading the page.
- Create a descriptive credential and select the least privilege needed.
- Copy the token from the one-time display into approved secret storage.
- Rotate an active credential to replace a lost or exposed token.
- Revoke it when access is no longer required.

Prefer separate read-only and read/write credentials. Credential records live
under `POKER_DATA_DIR/mcp` and are not part of application backup archives.

## Codex configuration

Expose the token to the Codex process through an environment variable, then
add only the variable name to Codex configuration:

```toml
[mcp_servers.poker_staging]
url = "https://<staging-agent-origin>/mcp"
bearer_token_env_var = "POKER_MCP_STAGING_TOKEN"
default_tools_approval_mode = "writes"
```

Do not place the token itself in `config.toml`, repository files, shell
history, screenshots, pull requests, or chat transcripts.

## Tool surface

Read access covers environment status, the processing queue, individual jobs,
history search, training progress, and benchmark summaries. Staging write
access covers reviewed-state approval, pre-reveal decision recording,
educational recommendation requests, and lesson review for existing jobs.

The hosted endpoint does not accept a local image path. Upload screenshots in
the Poker Hero UI first, then let the agent inspect or continue the resulting
job. Backup restore, dataset import, benchmark execution, and bulk archival are
not exposed.

The local stdio gateway's screenshot upload tool now targets the administrative OCR test boundary and is denied unless the deployment enables that mode; the gateway does not carry the administrative token, so screenshot uploads are made through the PWA administrator tools instead.

## Incident containment

1. Revoke the affected principal.
2. Set `POKER_MCP_ALLOW_WRITES=false` and redeploy staging if writes may be at
   risk.
3. Set `POKER_MCP_ENABLED=false` and redeploy for the global kill switch.
4. Rotate any other credential that shared the same secret-storage boundary.

The Worker-to-backend shared secret is not an MCP credential and must never be
given to an agent.
