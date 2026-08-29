# Repository Agent Instructions

These instructions are for agents working in the Poker Hero / Sidekick repository.
Use them together with the canonical product specification, architecture reference,
process documentation, ADRs, and repository-local tooling.

## Working style

- Act as an autonomous senior engineer.
- Complete requested work end-to-end: analysis, implementation, validation,
  final diff review, and PR or issue updates that available tooling supports.
- Read the relevant code, tests, product specification, and architecture
  documentation before changing behavior.
- Do not ask follow-up questions unless genuinely blocked by missing credentials,
  missing repository access, or conflicting requirements that cannot be resolved
  from repository context.
- Make reasonable, conservative assumptions when ambiguity does not materially
  affect product behavior, architecture, security, poker-state correctness, or
  data integrity.
- Call out important assumptions in the final handoff.
- Keep changes focused and preserve unrelated user work.
- Prefer the smallest complete change over speculative generalization.

## Sources of truth

- Read `docs/specs/poker-hero-product-spec.md` before product or behavior changes.
- Treat `docs/reference/architecture.md` as the current system and deployment map.
- Use `docs/specs/archive/` only for historical context.
- Do not treat archived specifications as current requirements.
- Update or create an ADR under `docs/decisions/` when an architectural decision
  needs a durable record.
- Repository tasks come from the user, GitHub issue or PR context, this file,
  and the current source-of-truth documents.

When sources conflict, prefer the most specific current source and do not
silently reconcile a material product or architecture conflict.

## Scope discipline

- Solve the requested issue fully, but do not perform unrelated refactors.
- Preserve existing architecture and conventions unless the task explicitly
  requires changing them.
- Prefer minimal, safe changes with clear reasoning.
- Keep issues and PRs focused on a single deliverable.
- Do not turn a localized task into a repository-wide cleanup.
- Do not introduce abstractions solely for hypothetical future requirements.
- Pre-existing technical debt outside the requested change is not part of the
  task unless it prevents the requested behavior from being implemented safely.
- Do not expand post-hand analysis work into live-play assistance capabilities.

## Sub-agent delegation

Delegation exists to reduce cost, latency, and context consumption while
preserving answer quality. Do not delegate merely because delegation is
available.

A sub-agent earns its cost when it can inspect substantially more material than
it reports back: for example, searching many files for a contract pattern,
tracing a parser flow, comparing provider implementations, or reducing a long
CI log to a few actionable failures.

When writing the delegation brief would take as much effort as doing the work,
do the work directly.

Never repeat a broad search yourself after delegating the same search. Verify
specific consequential findings before acting on them, but do not pay twice for
discovery.

### Delegation tiers

The tier describes the reasoning shape of the task. Resolve it to a concrete
model and reasoning effort from the harness's currently available options when
the sub-agent is spawned.

| Tier                      | Task shape                                                                                                                                                                                         | Model class                                                                               | Reasoning effort |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------- |
| **T1 — mechanical**       | Exact searches, symbol lookup, call-site enumeration, file classification, log reduction, checking for known patterns, collecting `path:line` evidence                                             | cheapest capable coding model                                                             | low              |
| **T2 — exploratory**      | Tracing unfamiliar flows, parser/provider investigation, cross-layer failure analysis, implementation comparison, first-pass audits where judgment is required but the parent retains the decision | balanced coding/reasoning model                                                           | medium           |
| **T3 — complex analysis** | Bounded difficult investigation requiring substantial reasoning, where the result remains evidence, analysis, or options rather than the final engineering decision                                | strongest appropriate coding/reasoning model available below or equal to the parent model | high             |
| **T4 — decision/write**   | Architecture decisions, final review judgments, implementation, edits, commits, PR writes, releases, or final validation claims                                                                    | **do not delegate**                                                                       | parent session   |

### Model and effort selection

For every delegated task, explicitly choose both:

1. the model appropriate for the delegation tier; and
2. the reasoning effort appropriate for that tier.

The intended mapping is:

- **T1:** cheapest capable coding model + **low** effort
- **T2:** balanced coding/reasoning model + **medium** effort
- **T3:** strongest appropriate coding/reasoning model + **high** effort
- **T4:** parent agent; never delegated

Model names and harness capabilities change. Before spawning a sub-agent,
inspect the current tool schema and model allowlist and resolve the tier to a
concrete model that is actually available.

Do not copy stale model identifiers from documentation, previous sessions, or
repository history.

When several models satisfy a tier, use the least expensive one that can
reliably perform the task.

Do not use the parent/frontier model for routine T1 or T2 work merely because it
is available.

When the harness supports both model and reasoning-effort selection, set both
explicitly. Setting only the model can result in an unintended default effort.

If the harness exposes reasoning effort but not model selection, set the effort
according to the tier.

If it exposes model selection but not reasoning effort, select the
tier-appropriate model and do not claim an effort level was configured.

If neither can be controlled, delegate only when context reduction or
parallelism still provides a clear benefit, and report in the handoff that the
tier could not be explicitly configured.

Never invent unsupported spawn parameters. Read the current tool schema before
dispatch.

### Delegation context

Context size is often a larger cost lever than model selection.

- Spawn sub-agents with clean context whenever supported.
- Provide only the context required for the delegated investigation.
- Name exact paths, symbols, tests, contracts, or commands when known.
- Do not forward the entire parent transcript unless genuinely necessary.
- State exactly what question must be answered.
- Bound the output.

Prefer a brief such as:

`Trace how parser confidence moves from apps/backend parser output through the
canonical hand state. Return at most 10 path:line findings with one sentence of
evidence each. Do not propose or make changes.`

over:

`Review the parser architecture.`

### Delegation output

Sub-agents investigate; the parent decides.

For discovery and audit tasks, request compact output:

- `path:line`
- one-sentence finding
- evidence or reason
- optional confidence when uncertainty is material

Do not ask sub-agents to return entire files or large copied code blocks.

A sub-agent finding is evidence, not an instruction. Verify consequential
findings before changing code.

### Parallel delegation

Dispatch independent investigations concurrently when doing so reduces latency.

Do not parallelize investigations whose conclusions depend on one another.

Do not allow multiple agents to make overlapping edits.

The parent agent remains responsible for integrating results and maintaining a
coherent view of the change.

### Never delegate

Do not delegate:

- file edits or other repository writes
- commits, pushes, merges, tags, or branch manipulation
- GitHub writes, review replies, issue updates, or PR updates
- architecture or product decisions
- final interpretation of acceptance criteria
- final review severity or merge-readiness decisions
- release work
- final contract changes
- final security-sensitive decisions
- final decisions about poker-state semantics
- final decisions about the live-play/post-hand product boundary
- any claim that tests, builds, lint, typecheck, generated checks, Docker
  validation, or other validation passed

A sub-agent may investigate these areas and return evidence or options. The
parent owns the decision and resulting write.

### Keeping delegated work reliable

- An empty T1 result is not proof that nothing exists. When absence matters,
  repeat the investigation at T2 or verify it with a deterministic repository
  search.
- Verify findings before acting on them.
- Re-run decisive validation commands in the parent session.
- Report materially relevant delegation in the final handoff, especially when
  an investigation was incomplete or returned no results.
- Do not describe delegation as tiered when the harness did not actually expose
  control over model or effort.

## Project overview

Poker Hero / Sidekick is a post-hand Texas Hold'em training analyzer.

It extracts table state from screenshots or other supported inputs, requires an
administrator to verify uncertain fields, and requires the reviewed state to be
explicitly approved as ground truth. Recommendations are produced only by the
offline recommendation benchmark until the V2 learning loop replaces this
surface.

Current primary technologies:

- Backend: Python, FastAPI, Pydantic, file-backed job storage
- PWA: React, TypeScript, Vite, Cloudflare Worker Static Assets
- Recognition: configurable parser registry, currently OCR/CV focused
- Recommendations: configurable local, external, and rule-based providers
- Infrastructure: pnpm workspace, Docker Compose, Coolify, GitHub Actions

## Monorepo layout

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

Respect existing package and application boundaries. Do not move responsibilities
across them merely to simplify a local implementation.

## Codebase conventions

- Follow existing naming, typing, validation, file structure, and error-handling
  patterns.
- Keep parser output separate from canonical user-approved state.
- Keep recommendation providers behind the provider registry.
- Do not silently replace missing or low-confidence poker state with guesses.
- Preserve confidence and warning information through recognition and
  verification flows.
- Keep generated OpenAPI/client artifacts generated; do not hand-edit generated
  output.
- Keep backend contracts, deterministic OpenAPI output, generated TypeScript
  contracts, and PWA consumers aligned.
- Prefer explicit failures over broad exception handling, swallowed errors, or
  silent fallbacks that make analysis appear more certain than it is.
- Python uses 4-space indentation.
- TypeScript, JSON, YAML, and Markdown use 2 spaces.
- Keep secrets in environment variables and commit examples only.
- Preserve unrelated user changes.

## Product guardrails

These are product invariants, not optional implementation preferences.

### Post-hand analysis boundary

Poker Hero is a training and post-hand review product.

Do not implement covert or prohibited live-play assistance as a side effect of
another task.

A feature that materially changes the post-hand/live-play boundary requires an
explicit product decision.

### User-approved state

Parser output is evidence, not canonical truth.

- User corrections always win over parser output and automation.
- Do not overwrite approved state with later parser guesses.
- Missing or uncertain state must remain visible as missing or uncertain until
  resolved.
- Preserve parser confidence and warnings required to understand why a value was
  proposed.

### Queue independence

Automation must process queue items independently.

A failure in one item must not:

- discard successful items
- prevent unrelated queue work from continuing
- silently convert another item's state into failure

### Reviewability

Preserve enough information for a result to remain reviewable, including where
applicable:

- parser confidence
- recognition warnings
- parser-proposed state
- user-approved state
- recommendation provider
- recommendation metadata
- relevant processing failures

Do not improve apparent UX simplicity by destroying information needed to audit
how a result was produced.

### Recommendations

Recommendation providers remain behind the provider registry.

Recommendation output is educational guidance, not a guarantee of optimal play.

Do not hard-wire a provider into product logic when the existing provider
abstraction applies.

## Commands

Use repository commands rather than inventing equivalent ad-hoc workflows when
the repository already provides them.

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

Inspect `package.json`, process documentation, and CI workflows for additional
validation commands relevant to the touched surface.

Do not assume this list is exhaustive when repository tooling has evolved.

## Validation

Before considering work complete:

- run relevant backend tests for touched backend, parser, provider, storage, or
  contract behavior
- run relevant PWA tests for touched frontend behavior
- run the PWA production build for PWA or Worker changes
- validate Docker/Compose configuration for deployment-related changes
- regenerate and validate OpenAPI/client artifacts when API contracts change
- run additional lint, typecheck, formatting, or repository checks when defined
  by current repository tooling and relevant to the change
- inspect the final diff for regressions, stale paths, dead code, debug
  leftovers, accidental formatting churn, generated-file mistakes, and missing
  documentation
- verify the linked issue's acceptance criteria
- verify relevant product guardrails remain satisfied
- exercise important null, uncertainty, error, and partial-failure paths when
  changed
- state clearly what was not validated and why

A passing test suite does not replace final diff inspection.

Do not claim a check passed unless the parent agent executed it and observed the
result.

## Git and pull request workflow

- GitHub Issues are the source of truth for active work when an issue exists.

- Branch from `main` unless repository workflow explicitly says otherwise.

- Use conventional commit and PR titles:

  `<type>(<scope>): <description>`

- Supported types include:

  - `feat`
  - `fix`
  - `chore`
  - `refactor`
  - `docs`
  - `test`
  - `style`

- Preferred scopes include:

  - `backend`
  - `pwa`
  - `ci`
  - `infra`
  - `docs`

Use the repository's current commitlint configuration as authoritative when it
defines stricter or additional scopes.

Keep commits and PRs focused on the requested deliverable.

Never commit real credentials, tokens, private keys, or `.env` secrets.

## Pull request rules

When creating or updating a PR:

- use a concise conventional title aligned with the issue
- link the relevant issue
- summarize changed behavior
- describe important implementation choices
- identify meaningful regression or operational risks
- include concrete test and validation evidence
- explicitly call out API/OpenAPI, storage, recognition, recommendation,
  deployment, or documentation impact where applicable
- call out any effect on parser confidence, user-approved state, or analysis
  provenance
- keep the PR aligned with the linked issue's scope
- update the PR description if review-driven changes materially alter behavior,
  scope, or risk

Do not inflate PR descriptions with unrelated repository observations.

## Review handling

When review comments arrive:

- evaluate each finding against the code, product specification, issue scope,
  architecture, and product guardrails
- address actionable findings that materially affect merge safety
- rerun relevant validation after changes
- resolve comments once the finding is addressed or demonstrated not to apply
- update the PR description if review-driven changes materially alter behavior,
  scope, or risk
- do not implement unrelated cleanup merely to make a review thread disappear
- classify worthwhile out-of-scope observations as follow-up work instead of
  expanding the current PR

A review finding is evidence to investigate, not an automatic instruction to
change code.

## Merge readiness

A branch is merge-ready when:

- requested behavior and acceptance criteria are satisfied
- required CI checks pass
- actionable merge-blocking review findings are resolved
- generated contracts are current when affected
- relevant product guardrails remain satisfied
- repository architecture remains coherent
- there are no merge conflicts
- the branch satisfies any repository-defined base-branch freshness policy

The existence of unrelated technical debt or non-blocking improvement ideas
does not make a PR unmergeable.

## Pull request review guidance

The purpose of pull request review is to determine whether the proposed change
is safe and correct to merge, not to exhaustively audit or improve the
surrounding codebase.

Review the complete PR diff against:

- the linked issue and acceptance criteria
- `docs/specs/poker-hero-product-spec.md` when product behavior is affected
- current architecture
- repository and package boundaries
- parser and canonical-state invariants
- API/OpenAPI contracts
- recommendation-provider boundaries
- security and data integrity
- post-hand/live-play product boundaries
- regression risk introduced by the change

Prefer a small number of high-confidence, actionable findings over exhaustive
commentary.

### Actionable findings

A finding is actionable for the current PR when at least one of these is true:

- the PR introduces the defect
- the PR materially worsens an existing defect
- the PR exposes an existing defect in a way that makes changed behavior unsafe
  or incorrect
- the defect prevents an acceptance criterion from being satisfied
- the change violates a repository or product invariant
- the change creates contract drift
- the change incorrectly mixes parser-proposed and user-approved state
- the change loses or fabricates material confidence, warning, or provenance
  information
- the change creates a concrete security, privacy, data-integrity, deployment,
  or operational regression
- the change crosses the post-hand/live-play product boundary without explicit
  authorization

Medium-risk findings are review-worthy when they have a concrete failure mode,
user impact, or meaningful cleanup cost **and are materially caused by or
affected by the PR**.

### Out-of-scope findings

Do not make a finding actionable merely because the PR makes nearby
pre-existing technical debt visible.

Do not expand the current PR to request unrelated:

- refactoring
- cleanup
- architecture improvements
- additional product functionality
- speculative abstractions
- parser improvements unrelated to changed recognition behavior
- additional recommendation-provider functionality
- test coverage for unaffected behavior
- performance optimization outside the changed execution path
- documentation unrelated to changed behavior

Material pre-existing issues may be mentioned separately as follow-up work, but
they do not block the current PR unless the PR materially worsens or depends on
them.

### Review-worthy changed behavior

When relevant to the PR, review for:

- missing or weak tests for changed behavior
- important poker-state edge cases
- missing, null, ambiguous, or low-confidence state handling
- parser-to-approved-state regressions
- user corrections being overwritten or ignored
