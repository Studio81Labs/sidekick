import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import recordedHandState from "./fixtures/recordedHandState.json";
import { RecordedHandTimeline } from "./RecordedHandTimeline";
import type { ImportedHandState, PlayerHandDetail } from "./playerApi";

const backendProducedState = recordedHandState as ImportedHandState;

describe("RecordedHandTimeline", () => {
  afterEach(cleanup);

  it("shows known currency for sparse tournament economics", () => {
    const sparseTournamentState: ImportedHandState = {
      ...backendProducedState,
      game: {
        ...backendProducedState.game,
        economics: {
          kind: "tournament",
          tournament_id: null,
          tournament_type: null,
          stage: null,
          entry_buy_in: null,
          entry_fee: null,
          blind_level: null,
          currency: "EUR",
          paid_places: null,
          players_remaining: null,
          payouts: [],
          remaining_stacks: [],
          bounty_format: null,
          bounties: [],
          icm_inputs_complete: false,
        },
      },
    };
    const detail = {
      detections: [
        {
          detection_id: "detection-1",
          state: backendProducedState,
        },
      ],
      canonical_revisions: [
        {
          revision: 1,
          state: sparseTournamentState,
        },
      ],
    } as PlayerHandDetail;

    render(<RecordedHandTimeline detail={detail} />);

    expect(
      screen.getByText(
        /Tournament economics · currency EUR · id not recorded · type not recorded · stage not recorded · buy-in not recorded · fee not recorded/,
      ),
    ).toBeInTheDocument();
  });

  it("keeps detected and approved states distinct without coercing decimal strings", () => {
    const detectedState: ImportedHandState = {
      ...backendProducedState,
      hero_player_id: null,
      hero_cards: [],
      chronology: {
        ...backendProducedState.chronology,
        played_at: "2026-09-11T10:00:00Z",
        source_timezone: "Europe/Prague",
        source_session_id: "detected-session",
        source_file_id: "detected-file",
        hand_ordinal: 7,
      },
      results: {
        stated_pot: backendProducedState.results?.stated_pot ?? null,
        awards: [
          { player_id: "hero", amount: "1", pot_index: 1, evidence: [] },
          { player_id: "hero", amount: "2", pot_index: null, evidence: [] },
        ],
        players: backendProducedState.results?.players ?? [],
        showdown: [
          {
            player_id: "villain",
            cards: [],
            disposition: "shown",
            evidence: [
              {
                raw_source_id: "file-1",
                line_start: 1,
                line_end: 1,
                marker: null,
              },
            ],
          },
        ],
      },
      streets: backendProducedState.streets.map((street) => {
        if (street.street === "preflop") {
          return {
            ...street,
            actions: street.actions.map((action, index) =>
              index === 0
                ? {
                    ...action,
                    evidence: [
                      {
                        raw_source_id: "file-1",
                        line_start: null,
                        line_end: null,
                        marker: null,
                      },
                    ],
                  }
                : action,
            ),
          };
        }
        return street.street === "flop"
          ? {
              ...street,
              board_cards: [{ rank: "Q", suit: "clubs" }],
            }
          : street;
      }),
      seats: backendProducedState.seats.map((seat) =>
        seat.player_id === "hero"
          ? {
              ...seat,
              position: {
                dealt_in_player_count: 2,
                action_index: 0,
                button_distance: 0,
                display_label: "BTN/SB",
              },
            }
          : seat.player_id === "villain"
            ? { ...seat, participation: "sitting_out" }
            : seat,
      ),
    };
    const approvedTournamentState: ImportedHandState = {
      ...backendProducedState,
      hero_cards: [backendProducedState.hero_cards[0]],
      results: {
        stated_pot: backendProducedState.results?.stated_pot ?? null,
        awards: backendProducedState.results?.awards ?? [],
        players: backendProducedState.results?.players ?? [],
        showdown: [
          {
            player_id: "hero",
            cards: [{ rank: "A", suit: "hearts" }],
            disposition: "shown",
            evidence: [],
          },
        ],
      },
      chronology: {
        ...backendProducedState.chronology,
        played_at: "2026-09-11T11:00:00Z",
        source_timezone: "America/Los_Angeles",
        source_session_id: "reviewed-session",
        source_file_id: "reviewed-file",
        hand_ordinal: 8,
      },
      game: {
        ...backendProducedState.game,
        economics: {
          kind: "tournament",
          tournament_id: "tournament-1",
          tournament_type: "progressive knockout",
          stage: "final table",
          entry_buy_in: "20",
          entry_fee: "2",
          blind_level: "10",
          currency: "USD",
          paid_places: 2,
          players_remaining: 2,
          payouts: [
            { place_from: 1, place_to: 1, amount: "100", share: "0.5" },
          ],
          remaining_stacks: [
            { player_id: "hero", stack: "120" },
            { player_id: "villain", stack: "80" },
          ],
          bounty_format: "progressive knockout",
          bounties: [
            { player_id: "hero", value: "15" },
            { player_id: "villain", value: null },
          ],
          icm_inputs_complete: false,
        },
      },
    };
    const detail = {
      detections: [
        {
          detection_id: "detection-1",
          state: detectedState,
        },
      ],
      canonical_revisions: [
        {
          revision: 2,
          state: approvedTournamentState,
        },
      ],
    } as PlayerHandDetail;

    render(<RecordedHandTimeline detail={detail} />);

    expect(screen.getByText("Recorded hand timeline")).toBeInTheDocument();
    expect(
      screen.getByText("Detected proposal detection-1"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Approved canonical revision 2"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Hero is not recorded/)).toBeInTheDocument();
    expect(
      screen.getAllByText(
        /cards A of hearts · incomplete holding \(1 of 2 cards\)/,
      ),
    ).toHaveLength(2);
    expect(
      screen.getByText(/villain \(display name not recorded\) · sitting out/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /BTN\/SB · dealt-in player count 2 · action index 0 · button distance 0/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Played at 2026-09-11T10:00:00Z · source timezone Europe\/Prague · source session detected-session · source file detected-file · hand ordinal 7/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Played at 2026-09-11T11:00:00Z · source timezone America\/Los_Angeles · source session reviewed-session · source file reviewed-file · hand ordinal 8/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(
        /Incremental amount: 0.5 USD · total committed: 0.5 USD/,
      ),
    ).toHaveLength(1);
    expect(
      screen.getAllByText(
        /Incremental amount: 0.5 chips · total committed: 0.5 chips/,
      ),
    ).toHaveLength(1);
    expect(
      screen.getAllByText(/client automatic · explicit marker · timeout/),
    ).toHaveLength(4);
    expect(
      screen.getByText(
        /Action evidence: file-1 · source excerpt redacted; no visible locator retained/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/Gross pot: 2 USD/)).toHaveLength(1);
    expect(screen.getAllByText(/Gross pot: 2 chips/)).toHaveLength(1);
    expect(screen.getAllByText(/gross components not recorded/)).toHaveLength(
      2,
    );
    expect(
      screen.getByText(/Cash economics · currency USD · rake percentage 5%/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /villain \(display name not recorded\) · shown · cards not recorded/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /hero \(display name not recorded\) · shown · cards A of hearts · incomplete holding \(1 of 2 cards\)/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/preflop · board no board cards/)).toHaveLength(
      2,
    );
    expect(
      screen.getByText(
        /Award to hero \(display name not recorded\) · 1 USD · pot 1/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Award to hero \(display name not recorded\) · 2 USD · pot not recorded/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /flop · board Q of clubs · incomplete board \(1 of 3 cards\)/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Tournament economics · currency USD · id tournament-1/),
    ).toBeInTheDocument();
    expect(screen.getByText(/buy-in 20 USD · fee 2 USD/)).toBeInTheDocument();
    expect(
      screen.getByText(/payouts 1-1: 100 USD · 0.5 share/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Remaining stacks hero \(display name not recorded\): 120 chips, villain \(display name not recorded\): 80 chips/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Bounty format progressive knockout · bounties hero \(display name not recorded\): 15 USD, villain \(display name not recorded\): not recorded/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText(/No awards were recorded/)).toHaveLength(1);
  });
});
