# Deployment

## Backend On Coolify

Configure the application with:

- Branch: `main`
- Build context: repository root
- Dockerfile: `apps/backend/Dockerfile`
- Port: `8000`
- Persistent volume mount: `/app/data`
- Health endpoint: `/api/health`

Create separate Coolify applications for `staging` and `production`. GitHub
Actions owns deployment promotion:

- a push to `main` deploys `staging`;
- a `v*` tag deploys `production`;
- a manual dispatch explicitly selects either environment.

Configure `COOLIFY_API_BASE_URL` as a repository variable and
`COOLIFY_API_TOKEN` as a repository secret. In each GitHub environment, set
`BACKEND_URL` and that environment's `COOLIFY_BACKEND_UUID`. The workflow
triggers the exact Coolify application, follows its deployment ID until it
finishes, and then verifies `/api/health`.

Start from `infra/docker/backend.env.example`. At minimum, set the parser,
layout, recommendation provider, data directory, upload limit, and allowed
origins. Set `POKER_DEPLOYMENT_ENVIRONMENT` to the exact Coolify application
environment (`staging` or `production`); environment-fixed MCP gateways reject
a missing or mismatched identity. The backend image already contains
`poker-postflop-solver`; keep
`POKER_LOCAL_SOLVER_ENGINE=postflop_solver` to use it. The default 768 MB solver
tree limit is separate from container overhead, so allocate at least 1.5 GB RAM
or lower `POKER_POSTFLOP_SOLVER_MAX_MEMORY_MB`. Keep provider URLs and
credentials in Coolify secrets.
To expose another poker client through `llm_vision`, add its normalized ID to
`POKER_PARSER_ENABLED_LAYOUT_PROFILES` and enable `llm_vision` in
`POKER_PARSER_ENABLED_PROVIDERS`. The API advertises parser/layout compatibility,
so deployment-defined profiles such as `pokerstars` are not offered with the
fixed-coordinate `ocr_cv` parser until local calibration is implemented.
Enable or select the `auto` parser only when `POKER_EXTERNAL_PARSER_URL` is set.
It tries local OCR for explicit registered client layouts, falls back to
external vision when local OCR rejects a capture, and routes `generic` or other
enabled layouts directly to the external endpoint. It never infers or changes
the selected layout profile.
`POKER_POSTFLOP_SOLVER_RANGE_MODE=contextual` uses a complete supported flop
open-and-call, open/3-bet/call, or open/3-bet/4-bet/call history whose
reconstructed root pot matches the recorded final commitments to select
position-aware ranges. It applies a reconstructed starting-stack policy when
the reviewed effective or visible stacks reconcile with current-street money;
otherwise evidence identifies the 100 BB standard assumption. Turn, river,
incomplete, and contradictory states retain the configured ranges. Set the mode
to `configured` when the deployment's explicit OOP/IP range strings must always
take precedence.

External OCR, solver, and LLM endpoints can each use an independent bearer
token. Configure the matching `POKER_*_BEARER_TOKEN` value as a Coolify secret
and use an HTTPS endpoint URL. `POKER_EXTERNAL_REQUEST_TIMEOUT_SECONDS` controls
all external HTTP parser and recommendation calls and defaults to 60 seconds.

For a public Coolify origin, generate a private Worker credential:

```bash
openssl rand -hex 32
```

Set that value as `POKER_PROXY_SHARED_SECRET` in Coolify and as the
`API_PROXY_SECRET` secret in the matching GitHub environment. The value
must contain at least 32 characters, and `BACKEND_URL` must use HTTPS. When
enabled, the backend accepts application API requests only through a Worker
carrying that secret. The unauthenticated `/api/health` route remains available
for Coolify health checks and reports the configured deployment environment.

Screenshot upload and live capture are disabled for players. To test parsers
against representative screenshots, set `POKER_ADMIN_OCR_TEST_ENABLED=true` and
a dedicated `POKER_ADMIN_OCR_TEST_TOKEN` (`openssl rand -hex 32`; at least 32
printable ASCII characters, never equal to `POKER_PROXY_SHARED_SECRET`). The
backend requires that token as `Authorization: Bearer ...` on every upload,
every benchmark dataset import, and every backup restore. Enter the token
only in the PWA **Administrator tools** dialog; it stays in browser memory
until locked or reloaded. The PWA verifies the token with the backend
through `GET /api/admin/ocr-test/session` before it unlocks any capture control.
Rollback is `POKER_ADMIN_OCR_TEST_ENABLED=false`, which also disables dataset
import and backup restore until the mode is enabled again; no setting restores
player-accessible capture or automatic recommendations.

This release removes the V1 recommendation and training routes and the
`recommended` job status. Before the backend starts, the container entrypoint
deletes job directories whose raw record has that retired status. It leaves
current records and malformed or unknown records untouched, and it takes the
exclusive data-volume lock before deleting anything. Current application
models remain strict; pre-release backups containing a `recommended` job are
still refused by `POST /api/backups/restore` with a 400.

After deployment, verify:

```bash
curl --fail https://<backend-origin>/api/health
test "$(curl --silent --output /dev/null --write-out '%{http_code}' \
  https://<backend-origin>/api/jobs)" = "401"
curl --fail https://<worker-origin>/api/jobs?limit=1
```

Every backend API response includes an `X-Request-ID`. The backend preserves a
valid caller-supplied ID or generates one, and emits a single-line JSON access
event containing that ID, the method, path, status, and request duration. Use
the ID to correlate a browser or Worker response with Coolify container logs.
Query strings and request bodies are not logged. Successful `/api/health`
probes are logged at debug level to keep routine platform checks quiet. The
event is emitted after the response body completes and identifies interrupted
or failed streams with `"outcome":"failed"`. Each container log line is a
standalone JSON object with its severity in the `level` field, ready for a JSON
log collector without stripping a Uvicorn prefix.
Set `POKER_ACCESS_LOG_LEVEL=DEBUG` when health-probe events are needed during
deployment diagnosis; the default `INFO` threshold suppresses them.

## Local Agent MCP Access

Use one local stdio MCP process per target environment. Start from
`apps/backend/mcp.env.example`, supply the variables through the MCP client's
secret/environment configuration, and run `pnpm backend:mcp`. Production
rejects `POKER_MCP_ALLOW_WRITES=true`; staging requires that explicit opt-in
before mutation tools are registered.

Prefer Cloudflare Access service credentials when the gateway calls the public
Worker. Store `POKER_MCP_CF_ACCESS_CLIENT_ID` and
`POKER_MCP_CF_ACCESS_CLIENT_SECRET` outside the repository. Direct backend
access can use `POKER_MCP_API_PROXY_SECRET` only from a trusted gateway process;
the value matches `POKER_PROXY_SHARED_SECRET` but remains an internal service
credential, not agent identity. All credential-bearing targets require HTTPS.

The gateway's only staging write tool approves a reviewed hand's canonical
state (`approve_hand_state`); screenshots must be uploaded through the app.
The gateway deliberately does not expose backup restore, dataset import,
benchmark execution, or bulk archive operations.

## Hosted Agent MCP Access

The backend can expose the same curated gateway as stateless Streamable HTTP at
`/mcp`. It is disabled by default. Follow
[`mcp-agent-access.md`](../reference/mcp-agent-access.md) to configure the exact
public staging URL, create a one-time bearer credential from the protected app
surface, and add the URL plus `bearer_token_env_var` to Codex.

For the current rollout, configure staging only. Keep production
`POKER_MCP_ENABLED=false` until production read access is explicitly approved.
Staging writes require `POKER_MCP_ALLOW_WRITES=true` as well as a credential
with write scope. Production configuration rejects that write flag.

The Cloudflare Worker proxies the exact `/mcp` path as well as `/api/*` and
preserves the caller's bearer header. If the MCP public URL is the Worker URL,
the existing `API_PROXY_SECRET`/`POKER_PROXY_SHARED_SECRET` pair also signs the
forwarded public host. If Codex connects to the public backend origin directly,
set `POKER_MCP_PUBLIC_URL` to that exact origin instead.

Create a separate high-entropy `MCP_ADMIN_TOKEN` in the staging GitHub
deployment environment and in any other environment before enabling its MCP
endpoint. The Worker requires it on `/api/mcp/principals` and descendant routes,
compares it without forwarding it, and fails closed when the secret is missing.
Enter it only into the **Agent access** unlock field; the PWA keeps it in
memory until the dialog is closed, reloaded, or locked. Do not reuse an agent
credential or `API_PROXY_SECRET` for this purpose. The value must contain at
least 32 printable ASCII characters without spaces; deployment rejects weak,
malformed, or reused values.

## Runtime Error Monitoring

Error reporting is optional and disabled when its DSN is blank. To enable
backend reporting, configure these Coolify values:

- secret `POKER_SENTRY_DSN`, using a complete HTTPS Sentry DSN;
- `POKER_SENTRY_ENVIRONMENT=staging` or `production`, matching the application;
- `POKER_SENTRY_RELEASE`, managed by the backend deployment workflow;
- optional `POKER_SENTRY_ERROR_SAMPLE_RATE`, from zero through one (default one).

Set the public `VITE_SENTRY_DSN` variable in each GitHub environment to enable
browser reporting. The PWA workflow supplies the selected environment and
the deployed commit SHA as the release. A browser DSN is a public client key by
design; do not place a Sentry API/auth token in any `VITE_*` value.

Both adapters report unhandled exceptions only. Expected validation, provider
input, and other handled API errors are not incidents. Before transmission,
the adapters remove request bodies, headers, query strings, cookies, user
context, breadcrumbs, arbitrary extras, local variables, and free-form error
messages. Both adapters disable automatic release-health sessions and client
reports; browser session replay and performance tracing are also disabled.
Events retain the exception type and stack locations plus release/environment tags;
backend events also include the route template, HTTP method, and `X-Request-ID`
for correlation with the JSON container log when that ID is a canonical UUIDv4.
Other caller-supplied request IDs remain local to the response and access log.
Reporting initialization and delivery failures leave the adapter disabled and
never prevent startup or alter the application response.

After configuration, trigger a test exception only in a non-production test
deployment and confirm that the event contains no cards, screenshots, player
names, request payloads, provider output, authorization data, or query values.
Use Sentry project alerts for notification delivery; the GitHub uptime issue
remains the independent availability signal.

## Backup Schedule And Restore Drill

Mount a second persistent or bind-backed volume at `/app/backups` and set
`POKER_BACKUP_DIR=/app/backups`. The entrypoint creates that directory and
grants the non-root `poker` user access. Do not treat `/app/data/backups` or a
second volume on the same host as disaster recovery: copy completed archives
to independent object storage or another host.

Create a stable volume identity and set it as `POKER_DATA_VOLUME_ID` in
Coolify:

```bash
openssl rand -hex 32
```

After the backend is healthy, inspect `/app/data` in the running backend
container and confirm the expected jobs are present. Then enroll that exact
mounted volume once from the running container:

```bash
python -m app.backup_cli init-volume
```

The command atomically writes a versioned `.poker-hero-data-volume` marker bound
to the configured identity. Do not run it from an unverified one-off container.
Scheduled export requires an exact marker match before opening stores,
publishing an archive, or applying retention. A container with a missing or
wrong `/app/data` mount therefore fails closed instead of rotating known-good
backups with an empty archive. Re-running initialization with the same identity
is safe; a different identity is rejected. Export also rechecks the marker and
requires both initialized store directories under the snapshot lock, so partial
volume corruption cannot be silently recreated as an incomplete backup.

Publication and retention hold a destination-wide operating-system file lock.
Overlapping scheduled runs or retries therefore serialize their short publish
phase, and `--retain` cannot let two exporters delete each other's archives.
If the destination filesystem cannot provide the lock, export fails without
publishing or pruning. Successful publication fsyncs the archive and backup
directory; newly created destination entries are fsynced through their existing
parent, and retention fsyncs the directory again after removing old entries.

API mutations hold a shared data-volume lock for their complete request,
including background work. Browser and operational exports take the exclusive
side of that lock while building an archive, so they wait for active mutations
and prevent a partial restore or import from becoming a scheduled backup.

Startup also participates in that lock, on both sides, and the two behave
differently.

The backend takes the **shared** side while it constructs the rest of its
workspace. Only an exclusive holder blocks that, so **a boot that overlaps a
running export waits for the export to finish**, then proceeds. That wait is
expected and is not a fault: the export drains, and startup continues. It is
bounded by
`POKER_DATA_LOCK_STARTUP_TIMEOUT_SECONDS` (default 600), which is set well clear
of a normal archive build so that a legitimate export never fails a deploy; the
bound exists only so a genuinely stuck volume produces a message instead of a
container hanging forever with no log line.

The container entrypoint takes the **exclusive** side when its raw preflight scan
finds a screenshot job with the retired `recommended` status. Under the lock it
rechecks the candidates, deletes only matching valid job directories, and
fsyncs the job store before current application models open it. With no matching
record, it skips the lock entirely.

The backend also takes the **exclusive** side when the imported-hand store has a
write journal entry left behind by an interrupted write, or when the job store
contains a parser job left in `created`. Interrupted-job recovery has its own
short hold and re-reads job state after acquiring it, so a live parser that
finishes while startup waits cannot be overwritten by stale recovery state.
When there is nothing to clean or recover, these acquires are skipped, so a
normal boot never requests exclusivity. When one is needed it is bounded by
`POKER_DATA_LOCK_RECOVERY_TIMEOUT_SECONDS` (default 30), deliberately much
tighter: `flock` gives no preference to waiters, so an exclusive acquire can be
starved indefinitely by overlapping shared holders rather than merely delayed,
and no length of wait fixes that. Cleanup and recovery are never skipped to get
past their timeout, because retired state or an unrecovered half-applied write
must not be served around.

Either startup bound expiring makes the backend **fail to start** with a
`DataLockTimeoutError` naming the lock file and which side it wanted, because
startup happens before the server binds and a silent wait would leave a container
that never turns healthy.

Browser backup export uses a separate exclusive-acquire budget,
`POKER_DATA_LOCK_EXPORT_TIMEOUT_SECONDS` (default 30). If active shared
mutations keep the lock busy past that request deadline, the endpoint returns
`409 Conflict` with a retryable, client-safe message instead of pinning a worker
thread indefinitely. This setting is independent from all startup and
request-write budgets.

**Diagnosing a restart loop after a failed deploy.** If the backend exits at
startup with `DataLockTimeoutError`, another process is holding the data volume
lock; this is not data corruption and the volume needs no repair. The usual cause
is the scheduled CLI export below, which holds the exclusive side unbounded for
the whole archive build. Check whether an export is running, let it finish, and
redeploy - or raise the corresponding timeout above for a volume where exports
routinely run longer than the default window.

Schedule a daily Coolify task against the backend image or run this inside a
one-off backend container:

```bash
python -m app.backup_cli export /app/backups --retain 14
```

The command prints the absolute archive path on success. It waits for live API
mutations to finish and exits nonzero if persisted active parsing work or a
resumable benchmark import still prevents a consistent export. Configure the
scheduler to alert on a nonzero exit and retry later; do not delete the last
known-good off-host archive after a failed run. Retention
only removes older files created with Poker Hero's timestamped backup filename
pattern.

Validate every copied archive at its final storage destination:

```bash
python -m app.backup_cli verify /app/backups/<archive>.zip
```

At least monthly, run the isolated recovery drill:

```bash
python -m app.backup_cli drill /app/backups/<archive>.zip
```

The drill validates the complete manifest, limits, models, images, and
checksums; restores into a temporary directory; repeats the restore to prove
idempotency; and re-exports and compares the recovered data. It never writes to
`POKER_DATA_DIR`. A successful drill reports the restored job and benchmark
report counts. Preserve scheduler logs and the tested archive name as recovery
evidence.

For an actual recovery, deploy a fresh backend data volume with
`POKER_ADMIN_OCR_TEST_ENABLED=true` and a dedicated `POKER_ADMIN_OCR_TEST_TOKEN`
(backup restore is an administrator action), unlock **Administrator tools** in
the information dialog with that token, restore the tested archive, verify
queue/history/benchmark counts, and only then switch traffic. Disable the mode
again afterwards unless parser testing continues on that deployment. Never test
a recovery by restoring into the live data directory.

## PWA On Cloudflare Workers

The `PWA Deploy` workflow builds `apps/pwa` and deploys the Worker.
It uses the same promotion model as the backend: `main` deploys `staging`, a
`v*` tag deploys `production`, and manual dispatch selects either environment.

Required secret:

- `CLOUDFLARE_API_TOKEN`

Required repository variables:

- `CLOUDFLARE_ACCOUNT_ID`
- `APP_WORKERS_SUBDOMAIN`

Required variables in both `staging` and `production`:

- `APP_WORKER_NAME` (use distinct names such as `poker-staging` and `poker`)
- `BACKEND_URL`

Optional per-environment variables:

- `VITE_API_BASE_URL` (leave unset for same-origin production API calls)
- `VITE_SENTRY_DSN`

Optional per-environment Cloudflare Access smoke-test secrets:

- `CLOUDFLARE_ACCESS_CLIENT_ID`
- `CLOUDFLARE_ACCESS_CLIENT_SECRET`

Required per-environment Worker-to-backend secret:

- `API_PROXY_SECRET`, matching Coolify `POKER_PROXY_SHARED_SECRET`

Required for staging and before enabling MCP in another environment:

- `MCP_ADMIN_TOKEN`, a separate high-entropy operator credential

Required environment variable for staging and any other environment with hosted
MCP enabled:

- `MCP_SMOKE_URL`, the exact public HTTPS `/mcp` URL reported by that
  deployment

The workflow smoke-tests both the SPA and `/api/health`. It reads the deployed
MCP configuration and fails when hosted MCP is enabled without a matching
`MCP_SMOKE_URL`, including in production. A PWA success with
an API `502` means the Worker deployed but its configured backend origin is not
healthy or reachable. It also reads one bounded processing-queue page so a
mismatched proxy credential fails deployment validation. The workflow also
calls the matching backend queue URL without that credential and requires a
`401`, proving the Coolify setting is active rather than merely accepting an
unused Worker header. It also requires unauthenticated MCP principal management
to return `401` and verifies that the Worker routes `/mcp` to the backend rather
than Static Assets. When `MCP_SMOKE_URL` is configured, the deployment workflow
uses `MCP_ADMIN_TOKEN` to issue an ephemeral read-only principal, verifies MCP
initialization and `get_environment_status` against the expected environment,
honors one bounded server `Retry-After` delay for each authenticated probe call
that meets the principal's read limit, and revokes the principal during cleanup.
Principal creation and revocation use bounded connection and transfer timeouts.
The credential expires within one
hour if cleanup cannot reach the deployment. When the optional Cloudflare
Access service credentials are configured, the authenticated probe forwards
them only to the validated deployment, configuration, and MCP URLs, including
the ephemeral principal creation and revocation requests.

The build step also enforces the install contract before deployment: `/sw.js`
must contain a build-versioned cache with exactly the emitted hashed bundles,
the manifest must remain root-scoped and standalone, and every declared icon
must exist at its advertised size. After deploying a new environment or custom
hostname, verify the runtime headers and manifest from an authorized client:

```bash
curl --fail --head https://<pwa-origin>/sw.js
curl --fail https://<pwa-origin>/manifest.webmanifest | jq '{id, scope, start_url, display, icons}'
```

`/sw.js` must return `Cache-Control: no-cache, no-store, must-revalidate` and
`Service-Worker-Allowed: /`. A successful generated
`/assets/<name>-<hash>.<ext>` response must return
`Cache-Control: public, max-age=31536000, immutable`; HTML, the manifest, icons,
and missing asset responses—including an HTML SPA fallback—must revalidate. In
Chromium DevTools, confirm the worker scope is the complete origin, launch once
online, then disable the network and open another application route. The shell
and offline notice must render, while an upload and approval fail visibly
and can be retried after reconnecting.
Also simulate an unreachable PWA origin while retaining another working network
connection; the manifest reachability probe must show the same notice even when
the browser still reports that its link is online.
Cache Storage may contain only `/` and hashed `/assets/` requests—never `/api`,
`/mcp`, screenshots, poker records, or credentials.

Normal rollback redeploys the last known-good build; its worker still waits for
the safe update handoff. For an emergency client reset, first preserve or
discard any visible drafts, then run the following in that origin's DevTools
console and reload online:

```js
await Promise.all(
  (await navigator.serviceWorker.getRegistrations()).map((registration) =>
    registration.unregister(),
  ),
);
await Promise.all(
  (await caches.keys())
    .filter((name) => name.startsWith("poker-hero-shell-"))
    .map((name) => caches.delete(name)),
);
location.reload();
```

Do not delete other origin caches or browser recovery projections. The next
successful production load registers the currently deployed worker again.

## Uptime Monitoring And Alerts

The `Uptime Monitor` workflow runs hourly at minute 17 and can also be dispatched
manually. By default it checks
`https://<APP_WORKER_NAME>.<APP_WORKERS_SUBDOMAIN>.workers.dev`; set the optional
per-environment variable `UPTIME_MONITOR_URL` to monitor a custom HTTPS hostname
instead. Scheduled runs monitor `staging`; manual dispatch can select `staging`
or `production`. Dispatches use the same admin-controlled target so Cloudflare
Access credentials cannot be redirected to an arbitrary host.

The hourly interval keeps the private staging monitor within a practical GitHub
Actions budget alongside ordinary CI. Use manual dispatch for an immediate
post-maintenance check.

The probe validates all three deployment boundaries with bounded one-MiB
responses, a 20-second attempt timeout, and three attempts:

- the SPA returns the stable `application-name` metadata marker for Poker Hero;
- same-origin `/api/health` returns JSON with `status: "ok"`;
- same-origin `/api/jobs?limit=1` returns a queue-shaped response, proving the
  Worker proxy and its backend credential are operational.

If Cloudflare Access protects the hostname, configure both
`CLOUDFLARE_ACCESS_CLIENT_ID` and `CLOUDFLARE_ACCESS_CLIENT_SECRET` as
per-environment secrets. The probe follows at most five same-origin
redirects and never forwards those service-token headers to another origin.

After all attempts fail, the workflow opens one issue titled
`[uptime] Poker Hero <environment> is unavailable` with the sanitized failure
and run link. Later failed runs reuse the environment-specific incident instead
of posting repeated comments. The first successful run closes every matching
open incident with a recovery link. Set optional `UPTIME_ISSUE_ASSIGNEE` in an
environment to a valid GitHub login for direct assignment notifications, and
ensure that user has repository issue notifications enabled. Workflow failures
remain visible in Actions even when no assignee is configured.

Validate the probe locally without contacting the deployment:

```bash
pnpm monitor:test
```

## Local Container Validation

```bash
docker compose -f infra/docker/docker-compose.yml config
docker build -f apps/backend/Dockerfile -t poker-hero-backend:test .
docker build -f apps/pwa/Dockerfile -t poker-hero-pwa:test .
```
