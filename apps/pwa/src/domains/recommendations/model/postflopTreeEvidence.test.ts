import { describe, expect, it } from "vitest";

import type { RecommendationEvidenceDetail } from "./recommendationEvidenceTypes";
import { appendPostflopTreeEvidence } from "./postflopTreeEvidence";

describe("postflop tree evidence", () => {
  it("presents position, modeled action, tree size, and solve limits", () => {
    const details: RecommendationEvidenceDetail[] = [];

    appendPostflopTreeEvidence(
      {
        hero_position: "ip",
        modeled_history: ["OOP check", "IP bet 5 BB"],
        tree: {
          starting_pot: 10,
          effective_stack: 90,
          max_iterations: 120,
          compressed_memory_mb: 16,
          target_exploitability_ratio: 0.01,
        },
      },
      details,
    );

    expect(details).toEqual([
      { label: "Position", value: "IP" },
      { label: "Modeled action", value: "OOP check → IP bet 5 BB" },
      { label: "Tree", value: "10 BB pot · 90 BB stack" },
      { label: "Solve budget", value: "120 iterations · 16 MB estimate" },
      { label: "Solve target", value: "1% pot exploitability" },
    ]);
  });
});
