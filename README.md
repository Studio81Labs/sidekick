# Poker Hero

Poker Hero is a post-hand Texas Hold'em training system. It preserves
administrator-reviewed OCR evidence separately from user-approved state and
keeps the hosted application outside the local player-data boundary.

The retired V1 screenshot recommendation runner, provider registry, heuristic
charts, and solver fallback are not part of this runtime. Native V2 grading
remains unavailable until the independent reference-source and certification
gates are satisfied. The product is not live-play assistance or poker-client
automation.

## Quick start

Prerequisites: Node 24, pnpm 11+, Python 3.11+, and Docker for container
workflows.

```bash
git clone <repo-url> && cd poker-hero
pnpm bootstrap
pnpm backend:dev
pnpm pwa:dev
```

The hosted PWA is available at `http://localhost:5173` and the API at
`http://localhost:8000`.

## Commands

| Command                                          | Description                                                      |
| ------------------------------------------------ | ---------------------------------------------------------------- |
| `pnpm bootstrap`                                 | Install workspace and backend dependencies                       |
| `pnpm backend:dev`                               | Start FastAPI with reload on port 8000                           |
| `pnpm backend:mcp`                               | Start the environment-status local MCP gateway over stdio        |
| `pnpm backend:benchmark <dataset.zip>`           | Benchmark a parser against an exported labeled dataset           |
| `pnpm backend:pokerstars-corpus <manifest.json>` | Assess PokerStars imports against private ground truth           |
| `pnpm backend:backup <command>`                  | Initialize, export, verify, or restore-drill application backups |
| `pnpm backend:test`                              | Run backend tests                                                |
| `pnpm api:generate`                              | Regenerate committed OpenAPI and TypeScript artifacts            |
| `pnpm pwa:test`                                  | Run PWA tests                                                    |
| `pnpm pwa:build`                                 | Build the hosted PWA                                             |
| `pnpm player:package`                            | Build a local player runtime bundle                              |
| `pnpm player:export-and-remove`                  | Export and remove a local player workspace                       |
| `pnpm docker:up`                                 | Build and start the local Docker stack                           |
| `pnpm docker:down`                               | Stop the local Docker stack                                      |

## Configuration

Backend settings use the `POKER_` prefix. `pnpm bootstrap` copies
`apps/backend/.env.example` to `apps/backend/.env` when needed.

- `POKER_PARSER_PROVIDER`: `mock`, `llm_vision`, `ocr_cv`, or `auto`.
- `POKER_PARSER_LAYOUT_PROFILE`: default layout identifier.
- `POKER_PARSER_ENABLED_PROVIDERS` and
  `POKER_PARSER_ENABLED_LAYOUT_PROFILES`: JSON lists of additional installed
  parser and layout choices for isolated administrator OCR tests.
- `POKER_EXTERNAL_PARSER_URL` and `POKER_EXTERNAL_PARSER_BEARER_TOKEN`:
  optional external-vision endpoint and credential. Authenticated endpoints
  must use HTTPS.
- `POKER_DATA_DIR`, `POKER_DATA_VOLUME_ID`, and backup/upload limit settings:
  file-backed administrative OCR state and operational backup controls.
- `POKER_ADMIN_OCR_TEST_ENABLED` and `POKER_ADMIN_OCR_TEST_TOKEN`:
  disabled-by-default administrator OCR test access. The token is distinct from
  the Worker proxy secret.
- `POKER_MCP_*`: exact hosted/local MCP policy and environment controls.
- `POKER_SENTRY_*`: optional scrubbed unhandled-error reporting.

See [the backend environment example](./apps/backend/.env.example) and
[the container environment example](./infra/docker/backend.env.example) for
the full settings contract. Current system, operational, and product details
live in [docs](./docs/README.md).

## Docker

```bash
pnpm docker:up
```

The PWA is available at `http://localhost:8080`, the backend at
`http://localhost:8000`, and local administrative OCR data is stored in the
`poker-data` volume.

## Repository layout

```text
apps/backend/       FastAPI, OCR parsers, player runtime, storage, and tests
apps/pwa/           React PWA, Worker, and local player app
packages/openapi/   Deterministic backend OpenAPI document and tooling
packages/openapi-client/
                    Generated TypeScript contract
infra/docker/       Local Compose and deployment environment example
docs/               Product specification, architecture, process, and ADRs
scripts/            Development and release automation
```
