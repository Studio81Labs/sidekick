import { describe, expect, it } from "vitest";

import {
  detectedState,
  jobRecord,
  recommendation,
} from "../../../test/analyzerHarness";
import {
  isCachedJobRecord,
  isCachedParserResult,
  isPristineBenchmarkImport,
} from "./cachedJobValidation";

const persistedJobId = "a".repeat(32);

describe("cached job validation", () => {
  it("accepts a complete active processing job", () => {
    expect(isCachedJobRecord(jobRecord({ id: persistedJobId }))).toBe(true);
  });

  it("rejects unsafe timestamps and archived processing records", () => {
    expect(
      isCachedJobRecord(
        jobRecord({ id: persistedJobId, updated_at: "2999-01-01T00:00:00Z" }),
      ),
    ).toBe(false);
    expect(
      isCachedJobRecord(
        jobRecord({
          id: persistedJobId,
          archived_at: "2026-08-15T00:00:00Z",
        }),
      ),
    ).toBe(false);
  });

  it("requires bounded parser confidences", () => {
    const parserResult = jobRecord().parser_result;
    expect(parserResult).not.toBeNull();
    expect(isCachedParserResult(parserResult)).toBe(true);
    expect(
      isCachedParserResult({
        ...parserResult,
        confidences: { hero_cards: 1.1 },
      }),
    ).toBe(false);
  });

  it("identifies untouched approved benchmark imports", () => {
    const benchmarkImport = jobRecord({
      id: persistedJobId,
      status: "approved",
      parser_result: null,
      approved_state: { ...detectedState, user_approved: true },
      recommendation,
      benchmark_included: true,
    });

    expect(isPristineBenchmarkImport(benchmarkImport)).toBe(false);
    expect(
      isPristineBenchmarkImport({ ...benchmarkImport, recommendation: null }),
    ).toBe(true);
  });
});
