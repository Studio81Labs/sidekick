# ADR 0047: Retire the V1 Screenshot Learning Surface

Status: accepted

Date: 2026-08-29

## Context

ADR 0046 made hand-history import the only player data path and kept
screenshot upload and live capture only as an administrator-only OCR test
capability. Pull request #436 implemented that boundary while preserving the
V1 screenshot-bound learning surface for records persisted before the boundary
(`input_context = legacy_player`): recommendation requests, pre-reveal training
decisions, training review and lesson notes, and training progress, all keyed
to screenshot jobs. The deployment is staging-only, so backward compatibility
with that data is not required, and the V2 product specification (§6.8)
already positions those analytics as diagnostic detail that returns on imported
decision points, not as a screenshot feature.

## Decision

The V1 screenshot learning surface is removed rather than kept behind a
compatibility flag. Every stored screenshot job is administrative OCR test
data: uploads, ground-truth approval, parser benchmarks, history/archive,
backups, and the administrator gate remain; the recommendation, training
decision, training review, training progress, and lesson export routes, their
job fields, the per-job recommendation selection, the `input_context` marker,
and the MCP tools that drove them are deleted. Recommendation providers, local
solvers, the recommendation domain models, and the offline recommendation
benchmark remain as kept infrastructure driven by settings alone.

Job status is `created | parsed | approved | error`. History readiness means
an approved job. The MCP gateway keeps its read tools and ground-truth
approval only.

## Consequences

V1 data migration and learning-surface compatibility remain out of scope. The
container entrypoint removes persisted screenshot job directories whose raw
record has the retired `recommended` status before the application validates
the current store. Cleanup takes the exclusive data-volume lock and rechecks
the candidates before deletion, so it cannot overlap another process's
mutation. Current models remain strict and never accept the retired status.
The PWA is an administrator OCR test console plus history/backups until the
Phase 1 import-first learning loop ships; the street/position/certainty
breakdowns return under the concept-mastery model per specification §6.8.
Adapting the MCP gateway to V2 workflows remains issue #428; the local
screenshot upload tool is gone with this decision.
