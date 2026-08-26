# Poker Hero — Specification V2

Status: current source of truth (supersedes V1)

Delivery is tracked by the [V2 roadmap issue](https://github.com/Studio81Labs/poker-hero/issues/404)
and its linked Phase [0](https://github.com/Studio81Labs/poker-hero/issues/405),
[1](https://github.com/Studio81Labs/poker-hero/issues/406),
[2](https://github.com/Studio81Labs/poker-hero/issues/407), and
[3](https://github.com/Studio81Labs/poker-hero/issues/408) epics.

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

The reference for grading remains solver/chart (§5); there is no other source of
truth about the correct action, and that inherently assumes a player who knows
the vocabulary. What the primary-user choice adds is a **pedagogical / onboarding
layer on top of the existing model**: the app teaches its own vocabulary
progressively (what a 3-bet is, position, range, EV), principle-first (§6.4), and
throttles density so the studying-but-not-expert user is never drowned in EV-loss
decimals. It is a layer over the skill tree, not a second skill tree.

### Consequence for validation (the dogfooding pair)

The builder is not a poker player. This is an asset, not a gap: it produces an
ideal two-person test pair that is otherwise hard to assemble.

- The **poker-player friend** validates that grading is _correct_ — that what the
  app calls a leak is genuinely a leak.
- The **non-player builder** validates that the teaching is _comprehensible_ —
  using a fixed assessment of reviewed, solved library spots. The builder first
  receives the principle-first explanation for one concept, then predicts the
  action in a new, unseen spot for that concept and explains the principle back
  in plain language.

If the app can teach the non-player builder, that is the strongest possible proof
it teaches. Phase 1 success (§9) therefore requires **both**: the friend finds a
real leak he didn't know he had, _and_ the non-player builder passes the fixed
library-based transfer assessment. Because the builder has no imported playing
history, this assessment does not claim to detect a personal leak, update mastery,
or contribute to proof-of-learning metrics.

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
- **Learning lives in aggregation and repetition, not in single hands.** The
  single-hand comparison is necessary but weak on its own. Value comes from
  detecting _recurring_ leaks and _drilling_ them.
- **The player predicts before the answer is revealed.** Active recall is the
  strongest lever available and is preserved even for imported hands.
- **The app must prove it taught.** Previously flagged leaks are re-measured on
  new sessions. "This leak is closing" is the core success signal, surfaced to
  the user.
- **Local-first, single-user.** No account system, no multi-tenant assumptions
  in the core. The player's data stays on their machine.
- **Capture is an operator capability, not a player feature.** In a local-first
  deployment, "administrator" means an explicitly authorized operator/tester,
  not an implicit role granted to every local user. Screenshot upload and live
  capture fail closed when the administrative test mode is disabled or the
  caller is unauthorized.

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
  provenance, game type, stakes, table size, blinds/antes. Missing source time
  remains explicitly unknown; ingestion time must not stand in for play time in
  recency, session, or proof-of-learning calculations.
- Button seat.
- Seats: for each, seat number, starting stack, and participation status
  (including dealt-in and sitting-out/not-dealt states). **Derived position**
  (UTG/MP/CO/BTN/SB/BB) is assigned only to dealt-in players and is computed from
  their action ring around the button; seated players who were not dealt in never
  shift another player's position. The heads-up special case (button = SB) is
  handled explicitly.
- Hero identity and hero hole cards (from the "dealt to" line).
- Streets: for each of preflop/flop/turn/river, the board cards and an **ordered
  action list** (actor, action type, total committed).
- Showdown and results.

**Identity and re-import semantics:** `(site, source hand id)` is the stable hand
identity unless a site adapter documents a stronger versioned namespace for a
format whose hand ids are not site-unique. Overlapping files and exact reimports
resolve to the existing hand and do not create a second canonical record,
decision, grade, mastery sample, or drill. Import attempts and source-file
provenance may be appended for audit without multiplying learning data. If the
same stable identity arrives with materially different source or detected
content, both inputs are preserved as a conflict for explicit user resolution;
neither silently overwrites the active approved revision or counts twice.

**Correctness oracle:** re-derive the pot from the action stream and reconcile
against the file's stated pot (accounting for rake, uncalled bets, side pots).
Independently-computed pot == stated pot is a per-hand pass/fail that validates
the action/amount parse without manual eyeballing. It is necessary but not
sufficient: a wrong button, hero identity, card, timestamp, or participation
status can reconcile the pot and still corrupt grading.

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
the new revision fails, the hand is visibly pending/failed and no stale artifact
from the prior revision may remain in learning state; unrelated hands continue
independently.

### 3.3 Decision extraction

The learning system does not consume hands — it consumes **decision points**.
From a user-approved canonical hand, extract each hero decision as:

- The canonical decision state (everything the recommendation provider needs).
- The **actual action taken** (from the history — this is the key gift of
  import: the real decision is already known).
- The **concept tag** (§6.1), derivable from the state.

One approved imported hand yields zero or more decision points (preflop, flop,
turn, river). A valid no-decision hand, such as a big-blind walk, is retained with
its provenance and an explicit no-decision outcome; it is not failed, graded, or
given a fabricated action. A real decision point is the atomic unit for grading,
mastery, and drilling.

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

This boundary preserves recognition development without exposing a workflow
that could be used as real-time poker assistance. Authorization must be enforced
by the backend/Worker boundary; frontend visibility alone is insufficient.

---

## 4. The player's real action vs. the study prediction

Import gives the real table decision. But the strongest learning lever is
_active recall_, so V2 captures up to two signals per decision point:

- **Table action** — what the player actually did, live, under real conditions
  (from the imported history).
- **Study prediction** (optional) — in drill/replay mode the hand is replayed to
  a decision point with the outcome hidden, and the player predicts what they'd
  do now, in calm study conditions.

The divergence between them is itself a lesson: "at the table you flatted; in
study you say 3-bet, and 3-bet is right — you know this, it escaped you live."
That gap distinguishes a _knowledge_ leak (you don't know the right play) from an
_execution_ leak (you know it but miss it in the moment), and they need different
remedies. This is richer than V1's single locked answer and is a core V2
capability.

---

## 5. Recommendation & grading model

Grading is what tells a decision "right" or "wrong." Its trustworthiness is the
ceiling on learning quality, so it is treated as first-class.

### 5.1 Coverage, stated honestly

- **Preflop** — solved and cheap. Position-aware charts (RFI, vs-RFI, vs-3bet,
  blind defense, squeeze, cold-call, short-stack) with explicit stack-depth
  bands and sizing boundaries. This is trustworthy grading. (V1's extensive
  preflop routing is retained here.)
- **Heads-up postflop** — solved trees, where reviewed history resolves an exact
  supported line. Trustworthy.
- **Multiway postflop** — _not_ solved. Currently a range/EV heuristic. This is
  the largest gap and covers a large share of real hands.

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
and the versioned material-frequency/EV tolerance used to decide support. The
player's action is a supported policy match when it has meaningful reference
frequency or is within the accepted EV-equivalence tolerance, even when it is
not the solver's headline action. Such a mixed-strategy alternative is not a
mistake and cannot create a leak or corrective drill.

Only an action outside the complete solved policy support can be called a
mistake and contribute an error to mastery. If the reference response omits the
policy detail needed to distinguish a supported mix from an error, the decision
remains visible as solved evidence but ungraded for mastery and drills. Aggregate
frequency adherence may be shown as diagnostic detail, but it does not
retroactively turn an individually supported action into a mistake.

This directly prevents the app from teaching wrong things. A player can never
have a leak "detected" or drilled on the basis of a guess. It also makes the
product honest about its own boundaries, which a study tool must be.

### 5.3 Sourcing the postflop gap (the open kill-criterion)

Preflop is settled. The multiway-postflop reference is the Phase-0 question that
gates whether the mastery model covers postflop at all:

- **Precompute** a bounded, high-value set of postflop solutions once (owned
  license), ship as static lookup — the same model serious tools use (preflop
  from HRC/Monker-class tools, postflop from Pio-class). Preferred if a bounded
  set covers enough real spots.
- **License** a solved-data feed. Dependency on someone else's roadmap.
- **Do not grade** postflop multiway at all in early versions — ship
  preflop + heads-up postflop mastery only, and mark everything else
  `heuristic`. Honest, and still valuable (preflop leaks are common and
  fixable). This is the acceptable MVP floor.

Kill criterion: if trustworthy postflop references cannot be obtained at
absorbable cost under a license permitting commercial serving of the outputs,
postflop mastery is deferred and the app ships preflop-first — it is **not**
faked with heuristics dressed as solver output.

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
maps to exactly one **primary concept**, derivable from its canonical state.

Illustrative (not exhaustive):

- **Preflop:** RFI-by-position; flat-vs-RFI; 3bet-vs-RFI; response-vs-3bet;
  blind-defense; squeeze; cold-call; short-stack shove/fold.
- **Flop:** c-bet decision; c-bet sizing by texture; defense-vs-cbet;
  check-raise; board-texture reading.
- **Turn:** barrel decision; probe; give-up; sizing-up.
- **River:** thin value; bluff selection; bluff-catching; overbet.

The taxonomy is data, not code — it is versioned and can grow. A decision that
maps to no supported concept is stored but does not participate in mastery.

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

A **leak is a concept where the player systematically deviates from the
reference**; that is the object the app teaches against — not an individual
misplayed hand.

Recency is based on preserved source play time and stable source-session order,
not file-import time. Decisions whose play chronology is unknown remain visible
but do not support directional regression or proof-of-learning claims.

### 6.3 Prioritization

Leaks are ranked by **frequency × EV cost**, so a recurring, fixable, expensive
error outranks a one-off cooler. The primary actionable surface is "your biggest
leaks right now," each expressed as a concept in plain language ("you defend the
big blind too tight vs button opens"), not as a hand list.

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

The dogfooding comprehension check uses a fixed pair of reviewed, solved library
spots for one concept: one teaching example and one unseen transfer question.
This assessment is not a personal drill, does not assert that the non-player has
a leak, and does not update mastery or proof-of-learning metrics.

### 6.6 Spaced repetition

Missed drills re-enter a scheduler (Leitner-style boxes: correct → longer
interval, wrong → shorter). This is what converts one-time recognition into
durable skill. Scheduling is per decision-point-within-concept so the player
re-faces the exact spots they got wrong, at growing intervals.

### 6.7 Proof of learning

The app must demonstrate it taught. When new sessions import, previously flagged
leaks are re-scored and the trend is surfaced: "Your BB-defense leak is closing
— accuracy 61% → 78% over your last 200 hands." A concept moving Leak →
Practicing → Mastered is the headline success event, not "hands reviewed." This
closes the loop that V1 never had. "Later" means later by preserved source hand
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

**Phase 0 — foundations and safety (two parallel spikes, one shared gate)**

- _Import spike:_ PokerStars adapter → detected hand → user-approved canonical
  hand → decision extraction. Kill criterion: ≥99% clean parse **with pot
  reconciliation passing** on ~1,000 real hands; non-pot fields are verified
  against ground truth, source time/order is preserved, and positions are
  verified including heads-up and sit-out cases.
- _Grading spike:_ confirm trustworthy references. Preflop charts in hand.
  Resolve §5.3 for postflop (precompute / license / defer). Kill criterion:
  obtain `solved` references you'd stake the product on, at absorbable cost,
  under a license permitting commercial serving of outputs — or consciously ship
  preflop-first.
- _Safety prerequisite:_ before any Phase 1 user validation, remove screenshot
  upload, live window/screen/tab capture, and recommendation automation from the
  player workflow. Preserve capture/upload only in the disabled-by-default,
  server-authorized administrative OCR test context defined by §3.4. Kill
  criterion: player UI and direct API attempts cannot invoke capture/upload or
  transition an administrative test input into recommendation or learning state.

Neither the learning model nor player validation starts until the two viability
spikes and the safety prerequisite clear. A failed viability gate kills or
reshapes the product; a failed safety prerequisite blocks Phase 1.

**Phase 1 — minimum teaching loop (preflop-first)**

- Import → review/correction → approved canonical hand → decision points →
  `solved` grading (preflop + HU postflop) → concept tagging → leak detection →
  principle feedback → active-recall drill → spaced repetition.
- Tested on the two-person dogfooding pair (Target user & boundaries §): the
  poker-player friend for grading correctness, the non-player builder for
  comprehensibility through the fixed solved-library transfer assessment.
- Success metric (**both required**): (a) on a real session the app surfaces a
  leak the friend did not already know he had ("huh, I do that?"), and after
  drilling a _later_ session shows that leak measurably closing; **and** (b) the
  non-player builder can explain one taught principle in plain language and apply
  it correctly to the fixed new, unseen solved-library spot for the same concept.
  The builder's assessment does not create a leak or mastery record. If (a)
  fails, grading or the mastery model is unproven; if (b) fails, the teaching is
  unproven — and no amount of UI polish fixes either.

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
  heuristic or policy-incomplete decisions never move mastery or generate
  drills.
- The app identifies **concept-level leaks** (recurring, EV-ranked), not just
  per-hand errors.
- Feedback teaches a **transferable principle**, verifiable by the player
  applying it to a new, unseen spot for the same concept; every displayed
  principle is human-reviewed, approved, and versioned.
- The player can **drill their own leaks** via active recall, with missed spots
  spaced-repeated.
- The app **proves it taught**: a previously flagged leak is re-measured on later
  sessions and shown closing (or not).
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
