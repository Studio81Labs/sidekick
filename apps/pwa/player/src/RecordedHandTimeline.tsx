import type { ImportedHandState, PlayerHandDetail } from "./playerApi";
import { unitIntervalPercentage } from "./playerDecimal";

interface RecordedState {
  label: string;
  state: ImportedHandState;
}

function readable(value: string): string {
  return value.replace(/_/g, " ");
}

function playerLabel(state: ImportedHandState, playerId: string): string {
  const seat = state.seats.find((item) => item.player_id === playerId);
  return seat?.display_name
    ? seat.display_name + " (" + playerId + ")"
    : playerId;
}

function positionLabel(
  position: ImportedHandState["seats"][number]["position"],
): string {
  if (position === null) return "not recorded";
  return (
    position.display_label +
    " · dealt-in player count " +
    position.dealt_in_player_count +
    " · action index " +
    position.action_index +
    " · button distance " +
    position.button_distance
  );
}

function lineLocation(evidence: {
  raw_source_id: string;
  line_start: number | null;
  line_end: number | null;
  marker: string | null;
}): string {
  const location =
    evidence.line_start === null
      ? "no line retained"
      : evidence.line_end === null || evidence.line_end === evidence.line_start
        ? "line " + evidence.line_start
        : "lines " + evidence.line_start + "-" + evidence.line_end;
  return (
    evidence.raw_source_id +
    " · " +
    location +
    (evidence.marker === null ? "" : " · marker " + evidence.marker)
  );
}

function amount(value: string | null, unit: string): string {
  return value === null ? "not recorded" : value + " " + unit;
}

function percentage(value: string | null): string {
  if (value === null) return "not recorded";
  const formatted = unitIntervalPercentage(value);
  return formatted === null ? "unavailable" : formatted + "%";
}

function cardLabel(card: { rank: string; suit: string }): string {
  return card.rank + " of " + card.suit;
}

const EXPECTED_BOARD_CARD_COUNTS = {
  preflop: 0,
  flop: 3,
  turn: 4,
  river: 5,
} as const;

function boardLabel(street: ImportedHandState["streets"][number]): string {
  const expectedCount = EXPECTED_BOARD_CARD_COUNTS[street.street];
  if (street.board_cards.length === 0) {
    return expectedCount === 0
      ? "not recorded"
      : `not recorded · incomplete board (0 of ${expectedCount} cards)`;
  }
  const cards = street.board_cards.map(cardLabel).join(", ");
  return street.board_cards.length < expectedCount
    ? `${cards} · incomplete board (${street.board_cards.length} of ${expectedCount} cards)`
    : cards;
}

function handAmountUnit(state: ImportedHandState): string {
  if (state.game.economics.kind === "tournament") {
    return "chips";
  }
  return state.game.economics.kind === "cash"
    ? (state.game.economics.currency ?? "units not recorded")
    : "units not recorded";
}

function monetaryAmountUnit(state: ImportedHandState): string {
  return state.game.economics.kind === "unknown"
    ? "currency not recorded"
    : (state.game.economics.currency ?? "currency not recorded");
}

function hasRecordedTimelineState(state: ImportedHandState): boolean {
  return (
    state.game !== undefined &&
    Array.isArray(state.seats) &&
    Array.isArray(state.streets)
  );
}

function recordedStates(detail: PlayerHandDetail): RecordedState[] {
  return [
    ...detail.detections.map((detection) => ({
      label: "Detected proposal " + detection.detection_id,
      state: detection.state,
    })),
    ...detail.canonical_revisions.map((revision) => ({
      label: "Approved canonical revision " + revision.revision,
      state: revision.state,
    })),
  ].filter(({ state }) => hasRecordedTimelineState(state));
}

function RecordedEconomics({
  state,
  handUnit,
  monetaryUnit,
}: {
  state: ImportedHandState;
  handUnit: string;
  monetaryUnit: string;
}): JSX.Element {
  const { blinds, economics } = state.game;
  return (
    <section>
      <h6>Recorded game and economics</h6>
      <p>
        Blinds: small {amount(blinds.small_blind, handUnit)} · big{" "}
        {amount(blinds.big_blind, handUnit)} · ante{" "}
        {amount(blinds.ante, handUnit)} · ante mode {readable(blinds.ante_mode)}{" "}
        · straddle {amount(blinds.straddle, handUnit)}
      </p>
      {economics.kind === "cash" ? (
        <p>
          Cash economics · currency {economics.currency ?? "not recorded"} ·{" "}
          rake percentage {percentage(economics.rake?.percentage ?? null)} · cap{" "}
          {amount(economics.rake?.cap ?? null, monetaryUnit)} · fixed drop{" "}
          {amount(economics.rake?.fixed_drop ?? null, monetaryUnit)}
          {economics.rake?.description
            ? " · " + economics.rake.description
            : ""}
        </p>
      ) : economics.kind === "tournament" ? (
        <>
          <p>
            Tournament economics · currency{" "}
            {economics.currency ?? "not recorded"} · id{" "}
            {economics.tournament_id ?? "not recorded"} · type{" "}
            {economics.tournament_type ?? "not recorded"} · stage{" "}
            {economics.stage ?? "not recorded"} · buy-in{" "}
            {amount(economics.entry_buy_in, monetaryUnit)} · fee{" "}
            {amount(economics.entry_fee, monetaryUnit)} · blind level{" "}
            {economics.blind_level ?? "not recorded"}
          </p>
          <p>
            Paid places {economics.paid_places ?? "not recorded"} · players
            remaining {economics.players_remaining ?? "not recorded"} · ICM
            inputs {economics.icm_inputs_complete ? "complete" : "partial"} ·{" "}
            payouts{" "}
            {economics.payouts.length === 0
              ? "not recorded"
              : economics.payouts
                  .map((payout) => {
                    const values = [
                      payout.amount === null
                        ? null
                        : amount(payout.amount, monetaryUnit),
                      payout.share === null ? null : payout.share + " share",
                    ].filter((value): value is string => value !== null);
                    return (
                      payout.place_from +
                      "-" +
                      payout.place_to +
                      ": " +
                      (values.length === 0
                        ? "not recorded"
                        : values.join(" · "))
                    );
                  })
                  .join(", ")}
          </p>
          <p>
            Remaining stacks{" "}
            {economics.remaining_stacks.length === 0
              ? "not recorded"
              : economics.remaining_stacks
                  .map(
                    (stack) =>
                      playerLabel(state, stack.player_id) +
                      ": " +
                      amount(stack.stack, handUnit),
                  )
                  .join(", ")}
          </p>
          <p>
            Bounty format {economics.bounty_format ?? "not recorded"} · bounties{" "}
            {economics.bounties.length === 0
              ? "not recorded"
              : economics.bounties
                  .map(
                    (bounty) =>
                      playerLabel(state, bounty.player_id) +
                      ": " +
                      amount(bounty.value, monetaryUnit),
                  )
                  .join(", ")}
          </p>
        </>
      ) : (
        <p>
          Economics are unknown
          {economics.reason ? " · " + economics.reason : ""}.
        </p>
      )}
    </section>
  );
}

function RecordedChronology({
  chronology,
}: {
  chronology: ImportedHandState["chronology"];
}): JSX.Element {
  return (
    <section>
      <h6>Recorded chronology</h6>
      <p>
        Played at {chronology.played_at ?? "not recorded"} · source timezone{" "}
        {chronology.source_timezone ?? "not recorded"} · source session{" "}
        {chronology.source_session_id ?? "not recorded"} · source file{" "}
        {chronology.source_file_id} · hand ordinal{" "}
        {chronology.hand_ordinal ?? "not recorded"}
      </p>
    </section>
  );
}

function RecordedStateTimeline({ label, state }: RecordedState): JSX.Element {
  const handUnit = handAmountUnit(state);
  const monetaryUnit = monetaryAmountUnit(state);
  const hero =
    state.hero_player_id === null
      ? "Hero is not recorded"
      : playerLabel(state, state.hero_player_id);
  const statedPot = state.results?.stated_pot;
  return (
    <details className="recorded-state" open>
      <summary>{label}</summary>
      <div className="recorded-state-content">
        <p>
          {state.game.variant.replace(/_/g, " ")} ·{" "}
          {readable(state.game.betting_limit)} · {state.game.table_size}-max ·
          button seat {state.button_seat ?? "not recorded"}
        </p>
        <p>
          Hero: <strong>{hero}</strong>
          {state.hero_cards.length > 0
            ? " · cards " +
              state.hero_cards.map(cardLabel).join(", ") +
              (state.hero_cards.length === 1
                ? " · incomplete holding (1 of 2 cards)"
                : "")
            : " · cards not recorded"}
        </p>
        <RecordedChronology chronology={state.chronology} />
        <RecordedEconomics
          state={state}
          handUnit={handUnit}
          monetaryUnit={monetaryUnit}
        />
        <section>
          <h6>Seats</h6>
          <ul>
            {state.seats.map((seat) => (
              <li key={seat.player_id}>
                Seat {seat.seat_number} · {playerLabel(state, seat.player_id)} ·{" "}
                {readable(seat.participation)} · stack{" "}
                {amount(seat.starting_stack, handUnit)} · position{" "}
                {positionLabel(seat.position)}
              </li>
            ))}
          </ul>
        </section>
        <section>
          <h6>Recorded action timeline</h6>
          {state.streets.map((street) => (
            <section className="recorded-street" key={street.street}>
              <h6>
                {readable(street.street)} · board {boardLabel(street)}
              </h6>
              {street.actions.length === 0 ? (
                <p>No actions were recorded for this street.</p>
              ) : (
                <ol>
                  {street.actions.map((action) => (
                    <li key={action.sequence}>
                      <strong>
                        {playerLabel(state, action.actor_id)} ·{" "}
                        {readable(action.action_type)}
                      </strong>
                      <span>
                        Incremental amount: {amount(action.amount, handUnit)} ·
                        total committed:{" "}
                        {amount(action.total_committed, handUnit)}
                        {action.all_in ? " · all-in" : ""}
                      </span>
                      <span>
                        Origin: {readable(action.origin.kind)} ·{" "}
                        {readable(action.origin.basis)}
                        {action.origin.automatic_reason === null
                          ? ""
                          : " · " + readable(action.origin.automatic_reason)}
                        {action.origin.confidence === null
                          ? " · confidence not recorded"
                          : " · confidence " + action.origin.confidence}
                        {action.origin.semantics_revision === null
                          ? ""
                          : " · semantics " + action.origin.semantics_revision}
                        {action.origin.review_reference === null
                          ? ""
                          : " · review " + action.origin.review_reference}
                      </span>
                      <ul className="recorded-evidence">
                        {action.evidence.map((evidence, index) => (
                          <li key={evidence.raw_source_id + "-" + index}>
                            Action evidence: {lineLocation(evidence)}
                          </li>
                        ))}
                        {action.origin.evidence.map((evidence, index) => (
                          <li key={evidence.raw_source_id + "-origin-" + index}>
                            Origin evidence: {lineLocation(evidence)}
                          </li>
                        ))}
                      </ul>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          ))}
        </section>
        <section>
          <h6>Recorded results</h6>
          {statedPot === null || statedPot === undefined ? (
            <p>No stated pot or rake total was recorded.</p>
          ) : (
            <p>
              Gross pot: {amount(statedPot.gross_total, handUnit)} · rake:{" "}
              {amount(statedPot.rake, handUnit)} · net pot:{" "}
              {amount(statedPot.net_total, handUnit)}
              {statedPot.gross_pots.length > 0
                ? " · gross components " +
                  statedPot.gross_pots
                    .map((item) => item + " " + handUnit)
                    .join(", ")
                : ""}
            </p>
          )}
          {state.results === null || state.results.awards.length === 0 ? (
            <p>No awards were recorded.</p>
          ) : (
            <ul>
              {state.results.awards.map((award, index) => (
                <li key={award.player_id + "-" + (award.pot_index ?? index)}>
                  Award to {playerLabel(state, award.player_id)} ·{" "}
                  {amount(award.amount, handUnit)} · pot{" "}
                  {award.pot_index ?? "not recorded"}
                  <ul className="recorded-evidence">
                    {award.evidence.map((evidence, evidenceIndex) => (
                      <li
                        key={evidence.raw_source_id + "-award-" + evidenceIndex}
                      >
                        Award evidence: {lineLocation(evidence)}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          {state.results === null || state.results.showdown.length === 0 ? (
            <p>No showdown was recorded.</p>
          ) : (
            <ul>
              {state.results.showdown.map((showdown) => (
                <li key={showdown.player_id}>
                  {playerLabel(state, showdown.player_id)} ·{" "}
                  {readable(showdown.disposition)}
                  {showdown.cards.length > 0
                    ? " · cards " +
                      showdown.cards.map(cardLabel).join(", ") +
                      (showdown.cards.length === 1
                        ? " · incomplete holding (1 of 2 cards)"
                        : "")
                    : " · cards not recorded"}
                  <ul className="recorded-evidence">
                    {showdown.evidence.map((evidence, evidenceIndex) => (
                      <li
                        key={
                          evidence.raw_source_id + "-showdown-" + evidenceIndex
                        }
                      >
                        Showdown evidence: {lineLocation(evidence)}
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
          {state.results === null || state.results.players.length === 0 ? (
            <p>No player-result totals were recorded.</p>
          ) : (
            <ul>
              {state.results.players.map((player) => (
                <li key={player.player_id}>
                  {playerLabel(state, player.player_id)} · net result{" "}
                  {amount(player.net_result, handUnit)} · collected{" "}
                  {amount(player.total_collected, handUnit)}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </details>
  );
}

/** A complete, read-only rendering of retained detected and approved states. */
export function RecordedHandTimeline({
  detail,
}: {
  detail: PlayerHandDetail;
}): JSX.Element {
  const states = recordedStates(detail);
  return (
    <section className="audit-block recorded-hand-timeline">
      <h4>Recorded hand timeline</h4>
      <p>
        Detected proposals and approved revisions are shown separately. Amounts
        remain exactly as recorded; missing, partial, and unknown facts are not
        inferred.
      </p>
      {states.length === 0 ? (
        <p>No recorded hand state remains for this lifecycle record.</p>
      ) : (
        states.map((recorded) => (
          <RecordedStateTimeline key={recorded.label} {...recorded} />
        ))
      )}
    </section>
  );
}
