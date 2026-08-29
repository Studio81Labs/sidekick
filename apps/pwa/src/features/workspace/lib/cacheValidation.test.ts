import { describe, expect, it } from "vitest";

import { detectedState, jobRecord } from "../../../test/analyzerHarness";
import {
  isCachedJobRecord,
  isPristineBenchmarkImport,
} from "./cachedJobValidation";
import { isCachedDetectedState } from "./cachedPokerStateValidation";

const persistedJobId = "a".repeat(32);

describe("workspace cache validation", () => {
  it("accepts a complete persisted processing job", () => {
    expect(isCachedJobRecord(jobRecord({ id: persistedJobId }))).toBe(true);
  });

  it("rejects duplicate cards in detected state", () => {
    expect(
      isCachedDetectedState({
        ...detectedState,
        board_cards: [detectedState.hero_cards[0]],
      }),
    ).toBe(false);
  });

  it("identifies approved benchmark imports that should stay out of processing", () => {
    expect(
      isPristineBenchmarkImport(
        jobRecord({
          id: persistedJobId,
          status: "approved",
          parser_result: null,
          approved_state: {
            ...detectedState,
            user_approved: true,
          },
          benchmark_included: true,
        }),
      ),
    ).toBe(true);
  });
});
