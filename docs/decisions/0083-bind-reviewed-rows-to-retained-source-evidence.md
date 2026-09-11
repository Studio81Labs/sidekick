# ADR 0083: Bind Reviewed Rows to Retained Source Evidence

Status: accepted; implementation required in #533 before #531 can merge

Date: 2026-09-11

## Context

Epic #405 and ADR 0082 require structured correction of recorded hands, including
added, removed and reordered action/result rows. #527 V1 is merged in #530 at
`c9fc364b2a6b8ef154e2a9145c78edb39e613ccd`. PR #531 implements the V2 editor.
Escalation #532 and reviews 3991376859/3991548681 expose a backend assumption
that prevents both genuinely added rows and removal of erroneous parsed rows.

`canonical_revision_from_review` calls `_preserve_review_excerpts` before
canonical validation. Its list matcher consumes detected items one-to-one and
requires every item with a private excerpt to survive in the reviewed list.
A new row cannot acquire its own correspondence, and an omitted row fails the
survival check. The same helper reconstructs visible corrections in
`_validate_corrections_win`, so bypassing it only in HTTP preview would produce
records that cannot subsequently validate. The browser has only sanitized
locators and must not supply or recreate hidden excerpts.

This is a provenance-restoration limitation, not evidence that the approved
product should forbid correcting parser omissions or extra rows. The raw source,
detection and earlier canonical revisions already retain the discarded proposal.

## Decision

Keep added and removed rows in the review MVP. Separate **source-reference
identity** from **row identity**: several reviewed facts may cite the same source
location. Resolve those references on the server against one immutable selected
detection; do not make a source locator a consumable row token or proof that the
parser emitted the reviewed fact.

Implement this in [#533](https://github.com/Studio81Labs/sidekick/issues/533)
(V2a), then integrate and finish #527 V2 in #531. The exact execution handoff is
[#496](https://github.com/Studio81Labs/sidekick/issues/496); the persistent
technical plan is [#405](https://github.com/Studio81Labs/sidekick/issues/405#technical-implementation-plan).

### Binding algorithm

1. Under the existing selected-detection and complete-record preconditions,
   construct a server-owned pool from `DetectedImportedHand.state` evidence and
   `DetectedImportedHand.field_evidence`. Use the typed evidence sites already
   enumerated by `_state_source_evidence` / `_detected_source_evidence`. Do not
   include other detections, other hands, editable drafts or arbitrary client
   dictionaries. The validated detection binds all pool entries to its one
   retained raw source; retain raw line-range and substring validation.
2. A locator key is the exact typed tuple
   `(raw_source_id, line_start, line_end, marker)`. Validate submitted scalar types
   before lookup, including rejection of booleans as line numbers. Preserve null
   versus non-null and exact marker/span values; do not equate missing end with
   an explicit end or use delimiter-joined strings, fuzzy spans or partial keys.
   The frontend may encode the tuple as a JSON array for collision-safe keys.
3. Preserve safe existing-row restoration: a unique existing correspondence may
   retain its occurrence-specific excerpt. An unchanged list's exact visible
   positional correspondence may retain its previous mapping. A changed or
   reordered ambiguous list cannot use traversal order or an index guess to
   select different hidden values. Do not reject safe unchanged current-format
   records merely because another occurrence has the same visible locator.
4. For a new or rebound evidence site without a safe existing correspondence,
   require a line or marker in its public locator and one **distinct excerpt
   value** in the authoritative pool for that exact key. Identical occurrences
   of the same key and same excerpt, including null, collapse to one value and
   may be reused without consuming one another. Different hidden values for the
   same key are ambiguous and must be rejected for a new binding. An excerpt-only
   locator with neither visible line nor marker cannot authorize a new binding.
5. Restore a deep copy of the retained server evidence at every actual canonical
   evidence site: action evidence, action-origin evidence, showdown evidence and
   award evidence. Handle previously absent result sections, empty lists and
   lists without prior private excerpts. Reject any client `excerpt` key, even
   null, unknown/foreign keys or unresolved ambiguity. Preserve the exact server
   excerpt; never trim, concatenate, regenerate or take it from another row by
   position. All public locator fields must be accounted for rather than silently
   overwritten with a convenient pool entry.
6. A removed row or optional section requires no surviving canonical placeholder
   for its evidence. Keep the immutable raw source, detection and prior revision
   audit; derive the normal non-overlapping, excerpt-free corrections against
   the detection and require a reason. Structural list changes may use the
   existing list/parent correction representation. Source preservation does not
   mean the active canonical record must keep an erroneously parsed fact.
7. Run the unchanged full hand/card/action/result, source-line, correction and
   aggregate lifecycle validation after restoration. A locator's existence
   proves where the reviewer associated a correction, not that the selected
   text establishes the asserted poker fact or an independently verified winner.
   Missing suitable retained evidence remains an explicit invalid correction;
   this decision does not add arbitrary raw-line selection or free-text evidence.

### Shared validation, persistence and privacy

Use one pure resolver in canonical preparation and the visible-correction
reconstruction in `_validate_corrections_win`. Preview, direct approval, exact
retry, reread/reparse and backup/restore must agree on the same canonical bytes.
Do not create an HTTP-only bypass or a new permissive raw-correction branch.
Keep existing valid current-format behavior and existing private-source checks;
a discovered need to change historical format validity requires escalation.

No new API endpoint, request/response field, server-issued token, persisted row
ID or mapping table is needed. The selected detection ID, existing record
preconditions and full reviewed state already supply the authority scope.
Canonical evidence plus the immutable detection and server-owned corrections
retain the resulting association for audit/reconstruction. Workspace layout 6
and backup schema 4 remain unchanged. No migration, legacy fallback or data
rewrite is authorized.

Preview remains read-only under its existing locks. Approval retains its full
precondition, conflict, deletion/recovery, retry and atomic cascade behavior.
Neither the client nor an error/preview/correction projection receives private
excerpts. Invalid bindings return the existing safe invalid-review response,
with a useful field pointer where available and no source values in error text.

### Action origin remains a separate invariant

Do not reuse source-reference matching as action-confirmation matching.
`_validate_user_confirmed_origin_corrections` and
`_detected_action_for_review_confirmation` still require an unambiguous
corresponding **detected unknown/unresolved action**, a real correction and a
review reference. A cloned locator must not manufacture that correspondence.
A genuinely added table action without it remains unknown/unresolved. Forced
posts/returns use the existing forced/system model and no inferred confidence or
voluntary attestation. Reuse cannot copy positive origin, semantics revisions or
automatic reasons onto a new fact.

The fresh #531 origin-controls finding needs this distinction: any non-forced
action may be explicitly corrected to unknown/unresolved; confirmation as
`user_confirmed` is available only when the existing detected-action invariant
permits it. An originally automatic or positively classified detection cannot
be converted to `user_confirmed` by a type round trip or a second approval.
Keep the original assertion in detection audit and explain the unresolved
canonical state. Broader positive-origin override needs its own product/domain
decision, not an implicit change in this provenance repair.

### Frontend and validation obligations

#531 must select from the immutable detection's sanitized state/field-evidence
options, not from the edited draft as authority. New rows require an explicit
binding choice; do not auto-select a nearby locator. A missing usable option is
visible. Display user correction/association separately from parser evidence;
never present the new row as parser-confirmed. Use the current server preview
and explicit approval, with existing draft/source/session fencing.

#533 must test realistic private-excerpt additions, removals, reordering and
previously absent/empty lists through preview, direct approval, persisted record
validation, reapproval/retry and backup/restore. Cover shared identical bindings,
field-evidence-only bindings, distinct-value ambiguity, unchanged safe mappings,
malformed scalar types/key collisions, absent/foreign keys, client excerpt keys,
invalid poker state, missing reason, stale/concurrent/deletion/recovery cases
and attempts to obtain user-confirmed origin through copied evidence. Verify
unchanged raw/detection bytes, excerpt-free corrections/responses and no preview
writes. #531 then needs real backend-plus-UI tests for the added/removed rows;
a mocked `valid:true` response is insufficient.

## Alternatives rejected

- Restrict review to existing rows: silently reduces the approved correction
  outcome and also leaves erroneously parsed extra rows uncorrectable.
- Restore excerpts in the browser, omit them, or relax validation only in
  preview: loses private provenance or creates records that fail later reads.
- Treat every locator as single-use: confuses a source citation with a row and
  blocks legitimate multiple facts linked to the same location.
- Accept any same-source span or choose the first hidden match: invents a source
  association and hides ambiguity.
- Add server-issued binding IDs/new API or persistence: unnecessary for the
  bounded retained-locator scope; exact immutable keys plus existing revision
  preconditions suffice. A future raw-line evidence browser is separate work.
- Weaken action-confirmation identity along with excerpt restoration: changes
  the voluntary-learning invariant and is unnecessary for ungraded review.

## Execution and supersession

This ADR supersedes ADR 0056's one-to-one/survival requirement only for canonical
row evidence restoration; its private-source ownership, audit, confirmation and
atomic approval requirements remain. It refines ADR 0082 without changing its
review product scope, fee boundary or deferred learning status.

Execution remains **SERIAL**, maximum one implementation writer/merge-bound PR:
architecture documentation → #533 backend V2a → rebase/finish #531 (#527 V2) →
#528 U1. #409 evidence and #414 release requirements are unchanged. Closing #532
resolves the design, not the implementation defect. #531 must not merge until
#533 is integrated, its real-backend validation passes and all actionable
review findings are addressed. Do not mark #527 or the Epic complete here.
