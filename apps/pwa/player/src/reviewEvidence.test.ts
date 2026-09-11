import { describe, expect, it } from "vitest";

import { sourceEvidenceKey, uniqueSourceEvidence } from "./reviewEvidence";

describe("review evidence identity", () => {
  it("keeps distinct locator tuples distinct when text contains delimiters", () => {
    const first = {
      raw_source_id: "source|one",
      line_start: 4,
      line_end: 4,
      marker: "marker",
    };
    const second = {
      raw_source_id: "source",
      line_start: 4,
      line_end: 4,
      marker: "one|marker",
    };

    expect(sourceEvidenceKey(first)).not.toBe(sourceEvidenceKey(second));
    expect(uniqueSourceEvidence([first, second])).toEqual([first, second]);
  });
});
