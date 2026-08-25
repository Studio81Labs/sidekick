import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { JobRecord } from "../../../shared/types/jobs";
import {
  AnalyzerTestApp as App,
  recommendation,
  recommendationWithEvidence,
  recommendedJob,
} from "../../../test/analyzerHarness";

describe("Analyzer recommendations", () => {
  it("shows normalized decision evidence for solver recommendations", async () => {
    const evidenceJob: JobRecord = {
      ...recommendedJob(),
      id: "evidence-job",
      original_filename: "evidence.png",
      image_filename: "evidence.png",
      recommendation: recommendationWithEvidence,
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: evidenceJob.id,
          job: evidenceJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    expect(within(evidence).getByText("Local EV solver")).toBeInTheDocument();
    expect(
      within(evidence).getByText("Postflop solver fallback"),
    ).toBeInTheDocument();
    expect(within(evidence).getByText("61%")).toBeInTheDocument();
    expect(within(evidence).getByText("55%")).toBeInTheDocument();
    expect(within(evidence).getByText("20%")).toBeInTheDocument();
    expect(within(evidence).getByText("EV 2.4 BB")).toBeInTheDocument();
    expect(within(evidence).getByText("72% frequency")).toBeInTheDocument();
    expect(
      within(evidence).getByText("Field folds 9% · each 30%"),
    ).toBeInTheDocument();
    expect(within(evidence).getByText("At current wager")).toBeInTheDocument();
    expect(
      within(evidence).getByText(
        "1 opponent · 10 BB committed · 13 BB total · hero 1 BB",
      ),
    ).toBeInTheDocument();
    const chosen = within(evidence)
      .getByText("Chosen")
      .closest('[role="listitem"]');
    expect(chosen).toHaveTextContent("raise");
    expect(chosen).toHaveTextContent("7.5 BB");
    expect(within(evidence).getAllByRole("listitem")).toHaveLength(4);
    expect(within(evidence).queryByText("invalid")).not.toBeInTheDocument();
    expect(
      within(evidence).getByLabelText("Decision context"),
    ).toBeInTheDocument();
    expect(
      within(evidence).queryByLabelText("Modeled ranges"),
    ).not.toBeInTheDocument();
  });

  it("shows postflop tree assumptions and expandable ranges", async () => {
    const longOopRange = `${"AA,".repeat(90)}AKs`;
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "postflop-solver-job",
      original_filename: "postflop.png",
      image_filename: "postflop.png",
      recommendation: {
        action: "call",
        sizing: null,
        confidence: 0.81,
        explanation: "The postflop solver recommends calling at 64% frequency.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          modeled_history: ["OOP bet 2.50 BB"],
          range_source: "preflop_chart_single_raised_pot",
          range_context: {
            scenario: "single_raised_pot",
            opener_position: "button",
            caller_position: "big_blind",
            opening_size_bb: 2.5,
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            decision_street: "turn",
            completed_street_count: 1,
            opener_fraction: 0.45,
            caller_continue_fraction: 0.4,
            caller_reraise_fraction: 0.12,
          },
          range_conditioning: {
            status: "applied",
            mode: "flop_root_posterior",
            decision_street: "turn",
            completed_streets: ["flop"],
            modeled_history: ["OOP check", "IP check", "deal Qs"],
            downstream_tree: "single_bet_no_raises",
            active_hands: { oop: 131, ip: 236 },
            hero_line_reach: 0.39559,
            compressed_memory_mb: 175.2,
            exploitability: { bb: 2.8216, pot_ratio: 0.51301 },
          },
          tree: {
            starting_pot: 10,
            effective_stack: 95,
            compressed_memory_mb: 34.6,
            max_iterations: 400,
            target_exploitability_ratio: 0.01,
          },
          ranges: {
            oop: longOopRange,
            ip: "QQ-22,AQs-A2s,ATo+",
          },
          exploitability: { bb: 0.12 },
          candidates: [
            { action: "fold", sizing: null, frequency: 0.1, ev: 0 },
            { action: "call", sizing: null, frequency: 0.64, ev: 2.4 },
            { action: "raise", sizing: 8, frequency: 0.26, ev: 2.1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    expect(within(evidence).getByText("Postflop solver")).toBeInTheDocument();
    expect(within(evidence).getByText("0.12 BB")).toBeInTheDocument();
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(within(decisionContext).getByText("IP")).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("OOP bet 2.50 BB"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("10 BB pot · 95 BB stack"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("400 iterations · 34.6 MB estimate"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("1% pot exploitability"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Preflop chart · single-raised pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Turn · 1 completed street"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Button opens 2.5 BB · Big blind calls",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Open 45% · flat 12%-40%"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Applied · Flop → Turn"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("OOP check → IP check → deal Qs"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Hero 39.6% · OOP 131 combos · IP 236 combos",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Single bet no raises · 175.2 MB estimate · 2.822 BB exploitability",
      ),
    ).toBeInTheDocument();

    const modeledRanges = within(evidence).getByLabelText("Modeled ranges");
    expect(modeledRanges).not.toHaveAttribute("open");
    await user.click(within(modeledRanges).getByText("Modeled ranges"));
    expect(modeledRanges).toHaveAttribute("open");
    expect(within(modeledRanges).getByText(longOopRange)).toBeVisible();
    expect(within(modeledRanges).getByText("QQ-22,AQs-A2s,ATo+")).toBeVisible();
  });

  it("shows why later-street range conditioning was skipped", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "postflop-conditioning-skipped-job",
      original_filename: "conditioning-skipped.png",
      image_filename: "conditioning-skipped.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.72,
        explanation:
          "The postflop solver recommends checking with the selected starting ranges.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          range_conditioning: {
            status: "skipped",
            reason: "conditioning tree exceeds the configured memory limit",
            estimated_compressed_memory_mb: 812.4,
            max_memory_mb: 768,
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText(
        "Skipped · conditioning tree exceeds the configured memory limit",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("812.4 MB estimate · 768 MB limit"),
    ).toBeInTheDocument();
  });

  it("shows contextual limped-pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "limped-postflop-job",
      original_filename: "limped-postflop.png",
      image_filename: "limped-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "oop",
          range_source: "preflop_chart_limped_pot",
          range_context: {
            scenario: "limped_pot",
            limper_position: "button",
            big_blind_position: "big_blind",
            limp_size_bb: 1,
            limper_range_model: "stack_adjusted_first_in_proxy",
            limp_response_policy: "heads_up_single_limper",
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            decision_street: "turn",
            completed_street_count: 1,
            limper_fraction: 0.45,
            big_blind_raise_fraction: 0.36,
          },
          ranges: {
            oop: "72o-32o",
            ip: "AA-77,AKs-AJs",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · limped pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Turn · 1 completed street"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Button limps 1 BB · Big blind checks"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Limper uses stack-adjusted first-in proxy",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Entry 45% · BB check 36%-100%"),
    ).toBeInTheDocument();
  });

  it("shows contextual isolation-raised-pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "isolation-raised-postflop-job",
      original_filename: "isolation-raised-postflop.png",
      image_filename: "isolation-raised-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "oop",
          range_source: "preflop_chart_isolation_raised_pot",
          range_context: {
            scenario: "isolation_raised_pot",
            limper_position: "button",
            isolation_raiser_position: "big_blind",
            limp_size_bb: 1,
            isolation_raise_size_bb: 4,
            limp_response_policy: "heads_up_single_limper",
            isolation_response_policy: "heads_up_after_hero_limp",
            isolation_raise_size_policy: "standard",
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            isolation_raiser_fraction: 0.36,
            limper_continue_fraction: 0.19,
            limper_reraise_fraction: 0.06,
          },
          ranges: {
            oop: "AA-22,AKs-A2s",
            ip: "KJs-76s,AQo-ATo",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · isolation-raised pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Button limps 1 BB · Big blind raises 4 BB · Button calls",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("BB isolate 36% · limper call 6%-19%"),
    ).toBeInTheDocument();
  });

  it("shows contextual limp-reraised-pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "limp-reraised-postflop-job",
      original_filename: "limp-reraised-postflop.png",
      image_filename: "limp-reraised-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          range_source: "preflop_chart_limp_reraised_pot",
          range_context: {
            scenario: "limp_reraised_pot",
            limper_position: "utg",
            isolation_raiser_position: "button",
            limp_reraiser_position: "utg",
            limp_size_bb: 1,
            isolation_raise_size_bb: 4,
            limp_reraise_size_bb: 12,
            limp_reraise_to_isolation_ratio: 3,
            isolation_response_policy: "heads_up_after_hero_limp",
            limp_reraise_response_policy: "heads_up_original_limper_reraise",
            isolation_raise_size_policy: "standard",
            limp_reraise_size_policy: "large",
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            limper_reraise_fraction: 0.045,
            isolation_raiser_continue_fraction: 0.045,
            isolation_raiser_four_bet_fraction: 0.0209,
          },
          ranges: {
            oop: "AA-QQ,AKs",
            ip: "JJ-TT,AQs",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · limp-reraised pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "UTG limps 1 BB · Button isolates 4 BB · UTG reraises 12 BB · Button calls",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Limper reraise 4.5% · isolator call 2.1%-4.5%",
      ),
    ).toBeInTheDocument();
  });

  it("shows contextual three-bet pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "three-bet-postflop-job",
      original_filename: "three-bet-postflop.png",
      image_filename: "three-bet-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          range_source: "preflop_chart_three_bet_pot",
          range_context: {
            scenario: "three_bet_pot",
            opener_position: "button",
            three_bettor_position: "big_blind",
            opening_size_bb: 2.5,
            three_bet_size_bb: 8,
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "standard_assumption",
            three_bettor_fraction: 0.12,
            opener_continue_fraction: 0.18,
            opener_four_bet_fraction: 0.065,
          },
          ranges: {
            oop: "AA-77,AKs-AJs",
            ip: "JJ-66,AQs-ATs",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · 3-bet pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB assumed"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Button opens 2.5 BB · Big blind 3-bets 8 BB · Button calls",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("3-bet 12% · flat 6.5%-18%"),
    ).toBeInTheDocument();
  });

  it("shows contextual cold-call three-bet pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "cold-three-bet-postflop-job",
      original_filename: "cold-three-bet-postflop.png",
      image_filename: "cold-three-bet-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          range_source: "preflop_chart_cold_three_bet_pot",
          range_context: {
            scenario: "cold_three_bet_pot",
            folded_opener_position: "utg",
            folded_opener_commitment_bb: 2.5,
            three_bettor_position: "cutoff",
            cold_caller_position: "button",
            opening_size_bb: 2.5,
            three_bet_size_bb: 8,
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            decision_street: "turn",
            completed_street_count: 1,
            three_bettor_fraction: 0.05,
            cold_caller_continue_fraction: 0.05,
            cold_caller_four_bet_fraction: 0.02,
          },
          ranges: {
            oop: "AA-77,AKs-AJs",
            ip: "JJ-66,AQs-ATs",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · cold-call 3-bet pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Turn · 1 completed street"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "UTG opens 2.5 BB · Cutoff 3-bets 8 BB · Button cold-calls · UTG folds 2.5 BB dead",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("3-bet 5% · cold-call 2%-5%"),
    ).toBeInTheDocument();
  });

  it("shows contextual squeeze pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "squeeze-postflop-job",
      original_filename: "squeeze-postflop.png",
      image_filename: "squeeze-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          range_source: "preflop_chart_squeeze_pot",
          range_context: {
            scenario: "squeeze_pot",
            folded_opener_position: "utg",
            folded_opener_commitment_bb: 2.5,
            caller_position: "button",
            squeezer_position: "small_blind",
            opening_size_bb: 2.5,
            squeeze_size_bb: 10,
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            decision_street: "turn",
            completed_street_count: 1,
            squeezer_fraction: 0.045,
            caller_continue_fraction: 0.0405,
            caller_four_bet_fraction: 0.019,
          },
          ranges: {
            oop: "AA-77,AKs-AJs",
            ip: "JJ-66,AQs-ATs",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · squeeze pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Turn · 1 completed street"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "UTG opens 2.5 BB · Button calls · Small blind squeezes 10 BB · Button calls · UTG folds 2.5 BB dead",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Squeeze 4.5% · call 1.9%-4%"),
    ).toBeInTheDocument();
  });

  it("shows contextual four-bet pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "four-bet-postflop-job",
      original_filename: "four-bet-postflop.png",
      image_filename: "four-bet-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          range_source: "preflop_chart_four_bet_pot",
          range_context: {
            scenario: "four_bet_pot",
            opener_position: "button",
            three_bettor_position: "big_blind",
            opening_size_bb: 2.5,
            three_bet_size_bb: 8,
            four_bet_size_bb: 20,
            stack_depth_policy: "medium",
            starting_effective_stack_bb: 50,
            stack_depth_source: "reconstructed",
            opener_four_bet_fraction: 0.0747,
            three_bettor_continue_fraction: 0.0665,
            three_bettor_five_bet_fraction: 0.0437,
          },
          ranges: {
            oop: "JJ-77,AQs-AJs",
            ip: "AA-JJ,AKs",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · 4-bet pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Medium · 50 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "Button opens 2.5 BB · Big blind 3-bets 8 BB · Button 4-bets 20 BB · Big blind calls",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("4-bet 7.5% · flat 4.4%-6.7%"),
    ).toBeInTheDocument();
  });

  it("shows contextual cold four-bet pot range assumptions", async () => {
    const postflopJob: JobRecord = {
      ...recommendedJob(),
      id: "cold-four-bet-postflop-job",
      original_filename: "cold-four-bet-postflop.png",
      image_filename: "cold-four-bet-postflop.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.8,
        explanation: "The postflop solver recommends checking.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "ip",
          range_source: "preflop_chart_cold_four_bet_pot",
          range_context: {
            scenario: "cold_four_bet_pot",
            folded_opener_position: "utg",
            folded_opener_commitment_bb: 2.5,
            three_bettor_position: "cutoff",
            cold_four_bettor_position: "button",
            opening_size_bb: 2.5,
            three_bet_size_bb: 8,
            four_bet_size_bb: 20,
            stack_depth_policy: "standard",
            starting_effective_stack_bb: 100,
            stack_depth_source: "reconstructed",
            cold_four_bettor_four_bet_fraction: 0.02,
            three_bettor_continue_fraction: 0.027,
            three_bettor_five_bet_fraction: 0.016,
          },
          ranges: {
            oop: "QQ,JJ",
            ip: "AA,KK,QQ",
          },
          candidates: [{ action: "check", sizing: null, frequency: 1, ev: 0 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: postflopJob.id,
          job: postflopJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const decisionContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(decisionContext).getByText("Preflop chart · cold 4-bet pot"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Standard · 100 BB starting"),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText(
        "UTG opens 2.5 BB · Cutoff 3-bets 8 BB · Button cold 4-bets 20 BB · UTG folds 2.5 BB dead · Cutoff calls",
      ),
    ).toBeInTheDocument();
    expect(
      within(decisionContext).getByText("Cold 4-bet 2% · flat 1.6%-2.7%"),
    ).toBeInTheDocument();
  });

  it("omits malformed postflop context while preserving valid evidence", async () => {
    const malformedJob: JobRecord = {
      ...recommendedJob(),
      id: "malformed-postflop-job",
      original_filename: "malformed.png",
      image_filename: "malformed.png",
      recommendation: {
        action: "check",
        sizing: null,
        confidence: 0.7,
        explanation: "Check remains available.",
        raw: {
          provider: "local_solver",
          engine: "postflop_solver",
          hero_position: "button",
          modeled_history: "OOP check",
          tree: {
            starting_pot: -1,
            effective_stack: -2,
            compressed_memory_mb: -1,
            max_iterations: 2.5,
            target_exploitability_ratio: 4,
          },
          range_conditioning: {
            status: "pending",
            hero_line_reach: 4,
            compressed_memory_mb: -10,
          },
          ranges: { oop: 42, ip: "" },
          candidates: [{ action: "check", sizing: null, frequency: 1 }],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        {
          id: malformedJob.id,
          job: malformedJob,
          savedAt: new Date().toISOString(),
        },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    expect(within(evidence).getByText("Postflop solver")).toBeInTheDocument();
    expect(within(evidence).getByText("100% frequency")).toBeInTheDocument();
    expect(
      within(evidence).queryByLabelText("Decision context"),
    ).not.toBeInTheDocument();
    expect(
      within(evidence).queryByLabelText("Modeled ranges"),
    ).not.toBeInTheDocument();
  });

  it("labels position-aware chart evidence without exposing its internal id", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "preflop-chart-job",
      original_filename: "preflop.png",
      image_filename: "preflop.png",
      recommendation: {
        action: "raise",
        sizing: 2.5,
        confidence: 0.74,
        explanation:
          "The position-aware preflop chart recommends raise to 2.5 BB.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          requested_engine: "postflop_solver",
          routing_reason: "the hand is preflop",
          hand_top_fraction: 0.28,
          policy_fraction: 0.45,
          stack_depth_policy: "standard",
          effective_stack: 100,
          base_open_fraction: 0.45,
          open_fraction: 0.45,
          target_open_size: 2.5,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 0 },
            { action: "raise", sizing: 2.5, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    expect(within(evidence).getByText("Preflop chart")).toBeInTheDocument();
    expect(
      within(evidence).getByText("Postflop solver route"),
    ).toBeInTheDocument();
    expect(
      within(evidence).queryByText("preflop_chart_v1"),
    ).not.toBeInTheDocument();
    expect(within(evidence).getByText("28%")).toBeInTheDocument();
    expect(within(evidence).getAllByText("45%")).toHaveLength(2);
    expect(within(evidence).getByText("100% frequency")).toBeInTheDocument();
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Standard · 100 BB"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("Opening range")).toBeInTheDocument();
    expect(within(chartContext).getByText("Open target")).toBeInTheDocument();
    expect(within(chartContext).getByText("2.5 BB")).toBeInTheDocument();
  });

  it("shows heads-up limp response chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "heads-up-limp-chart-job",
      original_filename: "heads-up-limp.png",
      image_filename: "heads-up-limp.png",
      recommendation: {
        action: "raise",
        sizing: 4,
        confidence: 0.82,
        explanation: "The preflop chart recommends an isolation raise to 4 BB.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.468,
          stack_depth_policy: "short",
          effective_stack: 20,
          limper_position: "button",
          limp_size: 1,
          limp_response_policy: "heads_up_single_limper",
          base_limp_raise_fraction: 0.36,
          limp_raise_fraction: 0.468,
          target_limp_raise_size: 4,
          maximum_limp_raise_total: 21,
          candidates: [
            { action: "check", sizing: null, frequency: 0 },
            { action: "raise", sizing: 4, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("Short · 20 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("Button")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Heads up single limper"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("46.8% (base 36%)"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("1 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("4 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("21 BB")).toBeInTheDocument();
  });

  it("shows two-limper big-blind chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "two-limper-chart-job",
      original_filename: "two-limpers.png",
      image_filename: "two-limpers.png",
      recommendation: {
        action: "raise",
        sizing: 5.25,
        confidence: 0.8,
        explanation: "The preflop chart recommends isolating two limpers.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.16,
          stack_depth_policy: "standard",
          effective_stack: 100,
          limper_positions: ["utg", "button"],
          limper_count: 2,
          limp_size: 1,
          multi_limp_response_policy: "big_blind_two_limpers",
          base_multi_limp_raise_fraction: 0.16,
          multi_limp_raise_fraction: 0.16,
          target_multi_limp_raise_size: 5.25,
          maximum_multi_limp_raise_total: 101,
          candidates: [
            { action: "check", sizing: null, frequency: 0 },
            { action: "raise", sizing: 5.25, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Standard · 100 BB"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("Limpers")).toBeInTheDocument();
    expect(within(chartContext).getByText("UTG · Button")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Big blind two limpers"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("16%")).toBeInTheDocument();
    expect(within(chartContext).getByText("1 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("5.25 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("101 BB")).toBeInTheDocument();
  });

  it("shows three-limper big-blind chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "three-limper-chart-job",
      original_filename: "three-limpers.png",
      image_filename: "three-limpers.png",
      recommendation: {
        action: "raise",
        sizing: 6.75,
        confidence: 0.8,
        explanation: "The preflop chart recommends isolating three limpers.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.12,
          stack_depth_policy: "standard",
          effective_stack: 100,
          limper_positions: ["utg", "cutoff", "button"],
          limper_count: 3,
          limp_size: 1,
          multi_limp_response_policy: "big_blind_three_limpers",
          base_multi_limp_raise_fraction: 0.12,
          multi_limp_raise_fraction: 0.12,
          target_multi_limp_raise_size: 6.75,
          maximum_multi_limp_raise_total: 101,
          candidates: [
            { action: "check", sizing: null, frequency: 0 },
            { action: "raise", sizing: 6.75, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Standard · 100 BB"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("Limpers")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("UTG · Cutoff · Button"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Big blind three limpers"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("12%")).toBeInTheDocument();
    expect(within(chartContext).getByText("1 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("6.75 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("101 BB")).toBeInTheDocument();
  });

  it("shows four-limper big-blind chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "four-limper-chart-job",
      original_filename: "four-limpers.png",
      image_filename: "four-limpers.png",
      recommendation: {
        action: "raise",
        sizing: 8.25,
        confidence: 0.8,
        explanation: "The preflop chart recommends isolating four limpers.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.075,
          stack_depth_policy: "standard",
          effective_stack: 100,
          limper_positions: ["utg", "hijack", "cutoff", "button"],
          limper_count: 4,
          limp_size: 1,
          multi_limp_response_policy: "big_blind_four_limpers",
          base_multi_limp_raise_fraction: 0.075,
          multi_limp_raise_fraction: 0.075,
          target_multi_limp_raise_size: 8.25,
          maximum_multi_limp_raise_total: 101,
          candidates: [
            { action: "check", sizing: null, frequency: 0 },
            { action: "raise", sizing: 8.25, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Standard · 100 BB"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("Limpers")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("UTG · Hijack · Cutoff · Button"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Big blind four limpers"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("7.5%")).toBeInTheDocument();
    expect(within(chartContext).getByText("1 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("8.25 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("101 BB")).toBeInTheDocument();
  });

  it("shows five-limper big-blind chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "five-limper-chart-job",
      original_filename: "five-limpers.png",
      image_filename: "five-limpers.png",
      recommendation: {
        action: "raise",
        sizing: 9,
        confidence: 0.8,
        explanation: "The preflop chart recommends isolating five limpers.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.06,
          stack_depth_policy: "standard",
          effective_stack: 100,
          limper_positions: [
            "utg",
            "hijack",
            "cutoff",
            "button",
            "small_blind",
          ],
          limper_count: 5,
          limp_size: 1,
          multi_limp_response_policy: "big_blind_five_limpers",
          base_multi_limp_raise_fraction: 0.06,
          multi_limp_raise_fraction: 0.06,
          target_multi_limp_raise_size: 9,
          maximum_multi_limp_raise_total: 101,
          candidates: [
            { action: "check", sizing: null, frequency: 0 },
            { action: "raise", sizing: 9, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Standard · 100 BB"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("Limpers")).toBeInTheDocument();
    expect(
      within(chartContext).getByText(
        "UTG · Hijack · Cutoff · Button · Small blind",
      ),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Big blind five limpers"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("6%")).toBeInTheDocument();
    expect(within(chartContext).getByText("1 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("9 BB")).toBeInTheDocument();
    expect(within(chartContext).getByText("101 BB")).toBeInTheDocument();
  });

  it("shows isolation-raise response chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "isolation-response-chart-job",
      original_filename: "isolation-response.png",
      image_filename: "isolation-response.png",
      recommendation: {
        action: "call",
        sizing: null,
        confidence: 0.8,
        explanation:
          "The preflop chart recommends continuing after the isolation raise.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0473,
          policy_fraction: 0.14,
          stack_depth_policy: "standard",
          effective_stack: 90,
          limper_position: "utg",
          limp_size: 1,
          isolation_raiser_position: "button",
          isolation_raise_size: 4,
          isolation_raise_to_limp_ratio: 4,
          isolation_raise_size_policy: "standard",
          isolation_response_policy: "heads_up_after_hero_limp",
          continue_fraction: 0.14,
          reraise_fraction: 0.045,
          maximum_reraise_total: 94,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 1 },
            { action: "raise", sizing: null, frequency: 0 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("Hero limper")).toBeInTheDocument();
    expect(within(chartContext).getByText("UTG")).toBeInTheDocument();
    expect(within(chartContext).getByText("Button")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("4 BB · 4x limp · Standard"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Heads up after hero limp"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 14% · Reraise 4.5%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("94 BB")).toBeInTheDocument();
    expect(within(chartContext).queryByText("Opener")).not.toBeInTheDocument();
    expect(
      within(chartContext).queryByText("3-bettor"),
    ).not.toBeInTheDocument();
  });

  it("shows original-limper reraise chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "limp-reraise-chart-job",
      original_filename: "limp-reraise.png",
      image_filename: "limp-reraise.png",
      recommendation: {
        action: "call",
        sizing: null,
        confidence: 0.8,
        explanation:
          "The preflop chart recommends continuing against the limp-reraise.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0355,
          policy_fraction: 0.045,
          stack_depth_policy: "standard",
          effective_stack: 88,
          limper_position: "utg",
          limp_size: 1,
          hero_isolation_raise_size: 4,
          limp_reraiser_position: "utg",
          limp_reraise_size: 12,
          limp_reraise_to_isolation_ratio: 3,
          limp_reraise_size_policy: "large",
          limp_reraise_response_policy: "heads_up_original_limper_reraise",
          continue_fraction: 0.045,
          four_bet_fraction: 0.0209,
          maximum_four_bet_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 1 },
            { action: "raise", sizing: null, frequency: 0 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Original limper"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Hero isolation"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("Limp reraiser")).toBeInTheDocument();
    expect(within(chartContext).getAllByText("UTG")).toHaveLength(2);
    expect(within(chartContext).getByText("4 BB")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("12 BB · 3x isolation · Large"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Heads up original limper reraise"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 4.5% · Four-bet 2.1%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
    expect(within(chartContext).queryByText("Opener")).not.toBeInTheDocument();
    expect(
      within(chartContext).queryByText("3-bettor"),
    ).not.toBeInTheDocument();
  });

  it("shows stack-aware facing-open chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "facing-open-chart-job",
      original_filename: "facing-open.png",
      image_filename: "facing-open.png",
      recommendation: {
        action: "raise",
        sizing: 3.6,
        confidence: 0.78,
        explanation:
          "The preflop chart recommends the stack-aware reraise line.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.1243,
          policy_fraction: 0.156,
          stack_depth_policy: "short",
          effective_stack: 20,
          opener_position: "button",
          base_opener_open_fraction: 0.45,
          opener_open_fraction: 0.405,
          opening_raise_size: 2.5,
          open_size_policy: "standard",
          continue_fraction: 0.36,
          reraise_fraction: 0.156,
          maximum_reraise_total: 3.6,
          candidates: [
            { action: "fold", sizing: null, frequency: 0.1 },
            { action: "call", sizing: null, frequency: 0.35 },
            { action: "raise", sizing: 3.6, frequency: 0.55 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("Short · 20 BB")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Button · 40.5% modeled (base 45%)"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("2.5 BB · Standard"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 36% · Reraise 15.6%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("3.6 BB")).toBeInTheDocument();
  });

  it("shows structured multi-caller chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "multi-caller-chart-job",
      original_filename: "multi-called-open.png",
      image_filename: "multi-called-open.png",
      recommendation: {
        action: "raise",
        sizing: 12.5,
        confidence: 0.78,
        explanation: "The preflop chart recommends a conservative squeeze.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.045,
          stack_depth_policy: "standard",
          effective_stack: 100,
          opener_position: "utg",
          opening_raise_size: 2.5,
          caller_positions: ["hijack", "cutoff"],
          caller_count: 2,
          caller_adjustment_policy: "double_caller_conservative",
          squeeze_open_multiple: 5,
          continue_fraction: 0.112,
          reraise_fraction: 0.0425,
          maximum_reraise_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 0 },
            { action: "raise", sizing: 12.5, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("UTG")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Hijack · Cutoff"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Double caller conservative · 5x squeeze"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 11.2% · Reraise 4.3%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
  });

  it("shows all three callers in a triple-caller chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "triple-caller-chart-job",
      original_filename: "triple-called-open.png",
      image_filename: "triple-called-open.png",
      recommendation: {
        action: "raise",
        sizing: 15,
        confidence: 0.8,
        explanation: "The preflop chart recommends a conservative squeeze.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.04,
          stack_depth_policy: "standard",
          effective_stack: 100,
          opener_position: "utg",
          opening_raise_size: 2.5,
          caller_positions: ["hijack", "cutoff", "button"],
          caller_count: 3,
          caller_adjustment_policy: "triple_caller_conservative",
          squeeze_open_multiple: 6,
          continue_fraction: 0.084,
          reraise_fraction: 0.04,
          maximum_reraise_total: 100.5,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 0 },
            { action: "raise", sizing: 15, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Hijack · Cutoff · Button"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Triple caller conservative · 6x squeeze"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 8.4% · Reraise 4%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100.5 BB")).toBeInTheDocument();
  });

  it("shows all four callers in the terminal full-table chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "four-caller-chart-job",
      original_filename: "four-called-open.png",
      image_filename: "four-called-open.png",
      recommendation: {
        action: "raise",
        sizing: 17.5,
        confidence: 0.8,
        explanation: "The preflop chart recommends a full-table squeeze.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.045,
          stack_depth_policy: "standard",
          effective_stack: 100,
          opener_position: "utg",
          opening_raise_size: 2.5,
          caller_positions: ["hijack", "cutoff", "button", "small_blind"],
          caller_count: 4,
          caller_adjustment_policy: "four_caller_conservative",
          squeeze_open_multiple: 7,
          continue_fraction: 0.12,
          reraise_fraction: 0.045,
          maximum_reraise_total: 101,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 0 },
            { action: "raise", sizing: 17.5, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(
      within(chartContext).getByText("Hijack · Cutoff · Button · Small blind"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Four caller conservative · 7x squeeze"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 12% · Reraise 4.5%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("101 BB")).toBeInTheDocument();
  });

  it("shows structured three-bet chart context", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "three-bet-chart-job",
      original_filename: "three-bet.png",
      image_filename: "three-bet.png",
      recommendation: {
        action: "raise",
        sizing: 17.6,
        confidence: 0.78,
        explanation: "The preflop chart recommends a four-bet.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.045,
          stack_depth_policy: "standard",
          effective_stack: 92,
          opener_position: "cutoff",
          opening_raise_size: 2.5,
          three_bettor_position: "button",
          three_bet_size: 8,
          three_bet_to_open_ratio: 3.2,
          three_bet_size_policy: "standard",
          continue_fraction: 0.12,
          four_bet_fraction: 0.045,
          maximum_four_bet_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 0 },
            { action: "raise", sizing: 17.6, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("Button")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("8 BB · 3.2x · Standard"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 12% · Four-bet 4.5%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
  });

  it("identifies conservative cold three-bet chart evidence", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "cold-three-bet-chart-job",
      original_filename: "cold-three-bet.png",
      image_filename: "cold-three-bet.png",
      recommendation: {
        action: "call",
        sizing: null,
        confidence: 0.75,
        explanation: "The preflop chart recommends a conservative cold call.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0355,
          policy_fraction: 0.06,
          stack_depth_policy: "standard",
          effective_stack: 92,
          opener_position: "utg",
          opening_raise_size: 2.5,
          three_bettor_position: "button",
          three_bet_size: 8,
          three_bet_to_open_ratio: 3.2,
          three_bet_size_policy: "standard",
          cold_three_bet_policy: "conservative_three_player",
          continue_fraction: 0.06,
          four_bet_fraction: 0.025,
          maximum_four_bet_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 1 },
            { action: "raise", sizing: null, frequency: 0 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("UTG")).toBeInTheDocument();
    expect(within(chartContext).getByText("Button")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Conservative three player"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 6% · Four-bet 2.5%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
  });

  it("identifies a heads-up squeeze response after hero calls", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "squeeze-response-chart-job",
      original_filename: "squeeze-response.png",
      image_filename: "squeeze-response.png",
      recommendation: {
        action: "call",
        sizing: null,
        confidence: 0.75,
        explanation: "The preflop chart recommends a conservative call.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0355,
          policy_fraction: 0.0405,
          stack_depth_policy: "standard",
          effective_stack: 90,
          opener_position: "utg",
          opening_raise_size: 2.5,
          hero_prior_commitment: 2.5,
          three_bettor_position: "small_blind",
          three_bet_size: 10,
          three_bet_to_open_ratio: 4,
          three_bet_size_policy: "large",
          squeeze_response_policy: "conservative_heads_up_squeeze",
          continue_fraction: 0.0405,
          four_bet_fraction: 0.019,
          maximum_four_bet_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 1 },
            { action: "raise", sizing: null, frequency: 0 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("UTG")).toBeInTheDocument();
    expect(within(chartContext).getByText("Small blind")).toBeInTheDocument();
    expect(within(chartContext).getAllByText("2.5 BB")).toHaveLength(2);
    expect(
      within(chartContext).getByText("Conservative heads up squeeze"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("10 BB · 4x · Large"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 4% · Four-bet 1.9%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
  });

  it("shows structured four-bet response evidence", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "four-bet-chart-job",
      original_filename: "four-bet.png",
      image_filename: "four-bet.png",
      recommendation: {
        action: "raise",
        sizing: 100,
        confidence: 0.78,
        explanation: "The preflop chart recommends a five-bet all-in.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0059,
          policy_fraction: 0.028,
          stack_depth_policy: "standard",
          effective_stack: 80,
          opener_position: "cutoff",
          opening_raise_size: 2.5,
          three_bettor_position: "button",
          three_bet_size: 8,
          three_bet_to_open_ratio: 3.2,
          four_bettor_position: "cutoff",
          four_bet_size: 20,
          four_bet_to_three_bet_ratio: 2.5,
          four_bet_size_policy: "standard",
          continue_fraction: 0.05,
          five_bet_fraction: 0.028,
          maximum_five_bet_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 0 },
            { action: "raise", sizing: 100, frequency: 1 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getAllByText("Cutoff")).toHaveLength(2);
    expect(within(chartContext).getByText("Button")).toBeInTheDocument();
    expect(within(chartContext).getByText("8 BB · 3.2x")).toBeInTheDocument();
    expect(
      within(chartContext).getByText("20 BB · 2.5x · Standard"),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 5% · Five-bet 2.8%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
  });

  it("identifies conservative cold four-bet response evidence", async () => {
    const chartJob: JobRecord = {
      ...recommendedJob(),
      id: "cold-four-bet-chart-job",
      original_filename: "cold-four-bet.png",
      image_filename: "cold-four-bet.png",
      recommendation: {
        action: "call",
        sizing: null,
        confidence: 0.76,
        explanation: "The preflop chart recommends a conservative call.",
        raw: {
          provider: "local_solver",
          engine: "preflop_chart_v1",
          hand_top_fraction: 0.0178,
          policy_fraction: 0.027,
          stack_depth_policy: "standard",
          effective_stack: 80,
          opener_position: "utg",
          opening_raise_size: 2.5,
          three_bettor_position: "cutoff",
          three_bet_size: 8,
          three_bet_to_open_ratio: 3.2,
          four_bettor_position: "button",
          four_bet_size: 20,
          four_bet_to_three_bet_ratio: 2.5,
          four_bet_size_policy: "standard",
          cold_four_bet_policy: "conservative_heads_up_after_opener_folds",
          continue_fraction: 0.027,
          five_bet_fraction: 0.016,
          maximum_five_bet_total: 100,
          candidates: [
            { action: "fold", sizing: null, frequency: 0 },
            { action: "call", sizing: null, frequency: 1 },
            { action: "raise", sizing: null, frequency: 0 },
          ],
        },
      },
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: chartJob.id, job: chartJob, savedAt: new Date().toISOString() },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );

    const evidence = await screen.findByLabelText("Decision evidence");
    const chartContext = within(evidence).getByLabelText("Decision context");
    expect(within(chartContext).getByText("UTG")).toBeInTheDocument();
    expect(within(chartContext).getByText("Cutoff")).toBeInTheDocument();
    expect(within(chartContext).getByText("Button")).toBeInTheDocument();
    expect(
      within(chartContext).getByText(
        "Conservative heads up after opener folds",
      ),
    ).toBeInTheDocument();
    expect(
      within(chartContext).getByText("Continue 2.7% · Five-bet 1.6%"),
    ).toBeInTheDocument();
    expect(within(chartContext).getByText("100 BB")).toBeInTheDocument();
  });
});
