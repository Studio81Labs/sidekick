# Poker Hero — Specification V2

Status: current source of truth (supersedes V1)

Delivery is tracked by the [V2 roadmap issue](https://github.com/Studio81Labs/poker-hero/issues/404)
and its linked Phase [0](https://github.com/Studio81Labs/poker-hero/issues/405),
[1](https://github.com/Studio81Labs/poker-hero/issues/406),
[2](https://github.com/Studio81Labs/poker-hero/issues/407), and
[3](https://github.com/Studio81Labs/poker-hero/issues/408) epics.
The durable player/operator, persistence, and migration boundary is recorded in
[ADR 0046](../decisions/0046-adopt-import-first-learning-boundary.md).

---

## 0. Why V2 exists

V1 is a capable pile of review analytics. It tracks accuracy by street and by
position, exposes EV loss, attributes engine routes, and calibrates certainty.
What it does **not** have is a theory of how a human actually gets better at
poker. It measures decisions; it does not teach.

The governing principle of V2 is one sentence:

> A learning app that does not measurably teach is a bad app.

Everything below is derived from that. The unit of the product is no longer a
_screenshot_ or even a _hand_ — it is a **concept the player is trying to
master**. Hands are merely evidence about which concepts are weak. Progress is
not "hands reviewed"; it is "leaks closed."

Two structural changes make this possible, and they are the spine of V2:

1. **Import-first data.** A single imported hand history carries every street,
   every action, exact sizes, and positions — losslessly, with the player's
   real decisions already recorded. Screenshot upload and live screen capture
   remain available only to administrators as disabled-by-default parser testing
   tools; they are not player data-source options.
2. **A concept-mastery learning model.** Flat accuracy buckets are replaced by a
   mastery model over a poker skill tree, driven by active recall, spaced
   repetition, and elaborative feedback — the mechanisms that actually produce
   learning.

---

## Primary target user & boundaries

This section exists to **hold the boundaries of the product**. It is placed
before everything else because it silently governs dozens of downstream
decisions — UI density, concept ordering, feedback tone, what is hidden by
default, and which reference engine is even appropriate. When a later decision is
ambiguous, it is resolved by asking "does this serve the primary user?"

### Primary user (in scope)

**The recreational-advancing player**: someone who knows the rules and plays (at
least occasionally, online, on a client that can export hand histories) but has
**never systematically studied** poker. They can lose a session and not know why.
They have hands to import and are frustrated by the density of existing tools.

This segment is the target because it is the largest population the
solver-grading engine can actually serve, it is underserved (incumbents are walls
of tables and frequencies that intimidate exactly this user — the reaction is
"I don't understand these benchmarks"), and it is where a warm, opinionated,
low-density design has real value rather than cosmetic value.

### Explicitly out of scope (the boundaries)

- **The complete beginner** who does not yet know hand rankings, positions, or
  basic rules. For this user a solver is the _wrong teacher_ — being told to
  "3-bet 68% to deny equity" over an empty foundation is noise, not learning.
  This user belongs to play-money apps, rules tutorials, and video content. The
  app may let them grow _into_ it (see below) but is not designed _for_ them.
- **The professional / serious grinder** who wants custom solving, node-locking,
  population exploits, and raw frequency tables. They already have PioSolver and
  GTO Wizard. Serving them means adding exactly the density that repels the
  primary user.

Holding both boundaries is the point. The failure mode to avoid is **sitting
between two chairs** — too basic for studying players, too solver-flavored for
true beginners.

### One entry, growing depth

Advancing players are not served by a separate "pro mode." They **grow up through
the app** via the concept taxonomy (§6.1): advanced concepts stay gated until the
foundational ones are demonstrated, and information density increases with
demonstrated mastery. One entry point, increasing depth — never two parallel
experiences.

### This does not change the V2 architecture

The reference for grading remains a solved chart/tree (§5), but it is an
educational model conditional on its verified inputs, economics, abstractions,
policy revision, and tolerances — not universal or guaranteed optimal play. What
the primary-user choice adds is a **pedagogical / onboarding layer on top of the
existing model**: the app teaches its own vocabulary progressively (what a 3-bet
is, position, range, EV), principle-first (§6.4), and throttles density so the
studying-but-not-expert user is never drowned in EV-loss decimals. It is a layer
over the skill tree, not a second skill tree.

### Consequence for validation (the dogfooding pair)

The builder is not a poker player. This is an asset, not a gap: it produces an
ideal two-person test pair that is otherwise hard to assemble.

- The **poker-player friend** validates that grading is _correct_ — that what the
  app calls a leak is genuinely a leak.
- The **non-player builder** validates that the teaching is _comprehensible_ —
  using a versioned, blinded pool of reviewed, solved library spots matched by
  concept, coverage band, policy/taxonomy revisions, and reviewed difficulty.
  For each attempt the builder first receives a principle-first teaching example,
  then predicts the action in a fresh holdout they have never attempted and
  explains the principle back in plain language. Holdout identity and answer
  remain hidden until submission; a used holdout is never considered unseen
  again, and retries draw a different item. The pool is rotated or replenished
  before unused holdouts run out.

If the app can teach the non-player builder, that is the strongest possible proof
it teaches. Phase 1 success (§9) therefore requires **both**: the friend finds a
real leak he didn't know he had, _and_ the non-player builder passes the blinded
pool-based transfer assessment with a fresh holdout. Because the builder
has no imported playing history, this assessment does not claim to detect a
personal leak, update mastery, or contribute to proof-of-learning metrics.

---

## 1. What changes from V1

**Restrict to administrative testing**

- Live capture from a window, screen, or browser tab and screenshot image upload
  remain available only as administrative parser-testing tools. They are
  disabled by default, require explicit deployment configuration and
  server-enforced administrator authorization, and are absent from the normal
  player UI. Hiding controls in the frontend is not an authorization boundary.
- Administrative capture/upload may exercise OCR, parser benchmarks, and
  diagnostics, but it must not loop into player learning, update mastery, or
  automatically request recommendations. This prevents the product from
  presenting a real-time-assistance capability while preserving the inputs
  needed to validate recognition.
- Automation that auto-requests recommendations during play is removed.

**Invert**

- Data sourcing inverts from screenshot-first to **import-first**. OCR is kept
  for administrator-run parser testing and benchmarking, not as an end-user
  fallback.

**Add (the new heart)**

- A **concept taxonomy** (poker skill tree).
- A **mastery model** per concept.
- A **drill engine** driven by active recall and spaced repetition.
- An **elaborative feedback layer** that teaches transferable principles, not
  solver outputs.
- A **trustworthiness gate**: mastery only ever updates on decisions graded
  against a genuine reference (solved chart or solved tree). Heuristic guesses
  never move a player's mastery.

**Keep (V1 did these well)**

- Config-driven parser and recommendation registries with a mock provider.
- The parser benchmark harness with an explicit ground-truth corpus and
  versioned export/import.
- The recommendation benchmark against trusted references (this becomes the
  instrument that validates grading quality — see §5).
- Evidence transparency (exposing chart policy, tree/range assumptions, and
  fallback context per decision).
- Backup/restore with checksums and conflict-safe merge.
- Failure isolation ("one item failing must not roll back unrelated items").

**Defer until after learning is validated**

- MCP agent gateway, deployment monitoring, rate limiting, runtime error
  reporting. These are hardening for a deployed multi-tenant product. They are
  premature while the central question — _does this app teach?_ — is unproven.
  They move to a "post-validation hardening" appendix and are not built in the
  early phases.

---

## 2. Design principles

- **Teach principles, not outputs.** "Solver raises AJs 68%" is a number nobody
  retains. "Against a tight UTG open you are at the top of your continuing range,
  so you 3-bet for value and denial" is a principle that transfers to the next
  hand. Feedback always states the principle first, then illustrates with the
  spot.
- **Never teach from a guess.** If a decision cannot be graded against a real
  reference, it is shown but does not move mastery, does not generate a drill,
  and is not called a "mistake."
- **Never grade involuntary behavior.** Forced posts and client actions caused
  by timeout, disconnect, or automation are not player decisions. Unknown
  action origin stays excluded until explicitly resolved.
- **Canonical lifecycle changes cascade.** Correction/reapproval, approval
  withdrawal, post-approval rejection, and deletion deactivate every dependent
  learning artifact before canonical state can disappear or stop being active.
- **Learning lives in aggregation and repetition, not in single hands.** The
  single-hand comparison is necessary but weak on its own. Value comes from
  detecting _recurring_ leaks and _drilling_ them.
- **The player predicts before the answer is revealed.** Active recall is the
  strongest lever available and is preserved even for imported hands.
- **The app must prove it taught.** Previously flagged leaks are re-measured on
  matched or opportunity-standardized evidence from genuinely later sessions,
  with uncertainty. "This leak is closing" is surfaced only when improvement
  cannot be explained by an easier case mix.
- **Local-first, single-user.** No account system or multi-tenant assumptions in
  the core. The supported V2 player runtime and persistence are delivered on the
  player's machine; raw histories, canonical state, and learning records never
  traverse or reside in the hosted V1 Worker/backend path. By default, grading
  also stays on that machine.
  Nothing is sent to a remote solved-data provider unless the player explicitly
  enables that provider after seeing the exact minimized outbound-data
  categories, retention/use policy, and network dependency. Local-only mode
  remains available; remote-only coverage is visibly unavailable when consent
  is absent or revoked.
- **Capture is an operator capability, not a player feature.** In a local-first
  deployment, "administrator" means an explicitly authorized operator/tester,
  not an implicit role granted to every local user. Screenshot upload and live
  capture fail closed when the administrative test mode is disabled or the
  caller is unauthorized.
- **Solved policy is educational reference guidance.** Player-facing grades,
  recommendations, principles, mastery, and drills state the policy assumptions
  and uncertainty and never claim guaranteed optimal play or guaranteed results.

---

## 3. Data source model

### 3.1 Primary path — hand history import

The player imports hand-history files exported by their poker client. Most
serious desktop clients write these to disk. Support order, chosen by format
cleanliness and market reach:

1. **PokerStars** — writes plain-text `.txt` histories to disk automatically;
   cleanest and best-documented format. First adapter.
2. **Winamax** — also automatic local files.
3. **888poker, partypoker/BetMGM, iPoker, ACR/WPN** — supported by every
   tracker; standard local files once enabled.
4. **GGPoker** — export exists via Pokercraft but is more manual and its format
   changes; treat as later, lower-priority, and expect adapter churn.

Sites without player export (WPT Global as of mid-2026, X-Poker, many
mobile/Asian apps) are not supported by the V2 player workflow. Their layouts
may still be exercised through the administrator-only OCR test surface.

### 3.2 Detected and user-approved hand model

All adapters emit one site-agnostic **detected hand** with field confidence,
warnings, and source evidence; they do not write directly into learning state.
The player reviews and corrects that output before explicitly approving the
**canonical hand** consumed downstream. User corrections always win, and the
rest of the system never sees site-specific text. The shared detected/approved
shape includes at minimum:

- Hand id, site, source hand timestamp (with source timezone/offset when
  available), stable source-session/file identity and ordering, import
  provenance, game type, stakes, table size, blinds/antes, and whether a
  positive ante is posted per player or by the big blind for the table. An ante
  scheme that the source semantics do not prove, including an omitted scheme on
  a positive ante, remains explicitly unknown and is not ready for decision
  extraction. A confirmed zero ante needs no poster scheme, so retained poster
  labels do not distinguish otherwise identical detections during re-import.
  Missing source time remains explicitly unknown; ingestion time must not stand
  in for play time in recency, session, or proof-of-learning calculations.
- Economic context when supplied: for cash games, currency and the applicable
  rake/drop schedule and cap; for tournaments, tournament identity/type and
  stage, separately reported entry buy-in/fee and source blind-level label,
  payout/paid-place structure, players remaining, relevant remaining stacks,
  bounty format/values, and any other ICM inputs. Entry costs use their explicitly
  supplied currency denomination, never tournament chips or hand rake. A
  blind-level label does not establish tournament stage or ICM readiness.
  [ADR 0077](../decisions/0077-retain-tournament-entry-and-level-source-facts.md)
  defines this optional source-fact extension and its compatibility prerequisite;
  implementation remains tracked in #409. Missing economic fields
  remain explicitly unknown rather than inferred. Tournament seat
  `remaining_stacks` entries used for current-hand extraction are the same
  hand-start stack snapshot as the seats' `starting_stack` values. Both use
  absolute tournament chips, not currency or BB. Before decision extraction,
  every dealt-in player with a known seat stack must have an exactly equal
  Decimal remaining-stack entry; additional off-table field players remain
  valid.
- Button seat.
- Seats: for each, seat number, starting stack, and participation status
  (including dealt-in and sitting-out/not-dealt states). Each dealt-in player
  preserves the exact dealt-in player count and action index/distance from the
  button, plus a table-size-specific display label such as UTG, UTG+1, UTG+2/LJ,
  HJ, CO, BTN, SB, or BB. Distinct full-ring seats are never collapsed into a
  generic MP label for grading. Positions are computed only from the dealt-in
  action ring around the button, so a seated player who was not dealt in never
  shifts another player's position. The heads-up special case (button = SB) is
  handled explicitly.
- Hero identity and hero hole cards (from the "dealt to" line).
- Streets: for each of preflop/flop/turn/river, the board cards and an **ordered
  action list** (actor, action type, total committed, and action origin). Action
  origin distinguishes known player-selected actions from forced/system posts,
  client-automatic actions caused by timeout/disconnect/automation, and unknown
  origin, with source evidence and confidence. An adapter may treat an unmarked
  normal action as player-selected only when its versioned source semantics make
  the absence of an automatic-action marker meaningful; otherwise origin stays
  unknown for review.
- Showdown and results.

**Identity and re-import semantics:** `(site, source hand id)` is the stable hand
identity unless a site adapter documents a stronger versioned namespace for a
format whose hand ids are not site-unique. Overlapping files and exact reimports
resolve to the existing hand and do not create a second canonical record,
decision, grade, mastery sample, or drill. Import attempts and source-file
provenance may be appended for audit without multiplying learning data. If the
same stable identity arrives with materially different source or detected
content, both inputs are preserved as a conflict for explicit user resolution;
neither silently overwrites the active approved revision or counts twice. An
additional materially distinct retained raw source remains covered by a
retained conflict whose scope includes another retained source, even before it
has a detection or participates in a canonical-source switch. An
approved revision may become active from a different retained raw source only
after a `resolved_use_source` conflict binds the prior canonical source and
explicitly selects the new source. Same-source corrections and reapprovals stay
ordinary canonical revisions and do not require a conflict.
Every persistence, extraction, and restore boundary revalidates the complete
aggregate graph from a fresh snapshot. Nested in-memory edits cannot bypass
checksums, corrections, chronology, conflicts, or source-evidence invariants.
Every audit-retaining lifecycle freshness marker advances through all retained
imports, detections, and approvals. This covers active, pending-review,
withdrawn, and rejected records; a deletion-pending request must occur after
that evidence and its lifecycle marker must reach the request. Resolving any
retained conflict also advances freshness to at least the resolution time so
backup/restore ordering cannot rank newer evidence by stale lifecycle state. A
deletion request must occur at or after every retained conflict resolution so
the request covers the complete audit record it will remove.

**Correctness oracle:** re-derive the pot from the action stream and reconcile
against the file's stated pot (accounting for rake, uncalled bets, side pots).
Independently-computed pot == stated pot is a per-hand pass/fail that validates
the action/amount parse without manual eyeballing. It is necessary but not
sufficient: a wrong button, hero identity, card, timestamp, or participation
status can reconcile the pot and still corrupt grading.

A complete action stream is not its own independent pot oracle. Missing results,
an absent stated-pot summary, a net total without the rake needed to recover a
like-for-like gross total, or awards without a stated comparable pot remain
reviewable but reconcile as indeterminate. Decision extraction requires a
passing reconciliation with zero discrepancy against an independent source
total; awards may corroborate that total but cannot replace it when gross versus
net semantics are unresolved. A stated comparator counts as independent only
when every value in at least one complete comparison route has non-empty raw
field evidence scoped to the stated-pot summary, or the active canonical
revision contains a semantically value-changing correction that audits that exact value.
Missing comparator provenance remains reviewable but blocks decision extraction.

Pot reconciliation remains an amount-only oracle and does not infer a site's
cash-rake formula from percentage, cap, and fixed-drop values. Decision
extraction separately checks any stated cash rake against the approved schedule.
An all-zero schedule permits only stated rake zero. If stated rake is present and
any schedule component is nonzero, extraction fails closed until the canonical
economics contract declares the calculation basis, cap/drop ordering and
applicability, and rounding policy required to derive an exact allowed value.
When stated rake is absent but stated gross and net totals differ, their
difference is material rake evidence and follows the same fail-closed schedule
gate. An absent stated rake preserves gross-only reconciliation and extraction
behavior only when no gross-to-net deduction is stated; tournament economics do
not use this cash-rake gate.

An uncalled return closes a betting round only when it exactly removes the
actor's unique unmatched live commitment after every other actionable opponent
has folded, responded, or gone all-in. Folded and all-in commitments still set
the matched floor; dead antes do not. An unresolved return remains reviewable
but cannot authorize a later street, results, or learning extraction, and no
same-street action may follow it.

**Approval boundary:** raw history, detected output, confidences, warnings,
reconciliation evidence, corrections, and final approved state remain separate
and reviewable. Approval may be performed per hand or explicitly across a
reviewed batch, but decision extraction and grading accept only the player's
approved canonical state. Unapproved or rejected hands never update mastery,
generate drills, or receive a grade.

Each approval has a monotonic canonical revision. Correcting and reapproving a
previously approved hand atomically supersedes every downstream artifact derived
from the old revision: decision points, grades, concept tags, mastery inputs and
aggregates, scheduled drill entries/attempt outcomes, and proof-of-learning
metrics. Superseded artifacts remain auditable but never active. If rebuilding
fails before the replacement revision and its derived artifacts form a durable
publish intent, the attempted reapproval rolls back: the prior approved revision
and its matching learning artifacts remain active. Those artifacts are not stale
because their canonical revision was never superseded. A failed call reports
only that reapproval did not complete, preserves the proposed correction, and
requires refreshed lifecycle state before retry; the exception does not prove
which side of the durability boundary failed. A recoverable durable intent
refuses newer per-hand lifecycle writes until roll-forward recovery completes
it, while a structurally unusable intent is quarantined with its evidence for
explicit repair. Neither the original failed response nor quarantine is
presented as a successful reapproval; refreshed state after recovery may show
that the replacement became active. No failure may expose an active canonical
revision with learning artifacts from a different revision, and unrelated hands
continue independently. ADR 0048 records this durability boundary.

Approval withdrawal, rejection after approval, and deletion use the same
invalidation boundary. One atomic logical transition removes the active
canonical pointer and deactivates/rebuilds every derived decision, grade, concept
tag, mastery input/aggregate, scheduled drill entry/attempt contribution, and
proof metric before physical removal is allowed. The implementation must never
delete canonical state first and leave active derived evidence behind. If the
transition cannot complete atomically, either the operation rolls back with the
hand still active or the hand becomes visibly deletion-pending and immediately
excluded from all grading/learning reads while isolated cleanup retries;
unrelated hands continue independently.

Withdrawal/rejection retains the inactive source, revision, and derived audit
trail. A permanent-delete request purges the hand-linked raw, detected,
canonical, conflict, and derived audit records only after logical deactivation
and aggregate/schedule rebuild succeeds, retaining at most a non-sensitive
deletion receipt required to prevent silent resurrection. Backup/restore honors
the deletion generation and cannot reactivate purged evidence from an older
backup without an explicit user-authorized reimport.

### 3.3 Decision extraction

The learning system does not consume hands — it consumes **decision points**.
From a user-approved canonical hand, extract each hero decision as:

- The canonical decision state (everything the recommendation provider needs).
- The **actual player-selected action taken**, including its approved action
  origin and source evidence (from the history — this is the key gift of import
  when voluntariness is known).
- The optional **primary concept tag** (§6.1), derivable from the state and
  absent when the taxonomy does not support the decision.

One approved imported hand yields zero or more decision points (preflop, flop,
turn, river). A valid no-decision hand, such as a big-blind walk, is retained with
its provenance and an explicit no-decision outcome; it is not failed, graded, or
given a fabricated action. Forced/system actions, known client-automatic actions
(including timeout/disconnect folds or checks), and actions whose origin remains
unknown are retained with their exclusion reason but are not emitted as player
decision points and never update mastery or schedule drills. A user may resolve
an unknown origin during approval only by explicitly confirming the action was
player-selected; the detected value and correction remain auditable. A real
voluntary decision point is the atomic unit for grading, mastery, and drilling.

The approved canonical hand is the authority for persisted decision points.
Before an active artifact is served to grading or learning, the local runtime
re-derives the complete extraction from a freshly validated canonical record and
requires exact equality with the stored artifact. A mismatch fails closed and
does not overwrite the retained bytes. Superseded artifacts remain
schema-validated audit snapshots but are never trusted as active learning state.
Each decision retains its own chronology and import provenance so the atomic
grading unit remains self-contained; the extraction envelope also retains those
hand-level facts because a valid hand can have no decision points. Historical
wager and full-increment scalars used to decide whether a short all-in reopened
betting are persisted with the decision and rechecked through the aggregate's
single shared rule rather than by replaying a second betting implementation.
ADR 0049 records this rehydration boundary.

### 3.4 Administrative OCR test path — screenshot upload and live capture

The V1 OCR pipeline, screenshot upload, and live window/screen/tab capture are
retained solely so administrators can test recognition against representative
client layouts:

- The capability is disabled by default and requires both deployment opt-in and
  server-enforced administrator authorization.
- Player-facing routes and navigation do not expose capture or screenshot image
  upload. Hand-history import is the only player data-source path.
- Test inputs may be uploaded or captured live, individually or repeatedly when
  required for parser diagnostics, but they remain in an isolated test context.
- Test inputs may feed OCR/CV parsing, confidence inspection, ground-truth
  approval, and parser benchmarks. They do not create player decision points,
  update mastery, generate drills, or auto-request recommendations.
- Test data is visibly marked, separately retained, and excluded from player
  exports, learning analytics, and proof-of-learning metrics.

Legacy V1 screenshot jobs and training answers remain audit-only. They cannot be
converted into canonical V2 hands or learning evidence because they do not
contain the imported ordered action stream and real table action required by
§3.3. A historical hand can enter V2 only through a new qualifying
hand-history import; the V1 screenshot, recommendation, or pre-reveal answer is
never reinterpreted as played-hand provenance.

This boundary preserves recognition development without exposing a workflow
that could be used as real-time poker assistance. Authorization must be enforced
by the backend/Worker boundary; frontend visibility alone is insufficient.

### 3.5 Local player runtime and persistence boundary

Before Phase 1, the V2 player PWA, API, and file-backed store are delivered as a
co-located runtime on the player's machine. The local backend serves the player
UI and API from a local origin, binds only to loopback (`127.0.0.1`/`::1`), and
persists raw imports, detected/approved revisions, conflicts, decisions, grades,
mastery, drills, proof metrics, and backups only in player-controlled local
storage. It requires a high-entropy per-install local API credential/session and
enforces local Host/Origin allowlists plus state-changing request/CSRF protection;
loopback binding is not treated as authentication. Non-loopback/LAN access is
denied. Any explicit operator-only non-loopback development mode is outside the
player runtime and requires TLS plus server-enforced authorization.

The browser does not send player records through the deployed Cloudflare Worker
or a centrally hosted FastAPI store. A remotely hosted static shell is not a
player-data proxy.

The current Worker → hosted FastAPI topology remains the deployed V1/admin
architecture while migration is implemented. It may expose legacy data for
read-only audit/export and the isolated administrative parser-test surface, but
it cannot accept V2 player imports or learning state. Phase 1 is blocked until
packaging/setup, local-origin routing, persistence/backup/restore, upgrade, and
direct-network tests prove that no player record reaches the hosted path. The
only permitted V2 player-data egress is the separately consented, minimized
remote solved lookup in §5.3; revoking it returns to fully local operation.

---

## 4. The player's real action vs. a later study prediction

Import gives the real table decision. Active recall adds a second, explicitly
later signal, so V2 captures up to two signals per decision point:

- **Table action** — what the player actually did, live, under real conditions
  (from the imported history).
- **Study prediction** (optional) — in drill/replay mode the hand is replayed to
  a decision point with the outcome hidden, and the player predicts what they
  would do now, in calm study conditions. The attempt records its own timestamp
  and whether any Poker Hero feedback for that decision/concept had already been
  revealed.

Their divergence is a useful **temporal comparison** between historical table
behavior and current study knowledge. It does not prove what the player knew
when the hand was played: later review, drills, or outside study may have changed
their knowledge. Even a prediction captured before Poker Hero reveals feedback
is only a clean current baseline, not proof of historical knowledge. The product
therefore does not classify a single divergence as an execution-versus-knowledge
leak or choose a remedy on that basis. Remedy selection requires repeated
prediction evidence plus genuinely later imported play (§6.7). This remains
richer than V1's single locked answer without inventing chronology.

---

## 5. Recommendation & grading model

Grading is what tells a decision "right" or "wrong." Its trustworthiness is the
ceiling on learning quality, so it is treated as first-class.

### 5.1 Coverage, stated honestly

- **Preflop** — tractable and comparatively cheap to solve, but not yet backed by
  a mastery-gradeable reference in the current implementation. The retained V1
  chart uses conservative heuristic thresholds; it remains `heuristic` and can
  never update mastery or generate drills. Phase 0 must source and benchmark an
  independently solved position-aware policy (RFI, vs-RFI, vs-3bet, blind
  defense, squeeze, cold-call, short-stack) with explicit table-size, structural
  position, stack-depth, sizing, economic, and mixed-policy boundaries. V1's
  routing/context extraction may be reused only where independently validated;
  its threshold policy must not be relabeled `solved`. Structured history is
  authoritative: any supplied opener position or size must match its first raise
  exactly, while a nonempty call-only/limp-only history carries neither opener
  field.
- **Heads-up postflop** — potentially mastery-gradeable only when the reviewed
  hand resolves an exact supported line against a benchmarked solved-tree
  revision **and** all required root inputs are verified: effective stack,
  players/relative position, pot and action history, board, and ranges derived
  and conditioned from complete prior-street evidence. Schema-v5 grading
  requires the full completed postflop prefix: turn includes flop, and river
  includes flop plus turn. Any 100-BB stack
  assumption, configured/default range, ambiguous player mapping, incomplete
  prior street, or approximate/skipped conditioning makes the current result
  `heuristic`, even if the current-street line exists.
- **Multiway postflop** — _not_ solved. Currently a range/EV heuristic. This is
  the largest gap and covers a large share of real hands.

Coverage also includes game economics. A solved route declares the cash rake
model or tournament chip-EV/ICM/bounty context it assumes, the exact blind/ante
level, ante poster scheme, and units used to convert canonical BB amounts, and
the canonical fields required to match it. Tournament grading maps table actors
to the identified remaining-stack and bounty entries rather than assuming
reserved player names. The ante poster scheme is part of the hashed economic
route identity: a positive ante must identify either per-player or big-blind
posting, while omitted or unknown posting is ungradeable rather than being
silently treated as the legacy per-player default.
Cash hands with an unknown or different material
rake structure and tournament hands lacking the payout, field, stack, or bounty
state required by the reference are heuristic/ungraded for mastery. A generic
chip-EV chart must never be presented as solved ICM or bounty-aware policy.
Likewise, every route declares supported dealt-in counts and exact structural
positions; hands outside that table-size/position coverage remain
heuristic/ungraded rather than being coerced into the nearest six-max label.

### 5.2 The trustworthiness gate (non-negotiable)

Every graded decision carries a `grade_source`:

- `solved` — solved chart or solved tree. **Eligible to move mastery or generate
  drills only when the resolved policy evidence is complete.**
- `heuristic` — range/EV fallback. **Shown to the player with an explicit
  "estimate, not solved" marker. Never moves mastery, never generates a drill,
  never labeled a mistake.**

`grade_source: solved` is necessary but not sufficient for right/wrong grading.
Each solved result also preserves the reference policy for the resolved spot:
supported actions and sizings, their frequencies when available, candidate EVs,
the EV/cost unit and utility-model provenance, the matched economic assumptions,
and the immutable reference/policy/tolerance revision used to decide support.
The player's action is a supported policy match when it has meaningful reference
frequency or is within the accepted EV-equivalence tolerance, even when it is
not the solver's headline action. Such a mixed-strategy alternative is not a
mistake and cannot create a leak or corrective drill.

Only an action outside the complete solved policy support can be called a
mistake and contribute an error to mastery. If the reference response omits the
policy detail needed to distinguish a supported mix from an error, the decision
remains visible as solved evidence but ungraded for mastery and drills. Aggregate
frequency adherence is evaluated separately over sufficiently large samples of
comparable decisions under the same reference and taxonomy revisions. A
statistically meaningful, material systematic deviation from the solved mix is
concept-level mastery/leak evidence, even when each individual action was
supported. It may prevent Mastered or prioritize practice, but it never
retroactively labels an individual supported realization a mistake. Small or
non-comparable samples remain diagnostic only.

Solved eligibility also requires evidence that every route-critical canonical
input matches the reference. A provider fallback or default for effective stack,
range, position, action history, board conditioning, or economic context is an
assumption, not verification, and forces the result to `heuristic`/ungraded.
For benchmark schema v5, that evidence must be matched against an independently
configured provider route catalog captured before the provider sees any case.
Poker Hero canonicalizes and hashes the raw configured route context itself and
retains the selected route, engine revision, configuration artifact, and adapter
binding identities. A provider-computed echo of case input is not an attestation;
missing, ambiguous, or changed bindings fail closed before grading.
Every schema-v5 case also requires exactly two distinct hero hole cards and the
exact board cardinality for its street; provider-declared required fields and an
exact-shape route binding cannot substitute for this semantic completeness.
The bound context includes every canonical decision-state field exposed to the
provider—cards, board, pot, wagers, stacks, players, positions, opener/action
context, and current/completed action histories—plus structural actor mapping,
economics, and utility. Range selection is bound through these exact derivation
inputs until a future canonical contract supplies explicit ranges. The raw
catalog declaration must retain the benchmark's exact recursive JSON shape,
including every canonical decision-state null, empty, and default-valued key;
surrounding objects mirror the benchmark-generated field presence, and omitted
or unknown required keys fail closed before provider execution.
The benchmark fingerprints an isolated corpus snapshot before provider hooks,
uses separate validated state copies for readiness inspection and execution, and
rejects any retained execution-state mutation before reading runtime trust
metadata or scoring the result. A structurally invalid dataset snapshot fails
before the binding catalog, required-field inspection, or provider is called. A
separately serialized and revalidated dataset-level trust snapshot plus a shared
validation pass over corpus-wide case rules prevents a non-serializable nested
case from masking a schema-version, tagged/range expectation, or grading-evidence
mutation. Once those global rules pass, a non-serializable nested case fails in
isolation before its case-scoped provider hooks; unrelated valid cases continue
from the deep snapshot, and the report omits the unprovable corpus fingerprint
so it cannot become an attested baseline. The declared schema version remains in
the report and controls this trust boundary: a version-5 corpus whose version is
mutated or whose evidence envelope becomes invalid or missing cannot downgrade
itself to version-4 execution or baseline rules.
After execution, a version-5 benchmark case completes only when the provider
reports the exact engine selected by that binding and no fallback metadata. A
missing, malformed, or different runtime engine and every explicit fallback are
case failures, retain only route/result audit identity, and contribute no policy,
EV, range-conditioning, or range-source evidence. Versions 1 through 4 retain
their diagnostic fallback scoring behavior.

Active mastery for one concept/coverage band uses one pinned reference-policy
revision. A new chart, solved tree, economic model, or support tolerance is
staged and benchmarked before activation. It must then either atomically regrade
all affected active decisions and rebuild mastery, drills, and proof metrics, or
start a clearly separate mastery series; old and new policy classifications are
never combined. Activation also requires a human-reviewed principle version
compatible with the new reference and taxonomy for every affected concept that
can appear in review or drills. Until migration and teaching-content approval
succeed, the prior revision stays active or the affected decisions are visibly
excluded; the new revision cannot schedule drills. Historical grades retain
their original reference revision for audit.

This directly prevents the app from teaching wrong things. A player can never
have a leak "detected" or drilled on the basis of a guess. It also makes the
product honest about its own boundaries, which a study tool must be.

### 5.3 Sourcing the postflop gap (the open kill-criterion)

Preflop is tractable, but the retained V1 chart is not a solved reference. Phase
0 must source and benchmark an independently solved preflop policy before any
preflop decision can move mastery. Multiway-postflop reference sourcing is the
additional Phase-0 question that gates whether mastery covers those spots at
all:

- **Precompute** a bounded, high-value set of postflop solutions once and ship
  it as a static lookup — the same model serious tools use (preflop from
  HRC/Monker-class tools, postflop from Pio-class). This is eligible only when
  Poker Hero owns the artifacts or the license explicitly permits embedding and
  redistributing the solved dataset/artifacts and updates in the locally
  distributed application. Preferred if a bounded set covers enough real spots.
- **License** a solved-data feed served from infrastructure covered by explicit
  commercial serving/derived-output rights. A feed license that forbids data
  redistribution is server-side only: its dataset is never embedded in or
  delivered with the local application. It is eligible only as an optional,
  explicit-consent provider. Its request contains the minimum pseudonymous
  route state needed for lookup (game/economic model, table/position, stack and
  sizing, prior actions, board/hole-card abstractions or cards, and conditioned
  ranges) and never raw hand history, site/hand/session identity, player names,
  source timestamps, screenshots, or mastery/profile data. Transport is
  encrypted, provider retention/training/logging use is disclosed and bounded,
  consent is revocable, and request/response provenance is auditable. Dependency
  on someone else's roadmap and on network availability.
- **Do not grade** postflop multiway at all in early versions — ship
  preflop + heads-up postflop mastery only, and mark everything else
  `heuristic`. Honest, and still valuable (preflop leaks are common and
  fixable). This is the acceptable MVP floor.

Kill criterion: every trustworthy reference must be usable under rights that
match its actual delivery mode — embedding and redistribution rights for a
shipped lookup, or server-side commercial serving/derived-output rights for a
non-distributed feed. A remote feed must also pass the consent, data-minimization,
transport, retention/use, audit, revocation, and local-only fallback boundary
above. If no compliant path is available at absorbable cost, postflop mastery is
deferred and the app ships preflop-first — it is **not** faked with heuristics
dressed as solver output.

### 5.4 The `llm_advice_provider`'s correct role

Not for _choosing_ the action (that needs a solver/chart). For _explaining_ an
already-graded action in human language — generating the transferable principle
(§6.4). LLM output is a draft, not publishable teaching content. A human reviewer
must validate its range claims, causal explanation, generalization, and
consistency with solved evidence, then approve a version before it can appear in
reviews or drills. Draft, approved, superseded, and retired versions are retained
with reviewer provenance; caching is keyed by concept/taxonomy/reference and
principle version, not called live per hand.

---

## 6. The learning model (the heart of V2)

This section is the reason V2 exists. It replaces V1's flat analytics with a
mastery model over a poker skill tree.

### 6.1 Concept taxonomy (the skill tree)

A hierarchical, versioned set of poker concepts. Each concept has an id, a
context (street + situation), and a testable definition. Every decision point
maps to zero or one **primary concept**, derivable from its canonical state. A
decision must map to exactly one supported primary concept before it is eligible
for mastery or drills.

Illustrative (not exhaustive):

- **Preflop:** RFI-by-position; flat-vs-RFI; 3bet-vs-RFI; response-vs-3bet;
  blind-defense; squeeze; cold-call; short-stack shove/fold.
- **Flop:** c-bet decision; c-bet sizing by texture; defense-vs-cbet;
  check-raise; board-texture reading.
- **Turn:** barrel decision; probe; give-up; sizing-up.
- **River:** thin value; bluff selection; bluff-catching; overbet.

The taxonomy is data, not code — it is versioned and can grow. A decision that
maps to no supported concept is stored with an absent tag and does not
participate in mastery; implementations must not fabricate a catch-all concept.
Every present tag records the immutable taxonomy/mapping revision and concept
definition revision that produced it.

Active mastery for one concept series uses one pinned taxonomy revision. A
taxonomy change that alters definitions or mapping (including splits and merges)
is staged and validated, then must atomically retag all affected active decisions
and rebuild mastery, drills, principles, and proof metrics, or start clearly
separate concept series. Old and new concept semantics are never combined. Until
migration succeeds, the prior taxonomy remains active or affected decisions are
visibly excluded; historical tags and derived artifacts retain their original
revision for audit. An approved principle is usable only with the compatible
taxonomy and reference revisions against which it was reviewed.

### 6.2 Mastery state per concept

Each concept holds a mastery state derived only from that player's
`solved`-graded decisions with complete mixed-strategy policy support tagged to
it:

- **Unknown** — insufficient sample.
- **Leak** — accuracy low and EV cost material over a sufficient recent sample.
- **Practicing** — improving, or mid-range accuracy.
- **Mastered** — high accuracy over a sufficient recent sample.

Regression is allowed: a Mastered concept can fall back to Practicing/Leak if
recent play degrades. Mastery is a function of mixed-strategy-aware
supported-policy accuracy on solved-graded decisions, sample size (for
confidence), recency (recent play weighted higher), and EV-loss magnitude (a
small-but-constant error can still be a Leak).

For mixed policies, mastery also measures aggregate action/sizing frequency
calibration across sufficiently comparable decisions with versioned confidence,
sample-size, and materiality thresholds. Systematically overusing a supported
low-frequency action can block Mastered or become leak evidence without changing
the supported status of any single realization.

A **leak is a concept where the player systematically deviates from the
reference**; that is the object the app teaches against — not an individual
misplayed hand.

Recency is based on preserved source play time and stable source-session order,
not file-import time. Decisions whose play chronology is unknown remain visible
but do not support directional regression or proof-of-learning claims.

Mastery movement and regression also control for opportunity mix. Comparable
evidence is matched or standardized on versioned, predeclared route/difficulty
features such as position, effective-stack bucket, action sequence and sizings,
hand/board-strength bucket, economic/utility model, and reference/taxonomy
revisions. Raw aggregates may remain diagnostic, but an easier or materially
different mix cannot advance mastery or create a regression claim. Insufficient
overlap or excessive uncertainty leaves the directional state unchanged.

### 6.3 Prioritization

Within one comparable economic/utility stratum, leaks are ranked by **frequency
× EV cost**, so a recurring, fixable, expensive error outranks a one-off
cooler. Cash big-blind EV, tournament chip EV, ICM utility, bounty utility, and
other models are not directly comparable. Every cost retains its unit and
utility-model provenance, and the default product maintains separate priority
queues for incompatible strata. A single cross-format ranking is allowed only
when a validated, versioned normalization explicitly maps those units with
visible uncertainty; raw costs are never mixed. The actionable surface shows
the biggest leaks for the selected comparable context, each expressed as a
concept in plain language ("you defend the big blind too tight vs button
opens"), not as a hand list.

### 6.4 Feedback — elaborative, principle-first

Every reveal (in review or drill) shows, in order:

1. **The transferable principle** for that concept ("vs a tight UTG open you're
   at the top of your continuing range; 3-betting gets value from worse aces and
   denies equity").
2. **The specific evidence** for this spot (solver line, relevant range/board
   context, EV delta) — retained from V1's evidence transparency.
3. **The player's own action** and, if a study prediction exists, both.

Principles are authored per concept or begin as LLM-generated drafts (§5.4), but
only a human-reviewed, approved version can be displayed or scheduled in a
drill. Every reveal records the exact principle version so later edits do not
rewrite what the player was taught. The principle is what transfers; policy
frequencies remain supporting evidence rather than the lesson itself.

### 6.5 Drill engine — active recall

A drill is a sequence of decision points sampled from concepts in **Leak** or
**Practicing** state, prioritized by §6.3, presented as active recall:

- Replay the hand to the decision point, outcome hidden.
- Player predicts the action (and optional sizing).
- Reveal: principle → evidence → player's real table action (if imported) →
  grade.

Drills draw from the player's _own_ hands first (their real leaks), which is the
wedge incumbents are weak at, and can be topped up with library spots for the
same concept when the player's own sample is thin.

The dogfooding comprehension check draws from a versioned, blinded pool of
reviewed, solved library spots matched by concept, revisions, coverage, and
difficulty. Each attempt uses a teaching example and a fresh holdout the builder
has never attempted; the holdout and answer remain blinded until submission,
retries never reuse a prior holdout, and the pool is rotated/replenished before
exhaustion. This assessment is not a personal drill, does not assert that the
non-player has a leak, and does not update mastery or proof-of-learning metrics.

### 6.6 Spaced repetition

Missed drills re-enter a scheduler (Leitner-style boxes: correct → longer
interval, wrong → shorter). This is what converts one-time recognition into
durable skill. Scheduling is per decision-point-within-concept so the player
re-faces the exact spots they got wrong, at growing intervals.

### 6.7 Proof of learning

The app must demonstrate it taught. When new sessions import, previously flagged
leaks are re-scored against matched opportunities or a fixed, versioned
opportunity distribution. Matching/standardization controls at minimum for
position, effective-stack bucket, prior action/sizing sequence, hand/board
strength or reviewed difficulty bucket, economic/utility model, and pinned
reference/taxonomy revisions. The method, cohort/distribution revision, overlap,
effective sample size, estimate, and uncertainty interval are retained.

"Your BB-defense leak is closing" is surfaced only when a predeclared minimum
sample and uncertainty threshold show improvement on comparable opportunities.
Raw before/after accuracy remains labeled diagnostic; if overlap is insufficient,
case mix shifts materially, or the interval includes no meaningful improvement,
the app says it cannot yet tell. A concept moving Leak → Practicing → Mastered
is the headline success event, not "hands reviewed," but opportunity drift alone
cannot cause that movement. "Later" means later by preserved source hand
time/session order, never merely imported later; unknown or contradictory source
chronology cannot prove that learning occurred after a drill.

### 6.8 What V1 analytics become

V1's street/position/certainty breakdowns are not deleted — they are demoted to
_diagnostic detail underneath a concept_. Mastery over the skill tree is the
primary model; the breakdowns are drill-downs for a curious user, not the
organizing principle.

---

## 7. Kept infrastructure (from V1, retained)

- **Config-driven parser & recommendation registries**, mock providers,
  field-level confidence gating, immutable catalog descriptors.
- **Parser benchmark**: explicit ground-truth corpus, per-layout scoping,
  versioned dataset export/import, regression thresholds. Still the way OCR
  accuracy is validated through the administrator-only capture/upload test path.
- **Recommendation benchmark**: evaluation against trusted strategy references.
  In V2 this is elevated: it is the instrument that proves `solved` grading is
  actually correct, and therefore that the mastery model is measuring something
  real. It requires a trusted reference corpus (which is the same sourcing
  question as §5.3 — the benchmark measures grading quality but does not create
  the references).
- **Evidence transparency**, **backup/restore with checksums**, **failure
  isolation**.

---

## 8. Deferred (post-validation hardening)

Not built until the learning model is validated on a real user:

- MCP agent gateway (staging/production, credentials, scopes).
- Deployment monitoring / scheduled probes.
- Resource rate limiting.
- Runtime error reporting.

These are correct for a shipped multi-tenant service and wrong for an unvalidated
single-user learning tool. Their presence in V1 is scope run ahead of proof.

---

## 9. Phased build plan (gated)

**Phase 0 — foundations and safety (two parallel spikes, two prerequisites, one
shared gate)**

- _Import spike:_ PokerStars adapter → detected hand → user-approved canonical
  hand → decision extraction. Kill criterion: ≥99% clean parse **with pot
  reconciliation passing** on ~1,000 real hands; non-pot fields are verified
  against ground truth, voluntary/automatic action origin is verified, source
  time/order is preserved, and positions are verified including heads-up and
  sit-out cases.
- _Grading spike:_ source and benchmark an independently solved preflop policy;
  the retained V1 heuristic chart is not eligible. Resolve §5.3 for postflop
  (precompute / license / defer). Kill criterion: obtain `solved` references
  you'd stake the product on, at absorbable cost, with rights matching the
  actual delivery mode (embedding/redistribution for shipped lookups or
  commercial serving/derived-output rights for server-only feeds), immutable
  policy revisions, complete mixed-strategy support, and declared
  table-size/position and cash/tournament economic assumptions. Any server-only
  feed must also pass the explicit-consent and minimized outbound-data boundary
  in §5.3 while preserving a local-only mode. If preflop sourcing fails, the
  teaching loop does not have a trustworthy MVP grading floor.
- _Safety prerequisite:_ before any Phase 1 user validation, remove screenshot
  upload, live window/screen/tab capture, and recommendation automation from the
  player workflow. Preserve capture/upload only in the disabled-by-default,
  server-authorized administrative OCR test context defined by §3.4. Kill
  criterion: player UI and direct API attempts cannot invoke capture/upload or
  transition an administrative test input into recommendation or learning state.
- _Local-delivery prerequisite:_ package and validate the co-located player PWA,
  API, persistence, backup/restore, and upgrade path defined by §3.5. Kill
  criterion: V2 imports and all player/learning records stay on the player
  machine; the deployed Worker/hosted backend cannot receive them, including by
  direct network/API attempts. The local service is loopback-only and authenticated;
  LAN/non-loopback, disallowed Host/Origin, unauthenticated, and forged
  state-changing requests are denied. The optional minimized remote solver
  request is tested separately under explicit consent.

Neither the learning model nor player validation starts until the two viability
spikes and both prerequisites clear. A failed viability gate kills or reshapes
the product; a failed safety or local-delivery prerequisite blocks Phase 1.

**Phase 1 — minimum teaching loop (preflop-first)**

- Import → review/correction → approved canonical hand → decision points →
  input-verified `solved` grading (independently sourced preflop and eligible HU
  postflop only) → versioned concept tagging → leak detection → principle
  feedback → active-recall drill → spaced repetition.
- Tested on the two-person dogfooding pair (Target user & boundaries §): the
  poker-player friend for grading correctness, the non-player builder for
  comprehensibility through the blinded solved-library transfer assessment.
- Success metric (**both required**): (a) on a real session the app surfaces a
  leak the friend did not already know he had ("huh, I do that?"), and after
  drilling a _later_ session shows that leak measurably closing on a matched or
  opportunity-standardized cohort with sufficient overlap/sample and a retained
  uncertainty interval; **and** (b) the non-player builder can explain one taught
  principle in plain language and apply it correctly to a fresh blinded
  solved-library holdout for the same concept. Every retry uses a holdout they
  have never attempted. The builder's assessment does not create a leak or
  mastery record. If (a) fails, grading or the mastery model is unproven; if (b)
  fails, the teaching is unproven — and no amount of UI polish fixes either.

**Phase 2 — breadth**

- More site adapters (Winamax, then 888/party/iPoker/ACR; GG last).
- Postflop mastery if §5.3 delivered it.
- Study-prediction vs table-action divergence (§4) as a first-class view.

**Phase 3 — hardening**

- The deferred infrastructure from §8, only if there is a real deployment need.

---

## 10. Success criteria (reframed around learning)

Poker Hero V2 is successful when:

- A player can import a session, review/correct detected state, approve canonical
  hands, and get decision points with real actions, with no screenshot upload or
  live-capture capability in the player experience.
- Exact/overlapping reimports are idempotent, conflicts require explicit
  resolution, and reapproval atomically replaces all active derived learning
  state from the superseded hand revision.
- Screenshot upload and live screen/window/tab capture remain available only in
  disabled-by-default administrative test mode, with server-enforced
  authorization and no path to recommendations, mastery, drills, or player
  learning data.
- Grading is honest: every decision shows whether it was `solved` or
  `heuristic`; solved grades preserve mixed-strategy policy support; and
  economic-context mismatches, heuristic results, or policy-incomplete decisions
  never move mastery or generate drills. Active mastery never mixes reference
  or taxonomy revisions, and assumed solver inputs never qualify as verified.
- The app identifies **concept-level leaks** (recurring, EV-ranked), not just
  per-hand errors.
- Feedback teaches a **transferable principle**, verifiable by the player
  applying it to a new, unseen spot for the same concept; every displayed
  principle is human-reviewed, approved, and versioned.
- All grades, recommendations, principles, mastery states, and drills are framed
  as conditional educational reference guidance, never guaranteed optimal play
  or guaranteed outcomes.
- The player can **drill their own leaks** via active recall, with missed spots
  spaced-repeated.
- The app **proves it taught**: a previously flagged leak is re-measured on later
  matched/standardized opportunities with uncertainty and shown closing, not
  closing, or not yet measurable.
- OCR can be validated by administrators through isolated screenshot upload and
  live capture without exposing those inputs as a player workflow.
- The parser and recommendation benchmarks demonstrate that grading is accurate
  enough to trust the mastery model.

Not a success criterion: number of features, number of analytics breakdowns, or
number of hands processed. Those are V1's metrics. V2's metric is **leaks
closed.**

---

## Appendix A — open questions carried into Phase 0

- Postflop reference sourcing (§5.3): precompute vs license vs defer — this is
  the single biggest unresolved decision and should be answered before any
  postflop learning work.
- Concept taxonomy authorship: who writes the principle library per concept, and
  is the initial pass authored or LLM-generated-then-reviewed?
- Mastery thresholds: exact sample sizes and accuracy cutoffs for
  Unknown/Leak/Practicing/Mastered need calibration against the friend's real
  data, not guessed up front.
