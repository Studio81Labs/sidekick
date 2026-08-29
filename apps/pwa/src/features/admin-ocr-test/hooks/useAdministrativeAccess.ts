import { useCallback, useEffect, useRef, useState } from "react";

import { normalizeAdministratorToken } from "../lib/administrativeAccess";

export interface UseAdministrativeAccessOptions {
  onLock?: () => void;
}

export interface AdministrativeAccessState {
  closeDialog: () => void;
  dialogOpen: boolean;
  lock: () => void;
  openDialog: () => void;
  token: string | null;
  unlock: (candidate: string) => boolean;
  unlocked: boolean;
}

export function useAdministrativeAccess({
  onLock,
}: UseAdministrativeAccessOptions): AdministrativeAccessState {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  // The owner's lock handler (stopping an active screen share) is redefined on
  // every render, so keep a ref to the latest one instead of a stale closure.
  const onLockRef = useRef(onLock);

  useEffect(() => {
    onLockRef.current = onLock;
  });

  const unlock = useCallback((candidate: string) => {
    const normalized = normalizeAdministratorToken(candidate);
    if (!normalized) {
      return false;
    }
    setToken(normalized);
    return true;
  }, []);

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
  };
}
