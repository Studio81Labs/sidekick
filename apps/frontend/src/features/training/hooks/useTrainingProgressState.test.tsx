import { createElement, type PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TrainingProgress } from "../../../shared/types";
import {
  deferredResponse,
  fetchMock,
  jsonResponse,
} from "../../../test/analyzerHarness";
import { useTrainingProgressState } from "./useTrainingProgressState";

function wrapper({ children }: PropsWithChildren) {
  return createElement(AppProviders, null, children);
}

function trainingProgress(reviewedHands: number): TrainingProgress {
  return {
    reviewed_hands: reviewedHands,
    action_matches: reviewedHands,
    exact_matches: reviewedHands,
    different_actions: 0,
    needs_review_hands: 0,
    action_accuracy: reviewedHands > 0 ? 1 : 0,
    exact_accuracy: reviewedHands > 0 ? 1 : 0,
    ev_compared_hands: 0,
    average_ev_loss_bb: null,
    street_summaries: [],
    recent_hands: [],
    review_queue_hands: 0,
    review_queue: [],
  };
}

describe("training progress state", () => {
  beforeEach(() => {
    fetchMock().mockReset();
  });

  it("keeps the newest progress response when an older load finishes later", async () => {
    const olderRequest = deferredResponse();
    fetchMock()
      .mockImplementationOnce(() => olderRequest.promise)
      .mockResolvedValueOnce(jsonResponse(trainingProgress(2)));
    const onError = vi.fn();
    const { result } = renderHook(() => useTrainingProgressState({ onError }), {
      wrapper,
    });

    act(() => {
      result.current.loadInitial();
      result.current.loadInitial();
    });
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.progress?.reviewed_hands).toBe(2);

    await act(async () => {
      olderRequest.resolve(jsonResponse(trainingProgress(1)));
      await olderRequest.promise;
    });

    expect(result.current.progress?.reviewed_hands).toBe(2);
    expect(onError).not.toHaveBeenCalledWith(
      expect.stringContaining("Could not load"),
    );
  });

  it("cancels a pending progress load without applying its response", async () => {
    const pendingRequest = deferredResponse();
    fetchMock().mockImplementationOnce(() => pendingRequest.promise);
    const { result } = renderHook(
      () => useTrainingProgressState({ onError: vi.fn() }),
      { wrapper },
    );

    act(() => {
      result.current.loadInitial();
      result.current.cancelLoads();
    });
    await act(async () => {
      pendingRequest.resolve(jsonResponse(trainingProgress(1)));
      await pendingRequest.promise;
    });

    expect(result.current.loading).toBe(false);
    expect(result.current.progress).toBeNull();
  });

  it("restores the previous filters when a progress query fails", async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(trainingProgress(3)))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "service unavailable" }, 503),
      );
    const onError = vi.fn();
    const { result } = renderHook(() => useTrainingProgressState({ onError }), {
      wrapper,
    });

    act(() => result.current.loadInitial());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.updatePositionFilter({
        kind: "position",
        position: "BTN",
        label: "BTN",
      });
    });

    expect(result.current.positionFilter).toBeNull();
    expect(result.current.progress?.reviewed_hands).toBe(3);
    expect(onError).toHaveBeenLastCalledWith("service unavailable");
  });
});
import { AppProviders } from "../../../app/providers/AppProviders";
