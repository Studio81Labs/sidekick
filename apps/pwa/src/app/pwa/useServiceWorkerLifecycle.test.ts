import { describe, expect, it } from "vitest";

import { shouldReloadForControllerChange } from "./useServiceWorkerLifecycle";
import type { UpdateSafetySnapshot } from "../../shared/pwa/updateSafety";

function safety(
  overrides: Partial<UpdateSafetySnapshot> = {},
): UpdateSafetySnapshot {
  return {
    busy: [],
    dirty: [],
    isBusy: false,
    isDirty: false,
    ...overrides,
  };
}

describe("service-worker controller handoff", () => {
  it("reloads a safe tab after that tab requested activation", () => {
    expect(shouldReloadForControllerChange(true, safety(), false)).toBe(true);
  });

  it("transitions an externally updated tab to a local reload prompt", () => {
    expect(shouldReloadForControllerChange(false, safety(), false)).toBe(false);
  });

  it("defers a locally requested reload if work becomes busy", () => {
    expect(
      shouldReloadForControllerChange(
        true,
        safety({ busy: ["upload"], isBusy: true }),
        true,
      ),
    ).toBe(false);
  });

  it("requires a confirmed discard before reloading dirty work", () => {
    const dirty = safety({ dirty: ["lesson note"], isDirty: true });
    expect(shouldReloadForControllerChange(true, dirty, false)).toBe(false);
    expect(shouldReloadForControllerChange(true, dirty, true)).toBe(true);
  });
});
