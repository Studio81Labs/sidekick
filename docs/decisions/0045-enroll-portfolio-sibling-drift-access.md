# ADR 0045: Enroll Portfolio Sibling Drift Access

Status: accepted

Date: 2026-08-26

## Context

Poker Hero now shares the Studio81 Labs repository and infrastructure baseline
with Nexcue, TableTap, and Tarmoto. The drift checker can compare action pins,
workflow claims, supply-chain policy, and topology-gated shared files, but a
repository-scoped GitHub Actions token cannot read the private sibling
repositories. Scheduling the checker therefore introduces a cross-repository
credential boundary that must be narrower than ordinary maintainer access and
must not let one repository write to another.

The organization profile publishes the current alpha PWA at
`https://poker.studio81.workers.dev`. This is the smoke-tested staging Worker,
not a claim that a production release exists. Portfolio copy must continue to
describe Poker Hero as post-hand training and never as live-play assistance.

## Decision

Studio81 Labs portfolio maintainers own one fine-grained GitHub personal access
token dedicated to sibling drift. It is restricted to the repositories named
by the four sibling workflows and grants only repository Contents read access.
Its private-repository selection is limited to the private siblings that need
authenticated reads; public siblings do not require an additional token
entitlement. It grants no issue, pull-request, workflow, administration,
package, deployment, or organization write permission. The token is stored
separately in Nexcue, TableTap, Tarmoto, and Poker Hero as the Actions repository secret
`SIBLING_READ_TOKEN`; it is never committed, exposed to pull-request workflows,
or passed to steps before the hash-locked parser dependency and checker
self-test complete.

Each repository schedules its own `sibling-drift.yml` workflow and lists the
other portfolio siblings in `SIBLING_REPOS`. The read token is used only as the
Bearer credential for sibling Contents API requests. The comparison produces
one report, fails if any sibling cannot be read, and never treats a partial
comparison as convergence.

This rollout adds Poker Hero, Nexcue, TableTap, and Tarmoto to one another's
inventories. Existing Taven entries in TableTap and Tarmoto are preserved but
remain outside this four-project portfolio-alignment decision.

Issue ownership stays local. Each workflow receives `issues: write` only for
its own repository through the ephemeral repository-scoped GitHub Actions
token. It creates, updates, or closes only the local issue identified by the
`infra-drift` label. The entire secret-bearing job is restricted to the default
branch, so a feature-branch dispatch cannot execute modified repository code
with the cross-repository read token. Checker changes are validated by the
token-free CI self-test before merge and exercised with the credential only
after landing on the default branch. The cross-repository read token is not used
for issue operations.

The credential expires within 90 days and is rotated before expiry. Rotation
creates the replacement with the same repository allowlist and Contents-only
permission, updates all four encrypted repository secrets, verifies one manual
default-branch run in each repository, and then revokes the old token. The
platform maintainer performing the rotation records no token value in issues,
logs, shell history, or documentation.

## Threat Boundaries

Compromise of `SIBLING_READ_TOKEN` can disclose source and configuration from
the selected private repositories, but cannot write code, issues, releases,
secrets, settings, or deployments. Restricting repository selection prevents
the token from becoming a general Studio81 organization reader. GitHub Actions
secrets remain unavailable to untrusted fork pull requests, and the scheduled
workflow does not execute code fetched from a sibling.

The local GitHub Actions token can write one repository's issues but cannot read
or mutate private siblings. Keeping the read and write capabilities in separate
credentials prevents the comparison loop from turning a sibling response into
a cross-repository write channel.

## Incident Response

On suspected disclosure, unexpected API access, maintainer departure, or a
scope mismatch, the credential owner immediately revokes the fine-grained token
at its issuer and removes or replaces `SIBLING_READ_TOKEN` in all four
repositories. Repository maintainers disable the schedule if revocation cannot
be confirmed, inspect Actions logs and the token audit trail, and open a private
security incident record. Scheduled drift failure is expected while the token
is absent and must not be converted into a silent skip.

## Consequences

All four repositories can compare private siblings without granting write
access outside their own issue trackers. The shared token still has a selected
private-repository read blast radius and creates a quarterly operational
obligation. A missing, expired, or under-scoped token makes drift runs fail
visibly rather than reporting false convergence.

The organization profile and repository homepage may link to the public alpha
Worker while production remains intentionally unconfigured. A future production
launch replaces that URL and status in repository metadata and portfolio copy;
it does not require changing the drift credential boundary.

## Rollout And Rollback

Rollout verifies that the `SIBLING_READ_TOKEN` secret name exists in all four
repositories, lands this ADR, adds every sibling to the corresponding
`SIBLING_REPOS` list, enables Poker Hero's Monday schedule, and manually runs
each workflow from its default branch. Every run must read every listed
repository and must create or update an `infra-drift` issue only in the
repository that ran it.

Rollback removes Poker Hero from all sibling lists, returns Poker Hero's
workflow to manual dispatch, and deletes Poker Hero's secret copy. If the
credential itself is unsafe, the incident procedure revokes it globally before
any repository edit. Existing local drift issues may be closed with a rollback
note; rollback never deletes sibling source, changes branch protection, or
widens another credential.
