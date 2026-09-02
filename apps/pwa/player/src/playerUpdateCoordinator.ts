import { useCallback, useEffect, useRef, useState } from "react";

import { PLAYER_ACTIVATE_UPDATE_MESSAGE } from "./playerUpdateProtocol";

export interface PlayerUpdateSafety {
  dirtyRevision: number;
  isBusy: boolean;
  isDirty: boolean;
}

export interface PlayerDraftState {
  approvalChanged: boolean;
  approvalStateReasonChanged: boolean;
  backupSelected: boolean;
  importFilesSelected: boolean;
  permanentDeletionReasonChanged: boolean;
}

interface PlayerUpdateState {
  activated: boolean;
  activating: boolean;
  available: boolean;
}

interface PlayerUpdateOptions {
  enabled?: boolean;
  reload?: () => void;
}

const INITIAL_STATE: PlayerUpdateState = {
  activated: false,
  activating: false,
  available: false,
};

export function playerUpdateDirtyReasons(drafts: PlayerDraftState): string[] {
  return [
    drafts.backupSelected ? "selected backup archive" : null,
    drafts.importFilesSelected ? "selected hand-history files" : null,
    drafts.approvalChanged ? "canonical approval draft" : null,
    drafts.approvalStateReasonChanged ? "approval-state reason" : null,
    drafts.permanentDeletionReasonChanged ? "permanent-deletion reason" : null,
  ].filter((reason): reason is string => reason !== null);
}

export function shouldReloadPlayerForControllerChange(
  activationRequestedHere: boolean,
  safety: PlayerUpdateSafety,
  confirmedDirtyRevision: number | null,
): boolean {
  return (
    activationRequestedHere &&
    !safety.isBusy &&
    (!safety.isDirty || confirmedDirtyRevision === safety.dirtyRevision)
  );
}

export function usePlayerUpdateCoordinator(
  safety: PlayerUpdateSafety,
  prepareForReload: () => void,
  options: PlayerUpdateOptions = {},
) {
  const enabled = options.enabled ?? import.meta.env.PROD;
  const reload = options.reload ?? (() => window.location.reload());
  const [state, setState] = useState(INITIAL_STATE);
  const waitingRef = useRef<ServiceWorker | null>(null);
  const activationRequestedRef = useRef(false);
  const confirmedDirtyRevisionRef = useRef<number | null>(null);
  const safetyRef = useRef(safety);
  const prepareForReloadRef = useRef(prepareForReload);
  const reloadRef = useRef(reload);
  safetyRef.current = safety;
  prepareForReloadRef.current = prepareForReload;
  reloadRef.current = reload;

  useEffect(() => {
    if (!enabled || !("serviceWorker" in navigator)) return;

    let cancelled = false;
    let registration: ServiceWorkerRegistration | null = null;
    let installing: ServiceWorker | null = null;
    let controller = navigator.serviceWorker.controller;

    const publishWaitingWorker = (worker: ServiceWorker | null) => {
      if (cancelled || !worker || !navigator.serviceWorker.controller) return;
      waitingRef.current = worker;
      setState({ activated: false, activating: false, available: true });
    };
    const onInstallingStateChange = () => {
      if (
        installing?.state === "installed" &&
        navigator.serviceWorker.controller
      ) {
        publishWaitingWorker(registration?.waiting ?? installing);
      }
    };
    const watchInstallingWorker = () => {
      installing?.removeEventListener("statechange", onInstallingStateChange);
      installing = registration?.installing ?? null;
      installing?.addEventListener("statechange", onInstallingStateChange);
      publishWaitingWorker(registration?.waiting ?? null);
    };
    const adoptRegistration = (nextRegistration: ServiceWorkerRegistration) => {
      if (registration !== nextRegistration) {
        registration?.removeEventListener("updatefound", watchInstallingWorker);
        registration = nextRegistration;
        registration.addEventListener("updatefound", watchInstallingWorker);
      }
      watchInstallingWorker();
    };
    const checkForUpdate = () => {
      void navigator.serviceWorker
        .getRegistration("/")
        .then((currentRegistration) => {
          if (cancelled || !currentRegistration) return;
          adoptRegistration(currentRegistration);
          return currentRegistration.update();
        })
        .catch(() => undefined);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") checkForUpdate();
    };
    const onControllerChange = () => {
      const previouslyControlled = controller !== null;
      controller = navigator.serviceWorker.controller;
      if (!previouslyControlled) return;

      const activationRequestedHere = activationRequestedRef.current;
      activationRequestedRef.current = false;
      waitingRef.current = null;
      if (
        shouldReloadPlayerForControllerChange(
          activationRequestedHere,
          safetyRef.current,
          confirmedDirtyRevisionRef.current,
        )
      ) {
        prepareForReloadRef.current();
        reloadRef.current();
        return;
      }
      confirmedDirtyRevisionRef.current = null;
      setState({ activated: true, activating: false, available: true });
    };

    navigator.serviceWorker.addEventListener(
      "controllerchange",
      onControllerChange,
    );
    window.addEventListener("focus", checkForUpdate);
    document.addEventListener("visibilitychange", onVisibilityChange);
    void navigator.serviceWorker
      .register("/sw.js", {
        scope: "/",
        updateViaCache: "none",
      })
      .then((nextRegistration) => {
        if (cancelled) return;
        adoptRegistration(nextRegistration);
        return nextRegistration.update();
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
      installing?.removeEventListener("statechange", onInstallingStateChange);
      registration?.removeEventListener("updatefound", watchInstallingWorker);
      navigator.serviceWorker.removeEventListener(
        "controllerchange",
        onControllerChange,
      );
      window.removeEventListener("focus", checkForUpdate);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [enabled]);

  const activate = useCallback(
    (discardDirty: boolean) => {
      if (safety.isBusy || (safety.isDirty && !discardDirty)) return false;
      if (state.activated) {
        prepareForReloadRef.current();
        reloadRef.current();
        return true;
      }
      const waiting = waitingRef.current;
      if (!waiting) return false;
      activationRequestedRef.current = true;
      confirmedDirtyRevisionRef.current =
        safety.isDirty && discardDirty ? safety.dirtyRevision : null;
      setState((current) => ({ ...current, activating: true }));
      waiting.postMessage({ type: PLAYER_ACTIVATE_UPDATE_MESSAGE });
      return true;
    },
    [safety.dirtyRevision, safety.isBusy, safety.isDirty, state.activated],
  );

  return { ...state, activate };
}
