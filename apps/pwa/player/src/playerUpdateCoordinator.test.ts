import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  playerUpdateDirtyReasons,
  shouldReloadPlayerForControllerChange,
  type PlayerUpdateSafety,
  usePlayerUpdateCoordinator,
} from "./playerUpdateCoordinator";
import { PLAYER_ACTIVATE_UPDATE_MESSAGE } from "./playerUpdateProtocol";

class FakeServiceWorker extends EventTarget {
  readonly postMessage = vi.fn();
  state: ServiceWorkerState = "installed";
}

class FakeServiceWorkerRegistration extends EventTarget {
  installing: ServiceWorker | null = null;
  readonly update = vi.fn().mockResolvedValue(undefined);

  constructor(readonly waiting: ServiceWorker | null) {
    super();
  }
}

class FakeServiceWorkerContainer extends EventTarget {
  controller: ServiceWorker | null = {} as ServiceWorker;
  readonly getRegistration = vi.fn();
  readonly register = vi.fn();
}

const originalServiceWorker = Object.getOwnPropertyDescriptor(
  navigator,
  "serviceWorker",
);

function safety(
  overrides: Partial<PlayerUpdateSafety> = {},
): PlayerUpdateSafety {
  return {
    dirtyRevision: 0,
    isBusy: false,
    isDirty: false,
    ...overrides,
  };
}

function installServiceWorkerContainer(
  waiting: FakeServiceWorker,
): FakeServiceWorkerContainer {
  const registration = new FakeServiceWorkerRegistration(
    waiting as unknown as ServiceWorker,
  );
  const container = new FakeServiceWorkerContainer();
  container.register.mockResolvedValue(registration);
  container.getRegistration.mockResolvedValue(registration);
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: container,
  });
  return container;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  if (originalServiceWorker) {
    Object.defineProperty(navigator, "serviceWorker", originalServiceWorker);
  } else {
    Reflect.deleteProperty(navigator, "serviceWorker");
  }
});

describe("player service-worker controller handoff", () => {
  it("accounts for every current local player draft owner", () => {
    expect(
      playerUpdateDirtyReasons({
        approvalChanged: true,
        approvalStateReasonChanged: true,
        backupSelected: true,
        importFilesSelected: true,
        permanentDeletionReasonChanged: true,
        reimportFileSelected: true,
      }),
    ).toEqual([
      "selected backup archive",
      "selected hand-history files",
      "selected deleted-hand reimport file",
      "canonical approval draft",
      "approval-state reason",
      "permanent-deletion reason",
    ]);
    expect(
      playerUpdateDirtyReasons({
        approvalChanged: false,
        approvalStateReasonChanged: false,
        backupSelected: false,
        importFilesSelected: false,
        permanentDeletionReasonChanged: false,
        reimportFileSelected: false,
      }),
    ).toEqual([]);
  });

  it("reloads only for a locally requested activation that remains safe", () => {
    expect(shouldReloadPlayerForControllerChange(true, safety(), null)).toBe(
      true,
    );
    expect(shouldReloadPlayerForControllerChange(false, safety(), null)).toBe(
      false,
    );
    expect(
      shouldReloadPlayerForControllerChange(
        true,
        safety({ isBusy: true }),
        null,
      ),
    ).toBe(false);
    expect(
      shouldReloadPlayerForControllerChange(
        true,
        safety({ dirtyRevision: 8, isDirty: true }),
        7,
      ),
    ).toBe(false);
    expect(
      shouldReloadPlayerForControllerChange(
        true,
        safety({ dirtyRevision: 8, isDirty: true }),
        8,
      ),
    ).toBe(true);
  });

  it("discovers a waiting worker and reloads after an explicit safe handoff", async () => {
    const worker = new FakeServiceWorker();
    const container = installServiceWorkerContainer(worker);
    const prepareForReload = vi.fn();
    const reload = vi.fn();
    const { result, unmount } = renderHook(() =>
      usePlayerUpdateCoordinator(safety(), prepareForReload, {
        enabled: true,
        reload,
      }),
    );

    await waitFor(() => expect(result.current.available).toBe(true));
    expect(container.register).toHaveBeenCalledWith("/sw.js", {
      scope: "/",
      updateViaCache: "none",
    });

    act(() => expect(result.current.activate(false)).toBe(true));
    expect(worker.postMessage).toHaveBeenCalledWith({
      type: PLAYER_ACTIVATE_UPDATE_MESSAGE,
    });

    act(() => {
      container.controller = {} as ServiceWorker;
      container.dispatchEvent(new Event("controllerchange"));
    });
    expect(prepareForReload).toHaveBeenCalledOnce();
    expect(reload).toHaveBeenCalledOnce();
    unmount();
  });

  it("does not prompt an uncontrolled first-install page", async () => {
    const worker = new FakeServiceWorker();
    const container = installServiceWorkerContainer(worker);
    container.controller = null;
    const { result, unmount } = renderHook(() =>
      usePlayerUpdateCoordinator(safety(), vi.fn(), {
        enabled: true,
        reload: vi.fn(),
      }),
    );

    await waitFor(() => expect(container.register).toHaveBeenCalledOnce());
    expect(result.current.available).toBe(false);
    expect(worker.postMessage).not.toHaveBeenCalled();
    unmount();
  });

  it("requires current-draft confirmation and defers reload after safety changes", async () => {
    const worker = new FakeServiceWorker();
    const container = installServiceWorkerContainer(worker);
    const prepareForReload = vi.fn();
    const reload = vi.fn();
    const { result, rerender, unmount } = renderHook(
      ({ currentSafety }: { currentSafety: PlayerUpdateSafety }) =>
        usePlayerUpdateCoordinator(currentSafety, prepareForReload, {
          enabled: true,
          reload,
        }),
      {
        initialProps: {
          currentSafety: safety({ dirtyRevision: 3, isDirty: true }),
        },
      },
    );

    await waitFor(() => expect(result.current.available).toBe(true));
    act(() => expect(result.current.activate(false)).toBe(false));
    expect(worker.postMessage).not.toHaveBeenCalled();

    act(() => expect(result.current.activate(true)).toBe(true));
    rerender({
      currentSafety: safety({ dirtyRevision: 4, isDirty: true }),
    });
    act(() => {
      container.controller = {} as ServiceWorker;
      container.dispatchEvent(new Event("controllerchange"));
    });

    expect(reload).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({
      activated: true,
      activating: false,
      available: true,
    });

    rerender({ currentSafety: safety() });
    act(() => expect(result.current.activate(false)).toBe(true));
    expect(prepareForReload).toHaveBeenCalledOnce();
    expect(reload).toHaveBeenCalledOnce();
    unmount();
  });
});
