import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiResponseError } from "../../../shared/api/core";
import type { AdministrativeSession } from "../../../domains/admin-ocr-test/api/adminOcrTestApi";
import {
  type AdministrativeUnlockResult,
  useAdministrativeAccess,
} from "./useAdministrativeAccess";

function authorizedVerifier() {
  return vi.fn(
    async (): Promise<AdministrativeSession> => ({
      enabled: true,
      authorized: true,
    }),
  );
}

describe("useAdministrativeAccess", () => {
  it("starts locked with the dialog closed", () => {
    const { result } = renderHook(() =>
      useAdministrativeAccess({ verify: authorizedVerifier() }),
    );

    expect(result.current.unlocked).toBe(false);
    expect(result.current.token).toBeNull();
    expect(result.current.dialogOpen).toBe(false);
    expect(result.current.verifying).toBe(false);
  });

  it("stores the normalized token only after the server confirms it", async () => {
    const verify = authorizedVerifier();
    const { result } = renderHook(() => useAdministrativeAccess({ verify }));

    let outcome: AdministrativeUnlockResult | null = null;
    await act(async () => {
      outcome = await result.current.unlock("  secret-token  ");
    });

    expect(outcome).toBe("unlocked");
    expect(verify).toHaveBeenCalledWith("secret-token");
    expect(result.current.token).toBe("secret-token");
    expect(result.current.unlocked).toBe(true);
  });

  it("notifies the owner before exposing an authorized session", async () => {
    const onUnlock = vi.fn();
    const { result } = renderHook(() =>
      useAdministrativeAccess({ onUnlock, verify: authorizedVerifier() }),
    );

    await act(async () => {
      await result.current.unlock("secret-token");
    });

    expect(onUnlock).toHaveBeenCalledOnce();
    expect(result.current.unlocked).toBe(true);
  });

  it("never asks the server about a blank token", async () => {
    const verify = authorizedVerifier();
    const { result } = renderHook(() => useAdministrativeAccess({ verify }));

    let outcome: AdministrativeUnlockResult | null = null;
    await act(async () => {
      outcome = await result.current.unlock("   ");
    });

    expect(outcome).toBe("blank");
    expect(verify).not.toHaveBeenCalled();
    expect(result.current.unlocked).toBe(false);
  });

  it.each([
    [401, "unauthorized"],
    [403, "disabled"],
    [500, "unavailable"],
  ])(
    "keeps the tools locked when verification answers %i",
    async (status, expected) => {
      const verify = vi
        .fn()
        .mockRejectedValue(new ApiResponseError("denied", status));
      const { result } = renderHook(() => useAdministrativeAccess({ verify }));

      let outcome: AdministrativeUnlockResult | null = null;
      await act(async () => {
        outcome = await result.current.unlock("secret-token");
      });

      expect(outcome).toBe(expected);
      expect(result.current.token).toBeNull();
      expect(result.current.unlocked).toBe(false);
    },
  );

  it("reports an unreachable server as unavailable", async () => {
    const verify = vi.fn().mockRejectedValue(new TypeError("offline"));
    const { result } = renderHook(() => useAdministrativeAccess({ verify }));

    let outcome: AdministrativeUnlockResult | null = null;
    await act(async () => {
      outcome = await result.current.unlock("secret-token");
    });

    expect(outcome).toBe("unavailable");
    expect(result.current.unlocked).toBe(false);
  });

  it("refuses a session the deployment reports as unauthorized", async () => {
    const verify = vi
      .fn()
      .mockResolvedValue({ enabled: true, authorized: false });
    const { result } = renderHook(() => useAdministrativeAccess({ verify }));

    let outcome: AdministrativeUnlockResult | null = null;
    await act(async () => {
      outcome = await result.current.unlock("secret-token");
    });

    expect(outcome).toBe("unauthorized");
    expect(result.current.token).toBeNull();
  });

  it("reports the in-flight verification so the dialog can wait", async () => {
    let release!: (session: AdministrativeSession) => void;
    const verify = vi.fn(
      () =>
        new Promise<AdministrativeSession>((resolve) => {
          release = resolve;
        }),
    );
    const { result } = renderHook(() => useAdministrativeAccess({ verify }));

    let pending!: Promise<AdministrativeUnlockResult>;
    act(() => {
      pending = result.current.unlock("secret-token");
    });
    await waitFor(() => expect(result.current.verifying).toBe(true));

    await act(async () => {
      release({ enabled: true, authorized: true });
      await pending;
    });

    expect(result.current.verifying).toBe(false);
    expect(result.current.unlocked).toBe(true);
  });

  it("locks, clears the token, and notifies the owner", async () => {
    const onLock = vi.fn();
    const { result } = renderHook(() =>
      useAdministrativeAccess({ onLock, verify: authorizedVerifier() }),
    );

    await act(async () => {
      await result.current.unlock("secret-token");
      result.current.openDialog();
    });
    act(() => {
      result.current.lock();
    });

    expect(result.current.token).toBeNull();
    expect(result.current.unlocked).toBe(false);
    expect(onLock).toHaveBeenCalledOnce();
    expect(result.current.dialogOpen).toBe(true);

    act(() => {
      result.current.closeDialog();
    });
    expect(result.current.dialogOpen).toBe(false);
  });
});
