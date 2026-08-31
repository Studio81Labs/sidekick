# Poker Hero

Post-hand Texas Hold'em training analyzer for screenshots from online poker
tables. Poker Hero extracts table state and requires an administrator to
verify uncertain fields and approve the reviewed state as ground truth.
Recommendations are produced only by the offline recommendation benchmark
until the V2 import-first learning loop ships.

The project is for study and post-hand review. It is not live-play automation,
covert real-time assistance, or a tool for taking actions in a poker client.

## Quick Start

Prerequisites: Node 24, pnpm 11+, Python 3.11+, Rust 1.85+, and Docker.

```bash
git clone <repo-url> && cd poker-hero
pnpm bootstrap
```

Then start the two apps in separate terminals:

```bash
pnpm backend:dev
pnpm pwa:dev
```

Open `http://localhost:5173`. The API runs at `http://localhost:8000`.

## Project Structure

```text
poker-hero/
├── apps/
│   ├── backend/             FastAPI API, OCR parsers, solvers, storage, tests
│   └── pwa/                 React/Vite product app and Cloudflare Worker proxy
├── packages/
│   ├── openapi/             Deterministic backend OpenAPI document and tooling
│   └── openapi-client/      Generated TypeScript wire contracts for the PWA
├── infra/
│   └── docker/              Local Compose and deployment env example
├── solver-plugins/
│   └── postflop/            Rust heads-up postflop solver adapter
├── docs/
│   ├── specs/               Canonical product specification and archive
│   ├── reference/           Architecture reference
│   └── process/             Deployment and operational procedures
├── scripts/                 Development automation
└── .github/workflows/       App-scoped CI and deployment pipelines
```

## Commands

| Command                                                | Description                                                      |
| ------------------------------------------------------ | ---------------------------------------------------------------- |
| `pnpm bootstrap`                                       | Install dependencies and build the local postflop solver         |
| `pnpm backend:dev`                                     | Start FastAPI with reload on port 8000                           |
| `pnpm backend:mcp`                                     | Start the environment-fixed local MCP gateway over stdio         |
| `pnpm backend:benchmark <dataset.zip>`                 | Benchmark a parser against an exported labeled dataset           |
| `pnpm backend:recommendation-benchmark <dataset.json>` | Benchmark a recommendation provider against trusted references   |
| `pnpm backend:backup <command>`                        | Initialize, export, verify, or restore-drill application backups |
| `pnpm backend:test`                                    | Run the backend pytest suite                                     |
| `pnpm api:generate`                                    | Regenerate the committed OpenAPI document and TypeScript client  |
| `pnpm api:check`                                       | Verify that committed OpenAPI artifacts are tracked and current  |
| `pnpm pwa:dev`                                         | Start Vite on port 5173                                          |
| `pnpm pwa:test`                                        | Run PWA tests                                                    |
| `pnpm pwa:build`                                       | Build the production PWA                                         |
| `pnpm pwa:performance`                                 | Build and enforce production bundle budgets                      |
| `pnpm monitor:test`                                    | Test the deployment uptime probe                                 |
| `pnpm test:e2e`                                        | Run browser workflow tests with isolated test providers          |
| `pnpm docker:up`                                       | Build and start both apps with Docker Compose                    |
| `pnpm docker:down`                                     | Stop the Compose stack                                           |

The browser workflow command starts temporary FastAPI, HTTP provider stub, and
Vite servers on ports 8010, 8011, and 4174. Install Chromium once with
`pnpm -C apps/pwa exec playwright install chromium` before the first local
run. Its backend job store is removed when the test server exits.

## Configuration

Backend settings use the `POKER_` prefix. `pnpm bootstrap` copies
`apps/backend/.env.example` to `apps/backend/.env` when needed.

The main provider switches are:

- `POKER_PARSER_PROVIDER`: `mock`, `llm_vision`, `ocr_cv`, or `auto`. Automatic
  recognition uses local OCR for explicit calibrated client layouts and
  external vision for `generic`, other layouts, or local OCR rejection; it
  requires `POKER_EXTERNAL_PARSER_URL`
- `POKER_PARSER_LAYOUT_PROFILE`: the default layout ID. Fixed-region `ocr_cv`
  supports `generic`, `fortuna`, `nations`, and `fortuna_nations`; external
  vision may use deployment-defined IDs such as `pokerstars`
- `POKER_PARSER_ENABLED_PROVIDERS` and
  `POKER_PARSER_ENABLED_LAYOUT_PROFILES`: JSON lists of additional installed
  parsers and layout IDs an administrator may select for each OCR test
  upload or live capture; the deployment defaults are always enabled and the UI
  shows only compatible parser/layout combinations
- `POKER_RECOMMENDATION_PROVIDER`: `rule_based`, `mock`, `local_solver`, `external_solver`, or `llm_advice`
- `POKER_LOCAL_SOLVER_ENGINE`: `postflop_solver` (default) or `local_ev`
- `POKER_POSTFLOP_SOLVER_RANGE_MODE`: derive ranges from a complete supported
  heads-up preflop history with `contextual` (default), or always use the
  configured OOP/IP ranges with `configured`
- `POKER_EXTERNAL_PARSER_BEARER_TOKEN`: optional bearer token for `llm_vision`
- `POKER_EXTERNAL_PROVIDER_BEARER_TOKEN`: optional bearer token for `external_solver`
- `POKER_LLM_ADVICE_BEARER_TOKEN`: optional bearer token for `llm_advice`
- `POKER_EXTERNAL_REQUEST_TIMEOUT_SECONDS`: timeout shared by external parser
  and recommendation requests (default 60 seconds)
- `POKER_DEPLOYMENT_ENVIRONMENT`: `local`, `staging`, or `production`; MCP
  gateways verify this identity before accessing jobs

For example, a private deployment can route Fortuna/Nations through local OCR
and PokerStars through external vision behind one automatic recognition option:

```dotenv
POKER_PARSER_PROVIDER=auto
POKER_PARSER_LAYOUT_PROFILE=fortuna_nations
POKER_PARSER_ENABLED_LAYOUT_PROFILES=["pokerstars"]
POKER_EXTERNAL_PARSER_URL=https://vision.example.com/parse
```

The automatic parser routes `pokerstars` directly to external vision. The local
`ocr_cv` option remains unavailable for that layout until a labeled corpus and
calibrated coordinates/templates are added.

- `POKER_DATA_DIR`: file-backed jobs and uploaded screenshots
- `POKER_DATA_VOLUME_ID`: stable deployment identity required only by the
  operational backup CLI
- `POKER_MAX_DATASET_UPLOAD_BYTES`: maximum parser dataset ZIP size for
  benchmark selection, export, and import (default 100 MiB)
- `POKER_MAX_BACKUP_UPLOAD_BYTES`: maximum full application backup ZIP size for
  export and restore (default 100 MiB)
- `POKER_DATA_LOCK_EXPORT_TIMEOUT_SECONDS`: maximum wait for browser backup
  export to acquire its exclusive snapshot lock (default 30 seconds)
- `POKER_API_RATE_LIMIT_ENABLED`: enable bounded per-client limits for uploads,
  benchmark runs, and archive transfers (default `true`)
- `POKER_API_RATE_LIMIT_*_PER_MINUTE`: tune each expensive-operation budget;
  the default is `120` for uploads and `6` for benchmarks/data transfers
- `POKER_CORS_ORIGINS`: JSON list of direct browser origins
- `POKER_PROXY_SHARED_SECRET`: optional Worker-to-backend credential, at least
  32 characters; leave empty for local development
- `POKER_ADMIN_OCR_TEST_ENABLED` and `POKER_ADMIN_OCR_TEST_TOKEN`: administrative
  OCR test mode for screenshot upload and live capture (ADR 0046). Disabled by
  default; when enabled every `POST /api/jobs` upload, every
  `POST /api/benchmarks/import` dataset import, and every
  `POST /api/backups/restore` must carry the token as
  `Authorization: Bearer ...`. Clients confirm a token with
  `GET /api/admin/ocr-test/session` before revealing capture controls. The
  token must contain at least 32
  printable ASCII characters and differ from `POKER_PROXY_SHARED_SECRET`
- `POKER_MCP_ENABLED` and `POKER_MCP_PUBLIC_URL`: hosted MCP kill switch and
  exact public HTTPS `/mcp` endpoint; hosted access defaults off
- `POKER_MCP_ALLOW_WRITES`: staging-only server write gate, independent of
  credential scope and Codex client approval
- `POKER_MCP_ALLOWED_ORIGINS` and `POKER_MCP_*_CALLS_PER_MINUTE`: exact browser
  origins and per-principal hosted read/write limits
- `POKER_SENTRY_DSN`: optional HTTPS Sentry DSN for scrubbed unhandled backend
  exception reports; leave empty to disable
- `POKER_SENTRY_ENVIRONMENT`, `POKER_SENTRY_RELEASE`, and
  `POKER_SENTRY_ERROR_SAMPLE_RATE`: optional error-report attribution and
  sampling controls

See [apps/backend/.env.example](./apps/backend/.env.example) for the complete
local contract and [infra/docker/backend.env.example](./infra/docker/backend.env.example)
for container-oriented values.

Bearer tokens are masked by the settings model and sent only in the standard
`Authorization: Bearer ...` header. Any external URL paired with a token must
use HTTPS. Keep deployed token values in Coolify secrets.

### Agent MCP Gateway

Poker Hero includes a curated MCP gateway for post-hand training agents. It can
run locally over stdio or be hosted by the deployed backend over authenticated
Streamable HTTP. It calls the same FastAPI contract as the browser, so parser
evidence, explicit approval, provider routing, rate limits, request IDs, and
persisted job state remain authoritative. It never reads providers or poker
stores directly.

Create a separate client configuration for each environment using
[apps/backend/mcp.env.example](./apps/backend/mcp.env.example). Every process
requires `POKER_MCP_ENVIRONMENT` and `POKER_MCP_API_BASE_URL`. Before any data
operation, it checks `/api/health` and refuses a backend whose
`POKER_DEPLOYMENT_ENVIRONMENT` does not match. Production is always read-only.
Staging write tools appear only with `POKER_MCP_ALLOW_WRITES=true`.

After exporting the selected configuration into the MCP process environment,
use this command in an MCP client that supports local stdio servers:

```bash
pnpm backend:mcp
```

The read surface covers environment status, the processing queue, individual
jobs, history search, and parser benchmark summaries. The staging write
profile adds only ground-truth approval for a reviewed state. Backup restore,
dataset import, benchmark execution, and bulk archival are intentionally not
exposed.

Cloudflare Access service credentials are the preferred authentication path
through a protected Worker. `POKER_MCP_API_PROXY_SECRET` exists only for a
trusted gateway deployment that calls the backend directly; do not give the
Worker-to-backend shared secret to an untrusted agent.

For the Nexcue-style hosted workflow, enable the staging route with
`POKER_MCP_ENABLED=true` and an exact HTTPS `POKER_MCP_PUBLIC_URL` ending in
`/mcp`. Configure the deployment's separate `MCP_ADMIN_TOKEN`, unlock
**About → Agent access** with it, create an environment-bound credential, store
the one-time token in an environment variable, and configure Codex:

```toml
[mcp_servers.poker_staging]
url = "https://<staging-agent-origin>/mcp"
bearer_token_env_var = "POKER_MCP_STAGING_TOKEN"
default_tools_approval_mode = "writes"
```

Hosted credentials are stored only as hashes and can be rotated or revoked.
The gateway does not upload screenshots; upload the hand in the app first,
then let the agent inspect or approve the resulting job. See
[`docs/reference/mcp-agent-access.md`](./docs/reference/mcp-agent-access.md)
for rollout and incident steps.

### Local Solver Engines

With `POKER_RECOMMENDATION_PROVIDER=local_solver`, the default
`postflop_solver` engine runs the pinned Rust Discounted CFR adapter. It accepts
heads-up flop, turn, and river states when `hero_position` identifies `IP`,
`OOP`, or button, or when reviewed hero and opponent seats establish an
unambiguous postflop order. A small-blind versus big-blind pair still requires
explicit IP/OOP review unless an exact called big-blind isolation, called
limp-reraise, squeeze, or cold 4-bet history resolves it. The called-isolation
and limp-reraise routes use the six-max chart contract when reviewed seats are
canonical blinds. On the limp-reraise route, a reviewed dealer/button alias
instead identifies the heads-up small blind and preserves its postflop IP
order. The other routes prove a multi-seat preflop line. Its ranges, bet tree,
iteration target, rake,
timeout, and memory ceiling are configurable through the
`POKER_POSTFLOP_SOLVER_*` variables in the example env files.
In the default `contextual` range mode, an exact two-player state with a
single 1 BB limp checked by the big blind, the same limp followed by a 2-5 BB
big-blind isolation raise and matching call by the original limper, a 1 BB
limp followed by a 2-5 BB isolation raise, original-limper reraise, and
isolator call, an open-and-call, ordinary open/3-bet/call, cold-caller
open/3-bet/call, open/call/squeeze/call, or
open/3-bet/4-bet/call preflop history, including a later cold 4-bettor after the
opener folds, selects transparent ranges from the same position-aware chart
boundaries used by the preflop trainer. The limped route
uses the limper's stack-adjusted first-in range as an explicit proxy and the
complement of the big blind's isolation-raise band as the checked range.
The called-isolation route uses that big-blind isolation band as the raiser's
range and the limper's adjusted continue band after excluding limp-reraises as
the calling range. Concrete reviewed seats or a consistent opposing OOP/IP
pair identify which represented actor owns each range. Non-big-blind isolation
raises retain configured ranges because the bundled chart does not define
their initial isolation band.
The called limp-reraise route uses the limper's adjusted reraise band and the
isolator's ratio- and stack-adjusted continue band after excluding 4-bets.
Unlike the called-isolation route, it supports every legal limper/isolator pair
because the chart defines both sides of those matchups.
Dead-money routes require the original opener to be absent
from the two reviewed survivors and keep that player's opening contribution in
the reconstructed root pot. The squeeze route applies the chart's existing
single-caller adjustment to the squeezer and its named squeeze-response policy
to the caller. The cold 4-bet route uses the cold player's adjusted 4-bet band
and the original 3-bettor's continue band after excluding 5-bets. The reviewed
sizes and a provable starting effective stack apply the remaining chart
response adjustments, and the backend verifies that the reconstructed
flop-root pot agrees with every represented commitment. A turn
additionally requires one terminal completed-flop history; a river requires
terminal completed-flop and completed-turn histories in order. Each completed
history ends in check-check or a matching call and records each wager as the
actor's total BB committed on that street.
When current-street money cannot be reconciled to the reviewed visible stacks,
the range context retains a labeled 100 BB stack assumption. Unsupported,
incomplete, contradictory, and other preflop trees retain the configured OOP/IP
ranges. Recommendation evidence records the selected source, policy context,
decision street, and completed-street verification. When terminal prior-street
histories and both visible stacks reconstruct the flop root, the adapter first
solves a memory-bounded flop-root tree, replays the reviewed actions and actual
turn/river cards, and uses the resulting posterior hand weights in the normal
current-street solve. The conditioning tree preserves observed prior-street
wagers, allows one configured bet size downstream, and omits unobserved raises;
the decision tree retains the configured bet and raise sizes. Evidence reports
whether conditioning was applied, its simplified tree profile, line reach,
active combinations, memory, and exploitability. Set the mode to `configured`
to disable contextual preflop selection; reviewed prior-street conditioning can
still refine those configured ranges.
Facing-bet trees also require the visible hero stack so the adapter can
reconstruct whether hero or the bettor was covered before the wager. The
facing action must identify the outstanding wager. Raised heads-up decisions
also require the opponent's visible stack and ordered current-street action
history. Each history wager is the player's total BB committed on that street;
the adapter validates the actors, pot, call amount, stacks, and final hero turn
before replaying the line. Incomplete or contradictory histories use fallback.
Completed-street history is separate from the replayed current-street list. It
both verifies later-street range and stack assumptions and, when the exact root
can be reconstructed within the memory limit, conditions each player's range
through the reviewed prior-street line.

`pnpm bootstrap` builds the adapter into
`solver-plugins/postflop/target/release/poker-postflop-solver`; the local backend
commands add that directory to `PATH`. Re-run bootstrap after pulling changes
to the Rust plugin.

Preflop hands with a recognized six-max position and an unambiguous supported
context use the bundled position-aware training chart. Supported contexts
include an unopened pot, one to five 1 BB limps to the big blind, a single open,
one open followed by one to four callers, a hero 1 BB limp facing one
later-position isolation raise after action returns heads-up,
a single opponent limp followed by hero's isolation raise and a reraise by the
original limper after action returns heads-up,
a hero open facing a 3-bet, a bounded opponent-open/opponent-3-bet sequence, and
a hero 3-bet facing either an opener 4-bet or a later cold 4-bet after the
opener folds. It also supports hero cold-calling an open, facing a later
squeeze, and acting heads-up after the opener folds. The chart uses
position-matchup boundaries plus
transparent adjustments for 2-4 BB opening sizes, supported 3-bet ratios, and
short, medium, standard, or deep effective stacks.
First-in ranges and sizing also adjust by stack depth. The chart reports its
hand-class ranking, base and adjusted policy, assumptions, and action frequencies
without presenting the result as a solved preflop tree. Approved states may
provide the opener position and total opening size as structured fields. An
ordered preflop history can represent a single open, one open followed by one
to four calls before hero, one to five ordered 1 BB limps before hero's
big-blind option, exactly
one hero open followed by one later-position 3-bet, or one opponent open followed
by one opponent 3-bet before hero. A complete
three-raise history can also represent an opponent open, hero 3-bet, and opener
4-bet with action returning to hero, or a later-position cold 4-bet after the
opener folds and action returns heads-up to hero. An open, matching hero call,
and later squeeze can represent the same heads-up return after the opener folds.
A hero 1 BB call followed by one later-position 2-5 BB raise can represent a
heads-up isolation response after every other player folds. This route requires
known hero and effective stacks, validates the call amount and reconstructed
pot, and exposes its position, size-band, stack, response-range, and raise-cap
adjustments as evidence.
One opponent 1 BB call, a 2-5 BB hero isolation raise, and a bounded reraise by
that same limper can represent the corresponding heads-up limp-reraise response.
This route requires the limper to act before hero, validates a full reraise up
to 4x the isolation total, and applies dedicated limper-versus-isolator,
size-band, and stack-depth continue/four-bet boundaries. Its evidence retains
the original limper, hero isolation total, limp-reraise total and ratio, named
policy, adjusted range, and reconstructed all-in cap.
The called-open routes require exactly three through six active players,
matching open/call totals, and legal seat order. They apply explicit conservative
range multipliers and 4x-open through 7x-open squeeze targets for one through
four callers, respectively. The cold 3-bet route also requires exactly three
active players and legal opener-3-bettor-hero order, then applies explicit
three-seat continue/four-bet boundaries. The chart validates position order,
total action sizes, amount to call, pot composition, and stack availability
before routing. The heads-up 4-bet route applies explicit matchup and size-band
continue/five-bet boundaries, with five-bets modeled as capped all-ins. The
cold 4-bet route uses narrower three-seat policies and keeps the folded
opener's commitment in pot validation. The squeeze-response route likewise
uses explicit three-seat policies, retains hero's prior call, and validates the
folded opener's dead money.
The heads-up limp route requires exactly one active limper and hero in the big
blind, validates the pot against blinds and the limp, then uses explicit
limper-position and stack-depth isolation ranges with a capped target size. The
multi-limper routes similarly require exactly one more active player than the
two through five distinct ordered 1 BB calls, plus hero's big-blind option. They
use explicit policies for every legal limper pair, triple, four-seat group, or
full-table sequence, progressively tighter stack-adjusted isolation ranges,
1.5x-pot targets of at least 5 BB through 8 BB, and the same effective-total cap.
Action-text parsing remains for older saved single-open hands.
Positionless and unsupported limped spots, including mismatched active-player
counts, action pending behind hero, or an isolation raise with another active
player, caller histories beyond the terminal six-max ordering, unsupported
squeezes with an active opener, another caller, or action behind, cold 4-bets
with action behind or another active player, unsupported limp-reraises, longer
preflop trees, multiway postflop states, and
incomplete, ambiguous-position, oversized, or failed trees use `local_ev` when
fallback is enabled. Recommendations preserve
the requested engine and routing or fallback reason in `raw` metadata. Set
`POKER_LOCAL_SOLVER_ENGINE=local_ev` to bypass both CFR and the preflop chart
and run the range/EV engine directly. Select `external_solver` at the provider
boundary for a future licensed service.

Clearing completed processing items persists an archive timestamp on each
backend job. The history rail restores the latest archived hands once per
browser session, keeps a small local cache for immediate rendering and fallback,
can load older archived hands in bounded pages, and can be refreshed explicitly
after another device archives work. Saving changes to a reopened archived hand
updates its history card and bounded browser cache immediately. Server-backed
search can find older hands by filename, cards, table context, screenshot
title, notes, or tags without replacing that newest-page cache. Every queue
and history item exposes screenshot details where those metadata fields can
be edited. The same dialog can permanently remove the job, original image,
analysis, and benchmark-corpus membership, so an incomplete parse never has
to remain stuck in processing.
Unarchived upload and capture jobs also survive reloads: the browser renders a
bounded local queue cache immediately, then reconciles the complete oldest-first
processing projection from the backend. Dataset-only benchmark imports stay out
of that operational queue. Bounded browser-session mutation leases keep
uncertain writes, uploads, and batch archives unsynchronized across a same-tab
reload until the backend projection proves the operation completed or the
recovery window expires. Benchmark dataset imports additionally carry a
client-generated request ID. Before parsing or changing the corpus, the backend
atomically publishes a pending journal containing the size-bounded archive.
Validation failures and completed results are persisted in that journal, while
interrupted or partial imports can resume idempotently from the same archive. A
dropped response or same-tab reload can therefore recover newly created
benchmark-only cases that intentionally appear in neither operational
projection.

The app information dialog can export a versioned full-data backup containing
every job record, original screenshot, screenshot title, notes and tags,
history timestamp, benchmark selection, and benchmark report. Restore
validates the complete ZIP, member paths, Pydantic records, image payloads,
limits, and SHA-256 checksums before writing. Missing records
are merged, exact records are reused, and a divergent existing job, image, or
report rejects the restore without overwriting current data. Provider
credentials, environment configuration, and transient import journals are
intentionally excluded.

Operators can create and validate the same archive format without the browser:

```bash
pnpm backend:backup init-volume
pnpm backend:backup export ./backups --retain 14
pnpm backend:backup verify ./backups/<archive>.zip
pnpm backend:backup drill ./backups/<archive>.zip
```

The drill restores only into temporary isolated storage, verifies a repeated
restore is idempotent, and compares a re-export with the source. Operational
exports coordinate with live API mutations through a shared data-volume lock,
then durably publish and rotate archives under a destination lock. See
[the deployment runbook](./docs/process/deployment.md#backup-schedule-and-restore-drill)
for Coolify mounts, scheduling, off-host copies, and recovery procedure.

### Offline Parser Benchmarks

Export approved ground-truth hands from the Parser benchmark dialog, then run
the same field-level evaluation without importing them into the configured data
directory:

```bash
pnpm backend:benchmark ./poker-hero-parser-dataset.zip \
  --parser-provider ocr_cv \
  --layout-profile fortuna_nations \
  --minimum-cases 25 \
  --minimum-accuracy 0.90 \
  --minimum-field-cases hero_cards=25 \
  --minimum-field-accuracy hero_cards=0.98 \
  --minimum-field-accuracy board_cards=0.98 \
  --minimum-field-accuracy pot_size=0.90 \
  --minimum-field-accuracy current_bet=0.90
```

The command prints overall and per-field accuracy plus cases needing review. Add
`--json` for a complete machine-readable report. It exits with status `1` when
any case fails or a configured corpus, label-count, overall-accuracy, or
field-accuracy threshold is missed. Repeat `--minimum-field-cases` and
`--minimum-field-accuracy` for cards, street, pot, bets, stacks, player count,
and position. Keep a separately labeled dataset and threshold command for each
client/layout so a strong result on one table cannot hide a regression on
another. Evaluation uses temporary storage and never changes the configured
`POKER_DATA_DIR` or the source ZIP.

Capture a trusted full report and use it to gate later runs from the same
parser, layout, and labeled corpus:

```bash
pnpm backend:benchmark ./poker-hero-parser-dataset.zip \
  --parser-provider ocr_cv \
  --layout-profile fortuna_nations \
  --json > ./fortuna-ocr-baseline.json

pnpm backend:benchmark ./poker-hero-parser-dataset.zip \
  --parser-provider ocr_cv \
  --layout-profile fortuna_nations \
  --baseline-report ./fortuna-ocr-baseline.json \
  --maximum-accuracy-drop 0.01 \
  --maximum-field-accuracy-drop hero_cards=0 \
  --maximum-field-accuracy-drop board_cards=0 \
  --maximum-field-accuracy-drop pot_size=0.02
```

Drop values are accuracy ratios, so `0.01` permits one percentage point. The
human report prints overall and per-field changes; `--json` keeps stdout as the
current full report while regression failures remain on stderr. A baseline with
a different parser, layout, or corpus fingerprint is rejected. The fingerprint
includes selected hand IDs, approved labels, and screenshot contents. After
changing selected hands, screenshots, or approved labels, review the new corpus
and deliberately capture a replacement baseline.

When multiple compatible parser plugins are enabled, the in-app benchmark
dialog compares each plugin's latest saved run for the selected layout. Reports
are fingerprinted against their labeled corpus; changed labels, selected hands,
and legacy reports without a fingerprint are marked for rerun rather than shown
as current. A
comparison row switches both the active recognition plugin and the scoped
report history without loading full case details for the other plugins. Run
comparison benchmarks every available compatible parser in sequence; a provider
failure is reported without discarding successful runs from the same comparison.

### Offline Recommendation Benchmarks

Run the configured recommendation provider against a versioned JSON corpus of
canonical hands and trusted reference policies:

```bash
pnpm backend:recommendation-benchmark ./recommendation-benchmark.json \
  --provider local_solver \
  --minimum-action-accuracy 0.90 \
  --minimum-conditioning-accuracy 1.00 \
  --minimum-conditioning-coverage 1.00 \
  --minimum-range-source-accuracy 1.00 \
  --minimum-range-source-coverage 1.00 \
  --maximum-ev-loss 0.05
```

The report measures supported-action and exact sizing-line agreement, mixed
policy distance, reference EV loss, provider failures, and recorded fallback
use. Version-3 corpora can require turn/river range-conditioning evidence;
version-4 postflop cases can additionally require the exact configured or
contextual range source. Both report separate agreement and evidence coverage.
Optional thresholds make the command suitable for local regression gates and
CI; `--json` emits the complete case report. It reads no screenshots and does
not change application data. Reference
policy frequencies and EVs must come from a trusted solver or reviewed strategy
source rather than the provider being evaluated. See
[the recommendation benchmark format](./docs/reference/recommendation-benchmark.md).

Capture a trusted report and gate direction-aware metric changes against the
same provider and normalized reference corpus:

```bash
pnpm backend:recommendation-benchmark ./recommendation-benchmark.json \
  --provider local_solver \
  --json > ./local-solver-baseline.json

pnpm backend:recommendation-benchmark ./recommendation-benchmark.json \
  --provider local_solver \
  --baseline-report ./local-solver-baseline.json \
  --maximum-metric-regression action_accuracy=0.01 \
  --maximum-metric-regression average_policy_distance=0.02 \
  --maximum-metric-regression average_ev_loss=0.05 \
  --maximum-metric-regression fallback_rate=0 \
  --maximum-street-metric-regression river:average_ev_loss=0.02 \
  --maximum-tag-metric-regression facing-bet:action_accuracy=0.01 \
  --maximum-case-metric-regression action_accuracy=0
```

Street and tag gates use the same direction-aware metric keys and catch scoped
regressions that aggregate results can hide. Case gates apply a metric threshold
to each trusted hand independently and fail when previously available evidence
disappears. Ratio deltas use `0.01` for one percentage point; EV-loss deltas are
BB. JSON stdout remains a reusable current report, while gate failures use
stderr.

## Docker

Run the full local stack:

```bash
pnpm docker:up
```

The PWA is available at `http://localhost:8080`, the backend at
`http://localhost:8000`, and job data is kept in the `poker-data` volume.
The backend image compiles and includes the pinned Rust postflop solver plugin.

Build either image directly from the repository root:

```bash
docker build -f apps/backend/Dockerfile -t poker-hero-backend .
docker build -f apps/pwa/Dockerfile -t poker-hero-pwa .
```

## Deployment

Each `staging` and `production` deployment uses two services:

- `apps/pwa` deploys to Cloudflare Workers Static Assets. Its Worker
  proxies same-origin `/api/*` requests to the configured backend.
- `apps/backend` deploys as a Docker service in Coolify with persistent storage
  mounted at `/app/data`.

For each Coolify application, use repository-root build context and Dockerfile
path `apps/backend/Dockerfile`. Expose port `8000` and mount a separate
persistent volume at `/app/data`. Pushes to `main` deploy staging, `v*` tags
deploy production, and manual workflows can select either environment.

The deployment workflows require repository secrets `CLOUDFLARE_API_TOKEN` and
`COOLIFY_API_TOKEN`, plus these repository variables:

- `CLOUDFLARE_ACCOUNT_ID`
- `APP_WORKERS_SUBDOMAIN`, for example `studio81`
- `COOLIFY_API_BASE_URL`

Each `staging` and `production` GitHub environment requires:

- `BACKEND_URL`, the environment's backend origin used by the Worker proxy
- `COOLIFY_BACKEND_UUID`, the environment's Coolify application
- `APP_WORKER_NAME`, distinct between environments
- `API_PROXY_SECRET`, matching that backend's `POKER_PROXY_SHARED_SECRET`

Staging, and any other environment before enabling hosted MCP, also requires
`MCP_ADMIN_TOKEN`, the separate operator bearer for principal management.

For a deployed backend, set the same random value in the Cloudflare
`API_PROXY_SECRET` secret and Coolify `POKER_PROXY_SHARED_SECRET` environment
variable, and use an `https://` `BACKEND_URL`. The Worker replaces any incoming
copy of its private header before proxying. FastAPI then rejects direct requests
to application API routes that do not carry the configured value; `/api/health`
remains available to platform health probes.

Backend responses carry `X-Request-ID`, which is also written to structured
container access logs for tracing requests through the Worker and Coolify.

Runtime error monitoring is disabled by default. Set `POKER_SENTRY_DSN` in
Coolify for backend failures and the public `VITE_SENTRY_DSN` environment
variable for browser failures. The PWA deployment
uses its commit SHA as the release. Both adapters remove poker state, request
bodies and metadata, user context, breadcrumbs, local variables, and free-form
exception text before sending an event. Browser tracing and replay are off.
Errors retain stack locations, exception type, environment/release, component,
and backend request correlation tags.

The `Uptime Monitor` workflow checks the deployed SPA, proxied health route,
and protected queue route every hour. Scheduled runs derive the staging URL from
`APP_WORKER_NAME` and `APP_WORKERS_SUBDOMAIN`, or use the optional
`UPTIME_MONITOR_URL` environment variable. Manual runs can select staging or
production. A failed probe opens one environment-specific GitHub outage issue;
the next successful probe closes it. Set optional `UPTIME_ISSUE_ASSIGNEE` in
each environment to a GitHub login that should receive the incident assignment.

Leave `VITE_API_BASE_URL` unset for the deployed Worker so browser requests use
same-origin `/api/*`.

See [docs/process/deployment.md](./docs/process/deployment.md) for the complete
deployment checklist and [docs/reference/architecture.md](./docs/reference/architecture.md)
for the runtime topology.

## API

- `GET /api/health`
- `POST /api/jobs`
- `GET /api/jobs/{job_id}`
- `PUT /api/jobs/{job_id}/metadata`
- `DELETE /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/image`
- `GET /api/history`
- `PUT /api/history`
- `POST /api/jobs/{job_id}/approve`
- `PUT /api/jobs/{job_id}/benchmark`
- `GET /api/benchmarks[?parser_provider=...&parser_layout_profile=...]`
- `GET /api/backups/export`
- `POST /api/backups/restore`
- `GET /api/benchmarks/export`
- `POST /api/benchmarks/import`
- `GET /api/benchmarks/{report_id}`
- `POST /api/benchmarks/run`

## Documentation

- [Product specification](./docs/specs/poker-hero-product-spec.md)
- [Architecture](./docs/reference/architecture.md)
- [Deployment](./docs/process/deployment.md)
- [Contributing](./CONTRIBUTING.md)

## License

Private - all rights reserved, except `solver-plugins/postflop`, which links the
AGPL-3.0-or-later `postflop-solver` project and is distributed under that
license.
