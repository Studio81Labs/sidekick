import { useCallback, useEffect, useRef, useState } from "react";

import {
  type AdministrativeSession,
  verifyAdministratorToken,
} from "../../../domains/admin-ocr-test/api/adminOcrTestApi";
import { ApiResponseError } from "../../../shared/api/core";
import {
  type AdministrativeUnlockFailure,
  administrativeAccessDenial,
  normalizeAdministratorToken,
} from "../lib/administrativeAccess";

export type AdministrativeUnlockResult =
  | AdministrativeUnlockFailure
  | "unlocked";

export interface UseAdministrativeAccessOptions {
  onLock?: () => void;
  /** Overridable so unit tests exercise the outcomes without a transport. */
  verify?: (token: string) => Promise<AdministrativeSession>;
}

export interface AdministrativeAccessState {
  closeDialog: () => void;
  dialogOpen: boolean;
  lock: () => void;
  openDialog: () => void;
  token: string | null;
  unlock: (candidate: string) => Promise<AdministrativeUnlockResult>;
  unlocked: boolean;
  verifying: boolean;
}

function failureFromError(error: unknown): AdministrativeUnlockFailure {
  return (
    (error instanceof ApiResponseError
      ? administrativeAccessDenial(error.status)
      : null) ?? "unavailable"
  );
}

export function useAdministrativeAccess({
  onLock,
  verify = verifyAdministratorToken,
}: UseAdministrativeAccessOptions): AdministrativeAccessState {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  // The owner's lock handler (stopping an active screen share) is redefined on
  // every render, so keep a ref to the latest one instead of a stale closure.
  const onLockRef = useRef(onLock);
  const verifyRef = useRef(verify);

  useEffect(() => {
    onLockRef.current = onLock;
    verifyRef.current = verify;
  });

  const unlock = useCallback(
    async (candidate: string): Promise<AdministrativeUnlockResult> => {
      const normalized = normalizeAdministratorToken(candidate);
      if (!normalized) {
        return "blank";
      }
      setVerifying(true);
      try {
        // The credential only becomes usable once the server confirms it, so a
        // guessed token never reveals an administrative capture control.
        const session = await verifyRef.current(normalized);
        if (!session.enabled) {
          return "disabled";
        }
        if (!session.authorized) {
          return "unauthorized";
        }
        setToken(normalized);
        return "unlocked";
      } catch (error) {
        return failureFromError(error);
      } finally {
        setVerifying(false);
      }
    },
    [],
  );

  const lock = useCallback(() => {
    setToken(null);
    onLockRef.current?.();
  }, []);

  return {
    closeDialog: useCallback(() => setDialogOpen(false), []),
    dialogOpen,
    lock,
    openDialog: useCallback(() => setDialogOpen(true), []),
    token,
    unlock,
    unlocked: token !== null,
    verifying,
  };
}
