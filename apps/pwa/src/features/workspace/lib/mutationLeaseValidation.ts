import type { JobMutationExpectation } from "./mutationLeaseTypes";

export function isJobMutationExpectation(
  value: unknown,
): value is JobMutationExpectation {
  if (value === null || typeof value !== "object") {
    return false;
  }
  const expectation = value as Record<string, unknown>;
  if (expectation.kind === "approval") {
    return typeof expectation.approvedStateKey === "string";
  }
  if (expectation.kind === "metadata") {
    return (
      (expectation.title === null || typeof expectation.title === "string") &&
      (expectation.notes === null || typeof expectation.notes === "string") &&
      Array.isArray(expectation.tags) &&
      expectation.tags.every((tag) => typeof tag === "string")
    );
  }
  return (
    expectation.kind === "benchmark-inclusion" &&
    typeof expectation.included === "boolean"
  );
}
