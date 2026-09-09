# Current-Only Cutover Removal Inventory

This inventory records the pre-release cutover authorized by
[ADR 0079](../decisions/0079-adopt-an-unreleased-current-only-cutover.md) and
implemented through [#517](https://github.com/Studio81Labs/sidekick/issues/517).
It does not claim player activation, source qualification, corpus evidence, or
solver certification.

| Removed surface                                                                                                                          | Current disposition                                                                                                                                                                                                  |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Player workspace layouts 1–5, manifestless adoption, and migration readers                                                               | Layout 6 only. Empty directories initialize; nonempty manifestless, malformed, unsafe, and unsupported stores are rejected before mutation. Lifetime/volume locks, recovery fencing, and durable publication remain. |
| Backup schemas 1–3 and downgrade/upgrade compatibility                                                                                   | Schema 4 only. Current checksum, inventory, conflict-safe restore, deletion-generation protection, and export-before-remove integrity remain.                                                                        |
| Legacy content/economic hash omissions and dual-digest acceptance                                                                        | Current complete serialization is the sole encoding; semantic source-occurrence exclusion and confirmed-zero-ante equivalence remain.                                                                                |
| Screenshot/BB recommendation benchmark, providers, fallback solvers/ranges, heuristic chart, CLI, settings, fixtures, and runtime assets | No replacement through screenshot analysis. Native V2 reference/certification remains unavailable until independently qualified.                                                                                     |
| Hosted `/analyzer` routes, aliases, and catch-all redirects                                                                              | One explicit hosted administrator console: `/admin/ocr` (including its job and benchmark views). The distinct local `apps/pwa/player` application remains local-only.                                                |
| Hosted `/api/jobs`, `/api/history`, `/api/benchmarks`, `/api/backups`, and `/api/admin/ocr-test/session`                                 | Unregistered: ordinary retirement responses only, with no forwarding. Current operator routes live exclusively under `/api/admin/ocr/...`, including `/api/admin/ocr/session`.                                       |
| Direct image/export URLs that could omit operator credentials                                                                            | The hosted UI fetches authenticated images, datasets, and backups into memory before rendering or downloading them.                                                                                                  |
| MCP job/history/benchmark/approval tools and their internal calls to retired routes                                                      | The optional MCP gateway retains only `get_environment_status`; it cannot access operator data or mutate it.                                                                                                         |

## Reused current components

- OCR parser output, confidence, warnings, and the explicit approved-state
  workflow remain the administrator diagnostic/ground-truth surface.
- Job locking, request isolation, idempotency, safe concurrent edits, current
  archive/benchmark schemas, and backup integrity remain operator requirements.
- Public health/static assets remain deployable. The Worker denies hosted
  `/api/player` requests, while the local player application keeps its loopback,
  session, Host/Origin/CSRF, and local-storage boundaries.

Unsupported prior development files must remain outside the active workspace;
the supported remedy is a fresh empty development directory and authorized
source reimport as new, unapproved detections. No reader relabels, imports,
resets, or deletes unsupported data automatically.
