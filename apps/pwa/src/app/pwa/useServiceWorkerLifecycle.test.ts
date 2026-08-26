import { describe, expect, it } from "vitest";

import { shouldReloadForControllerChange } from "./useServiceWorkerLifecycle";
import type { UpdateSafetySnapshot } from "../../shared/pwa/updateSafety";

function safety(
  overrides: Partial<UpdateSafetySnapshot> = {},
): UpdateSafetySnapshot {
  return {
    busy: [],
    dirty: [],
    dirtyRevision: 0,
    isBusy: false,
    isDirty: false,
    ...overrides,
  };
}

describe("service-worker controller handoff", () => {
  it("reloads a safe tab after that tab requested activation", () => {
    expect(shouldReloadForControllerChange(true, safety(), null)).toBe(true);
  });

  it("transitions an externally updated tab to a local reload prompt", () => {
    expect(shouldReloadForControllerChange(false, safety(), null)).toBe(false);
  });

  it("defers a locally requested reload if work becomes busy", () => {
    expect(
      shouldReloadForControllerChange(
        true,
        safety({ busy: ["upload"], isBusy: true }),
        null,
      ),
    ).toBe(false);
  });

  it("requires a confirmation for the current dirty revision", () => {
    const dirty = safety({
      dirty: ["lesson note"],
      dirtyRevision: 7,
      isDirty: true,
    });
    expect(shouldReloadForControllerChange(true, dirty, null)).toBe(false);
    expect(shouldReloadForControllerChange(true, dirty, 6)).toBe(false);
    expect(shouldReloadForControllerChange(true, dirty, 7)).toBe(true);
  });
});
