import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PwaRuntime } from "./PwaRuntime";
import {
  UpdateSafetyProvider,
  useUpdateSafetyRegistration,
  type UpdateSafetyReasons,
} from "../../shared/pwa/updateSafety";

const lifecycle = vi.hoisted(() => ({
  activate: vi.fn(() => true),
  activated: false,
  activating: false,
  available: true,
  prepareForReload: null as null | (() => void),
}));

vi.mock("./useServiceWorkerLifecycle", () => ({
  useServiceWorkerLifecycle: (
    _safety: unknown,
    prepareForReload: () => void,
  ) => {
    lifecycle.prepareForReload = prepareForReload;
    return lifecycle;
  },
}));

function SafetySource({ reasons }: { reasons: UpdateSafetyReasons }) {
  useUpdateSafetyRegistration("test", reasons);
  return null;
}

function renderRuntime(reasons: UpdateSafetyReasons = { busy: [], dirty: [] }) {
  return render(
    <UpdateSafetyProvider>
      <SafetySource reasons={reasons} />
      <PwaRuntime />
    </UpdateSafetyProvider>,
  );
}

beforeEach(() => {
  lifecycle.activate.mockReset();
  lifecycle.activate.mockReturnValue(true);
  lifecycle.activated = false;
  lifecycle.activating = false;
  lifecycle.available = true;
  lifecycle.prepareForReload = null;
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(null, {
        headers: { "content-type": "application/manifest+json" },
      }),
    ),
  );
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("PWA runtime status and update handoff", () => {
  it("offers an explicit reload when the workspace is safe", () => {
    renderRuntime();

    fireEvent.click(screen.getByRole("button", { name: "Reload update" }));
    expect(lifecycle.activate).toHaveBeenCalledWith(false);
  });

  it("requires explicit discard confirmation for a dirty workspace", () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false);
    renderRuntime({ busy: [], dirty: ["lesson note"] });

    fireEvent.click(screen.getByRole("button", { name: "Discard and reload" }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(lifecycle.activate).not.toHaveBeenCalled();

    confirm.mockReturnValueOnce(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard and reload" }));
    expect(lifecycle.activate).toHaveBeenCalledWith(true);
  });

  it("does not expose an activation action while an operation is busy", () => {
    renderRuntime({ busy: ["screenshot upload"], dirty: [] });

    expect(screen.getByText(/wait for active work to finish/i)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("guards unload until the confirmed update is actually reloading", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    renderRuntime({ busy: [], dirty: ["training answer"] });

    const unsafeUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(unsafeUnload);
    expect(unsafeUnload.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Discard and reload" }));
    const deferredUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(deferredUnload);
    expect(deferredUnload.defaultPrevented).toBe(true);

    act(() => lifecycle.prepareForReload?.());
    const confirmedUnload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(confirmedUnload);
    expect(confirmedUnload.defaultPrevented).toBe(false);
  });

  it("announces offline limits", () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderRuntime();

    expect(screen.getByText(/Offline — the shell/i)).toBeVisible();
  });

  it("announces cached-shell mode when the origin is unreachable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("origin unavailable")),
    );
    renderRuntime();

    expect(await screen.findByText(/Offline — the shell/i)).toBeVisible();
    expect(fetch).toHaveBeenCalledWith(
      "/manifest.webmanifest",
      expect.objectContaining({ cache: "no-store", method: "HEAD" }),
    );
  });
});
