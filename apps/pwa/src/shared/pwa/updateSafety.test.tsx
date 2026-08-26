import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  UpdateSafetyProvider,
  useUpdateSafetyRegistration,
  useUpdateSafetySnapshot,
  type UpdateSafetyReasons,
} from "./updateSafety";

afterEach(cleanup);

function Source({
  name,
  reasons,
}: {
  name: string;
  reasons: UpdateSafetyReasons;
}) {
  useUpdateSafetyRegistration(name, reasons);
  return null;
}

function Snapshot() {
  const safety = useUpdateSafetySnapshot();
  return <output aria-label="update safety">{JSON.stringify(safety)}</output>;
}

describe("update safety registry", () => {
  it("aggregates, de-duplicates, and sorts reasons from independent owners", () => {
    render(
      <UpdateSafetyProvider>
        <Source
          name="analyzer"
          reasons={{ busy: ["upload"], dirty: ["training answer"] }}
        />
        <Source
          name="agent-access"
          reasons={{
            busy: ["credential rotation", "upload"],
            dirty: ["administrator session"],
          }}
        />
        <Snapshot />
      </UpdateSafetyProvider>,
    );

    expect(
      JSON.parse(screen.getByLabelText("update safety").textContent ?? ""),
    ).toEqual({
      busy: ["credential rotation", "upload"],
      dirty: ["administrator session", "training answer"],
      isBusy: true,
      isDirty: true,
    });
  });

  it("updates and unregisters a source without retaining stale safety state", () => {
    const view = render(
      <UpdateSafetyProvider>
        <Source name="draft" reasons={{ busy: [], dirty: ["note"] }} />
        <Snapshot />
      </UpdateSafetyProvider>,
    );

    view.rerender(
      <UpdateSafetyProvider>
        <Source name="draft" reasons={{ busy: [], dirty: [] }} />
        <Snapshot />
      </UpdateSafetyProvider>,
    );
    expect(
      JSON.parse(screen.getByLabelText("update safety").textContent ?? ""),
    ).toEqual({ busy: [], dirty: [], isBusy: false, isDirty: false });

    view.rerender(
      <UpdateSafetyProvider>
        <Snapshot />
      </UpdateSafetyProvider>,
    );
    expect(
      JSON.parse(screen.getByLabelText("update safety").textContent ?? ""),
    ).toEqual({ busy: [], dirty: [], isBusy: false, isDirty: false });
  });
});
