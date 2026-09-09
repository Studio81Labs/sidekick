import { act, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DetectedState } from "../../../shared/types/poker";
import {
  AnalyzerTestApp as App,
  approvedJob,
  canonicalState,
  deferredResponse,
  detectedState,
  fetchMock,
  jobRecord,
  jsonResponse,
  processingQueueResponse,
  uploadScreenshot,
} from "../../../test/analyzerHarness";

describe("Analyzer hand review", () => {
  it("does not approve an image-backed job until its matching screenshot loads", async () => {
    const created = jobRecord();
    const image = deferredResponse();
    const existingFetch = globalThis.fetch;
    const fetch = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith(`/jobs/${created.id}/image`)) {
        return image.promise;
      }
      return existingFetch(input, init);
    });
    vi.stubGlobal("fetch", fetch);
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    const approve = await screen.findByRole("button", {
      name: "Approve state",
    });
    await waitFor(() =>
      expect(
        fetch.mock.calls.some(([input]) =>
          String(input).endsWith(`/jobs/${created.id}/image`),
        ),
      ).toBe(true),
    );

    expect(approve).toBeDisabled();
    expect(fetchMock()).toHaveBeenCalledTimes(2);

    await act(async () => {
      image.resolve(new Response("table image"));
    });
    await waitFor(() => expect(approve).toBeEnabled());

    await user.click(approve);
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
  });

  it("displays backend upload errors as queue attention items", async () => {
    const validJob = jobRecord({ original_filename: "valid.png" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(validJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([validJob]))
      .mockResolvedValueOnce(
        jsonResponse(
          { detail: "Upload must contain supported image data" },
          400,
        ),
      )
      .mockResolvedValueOnce(processingQueueResponse([validJob]));
    render(<App />);

    await uploadScreenshot("valid.png");
    expect(await screen.findByDisplayValue("Ah Kd")).toBeInTheDocument();
    expect(
      screen.getByAltText("Uploaded poker table screenshot"),
    ).toBeInTheDocument();

    await uploadScreenshot("broken.png");

    expect(
      await screen.findByText(
        "1 screenshot need attention. Check the failed queue items.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Open screenshot 1: valid.png" }),
    ).toBeInTheDocument();
    const failedItem = screen.getByRole("button", {
      name: "Open screenshot 2: broken.png",
    });
    expect(within(failedItem).getByText("error")).toBeInTheDocument();
    expect(
      within(failedItem).getByText("Upload must contain supported image data"),
    ).toBeInTheDocument();
    await waitFor(() => expect(failedItem).toHaveClass("active"));
  });

  it("sends corrected approval payload with user_approved forced true", async () => {
    const correctedState = canonicalState({
      current_bet: 3.5,
      opponent_wager: null,
      facing_action: null,
      action_context: null,
    });
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(correctedState)));
    render(<App />);

    const user = await uploadScreenshot();
    const currentBetInput = await screen.findByLabelText(/Current bet/);
    await user.clear(currentBetInput);
    await user.type(currentBetInput, "3.5");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const approveOptions = fetchMock().mock.calls[2][1];
    const payload = JSON.parse(String(approveOptions?.body));

    expect(fetchMock().mock.calls[2][0]).toBe(
      "http://localhost:8000/api/admin/ocr/jobs/job-123/approve",
    );
    expect(payload.current_bet).toBe(3.5);
    expect(payload.opponent_wager).toBeNull();
    expect(payload.facing_action).toBeNull();
    expect(payload.action_context).toBeNull();
    expect(payload.user_approved).toBe(true);
  });

  it("submits structured opener context for preflop raise states", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 4,
      current_bet: 1.5,
      hero_position: "big blind",
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces 1.5 BB to call into a 4 BB pot",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    const approvedState = canonicalState({
      ...preflopState,
      preflop_opener_position: "button",
      preflop_open_size: 2.5,
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob(approvedState)));
    render(<App />);

    const user = await uploadScreenshot();
    await user.selectOptions(
      await screen.findByLabelText(/Opener position/),
      "button",
    );
    await user.type(screen.getByLabelText(/Opening size/), "2.5");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBe("button");
    expect(payload.preflop_open_size).toBe(2.5);
  });

  it("submits structured preflop history and synchronizes opener context", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 12,
      current_bet: 5.5,
      hero_stack: 97.5,
      effective_stack: 92,
      players_in_hand: 6,
      hero_position: "cutoff",
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces a 3-bet",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(
      screen.getByRole("button", { name: "Add preflop action" }),
    );
    await user.type(screen.getByLabelText("Preflop action 1 amount"), "2.5");
    await user.click(
      screen.getByRole("button", { name: "Add preflop action" }),
    );
    await user.type(screen.getByLabelText("Preflop action 2 amount"), "8");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBe("cutoff");
    expect(payload.preflop_open_size).toBe(2.5);
    expect(payload.preflop_action_history).toEqual([
      { actor: "cutoff", action: "raise", amount: 2.5 },
      { actor: "button", action: "raise", amount: 8 },
    ]);
  });

  it("clears stale opener context for call-first structured history", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 6.5,
      current_bet: 3,
      hero_stack: 99,
      effective_stack: 90,
      players_in_hand: 2,
      hero_position: "utg",
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "utg", action: "call", amount: 1 },
        { actor: "button", action: "raise", amount: 4 },
      ],
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero limped and faces an isolation raise",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBeNull();
    expect(payload.preflop_open_size).toBeNull();
    expect(payload.preflop_action_history).toEqual([
      { actor: "utg", action: "call", amount: 1 },
      { actor: "button", action: "raise", amount: 4 },
    ]);
  });

  it("loads structured preflop history into editable controls", async () => {
    const preflopState: DetectedState = {
      ...detectedState,
      board_cards: [],
      pot_size: 12,
      current_bet: 5.5,
      hero_stack: 97.5,
      effective_stack: 92,
      players_in_hand: 6,
      hero_position: "cutoff",
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "cutoff", action: "raise", amount: 2.5 },
        { actor: "button", action: "raise", amount: 8 },
      ],
      street: "preflop",
      facing_action: "raise",
      action_context: "Hero faces a 3-bet",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: preflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]));
    render(<App />);

    await uploadScreenshot();

    expect(await screen.findByLabelText("Preflop action 1 actor")).toHaveValue(
      "cutoff",
    );
    expect(screen.getByLabelText("Preflop action 1 amount")).toHaveValue("2.5");
    expect(screen.getByLabelText("Preflop action 2 actor")).toHaveValue(
      "button",
    );
    expect(screen.getByLabelText("Preflop action 2 amount")).toHaveValue("8");
    expect(screen.queryByLabelText(/Opener position/)).not.toBeInTheDocument();
  });

  it("preserves hidden preflop history when approving a postflop state", async () => {
    const postflopState: DetectedState = {
      ...detectedState,
      opponent_stack: 90,
      preflop_opener_position: "cutoff",
      preflop_open_size: 2.5,
      preflop_action_history: [
        { actor: "cutoff", action: "raise", amount: 2.5 },
        { actor: "button", action: "raise", amount: 8 },
      ],
      facing_action: "raise",
      postflop_action_history: [
        { actor: "oop", action: "bet", amount: 2.5 },
        { actor: "ip", action: "raise", amount: 7.5 },
      ],
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: postflopState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    expect(
      screen.queryByRole("button", { name: "Add preflop action" }),
    ).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText(/Street/), "turn");
    await user.selectOptions(screen.getByLabelText(/Facing action/), "bet");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.preflop_opener_position).toBe("cutoff");
    expect(payload.preflop_open_size).toBe(2.5);
    expect(payload.preflop_action_history).toEqual([
      { actor: "cutoff", action: "raise", amount: 2.5 },
      { actor: "button", action: "raise", amount: 8 },
    ]);
  });

  it("submits structured postflop history for a raised decision", async () => {
    const raisedState: DetectedState = {
      ...detectedState,
      pot_size: 19,
      current_bet: 5,
      hero_stack: 98,
      effective_stack: 93,
      players_in_hand: 2,
      hero_position: "OOP",
      facing_action: "raise",
      action_context: "Hero bet 2 BB and faces a raise to 7 BB",
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: raisedState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    await user.type(await screen.findByLabelText(/Opponent stack/), "93");
    await user.click(screen.getByRole("button", { name: "Add action" }));
    await user.selectOptions(screen.getByLabelText("Action 1 type"), "bet");
    await user.type(screen.getByLabelText("Action 1 amount"), "2");
    await user.click(screen.getByRole("button", { name: "Add action" }));
    await user.selectOptions(screen.getByLabelText("Action 2 type"), "raise");
    await user.type(screen.getByLabelText("Action 2 amount"), "7");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.opponent_stack).toBe(93);
    expect(payload.postflop_action_history).toEqual([
      { actor: "oop", action: "bet", amount: 2 },
      { actor: "ip", action: "raise", amount: 7 },
    ]);
  });

  it("loads and submits completed street history for a turn decision", async () => {
    const turnState: DetectedState = {
      ...detectedState,
      board_cards: [
        ...detectedState.board_cards,
        { rank: "2", suit: "diamonds" },
      ],
      pot_size: 9.5,
      current_bet: 0,
      hero_stack: 95.5,
      opponent_stack: 95.5,
      effective_stack: 95.5,
      players_in_hand: 2,
      hero_position: "OOP",
      opponent_position: "IP",
      street: "turn",
      facing_action: null,
      completed_postflop_streets: [
        {
          street: "flop",
          actions: [
            { actor: "oop", action: "bet", amount: 2 },
            { actor: "ip", action: "call", amount: 2 },
          ],
        },
      ],
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: turnState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()));
    render(<App />);

    const user = await uploadScreenshot();
    expect(
      await screen.findByLabelText("Completed action 1 street"),
    ).toHaveValue("flop");
    expect(screen.getByLabelText("Completed action 1 actor")).toHaveValue(
      "oop",
    );
    expect(screen.getByLabelText("Completed action 1 type")).toHaveValue("bet");
    expect(screen.getByLabelText("Completed action 1 amount")).toHaveValue("2");
    expect(screen.getByLabelText("Completed action 2 actor")).toHaveValue("ip");
    expect(screen.getByLabelText("Completed action 2 type")).toHaveValue(
      "call",
    );
    expect(screen.getByLabelText(/Opponent stack/)).toHaveValue("95.5");

    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(3));
    const payload = JSON.parse(String(fetchMock().mock.calls[2][1]?.body));
    expect(payload.completed_postflop_streets).toEqual([
      {
        street: "flop",
        actions: [
          { actor: "oop", action: "bet", amount: 2 },
          { actor: "ip", action: "call", amount: 2 },
        ],
      },
    ]);
  });

  it("adds river history actions to a street with remaining capacity", async () => {
    const riverState: DetectedState = {
      ...detectedState,
      board_cards: [
        ...detectedState.board_cards,
        { rank: "2", suit: "diamonds" },
        { rank: "3", suit: "clubs" },
      ],
      street: "river",
      facing_action: null,
      completed_postflop_streets: [
        {
          street: "flop",
          actions: [
            { actor: "oop", action: "bet", amount: 1 },
            { actor: "ip", action: "raise", amount: 2 },
            { actor: "oop", action: "raise", amount: 3 },
            { actor: "ip", action: "raise", amount: 4 },
            { actor: "oop", action: "raise", amount: 5 },
            { actor: "ip", action: "raise", amount: 6 },
            { actor: "oop", action: "raise", amount: 7 },
            { actor: "ip", action: "call", amount: 7 },
          ],
        },
      ],
    };
    const parsedJob = jobRecord({
      parser_result: {
        ...jobRecord().parser_result!,
        state: riverState,
      },
    });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(parsedJob, 201))
      .mockResolvedValueOnce(processingQueueResponse([parsedJob]));
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Add action" }));

    const addedStreet = screen.getByLabelText("Completed action 9 street");
    expect(addedStreet).toHaveValue("turn");
    expect(
      within(addedStreet).getByRole("option", { name: "Flop" }),
    ).toBeDisabled();
  });

  it("prevents field edits while approval is pending", async () => {
    const pendingApproval = deferredResponse();
    const created = jobRecord();
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockReturnValueOnce(pendingApproval.promise);
    render(<App />);

    const user = await uploadScreenshot();
    const heroCardsInput = await screen.findByLabelText(/Hero cards/);
    const potInput = screen.getByLabelText(/Pot/);
    const streetSelect = screen.getByLabelText(/Street/);
    const actionContextInput = screen.getByLabelText(/Action context/);

    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() => expect(potInput).toBeDisabled());
    expect(heroCardsInput).toBeDisabled();
    expect(streetSelect).toBeDisabled();
    expect(actionContextInput).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Parser benchmark" }),
    ).toBeDisabled();

    await user.type(potInput, "18");
    expect(potInput).toHaveValue("12.5");

    pendingApproval.resolve(jsonResponse(approvedJob()));

    await waitFor(() => expect(potInput).toBeEnabled());
    expect(
      screen.getByRole("button", { name: "Parser benchmark" }),
    ).toBeEnabled();
    expect(potInput).toHaveValue("12.5");
    expect(
      screen.getByRole("button", { name: "Reset to parser" }),
    ).toBeEnabled();
  });
});
