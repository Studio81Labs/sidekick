import { useCallback, useEffect, useRef, useState } from "react";

import type { UpdateSafetySnapshot } from "../../shared/pwa/updateSafety";

interface ServiceWorkerUpdateState {
  activated: boolean;
  activating: boolean;
  available: boolean;
}

const INITIAL_STATE: ServiceWorkerUpdateState = {
  activated: false,
  activating: false,
  available: false,
};

export function shouldReloadForControllerChange(
  activationRequestedHere: boolean,
  safety: UpdateSafetySnapshot,
  discardConfirmed: boolean,
): boolean {
  return (
    activationRequestedHere &&
    !safety.isBusy &&
    (!safety.isDirty || discardConfirmed)
  );
}

export function useServiceWorkerLifecycle(
  safety: UpdateSafetySnapshot,
  prepareForReload: () => void,
) {
  const [state, setState] = useState(INITIAL_STATE);
  const waitingRef = useRef<ServiceWorker | null>(null);
  const activationRequestedRef = useRef(false);
  const discardConfirmedRef = useRef(false);
  const safetyRef = useRef(safety);
  const prepareForReloadRef = useRef(prepareForReload);
  safetyRef.current = safety;
  prepareForReloadRef.current = prepareForReload;

  useEffect(() => {
    if (!import.meta.env.PROD || !("serviceWorker" in navigator)) return;

    let cancelled = false;
    let registration: ServiceWorkerRegistration | null = null;
    let installing: ServiceWorker | null = null;
    let controller = navigator.serviceWorker.controller;

    const publishWaitingWorker = (worker: ServiceWorker | null) => {
      if (cancelled || !worker) return;
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
    const onReturnToApp = () => {
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
      if (document.visibilityState === "visible") onReturnToApp();
    };
    const onControllerChange = () => {
      const previouslyControlled = controller !== null;
      controller = navigator.serviceWorker.controller;
      if (!previouslyControlled) return;

      const activationRequestedHere = activationRequestedRef.current;
      activationRequestedRef.current = false;
      waitingRef.current = null;
      const current = safetyRef.current;
      if (
        shouldReloadForControllerChange(
          activationRequestedHere,
          current,
          discardConfirmedRef.current,
        )
      ) {
        prepareForReloadRef.current();
        window.location.reload();
        return;
      }
      discardConfirmedRef.current = false;
      setState({ activated: true, activating: false, available: true });
    };

    navigator.serviceWorker.addEventListener(
      "controllerchange",
      onControllerChange,
    );
    window.addEventListener("focus", onReturnToApp);
    document.addEventListener("visibilitychange", onVisibilityChange);
    void navigator.serviceWorker
      .register("/sw.js", {
        scope: "/",
        type: "module",
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
      window.removeEventListener("focus", onReturnToApp);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  const activate = useCallback(
    (discardDirty: boolean) => {
      if (safety.isBusy || (safety.isDirty && !discardDirty)) return false;
      if (state.activated) {
        prepareForReloadRef.current();
        window.location.reload();
        return true;
      }
      const waiting = waitingRef.current;
      if (!waiting) return false;
      activationRequestedRef.current = true;
      discardConfirmedRef.current = discardDirty;
      setState((current) => ({ ...current, activating: true }));
      waiting.postMessage({ type: "POKER_HERO_ACTIVATE_UPDATE" });
      return true;
    },
    [safety.isBusy, safety.isDirty, state.activated],
  );

  return { ...state, activate };
}
