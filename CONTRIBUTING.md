# Contributing To Poker Hero

For agent-specific guidance see [AGENTS.md](./AGENTS.md). The canonical product
requirements live in [docs/specs/poker-hero-product-spec.md](./docs/specs/poker-hero-product-spec.md).

## Getting Started

1. Install Node 24, pnpm 11+, Python 3.11+, Rust 1.85+, and Docker.
2. Run `pnpm bootstrap`.
3. Start the API with `pnpm backend:dev` and the UI with `pnpm frontend:dev`.

## Branches And Commits

- Branch from `main`.
- Name branches `<type>/<short-slug>`.
- Use conventional commits: `<type>(<scope>): <description>`.
- Preferred scopes are `backend`, `frontend`, `ci`, `infra`, and `docs`.

## Before Opening A PR

Run the checks relevant to the change:

```bash
pnpm backend:test
pnpm api:check
pnpm frontend:test
pnpm frontend:performance
pnpm monitor:test
pnpm test:e2e
docker compose -f infra/docker/compose.yaml config
```

Release and deployment changes must also run the locked Rust solver suite, both
container builds, and an isolated backup export/verify/restore drill. If
deployment files changed, build the affected image from the repository root.
If behavior changed, update the product spec or architecture reference in the
same PR.

## Secrets And Local Data

Never commit real `.env` files, API keys, access tokens, screenshots containing
private player data, or the contents of `apps/backend/data/`. Use committed
`.env.example` files as templates.

## Pull Request Flow

1. Push the branch and open a PR against `main`.
2. Use a conventional-commit PR title.
3. Include a concise summary, risks, and test evidence.
4. Address review comments with follow-up commits.
5. Squash and merge after required checks pass.
