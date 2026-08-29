import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useAdministrativeAccess } from "./useAdministrativeAccess";

describe("useAdministrativeAccess", () => {
  it("starts locked with the dialog closed", () => {
    const { result } = renderHook(() => useAdministrativeAccess({}));

    expect(result.current.unlocked).toBe(false);
    expect(result.current.token).toBeNull();
    expect(result.current.dialogOpen).toBe(false);
  });

  it("unlocks with a normalized token and rejects blank input", () => {
    const { result } = renderHook(() => useAdministrativeAccess({}));

    let accepted = false;
    act(() => {
      accepted = result.current.unlock("   ");
    });
    expect(accepted).toBe(false);
    expect(result.current.unlocked).toBe(false);

    act(() => {
      accepted = result.current.unlock("  secret-token  ");
    });
    expect(accepted).toBe(true);
    expect(result.current.token).toBe("secret-token");
    expect(result.current.unlocked).toBe(true);
  });

  it("locks, clears the token, and notifies the owner", () => {
    const onLock = vi.fn();
    const { result } = renderHook(() => useAdministrativeAccess({ onLock }));

    act(() => {
      result.current.unlock("secret-token");
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
