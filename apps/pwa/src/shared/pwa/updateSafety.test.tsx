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
  revision = "default",
}: {
  name: string;
  reasons: UpdateSafetyReasons;
  revision?: string;
}) {
  useUpdateSafetyRegistration(name, reasons, revision);
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

    const snapshot = JSON.parse(
      screen.getByLabelText("update safety").textContent ?? "",
    ) as Record<string, unknown>;
    expect(snapshot).toMatchObject({
      busy: ["credential rotation", "upload"],
      dirty: ["administrator session", "training answer"],
      isBusy: true,
      isDirty: true,
    });
    expect(snapshot.dirtyRevision).toEqual(expect.any(Number));
    expect(snapshot.dirtyRevision).not.toBe(0);
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
    ).toEqual({
      busy: [],
      dirty: [],
      dirtyRevision: 0,
      isBusy: false,
      isDirty: false,
    });

    view.rerender(
      <UpdateSafetyProvider>
        <Snapshot />
      </UpdateSafetyProvider>,
    );
    expect(
      JSON.parse(screen.getByLabelText("update safety").textContent ?? ""),
    ).toEqual({
      busy: [],
      dirty: [],
      dirtyRevision: 0,
      isBusy: false,
      isDirty: false,
    });
  });

  it("advances the dirty revision when draft content changes", () => {
    const view = render(
      <UpdateSafetyProvider>
        <Source
          name="draft"
          reasons={{ busy: [], dirty: ["note"] }}
          revision="first text"
        />
        <Snapshot />
      </UpdateSafetyProvider>,
    );
    const first = JSON.parse(
      screen.getByLabelText("update safety").textContent ?? "",
    ) as { dirtyRevision: number };

    view.rerender(
      <UpdateSafetyProvider>
        <Source
          name="draft"
          reasons={{ busy: [], dirty: ["note"] }}
          revision="new text"
        />
        <Snapshot />
      </UpdateSafetyProvider>,
    );
    const second = JSON.parse(
      screen.getByLabelText("update safety").textContent ?? "",
    ) as { dirtyRevision: number };

    expect(second.dirtyRevision).toBeGreaterThan(first.dirtyRevision);
  });
});
