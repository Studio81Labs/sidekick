import { useRef, useState, type ChangeEvent } from "react";

import type {
  ImportedHandCard,
  ImportedHandSourceEvidence,
  ImportedHandState,
} from "./playerApi";
import { sourceEvidenceKey, uniqueSourceEvidence } from "./reviewEvidence";

type Street = ImportedHandState["streets"][number]["street"];
type Action = ImportedHandState["streets"][number]["actions"][number];
type Seat = ImportedHandState["seats"][number];
type ReviewError = { pointer: string; message: string };

const CARD_RANKS = [
  "2",
  "3",
  "4",
  "5",
  "6",
  "7",
  "8",
  "9",
  "T",
  "J",
  "Q",
  "K",
  "A",
];
const CARD_SUITS = [
  { value: "clubs", label: "clubs (c)" },
  { value: "diamonds", label: "diamonds (d)" },
  { value: "hearts", label: "hearts (h)" },
  { value: "spades", label: "spades (s)" },
] as const;
const STREETS: Street[] = ["preflop", "flop", "turn", "river"];
const ACTION_TYPES: Action["action_type"][] = [
  "post_ante",
  "post_small_blind",
  "post_big_blind",
  "post_straddle",
  "fold",
  "check",
  "bet",
  "call",
  "raise",
  "uncalled_return",
];
const FORCED_ACTION_TYPES: readonly Action["action_type"][] = [
  "post_ante",
  "post_small_blind",
  "post_big_blind",
  "post_straddle",
  "uncalled_return",
];
const REVIEW_SOURCE_LINE_MARKER = "review-source-line/v1";

function readable(value: string): string {
  return value.replace(/_/g, " ");
}

function cloneState(state: ImportedHandState): ImportedHandState {
  return structuredClone(state);
}

function parseInteger(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

function nullableText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function clearDerivedPositions(state: ImportedHandState): void {
  state.seats = state.seats.map((seat) => ({ ...seat, position: null }));
}

function resequence(actions: Action[]): Action[] {
  return actions.map((action, sequence) => ({ ...action, sequence }));
}

function correctedOriginForActionType(
  action: Action,
  actionType: Action["action_type"],
): Action["origin"] {
  if (FORCED_ACTION_TYPES.includes(actionType)) {
    if (action.origin.kind === "forced_system") return action.origin;
    return {
      ...action.origin,
      kind: "forced_system",
      basis: "explicit_marker",
      confidence: null,
      semantics_revision: null,
      automatic_reason: null,
      review_reference: null,
    };
  }
  if (action.origin.kind !== "forced_system") return action.origin;
  return {
    ...action.origin,
    kind: "unknown",
    basis: "unresolved",
    confidence: null,
    semantics_revision: null,
    automatic_reason: null,
    review_reference: null,
  };
}

function actionConfirmationKey(streetIndex: number, action: Action): string {
  return JSON.stringify([
    streetIndex,
    action.actor_id,
    action.action_type,
    action.amount,
    action.total_committed,
    action.all_in,
    action.evidence.map(sourceEvidenceKey),
    action.origin.kind,
    action.origin.basis,
    action.origin.confidence,
    action.origin.evidence.map(sourceEvidenceKey),
    action.origin.semantics_revision,
    action.origin.automatic_reason,
    action.origin.review_reference,
  ]);
}

function errorFor(errors: readonly ReviewError[], path: string): string | null {
  const matches = errors.filter(
    (error) =>
      error.pointer === path || error.pointer === `/approved_state${path}`,
  );
  return matches.length === 0
    ? null
    : matches.map((error) => error.message).join(" ");
}

function FieldError({
  errors,
  path,
}: {
  errors: readonly ReviewError[];
  path: string;
}): JSX.Element | null {
  const message = errorFor(errors, path);
  return message ? <p className="review-field-error">{message}</p> : null;
}

function TextField({
  label,
  value,
  onChange,
  disabled,
  errors = [],
  path,
  placeholder,
  clearable = true,
}: {
  label: string;
  value: string | null;
  onChange: (value: string | null) => void;
  disabled: boolean;
  errors?: readonly ReviewError[];
  path: string;
  placeholder?: string;
  clearable?: boolean;
}) {
  const error = errorFor(errors, path);
  return (
    <label className="review-field">
      <span>{label}</span>
      <span className="review-input-row">
        <input
          aria-label={label}
          aria-invalid={error ? true : undefined}
          disabled={disabled}
          placeholder={placeholder ?? "Not recorded"}
          type="text"
          value={value ?? ""}
          onBlur={() => onChange(nullableText(value ?? ""))}
          onChange={(event) =>
            onChange(event.target.value === "" ? null : event.target.value)
          }
        />
        {clearable ? (
          <button
            disabled={disabled || value === null}
            type="button"
            onClick={() => onChange(null)}
          >
            Clear
          </button>
        ) : null}
      </span>
      <FieldError errors={errors} path={path} />
    </label>
  );
}

function DecimalField({
  label,
  value,
  onChange,
  disabled,
  errors = [],
  path,
}: Omit<Parameters<typeof TextField>[0], "placeholder">) {
  const error = errorFor(errors, path);
  return (
    <label className="review-field">
      <span>{label}</span>
      <span className="review-input-row">
        <input
          aria-label={label}
          aria-invalid={error ? true : undefined}
          disabled={disabled}
          inputMode="decimal"
          placeholder="Not recorded"
          type="text"
          value={value ?? ""}
          onChange={(event) => onChange(nullableText(event.target.value))}
        />
        <button
          disabled={disabled || value === null}
          type="button"
          onClick={() => onChange(null)}
        >
          Clear
        </button>
      </span>
      <span className="field-help">
        Exact decimal text is retained; no rounding is applied in the browser.
      </span>
      <FieldError errors={errors} path={path} />
    </label>
  );
}

function IntegerField({
  label,
  value,
  onChange,
  disabled,
  errors = [],
  path,
  positive = false,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  disabled: boolean;
  errors?: readonly ReviewError[];
  path: string;
  positive?: boolean;
}) {
  const error = errorFor(errors, path);
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const parsed = parseInteger(event.target.value);
    if (event.target.value.trim() === "") onChange(null);
    else if (parsed !== null && (!positive || parsed > 0)) onChange(parsed);
  };
  return (
    <label className="review-field">
      <span>{label}</span>
      <span className="review-input-row">
        <input
          aria-label={label}
          aria-invalid={error ? true : undefined}
          disabled={disabled}
          inputMode="numeric"
          min={positive ? 1 : 0}
          type="number"
          value={value ?? ""}
          onChange={handleChange}
        />
        <button
          disabled={disabled || value === null}
          type="button"
          onClick={() => onChange(null)}
        >
          Clear
        </button>
      </span>
      <FieldError errors={errors} path={path} />
    </label>
  );
}

function SelectField({
  label,
  value,
  options,
  onChange,
  disabled,
  errors = [],
  path,
  unknownLabel = "Not recorded",
}: {
  label: string;
  value: string | null;
  options: readonly string[];
  onChange: (value: string | null) => void;
  disabled: boolean;
  errors?: readonly ReviewError[];
  path: string;
  unknownLabel?: string;
}) {
  const error = errorFor(errors, path);
  return (
    <label className="review-field">
      <span>{label}</span>
      <select
        aria-label={label}
        aria-invalid={error ? true : undefined}
        disabled={disabled}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value || null)}
      >
        <option value="">{unknownLabel}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {readable(option)}
          </option>
        ))}
      </select>
      <FieldError errors={errors} path={path} />
    </label>
  );
}

function CardList({
  label,
  cards,
  onChange,
  disabled,
  maximum = 5,
  path,
}: {
  label: string;
  cards: ImportedHandCard[];
  onChange: (cards: ImportedHandCard[]) => void;
  disabled: boolean;
  maximum?: number;
  path: string;
}) {
  return (
    <fieldset className="review-field card-list">
      <legend>{label}</legend>
      {cards.map((card, index) => (
        <div
          className="review-input-row"
          key={`${path}-${index}-${card.rank}-${card.suit}`}
        >
          <select
            aria-label={`${label} ${index + 1} rank`}
            disabled={disabled}
            value={card.rank}
            onChange={(event) => {
              const next = [...cards];
              next[index] = { ...card, rank: event.target.value };
              onChange(next);
            }}
          >
            {CARD_RANKS.map((rank) => (
              <option key={rank} value={rank}>
                {rank}
              </option>
            ))}
          </select>
          <select
            aria-label={`${label} ${index + 1} suit`}
            disabled={disabled}
            value={card.suit}
            onChange={(event) => {
              const next = [...cards];
              next[index] = { ...card, suit: event.target.value };
              onChange(next);
            }}
          >
            {CARD_SUITS.map((suit) => (
              <option key={suit.value} value={suit.value}>
                {suit.label}
              </option>
            ))}
          </select>
          <button
            disabled={disabled}
            type="button"
            onClick={() =>
              onChange(cards.filter((_, itemIndex) => itemIndex !== index))
            }
          >
            Remove card
          </button>
        </div>
      ))}
      <button
        disabled={disabled || cards.length >= maximum}
        type="button"
        onClick={() => onChange([...cards, { rank: "A", suit: "spades" }])}
      >
        Add card
      </button>
      <span className="field-help">
        No cards is an explicit unknown or absent card record.
      </span>
    </fieldset>
  );
}

function DecimalList({
  label,
  values,
  onChange,
  disabled,
  errors = [],
  path,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
  disabled: boolean;
  errors?: readonly ReviewError[];
  path: string;
}) {
  return (
    <fieldset className="review-field">
      <legend>{label}</legend>
      {values.map((value, index) => {
        const itemPath = `${path}/${index}`;
        const error = errorFor(errors, itemPath);
        return (
          <div className="review-input-row" key={`${itemPath}-${index}`}>
            <input
              aria-invalid={error ? true : undefined}
              disabled={disabled}
              inputMode="decimal"
              type="text"
              value={value}
              onChange={(event) => {
                const next = [...values];
                next[index] = event.target.value;
                onChange(next);
              }}
            />
            <button
              disabled={disabled}
              type="button"
              onClick={() =>
                onChange(values.filter((_, itemIndex) => itemIndex !== index))
              }
            >
              Remove amount
            </button>
            <FieldError errors={errors} path={itemPath} />
          </div>
        );
      })}
      <button
        disabled={disabled}
        type="button"
        onClick={() => onChange([...values, ""])}
      >
        Add amount
      </button>
      <span className="field-help">
        Each amount stays exact decimal text; an empty list remains distinct
        from an unrecorded stated pot.
      </span>
    </fieldset>
  );
}

function ReadOnlyEvidence({
  label,
  evidence,
}: {
  label: string;
  evidence: Action["evidence"];
}) {
  return (
    <p className="review-read-only">
      {label}:{" "}
      {evidence.length === 0
        ? "no retained locator"
        : evidence.map(evidenceLabel).join("; ")}
    </p>
  );
}

function evidenceLabel(evidence: ImportedHandSourceEvidence): string {
  const line =
    evidence.line_start === null
      ? "no line"
      : evidence.line_end === null || evidence.line_end === evidence.line_start
        ? `line ${evidence.line_start}`
        : `lines ${evidence.line_start}-${evidence.line_end}`;
  const provenance =
    evidence.marker === REVIEW_SOURCE_LINE_MARKER
      ? "User-selected source line"
      : "Retained parser locator";
  return `${provenance} · ${evidence.raw_source_id} · ${line}${evidence.marker ? ` · ${evidence.marker}` : ""}`;
}

function EvidenceBinding({
  disabled,
  evidence,
  errors,
  label,
  options,
  path,
  onChange,
}: {
  disabled: boolean;
  evidence: readonly ImportedHandSourceEvidence[];
  errors: readonly ReviewError[];
  label: string;
  options: readonly ImportedHandSourceEvidence[];
  path: string;
  onChange: (evidence: ImportedHandSourceEvidence[]) => void;
}) {
  const selected = evidence[0] ? sourceEvidenceKey(evidence[0]) : "";
  return (
    <label className="review-field">
      <span>{label}</span>
      <select
        aria-label={label}
        aria-invalid={errorFor(errors, path) ? true : undefined}
        disabled={disabled || options.length === 0}
        value={selected}
        onChange={(event) => {
          const selectedEvidence = options.find(
            (item) => sourceEvidenceKey(item) === event.target.value,
          );
          onChange(selectedEvidence ? [structuredClone(selectedEvidence)] : []);
        }}
      >
        <option value="">No retained locator bound</option>
        {options.map((item) => (
          <option key={sourceEvidenceKey(item)} value={sourceEvidenceKey(item)}>
            {evidenceLabel(item)}
          </option>
        ))}
      </select>
      <span className="field-help">
        {options.length === 0
          ? "No retained source locator is available for this correction."
          : "Choose the retained source locator that supports this recorded row."}
      </span>
      <FieldError errors={errors} path={path} />
    </label>
  );
}

function seatStableKey(
  seat: Seat,
  index: number,
  immutablePlayerIds: readonly string[],
): string {
  // Detected player IDs are read-only in this editor, so they remain a stable
  // row identity while a reviewer corrects editable seat fields. New rows do
  // not acquire an ID until preview, so keep their draft position stable.
  return immutablePlayerIds.includes(seat.player_id)
    ? `retained-seat-${seat.player_id}`
    : `draft-seat-${index}`;
}

function actionDraft(): Action {
  return {
    sequence: 0,
    actor_id: "",
    action_type: "check",
    amount: null,
    total_committed: null,
    all_in: false,
    origin: {
      kind: "unknown",
      basis: "unresolved",
      confidence: null,
      evidence: [],
      semantics_revision: null,
      automatic_reason: null,
      review_reference: null,
    },
    evidence: [],
  };
}

function seatDraft(seats: Seat[]): Seat {
  return {
    seat_number: Math.max(0, ...seats.map((seat) => seat.seat_number)) + 1,
    player_id: "",
    display_name: null,
    starting_stack: null,
    participation: "unknown",
    position: null,
  };
}

export interface StructuredHandReviewEditorProps {
  confirmationActionCandidates?: readonly (readonly Action[])[];
  disabled: boolean;
  evidenceOptions?: readonly ImportedHandSourceEvidence[];
  errors: readonly ReviewError[];
  immutablePlayerIds?: readonly string[];
  state: ImportedHandState;
  onChange: (state: ImportedHandState) => void;
}

/**
 * The player review surface deliberately edits only typed state fields. Source
 * identity, action-origin semantics, and evidence locators remain visible but
 * cannot be synthesized or altered by the browser.
 */
export function StructuredHandReviewEditor({
  confirmationActionCandidates = [],
  disabled,
  evidenceOptions = [],
  errors,
  immutablePlayerIds = [],
  state,
  onChange,
}: StructuredHandReviewEditorProps) {
  const actionDraftIdCounter = useRef(0);
  const actionDraftIdsRef = useRef<string[][] | null>(null);
  const change = (mutate: (next: ImportedHandState) => void) => {
    const next = cloneState(state);
    mutate(next);
    onChange(next);
  };
  const isComplete =
    state.game !== undefined &&
    Array.isArray(state.seats) &&
    Array.isArray(state.streets);
  if (!isComplete) {
    return (
      <p className="deletion-failure">
        This retained detection is incomplete and cannot be reviewed with the
        structured form. Reload the hand; no local correction has been saved.
      </p>
    );
  }
  const createActionDraftId = () => {
    const id = actionDraftIdCounter.current;
    actionDraftIdCounter.current += 1;
    return `draft-action-${id}`;
  };
  if (actionDraftIdsRef.current === null) {
    actionDraftIdsRef.current = state.streets.map((street) =>
      street.actions.map(() => createActionDraftId()),
    );
  }
  const actionDraftIds = actionDraftIdsRef.current;
  const updateActionDraftIds = (
    streetIndex: number,
    update: (draftIds: string[]) => string[],
  ) => {
    const next =
      actionDraftIdsRef.current?.map((draftIds) => [...draftIds]) ?? [];
    next[streetIndex] = update(next[streetIndex] ?? []);
    actionDraftIdsRef.current = next;
  };
  const removeStreetActionDraftIds = (streetIndex: number) => {
    actionDraftIdsRef.current =
      actionDraftIdsRef.current?.filter((_, index) => index !== streetIndex) ??
      [];
  };
  const players = state.seats
    .map((seat) => seat.player_id)
    .filter((playerId) => playerId !== "");
  const retainedEvidence = uniqueSourceEvidence(evidenceOptions);
  const currentActionKeyCounts = new Map<string, number>();
  for (const [streetIndex, street] of state.streets.entries()) {
    for (const action of street.actions) {
      const key = actionConfirmationKey(streetIndex, action);
      currentActionKeyCounts.set(
        key,
        (currentActionKeyCounts.get(key) ?? 0) + 1,
      );
    }
  }
  const confirmationCandidateKeyCounts = new Map<string, number>();
  for (const [streetIndex, actions] of confirmationActionCandidates.entries()) {
    for (const action of actions) {
      if (
        action.origin.kind !== "unknown" ||
        action.origin.basis !== "unresolved"
      ) {
        continue;
      }
      const key = actionConfirmationKey(streetIndex, action);
      confirmationCandidateKeyCounts.set(
        key,
        (confirmationCandidateKeyCounts.get(key) ?? 0) + 1,
      );
    }
  }
  return (
    <div className="structured-review-editor">
      <section className="review-section">
        <h5>Recorded hand and chronology</h5>
        <div className="review-grid">
          <p className="review-read-only">
            Identity: {state.identity.namespace} · {state.identity.site} #
            {state.identity.source_hand_id}
          </p>
          <TextField
            disabled={disabled}
            label="Played at"
            path="/chronology/played_at"
            value={state.chronology.played_at}
            onChange={(value) =>
              change((next) => {
                next.chronology.played_at = value;
              })
            }
          />
          <TextField
            disabled={disabled}
            label="Source timezone"
            path="/chronology/source_timezone"
            value={state.chronology.source_timezone}
            onChange={(value) =>
              change((next) => {
                next.chronology.source_timezone = value;
              })
            }
          />
          <TextField
            disabled={disabled}
            label="Source session"
            path="/chronology/source_session_id"
            value={state.chronology.source_session_id}
            onChange={(value) =>
              change((next) => {
                next.chronology.source_session_id = value;
              })
            }
          />
          <IntegerField
            disabled={disabled}
            label="Hand ordinal"
            path="/chronology/hand_ordinal"
            value={state.chronology.hand_ordinal}
            onChange={(value) =>
              change((next) => {
                next.chronology.hand_ordinal = value;
              })
            }
            positive
          />
          <p className="review-read-only">
            Source file identity: {state.chronology.source_file_id}
          </p>
        </div>
      </section>

      <section className="review-section">
        <h5>Game, blinds, and economics</h5>
        <div className="review-grid">
          <p className="review-read-only">Variant: Texas Hold’em</p>
          <SelectField
            disabled={disabled}
            label="Betting limit"
            options={["no_limit", "pot_limit", "fixed_limit", "unknown"]}
            path="/game/betting_limit"
            value={state.game.betting_limit}
            onChange={(value) =>
              change((next) => {
                next.game.betting_limit = (value ??
                  "unknown") as ImportedHandState["game"]["betting_limit"];
              })
            }
          />
          <IntegerField
            disabled={disabled}
            label="Table size"
            path="/game/table_size"
            value={state.game.table_size}
            onChange={(value) => {
              if (value !== null)
                change((next) => {
                  next.game.table_size = value;
                });
            }}
            positive
          />
          <DecimalField
            disabled={disabled}
            label="Small blind"
            path="/game/blinds/small_blind"
            value={state.game.blinds.small_blind}
            onChange={(value) =>
              change((next) => {
                next.game.blinds.small_blind = value;
              })
            }
          />
          <DecimalField
            disabled={disabled}
            label="Big blind"
            path="/game/blinds/big_blind"
            value={state.game.blinds.big_blind}
            onChange={(value) =>
              change((next) => {
                next.game.blinds.big_blind = value;
              })
            }
          />
          <DecimalField
            disabled={disabled}
            label="Ante"
            path="/game/blinds/ante"
            value={state.game.blinds.ante}
            onChange={(value) =>
              change((next) => {
                next.game.blinds.ante = value;
              })
            }
          />
          <SelectField
            disabled={disabled}
            label="Ante mode"
            options={["per_player", "big_blind", "unknown"]}
            path="/game/blinds/ante_mode"
            value={state.game.blinds.ante_mode}
            onChange={(value) =>
              change((next) => {
                next.game.blinds.ante_mode = (value ??
                  "unknown") as ImportedHandState["game"]["blinds"]["ante_mode"];
              })
            }
          />
          <DecimalField
            disabled={disabled}
            label="Straddle"
            path="/game/blinds/straddle"
            value={state.game.blinds.straddle}
            onChange={(value) =>
              change((next) => {
                next.game.blinds.straddle = value;
              })
            }
          />
          <SelectField
            disabled={disabled}
            label="Economics"
            options={["cash", "tournament", "unknown"]}
            path="/game/economics/kind"
            value={state.game.economics.kind}
            onChange={(value) =>
              change((next) => {
                if (value === next.game.economics.kind) return;
                if (value === "cash")
                  next.game.economics = {
                    kind: "cash",
                    currency: null,
                    rake: null,
                  };
                else if (value === "tournament")
                  next.game.economics = {
                    kind: "tournament",
                    tournament_id: null,
                    tournament_type: null,
                    stage: null,
                    entry_buy_in: null,
                    entry_fee: null,
                    blind_level: null,
                    currency: null,
                    paid_places: null,
                    players_remaining: null,
                    payouts: [],
                    remaining_stacks: [],
                    bounty_format: null,
                    bounties: [],
                    icm_inputs_complete: false,
                  };
                else next.game.economics = { kind: "unknown", reason: null };
              })
            }
          />
        </div>
        {state.game.economics.kind === "cash" ? (
          <CashEconomics
            disabled={disabled}
            economics={state.game.economics}
            errors={errors}
            onChange={(economics) =>
              change((next) => {
                next.game.economics = economics;
              })
            }
          />
        ) : null}
        {state.game.economics.kind === "tournament" ? (
          <TournamentEconomics
            disabled={disabled}
            economics={state.game.economics}
            errors={errors}
            players={players}
            onChange={(economics) =>
              change((next) => {
                next.game.economics = economics;
              })
            }
          />
        ) : null}
        {state.game.economics.kind === "unknown" ? (
          <TextField
            disabled={disabled}
            label="Why economics are unknown"
            path="/game/economics/reason"
            value={state.game.economics.reason}
            onChange={(value) =>
              change((next) => {
                if (next.game.economics.kind === "unknown")
                  next.game.economics.reason = value;
              })
            }
          />
        ) : null}
      </section>

      <section className="review-section">
        <h5>Seats, participation, button, and Hero</h5>
        <div className="review-grid">
          <IntegerField
            disabled={disabled}
            label="Button seat"
            path="/button_seat"
            value={state.button_seat}
            onChange={(value) =>
              change((next) => {
                next.button_seat = value;
                clearDerivedPositions(next);
              })
            }
            positive
          />
          <SelectField
            disabled={disabled}
            label="Hero player"
            options={players}
            path="/hero_player_id"
            value={state.hero_player_id}
            onChange={(value) =>
              change((next) => {
                next.hero_player_id = value;
                if (value === null) next.hero_cards = [];
              })
            }
          />
          <CardList
            disabled={disabled}
            label="Hero cards"
            maximum={2}
            path="/hero_cards"
            cards={state.hero_cards}
            onChange={(cards) =>
              change((next) => {
                next.hero_cards = cards;
              })
            }
          />
        </div>
        <div className="review-list">
          {state.seats.map((seat, index) => (
            <SeatEditor
              key={seatStableKey(seat, index, immutablePlayerIds)}
              disabled={disabled}
              errors={errors}
              immutablePlayerIds={immutablePlayerIds}
              path={`/seats/${index}`}
              seat={seat}
              onChange={(updated) =>
                change((next) => {
                  next.seats[index] = updated;
                  clearDerivedPositions(next);
                })
              }
              onMove={(direction) =>
                change((next) => {
                  const target = index + direction;
                  if (target < 0 || target >= next.seats.length) return;
                  [next.seats[index], next.seats[target]] = [
                    next.seats[target],
                    next.seats[index],
                  ];
                  clearDerivedPositions(next);
                })
              }
              onRemove={() =>
                change((next) => {
                  next.seats.splice(index, 1);
                  clearDerivedPositions(next);
                })
              }
            />
          ))}
        </div>
        <button
          disabled={disabled}
          type="button"
          onClick={() =>
            change((next) => {
              next.seats.push(seatDraft(next.seats));
              clearDerivedPositions(next);
            })
          }
        >
          Add seat
        </button>
        <p className="field-help">
          Changing the button, a seat, or participation clears displayed
          positions until the preview can derive them from a complete known
          dealt-in ring. A new seat has no source evidence; assign its player
          identity and use preview to validate it.
        </p>
      </section>

      <section className="review-section">
        <h5>Recorded streets and actions</h5>
        {state.streets.map((street, streetIndex) => (
          <StreetEditor
            key={street.street}
            actionDraftIds={actionDraftIds[streetIndex] ?? []}
            confirmationCandidateKeyCounts={confirmationCandidateKeyCounts}
            createActionDraftId={createActionDraftId}
            currentActionKeyCounts={currentActionKeyCounts}
            disabled={disabled}
            evidenceOptions={retainedEvidence}
            errors={errors}
            players={players}
            path={`/streets/${streetIndex}`}
            street={street}
            streetIndex={streetIndex}
            onActionDraftIdsChange={(update) =>
              updateActionDraftIds(streetIndex, update)
            }
            onChange={(updated) =>
              change((next) => {
                next.streets[streetIndex] = updated;
              })
            }
            onRemove={
              streetIndex === 0 || streetIndex !== state.streets.length - 1
                ? undefined
                : () =>
                    change((next) => {
                      removeStreetActionDraftIds(streetIndex);
                      next.streets.splice(streetIndex, 1);
                    })
            }
          />
        ))}
        <button
          disabled={disabled || state.streets.length >= STREETS.length}
          type="button"
          onClick={() =>
            change((next) => {
              const street = STREETS[next.streets.length];
              if (street) {
                actionDraftIdsRef.current = [
                  ...(actionDraftIdsRef.current ?? []),
                  [],
                ];
                next.streets.push({ street, board_cards: [], actions: [] });
              }
            })
          }
        >
          Add next street
        </button>
      </section>

      <section className="review-section">
        <h5>Recorded results</h5>
        <ResultsEditor
          disabled={disabled}
          errors={errors}
          evidenceOptions={retainedEvidence}
          players={players}
          results={state.results}
          onChange={(results) =>
            change((next) => {
              next.results = results;
            })
          }
        />
      </section>

      <details className="review-provenance">
        <summary>Read-only technical provenance</summary>
        <p>
          Raw hand identity, source file identity, parser confidence,
          action-origin semantics, and evidence locators are retained
          separately. New recorded rows must bind an existing locator; this
          editor never creates one.
        </p>
      </details>
    </div>
  );
}

function CashEconomics({
  disabled,
  economics,
  errors,
  onChange,
}: {
  disabled: boolean;
  economics: Extract<ImportedHandState["game"]["economics"], { kind: "cash" }>;
  errors: readonly ReviewError[];
  onChange: (
    value: Extract<ImportedHandState["game"]["economics"], { kind: "cash" }>,
  ) => void;
}) {
  const rake = economics.rake;
  return (
    <div className="review-grid nested-review-grid">
      <TextField
        disabled={disabled}
        errors={errors}
        label="Cash currency"
        path="/game/economics/currency"
        value={economics.currency}
        onChange={(value) => onChange({ ...economics, currency: value })}
      />
      <label className="review-field">
        <span>Rake record</span>
        <select
          disabled={disabled}
          value={rake === null ? "none" : "recorded"}
          onChange={(event) =>
            onChange({
              ...economics,
              rake:
                event.target.value === "none"
                  ? null
                  : (rake ?? {
                      percentage: null,
                      cap: null,
                      fixed_drop: null,
                      description: null,
                    }),
            })
          }
        >
          <option value="none">Not recorded</option>
          <option value="recorded">Recorded</option>
        </select>
      </label>
      {rake ? (
        <>
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Rake percentage"
            path="/game/economics/rake/percentage"
            value={rake.percentage}
            onChange={(value) =>
              onChange({ ...economics, rake: { ...rake, percentage: value } })
            }
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Rake cap"
            path="/game/economics/rake/cap"
            value={rake.cap}
            onChange={(value) =>
              onChange({ ...economics, rake: { ...rake, cap: value } })
            }
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Fixed drop"
            path="/game/economics/rake/fixed_drop"
            value={rake.fixed_drop}
            onChange={(value) =>
              onChange({ ...economics, rake: { ...rake, fixed_drop: value } })
            }
          />
          <TextField
            disabled={disabled}
            errors={errors}
            label="Rake description"
            path="/game/economics/rake/description"
            value={rake.description}
            onChange={(value) =>
              onChange({ ...economics, rake: { ...rake, description: value } })
            }
          />
        </>
      ) : null}
    </div>
  );
}

function TournamentEconomics({
  disabled,
  economics,
  errors,
  players,
  onChange,
}: {
  disabled: boolean;
  economics: Extract<
    ImportedHandState["game"]["economics"],
    { kind: "tournament" }
  >;
  errors: readonly ReviewError[];
  players: string[];
  onChange: (
    value: Extract<
      ImportedHandState["game"]["economics"],
      { kind: "tournament" }
    >,
  ) => void;
}) {
  return (
    <div className="nested-review-grid">
      <div className="review-grid">
        <TextField
          disabled={disabled}
          errors={errors}
          label="Tournament ID"
          path="/game/economics/tournament_id"
          value={economics.tournament_id}
          onChange={(value) => onChange({ ...economics, tournament_id: value })}
        />
        <TextField
          disabled={disabled}
          errors={errors}
          label="Tournament type"
          path="/game/economics/tournament_type"
          value={economics.tournament_type}
          onChange={(value) =>
            onChange({ ...economics, tournament_type: value })
          }
        />
        <TextField
          disabled={disabled}
          errors={errors}
          label="Tournament stage"
          path="/game/economics/stage"
          value={economics.stage}
          onChange={(value) => onChange({ ...economics, stage: value })}
        />
        <TextField
          disabled={disabled}
          errors={errors}
          label="Tournament currency"
          path="/game/economics/currency"
          value={economics.currency}
          onChange={(value) => onChange({ ...economics, currency: value })}
        />
        <DecimalField
          disabled={disabled}
          errors={errors}
          label="Entry buy-in"
          path="/game/economics/entry_buy_in"
          value={economics.entry_buy_in}
          onChange={(value) => onChange({ ...economics, entry_buy_in: value })}
        />
        <DecimalField
          disabled={disabled}
          errors={errors}
          label="Entry fee"
          path="/game/economics/entry_fee"
          value={economics.entry_fee}
          onChange={(value) => onChange({ ...economics, entry_fee: value })}
        />
        <TextField
          disabled={disabled}
          errors={errors}
          label="Blind level"
          path="/game/economics/blind_level"
          value={economics.blind_level}
          onChange={(value) => onChange({ ...economics, blind_level: value })}
        />
        <IntegerField
          disabled={disabled}
          errors={errors}
          label="Paid places"
          path="/game/economics/paid_places"
          value={economics.paid_places}
          onChange={(value) => onChange({ ...economics, paid_places: value })}
          positive
        />
        <IntegerField
          disabled={disabled}
          errors={errors}
          label="Players remaining"
          path="/game/economics/players_remaining"
          value={economics.players_remaining}
          onChange={(value) =>
            onChange({ ...economics, players_remaining: value })
          }
          positive
        />
        <label className="review-field">
          <span>ICM inputs complete</span>
          <input
            checked={economics.icm_inputs_complete}
            disabled={disabled}
            type="checkbox"
            onChange={(event) =>
              onChange({
                ...economics,
                icm_inputs_complete: event.target.checked,
              })
            }
          />
        </label>
        <TextField
          disabled={disabled}
          errors={errors}
          label="Bounty format"
          path="/game/economics/bounty_format"
          value={economics.bounty_format}
          onChange={(value) => onChange({ ...economics, bounty_format: value })}
        />
      </div>
      <SimpleEconomicLists
        disabled={disabled}
        economics={economics}
        errors={errors}
        players={players}
        onChange={onChange}
      />
    </div>
  );
}

function SimpleEconomicLists({
  disabled,
  economics,
  errors,
  players,
  onChange,
}: {
  disabled: boolean;
  economics: Extract<
    ImportedHandState["game"]["economics"],
    { kind: "tournament" }
  >;
  errors: readonly ReviewError[];
  players: string[];
  onChange: (
    value: Extract<
      ImportedHandState["game"]["economics"],
      { kind: "tournament" }
    >,
  ) => void;
}) {
  return (
    <div className="review-list">
      <h6>Payouts</h6>
      {economics.payouts.map((payout, index) => (
        <div className="review-list-row" key={`payout-${index}`}>
          <IntegerField
            disabled={disabled}
            errors={errors}
            label="From place"
            path={`/game/economics/payouts/${index}/place_from`}
            value={payout.place_from}
            onChange={(value) => {
              if (value !== null) {
                const payouts = [...economics.payouts];
                payouts[index] = { ...payout, place_from: value };
                onChange({ ...economics, payouts });
              }
            }}
            positive
          />
          <IntegerField
            disabled={disabled}
            errors={errors}
            label="To place"
            path={`/game/economics/payouts/${index}/place_to`}
            value={payout.place_to}
            onChange={(value) => {
              if (value !== null) {
                const payouts = [...economics.payouts];
                payouts[index] = { ...payout, place_to: value };
                onChange({ ...economics, payouts });
              }
            }}
            positive
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Payout amount"
            path={`/game/economics/payouts/${index}/amount`}
            value={payout.amount}
            onChange={(value) => {
              const payouts = [...economics.payouts];
              payouts[index] = { ...payout, amount: value };
              onChange({ ...economics, payouts });
            }}
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Payout share"
            path={`/game/economics/payouts/${index}/share`}
            value={payout.share}
            onChange={(value) => {
              const payouts = [...economics.payouts];
              payouts[index] = { ...payout, share: value };
              onChange({ ...economics, payouts });
            }}
          />
          <button
            disabled={disabled}
            type="button"
            onClick={() =>
              onChange({
                ...economics,
                payouts: economics.payouts.filter(
                  (_, itemIndex) => itemIndex !== index,
                ),
              })
            }
          >
            Remove payout
          </button>
        </div>
      ))}
      <button
        disabled={disabled}
        type="button"
        onClick={() =>
          onChange({
            ...economics,
            payouts: [
              ...economics.payouts,
              { place_from: 1, place_to: 1, amount: null, share: null },
            ],
          })
        }
      >
        Add payout
      </button>
      <h6>Remaining stacks and bounties</h6>
      {(["remaining_stacks", "bounties"] as const).map((kind) => (
        <div key={kind}>
          {economics[kind].map((item, index) => (
            <div
              className="review-list-row"
              key={`${kind}-${index}-${item.player_id}`}
            >
              <SelectField
                disabled={disabled}
                label="Player"
                options={players}
                path={`/game/economics/${kind}/${index}/player_id`}
                value={item.player_id}
                onChange={(value) => {
                  if (value) {
                    const rows = [...economics[kind]];
                    rows[index] = { ...item, player_id: value };
                    onChange({ ...economics, [kind]: rows });
                  }
                }}
              />
              <DecimalField
                disabled={disabled}
                errors={errors}
                label={kind === "bounties" ? "Bounty" : "Stack"}
                path={`/game/economics/${kind}/${index}/${kind === "bounties" ? "value" : "stack"}`}
                value={
                  kind === "bounties"
                    ? (item as { value: string | null }).value
                    : (item as { stack: string | null }).stack
                }
                onChange={(value) => {
                  const rows = [...economics[kind]];
                  rows[index] =
                    kind === "bounties"
                      ? { ...item, value }
                      : { ...item, stack: value };
                  onChange({ ...economics, [kind]: rows });
                }}
              />
              <button
                disabled={disabled}
                type="button"
                onClick={() =>
                  onChange({
                    ...economics,
                    [kind]: economics[kind].filter(
                      (_, itemIndex) => itemIndex !== index,
                    ),
                  })
                }
              >
                Remove
              </button>
            </div>
          ))}
          <button
            disabled={disabled || players.length === 0}
            type="button"
            onClick={() =>
              onChange({
                ...economics,
                [kind]: [
                  ...economics[kind],
                  kind === "bounties"
                    ? { player_id: players[0], value: null }
                    : { player_id: players[0], stack: null },
                ],
              })
            }
          >
            Add {kind === "bounties" ? "bounty" : "stack"}
          </button>
        </div>
      ))}
    </div>
  );
}

function SeatEditor({
  disabled,
  errors,
  immutablePlayerIds,
  path,
  seat,
  onChange,
  onMove,
  onRemove,
}: {
  disabled: boolean;
  errors: readonly ReviewError[];
  immutablePlayerIds: readonly string[];
  path: string;
  seat: Seat;
  onChange: (seat: Seat) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
}) {
  return (
    <article className="review-list-item">
      <h6>
        Seat {seat.seat_number} ·{" "}
        <span className="review-read-only">
          {seat.player_id === ""
            ? "new player identity required"
            : `player identity ${seat.player_id}`}
        </span>
      </h6>
      <div className="review-grid">
        {!immutablePlayerIds.includes(seat.player_id) ? (
          <TextField
            clearable={false}
            disabled={disabled}
            errors={errors}
            label="Player identity"
            path={`${path}/player_id`}
            value={seat.player_id}
            onChange={(value) => onChange({ ...seat, player_id: value ?? "" })}
          />
        ) : null}
        <IntegerField
          disabled={disabled}
          errors={errors}
          label="Seat number"
          path={`${path}/seat_number`}
          value={seat.seat_number}
          onChange={(value) => {
            if (value !== null) onChange({ ...seat, seat_number: value });
          }}
          positive
        />
        <TextField
          disabled={disabled}
          errors={errors}
          label="Display name"
          path={`${path}/display_name`}
          value={seat.display_name}
          onChange={(value) => onChange({ ...seat, display_name: value })}
        />
        <DecimalField
          disabled={disabled}
          errors={errors}
          label="Starting stack"
          path={`${path}/starting_stack`}
          value={seat.starting_stack}
          onChange={(value) => onChange({ ...seat, starting_stack: value })}
        />
        <SelectField
          disabled={disabled}
          errors={errors}
          label="Participation"
          options={["dealt_in", "sitting_out", "not_dealt", "unknown"]}
          path={`${path}/participation`}
          value={seat.participation}
          onChange={(value) =>
            onChange({
              ...seat,
              participation: (value ?? "unknown") as Seat["participation"],
            })
          }
        />
        <p className="review-read-only">
          Displayed position: {seat.position?.display_label ?? "not derived"}
        </p>
      </div>
      <div className="lifecycle-action-buttons">
        <button disabled={disabled} type="button" onClick={() => onMove(-1)}>
          Move earlier
        </button>
        <button disabled={disabled} type="button" onClick={() => onMove(1)}>
          Move later
        </button>
        <button disabled={disabled} type="button" onClick={onRemove}>
          Remove seat
        </button>
      </div>
    </article>
  );
}

function StreetEditor({
  actionDraftIds,
  confirmationCandidateKeyCounts,
  createActionDraftId,
  currentActionKeyCounts,
  disabled,
  evidenceOptions,
  errors,
  players,
  path,
  street,
  streetIndex,
  onActionDraftIdsChange,
  onChange,
  onRemove,
}: {
  actionDraftIds: readonly string[];
  confirmationCandidateKeyCounts: ReadonlyMap<string, number>;
  createActionDraftId: () => string;
  currentActionKeyCounts: ReadonlyMap<string, number>;
  disabled: boolean;
  evidenceOptions: readonly ImportedHandSourceEvidence[];
  errors: readonly ReviewError[];
  players: string[];
  path: string;
  street: ImportedHandState["streets"][number];
  streetIndex: number;
  onActionDraftIdsChange: (update: (draftIds: string[]) => string[]) => void;
  onChange: (street: ImportedHandState["streets"][number]) => void;
  onRemove?: () => void;
}) {
  return (
    <article className="review-list-item">
      <h6>{readable(street.street)}</h6>
      <CardList
        disabled={disabled}
        label={`${readable(street.street)} board cards`}
        maximum={
          street.street === "preflop"
            ? 0
            : street.street === "flop"
              ? 3
              : street.street === "turn"
                ? 4
                : 5
        }
        path={`${path}/board_cards`}
        cards={street.board_cards}
        onChange={(board_cards) => onChange({ ...street, board_cards })}
      />
      <div className="review-list">
        {street.actions.map((action, index) => (
          <ActionEditor
            key={actionDraftIds[index] ?? `missing-action-draft-${index}`}
            action={action}
            canConfirmPlayerSelectedOrigin={
              currentActionKeyCounts.get(
                actionConfirmationKey(streetIndex, action),
              ) === 1 &&
              confirmationCandidateKeyCounts.get(
                actionConfirmationKey(streetIndex, action),
              ) === 1
            }
            disabled={disabled}
            evidenceOptions={evidenceOptions}
            errors={errors}
            path={`${path}/actions/${index}`}
            players={players}
            onChange={(updated) => {
              const actions = [...street.actions];
              actions[index] = updated;
              onChange({ ...street, actions: resequence(actions) });
            }}
            onMove={(direction) => {
              const target = index + direction;
              if (target < 0 || target >= street.actions.length) return;
              onActionDraftIdsChange((draftIds) => {
                const next = [...draftIds];
                [next[index], next[target]] = [next[target], next[index]];
                return next;
              });
              const actions = [...street.actions];
              [actions[index], actions[target]] = [
                actions[target],
                actions[index],
              ];
              onChange({ ...street, actions: resequence(actions) });
            }}
            onRemove={() => {
              onActionDraftIdsChange((draftIds) =>
                draftIds.filter((_, itemIndex) => itemIndex !== index),
              );
              onChange({
                ...street,
                actions: resequence(
                  street.actions.filter((_, itemIndex) => itemIndex !== index),
                ),
              });
            }}
          />
        ))}
      </div>
      <button
        disabled={disabled || evidenceOptions.length === 0}
        type="button"
        onClick={() => {
          onActionDraftIdsChange((draftIds) => [
            ...draftIds,
            createActionDraftId(),
          ]);
          onChange({
            ...street,
            actions: [
              ...street.actions,
              { ...actionDraft(), sequence: street.actions.length },
            ],
          });
        }}
      >
        Add action
      </button>
      <p className="field-help">
        New actions must bind a retained source locator. Reordering preserves
        each action's existing evidence; preview rejects any ambiguous mapping.
      </p>
      {onRemove ? (
        <button disabled={disabled} type="button" onClick={onRemove}>
          Remove street
        </button>
      ) : null}
    </article>
  );
}

function ActionEditor({
  action,
  canConfirmPlayerSelectedOrigin,
  disabled,
  evidenceOptions,
  errors,
  path,
  players,
  onChange,
  onMove,
  onRemove,
}: {
  action: Action;
  canConfirmPlayerSelectedOrigin: boolean;
  disabled: boolean;
  evidenceOptions: readonly ImportedHandSourceEvidence[];
  errors: readonly ReviewError[];
  path: string;
  players: string[];
  onChange: (action: Action) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
}) {
  const [confirmationReference, setConfirmationReference] = useState("");
  const missingEvidence =
    action.evidence.length === 0 || action.origin.evidence.length === 0;
  const hasUserSelectedSourceLine = [
    ...action.evidence,
    ...action.origin.evidence,
  ].some((evidence) => evidence.marker === REVIEW_SOURCE_LINE_MARKER);
  const canConfirmUnknownOrigin =
    canConfirmPlayerSelectedOrigin &&
    !hasUserSelectedSourceLine &&
    action.origin.kind === "unknown" &&
    action.origin.basis === "unresolved";
  const canKeepOriginUnresolved =
    !FORCED_ACTION_TYPES.includes(action.action_type) &&
    !(action.origin.kind === "unknown" && action.origin.basis === "unresolved");
  return (
    <article className="review-list-item">
      <h6>Action {action.sequence + 1}</h6>
      <div className="review-grid">
        <SelectField
          disabled={disabled}
          errors={errors}
          label="Actor"
          options={players}
          path={`${path}/actor_id`}
          value={action.actor_id || null}
          onChange={(value) => onChange({ ...action, actor_id: value ?? "" })}
        />
        <SelectField
          disabled={disabled}
          errors={errors}
          label="Action type"
          options={ACTION_TYPES}
          path={`${path}/action_type`}
          value={action.action_type}
          onChange={(value) => {
            const action_type = (value ?? "check") as Action["action_type"];
            onChange({
              ...action,
              action_type,
              origin: correctedOriginForActionType(action, action_type),
            });
          }}
        />
        <DecimalField
          disabled={disabled}
          errors={errors}
          label="Amount"
          path={`${path}/amount`}
          value={action.amount}
          onChange={(value) => onChange({ ...action, amount: value })}
        />
        <DecimalField
          disabled={disabled}
          errors={errors}
          label="Total committed"
          path={`${path}/total_committed`}
          value={action.total_committed}
          onChange={(value) => onChange({ ...action, total_committed: value })}
        />
        <label className="review-field">
          <span>All in</span>
          <input
            checked={action.all_in}
            disabled={disabled}
            type="checkbox"
            onChange={(event) =>
              onChange({ ...action, all_in: event.target.checked })
            }
          />
        </label>
      </div>
      <p className="field-help">
        Changing a post or uncalled return uses the required forced-system
        origin. Changing it to a table action leaves the origin unresolved until
        you explicitly confirm player selection from retained evidence.
      </p>
      {missingEvidence ? (
        <EvidenceBinding
          disabled={disabled}
          errors={errors}
          evidence={action.evidence}
          label="Bind retained source evidence"
          options={evidenceOptions}
          path={`${path}/evidence`}
          onChange={(evidence) =>
            onChange({
              ...action,
              evidence,
              origin: { ...action.origin, evidence },
            })
          }
        />
      ) : (
        <>
          <p className="review-read-only">
            Origin: {readable(action.origin.kind)} ·{" "}
            {readable(action.origin.basis)}
            {action.origin.confidence === null
              ? ""
              : ` · confidence ${action.origin.confidence}`}
            {action.origin.semantics_revision
              ? ` · semantics ${action.origin.semantics_revision}`
              : ""}
            {action.origin.automatic_reason
              ? ` · automatic reason ${action.origin.automatic_reason}`
              : ""}
            {action.origin.review_reference
              ? ` · review reference ${action.origin.review_reference}`
              : ""}
          </p>
          <ReadOnlyEvidence
            evidence={action.origin.evidence}
            label="Origin evidence"
          />
          <ReadOnlyEvidence evidence={action.evidence} label="Evidence" />
        </>
      )}
      {canConfirmUnknownOrigin ? (
        <div className="review-grid">
          <TextField
            clearable={false}
            disabled={disabled}
            errors={errors}
            label="Origin confirmation reference"
            path={`${path}/origin/review_reference`}
            value={confirmationReference || null}
            onChange={(value) => setConfirmationReference(value ?? "")}
          />
          <button
            disabled={
              disabled ||
              missingEvidence ||
              confirmationReference.trim().length === 0
            }
            type="button"
            onClick={() =>
              onChange({
                ...action,
                origin: {
                  ...action.origin,
                  kind: "player_selected",
                  basis: "user_confirmed",
                  semantics_revision: null,
                  automatic_reason: null,
                  review_reference: confirmationReference.trim(),
                },
              })
            }
          >
            Confirm player-selected origin
          </button>
          <p className="field-help">
            This is a user review confirmation tied to retained action evidence,
            not a parser-semantic claim.
          </p>
        </div>
      ) : null}
      {canKeepOriginUnresolved ? (
        <button
          disabled={disabled}
          type="button"
          onClick={() =>
            onChange({
              ...action,
              origin: {
                ...action.origin,
                kind: "unknown",
                basis: "unresolved",
                confidence: null,
                semantics_revision: null,
                automatic_reason: null,
                review_reference: null,
              },
            })
          }
        >
          Keep origin unresolved
        </button>
      ) : null}
      <div className="lifecycle-action-buttons">
        <button disabled={disabled} type="button" onClick={() => onMove(-1)}>
          Move earlier
        </button>
        <button disabled={disabled} type="button" onClick={() => onMove(1)}>
          Move later
        </button>
        <button disabled={disabled} type="button" onClick={onRemove}>
          Remove action
        </button>
      </div>
    </article>
  );
}

function ResultsEditor({
  disabled,
  evidenceOptions,
  errors,
  players,
  results,
  onChange,
}: {
  disabled: boolean;
  evidenceOptions: readonly ImportedHandSourceEvidence[];
  errors: readonly ReviewError[];
  players: string[];
  results: ImportedHandState["results"];
  onChange: (results: ImportedHandState["results"]) => void;
}) {
  if (results === null)
    return (
      <div>
        <p>No results are recorded.</p>
        <button
          disabled={disabled}
          type="button"
          onClick={() =>
            onChange({
              stated_pot: null,
              showdown: [],
              awards: [],
              players: [],
            })
          }
        >
          Record results
        </button>
      </div>
    );
  const pot = results.stated_pot;
  return (
    <div className="review-list">
      <label className="review-field">
        <span>Stated pot</span>
        <select
          disabled={disabled}
          value={pot === null ? "none" : "recorded"}
          onChange={(event) =>
            onChange({
              ...results,
              stated_pot:
                event.target.value === "none"
                  ? null
                  : (pot ?? {
                      gross_total: null,
                      rake: null,
                      net_total: null,
                      gross_pots: [],
                    }),
            })
          }
        >
          <option value="none">Not recorded</option>
          <option value="recorded">Recorded</option>
        </select>
      </label>
      {pot ? (
        <div className="review-grid">
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Gross total"
            path="/results/stated_pot/gross_total"
            value={pot.gross_total}
            onChange={(value) =>
              onChange({
                ...results,
                stated_pot: { ...pot, gross_total: value },
              })
            }
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Rake"
            path="/results/stated_pot/rake"
            value={pot.rake}
            onChange={(value) =>
              onChange({ ...results, stated_pot: { ...pot, rake: value } })
            }
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Net total"
            path="/results/stated_pot/net_total"
            value={pot.net_total}
            onChange={(value) =>
              onChange({ ...results, stated_pot: { ...pot, net_total: value } })
            }
          />
          <DecimalList
            disabled={disabled}
            errors={errors}
            label="Gross pots"
            path="/results/stated_pot/gross_pots"
            values={pot.gross_pots}
            onChange={(gross_pots) =>
              onChange({ ...results, stated_pot: { ...pot, gross_pots } })
            }
          />
        </div>
      ) : null}
      <ResultLists
        disabled={disabled}
        evidenceOptions={evidenceOptions}
        errors={errors}
        players={players}
        results={results}
        onChange={onChange}
      />
      <button disabled={disabled} type="button" onClick={() => onChange(null)}>
        Clear all recorded results
      </button>
    </div>
  );
}

function ResultLists({
  disabled,
  evidenceOptions,
  errors,
  players,
  results,
  onChange,
}: {
  disabled: boolean;
  evidenceOptions: readonly ImportedHandSourceEvidence[];
  errors: readonly ReviewError[];
  players: string[];
  results: NonNullable<ImportedHandState["results"]>;
  onChange: (value: NonNullable<ImportedHandState["results"]>) => void;
}) {
  return (
    <div className="review-list">
      <h6>Showdown</h6>
      {results.showdown.map((entry, index) => (
        <div
          className="review-list-row"
          key={`showdown-${entry.player_id}-${index}`}
        >
          <SelectField
            disabled={disabled}
            errors={errors}
            label="Player"
            options={players}
            path={`/results/showdown/${index}/player_id`}
            value={entry.player_id}
            onChange={(value) => {
              if (value) {
                const showdown = [...results.showdown];
                showdown[index] = { ...entry, player_id: value };
                onChange({ ...results, showdown });
              }
            }}
          />
          <SelectField
            disabled={disabled}
            errors={errors}
            label="Disposition"
            options={["shown", "mucked", "not_shown", "unknown"]}
            path={`/results/showdown/${index}/disposition`}
            value={entry.disposition}
            onChange={(value) => {
              const showdown = [...results.showdown];
              showdown[index] = {
                ...entry,
                disposition: (value ?? "unknown") as typeof entry.disposition,
              };
              onChange({ ...results, showdown });
            }}
          />
          <CardList
            disabled={disabled}
            label="Showdown cards"
            maximum={2}
            path={`/results/showdown/${index}/cards`}
            cards={entry.cards}
            onChange={(cards) => {
              const showdown = [...results.showdown];
              showdown[index] = { ...entry, cards };
              onChange({ ...results, showdown });
            }}
          />
          {entry.evidence.length === 0 ? (
            <EvidenceBinding
              disabled={disabled}
              errors={errors}
              evidence={entry.evidence}
              label="Bind retained source evidence"
              options={evidenceOptions}
              path={`/results/showdown/${index}/evidence`}
              onChange={(evidence) => {
                const showdown = [...results.showdown];
                showdown[index] = { ...entry, evidence };
                onChange({ ...results, showdown });
              }}
            />
          ) : (
            <ReadOnlyEvidence evidence={entry.evidence} label="Evidence" />
          )}
          <button
            disabled={disabled}
            type="button"
            onClick={() =>
              onChange({
                ...results,
                showdown: results.showdown.filter(
                  (_, itemIndex) => itemIndex !== index,
                ),
              })
            }
          >
            Remove showdown
          </button>
        </div>
      ))}
      <button
        disabled={
          disabled || players.length === 0 || evidenceOptions.length === 0
        }
        type="button"
        onClick={() =>
          onChange({
            ...results,
            showdown: [
              ...results.showdown,
              {
                player_id: players[0],
                cards: [],
                disposition: "unknown",
                evidence: [],
              },
            ],
          })
        }
      >
        Add showdown
      </button>
      <h6>Awards</h6>
      {results.awards.map((award, index) => (
        <div
          className="review-list-row"
          key={`award-${award.player_id}-${award.pot_index}-${index}`}
        >
          <SelectField
            disabled={disabled}
            errors={errors}
            label="Player"
            options={players}
            path={`/results/awards/${index}/player_id`}
            value={award.player_id}
            onChange={(value) => {
              if (value) {
                const awards = [...results.awards];
                awards[index] = { ...award, player_id: value };
                onChange({ ...results, awards });
              }
            }}
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Award amount"
            path={`/results/awards/${index}/amount`}
            value={award.amount}
            onChange={(value) => {
              const awards = [...results.awards];
              awards[index] = { ...award, amount: value };
              onChange({ ...results, awards });
            }}
          />
          <IntegerField
            disabled={disabled}
            errors={errors}
            label="Pot index"
            path={`/results/awards/${index}/pot_index`}
            value={award.pot_index}
            onChange={(value) => {
              const awards = [...results.awards];
              awards[index] = { ...award, pot_index: value };
              onChange({ ...results, awards });
            }}
          />
          {award.evidence.length === 0 ? (
            <EvidenceBinding
              disabled={disabled}
              errors={errors}
              evidence={award.evidence}
              label="Bind retained source evidence"
              options={evidenceOptions}
              path={`/results/awards/${index}/evidence`}
              onChange={(evidence) => {
                const awards = [...results.awards];
                awards[index] = { ...award, evidence };
                onChange({ ...results, awards });
              }}
            />
          ) : (
            <ReadOnlyEvidence evidence={award.evidence} label="Evidence" />
          )}
          <button
            disabled={disabled}
            type="button"
            onClick={() =>
              onChange({
                ...results,
                awards: results.awards.filter(
                  (_, itemIndex) => itemIndex !== index,
                ),
              })
            }
          >
            Remove award
          </button>
        </div>
      ))}
      <button
        disabled={
          disabled || players.length === 0 || evidenceOptions.length === 0
        }
        type="button"
        onClick={() =>
          onChange({
            ...results,
            awards: [
              ...results.awards,
              {
                player_id: players[0],
                amount: null,
                pot_index: null,
                evidence: [],
              },
            ],
          })
        }
      >
        Add award
      </button>
      <h6>Player results</h6>
      {results.players.map((result, index) => (
        <div
          className="review-list-row"
          key={`result-${result.player_id}-${index}`}
        >
          <SelectField
            disabled={disabled}
            errors={errors}
            label="Player"
            options={players}
            path={`/results/players/${index}/player_id`}
            value={result.player_id}
            onChange={(value) => {
              if (value) {
                const rows = [...results.players];
                rows[index] = { ...result, player_id: value };
                onChange({ ...results, players: rows });
              }
            }}
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Net result"
            path={`/results/players/${index}/net_result`}
            value={result.net_result}
            onChange={(value) => {
              const rows = [...results.players];
              rows[index] = { ...result, net_result: value };
              onChange({ ...results, players: rows });
            }}
          />
          <DecimalField
            disabled={disabled}
            errors={errors}
            label="Total collected"
            path={`/results/players/${index}/total_collected`}
            value={result.total_collected}
            onChange={(value) => {
              const rows = [...results.players];
              rows[index] = { ...result, total_collected: value };
              onChange({ ...results, players: rows });
            }}
          />
          <button
            disabled={disabled}
            type="button"
            onClick={() =>
              onChange({
                ...results,
                players: results.players.filter(
                  (_, itemIndex) => itemIndex !== index,
                ),
              })
            }
          >
            Remove result
          </button>
        </div>
      ))}
      <button
        disabled={disabled || players.length === 0}
        type="button"
        onClick={() =>
          onChange({
            ...results,
            players: [
              ...results.players,
              {
                player_id: players[0],
                net_result: null,
                total_collected: null,
              },
            ],
          })
        }
      >
        Add player result
      </button>
    </div>
  );
}
