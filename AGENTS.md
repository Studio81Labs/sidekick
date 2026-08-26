# Repository Agent Instructions

## Working Style

- Act as an autonomous senior engineer and complete requested work end to end.
- Make reasonable assumptions when requirements are clear enough to proceed.
- Keep changes focused and preserve user work outside the requested scope.
- Read the relevant code, tests, and product documentation before changing behavior.

## Sources Of Truth

- Read `docs/specs/poker-hero-product-spec.md` before product or behavior changes.
- Treat `docs/reference/architecture.md` as the current system and deployment map.
- Use `docs/specs/archive/` only for historical context.
- Update an ADR under `docs/decisions/` when an architectural decision needs a durable record.

## Project Overview

Poker Hero is a post-hand Texas Hold'em training analyzer. It extracts table
state from screenshots, asks the user to verify uncertain fields, and returns
an educational recommendation from a configurable provider.

- Backend: Python, FastAPI, Pydantic, file-backed job storage
- PWA: React, TypeScript, Vite, Cloudflare Worker Static Assets
- Recognition: configurable parser registry, currently OCR/CV focused
- Recommendations: configurable local, external, and rule-based providers
- Infra: pnpm workspace, Docker Compose, Coolify, GitHub Actions

## Monorepo Layout

```text
apps/backend/       FastAPI API, parsers, providers, storage, tests
apps/pwa/           React control panel and Cloudflare Worker
packages/openapi/   Deterministic backend OpenAPI document and tooling
packages/openapi-client/ Generated TypeScript contract consumed by the PWA
infra/docker/       Local Compose and backend deployment env example
docs/specs/         Canonical product spec and historical plans
docs/reference/     Architecture and system reference
docs/process/       Setup, deployment, and operational procedures
scripts/            Development automation
```

## Codebase Conventions

- Follow existing naming, typing, validation, and error-handling patterns.
- Keep parser output separate from canonical user-approved state.
- Keep recommendation providers behind the provider registry.
- Do not silently replace missing or low-confidence poker state with guesses.
- Python uses 4-space indentation; TypeScript, JSON, YAML, and Markdown use 2 spaces.
- Keep secrets in environment variables. Commit examples only.

## Product Guardrails

- The app is for training and post-hand review, not covert live-play assistance.
- User corrections always win over parser output and automation.
- Automation must process queue items independently; one failure must not discard
  successful items or stop unrelated queue work.
- Preserve parser confidences, warnings, approved state, and recommendation
  metadata so results remain reviewable.
- Recommendation output must be framed as educational guidance, not guaranteed
  optimal play.

## Commands

```bash
pnpm bootstrap
pnpm backend:dev
pnpm backend:test
pnpm pwa:dev
pnpm pwa:test
pnpm pwa:build
pnpm docker:up
pnpm docker:down
```

## Validation

- Run relevant backend and PWA tests for touched behavior.
- Run the PWA production build for PWA or Worker changes.
- Validate Docker/Compose configuration for deployment changes.
- Inspect the final diff for stale paths, debug code, and missing documentation.
- State clearly when a check could not be run.

## Pull Requests

- Use conventional commit titles: `<type>(<scope>): <description>`.
- Types: `feat`, `fix`, `chore`, `refactor`, `docs`, `test`, `style`.
- Preferred scopes: `backend`, `pwa`, `ci`, `infra`, `docs`.
- Keep PRs focused and include summary, risks, and test evidence.
- Merge only when required checks pass and review threads are resolved.
