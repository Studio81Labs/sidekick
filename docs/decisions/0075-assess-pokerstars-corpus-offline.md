# ADR 0075: Assess the PokerStars Corpus Offline

Status: accepted

Date: 2026-09-05

## Context

Issue #409 requires evidence from approximately 1,000 representative, legally
obtained or sanitized PokerStars histories. The bounded adapter already returns
isolated per-hand parses, reconciliation outcomes, and structured diagnostics,
but its synthetic fixtures are not a representative corpus and a parser
`clean` disposition proves only amount reconciliation. It does not compare
chronology, economics, positions, action order, or action-origin semantics with
independently authored ground truth.

The assessment must not turn private hand-history material into application
state or leak raw text, local filenames, source hand identifiers, player names,
cards, or evidence excerpts into a retained report.

## Decision

Add a dedicated offline corpus assessment command. It accepts a strict,
versioned manifest whose cases identify local source paths and contiguous hand
ordinals, but whose parsed expectations are a closed private projection: source
hand identity and chronology, complete game/economic context, seats and
structural positions, hero and board cards, every ordered action, action-origin
semantics and confidence, action evidence line numbers, stated pot, showdown,
awards, player results, and parser warnings. Expected rejections name a
structured diagnostic code. Coverage tags are sorted and their inferable claims
must agree with the ground-truth projection.

Every source is bounded, read as strict UTF-8, and parsed through the production
PokerStars adapter with a deterministic assessment context. Hands and
diagnostics are matched by manifest ordinal. Duplicate cases, skipped manifest
ordinals, unsafe paths, invalid labels, duplicate diagnostics, and parser
outputs without labels fail closed. Duplicate source bytes and repeated labeled
source hand IDs are also rejected so copied hands cannot inflate the corpus. A
file-level rejection marks each expected case from that file as failed without
discarding results from other files.

The report is a separate sanitized, closed contract. It contains adapter and
format revisions, a deterministic digest over source bytes and labels, exact
aggregate denominators and composition counts, and one ordinal-only result with
failure codes per case. It never contains manifest case IDs or source paths,
parser messages, actual or expected field values, raw provenance identifiers,
cards, or source excerpts. The command can gate minimum case count, clean parse
rate, coverage-tag counts, and an expected corpus fingerprint. The clean rate
uses every labeled hand as its denominator, including expected rejections, so
unsupported cases cannot be relabeled out of the Phase 0 gate.

The command never opens `PlayerWorkspace`, imports a hand, writes player data,
approves parser output, or exposes an HTTP route. It is evidence tooling only.

## Consequences

The real Phase 0 corpus can now be evaluated reproducibly without using the
player application boundary or persisting identifying report data. Per-hand
failures remain actionable by ordinal to the local corpus custodian, while the
stored report is safe to compare and share within the project.

This decision does not provide the representative corpus, establish source
rights, expand the supported PokerStars syntax, prove 99% accuracy, approve any
detected state, or close #409. Those claims require the actual corpus,
independent labels, required format composition, and a passing gated run.
