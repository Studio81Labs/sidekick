import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

import "./PwaRuntime.css";
import { isPwaOriginReachable } from "./serviceWorkerRuntime";
import { useServiceWorkerLifecycle } from "./useServiceWorkerLifecycle";
import { useUpdateSafetySnapshot } from "../../shared/pwa/updateSafety";

const ORIGIN_PROBE_INTERVAL_MS = 30_000;
const ORIGIN_PROBE_TIMEOUT_MS = 5_000;

export function PwaRuntime() {
  const safety = useUpdateSafetySnapshot();
  const permitNextUnloadRef = useRef(false);
  const prepareForUpdateReload = useCallback(() => {
    permitNextUnloadRef.current = true;
    window.setTimeout(() => {
      permitNextUnloadRef.current = false;
    }, 0);
  }, []);
  const update = useServiceWorkerLifecycle(safety, prepareForUpdateReload);
  const [originReachable, setOriginReachable] = useState(
    () => navigator.onLine,
  );

  useEffect(() => {
    let active = true;
    let controller: AbortController | null = null;
    let timeoutId: number | null = null;

    const cancelProbe = () => {
      controller?.abort();
      controller = null;
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      timeoutId = null;
    };
    const verifyOrigin = async () => {
      cancelProbe();
      const currentController = new AbortController();
      controller = currentController;
      timeoutId = window.setTimeout(
        () => currentController.abort(),
        ORIGIN_PROBE_TIMEOUT_MS,
      );
      const reachable = await isPwaOriginReachable(currentController.signal);
      if (active && controller === currentController) {
        setOriginReachable(reachable);
        cancelProbe();
      }
    };
    const onOnline = () => void verifyOrigin();
    const onOffline = () => {
      cancelProbe();
      setOriginReachable(false);
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void verifyOrigin();
    };

    void verifyOrigin();
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    window.addEventListener("focus", onOnline);
    document.addEventListener("visibilitychange", onVisibilityChange);
    const intervalId = window.setInterval(
      () => void verifyOrigin(),
      ORIGIN_PROBE_INTERVAL_MS,
    );
    return () => {
      active = false;
      cancelProbe();
      window.clearInterval(intervalId);
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.removeEventListener("focus", onOnline);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, []);

  useLayoutEffect(() => {
    if (!safety.isBusy && !safety.isDirty) return;
    const preventUnsafeUnload = (event: BeforeUnloadEvent) => {
      if (permitNextUnloadRef.current) {
        permitNextUnloadRef.current = false;
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", preventUnsafeUnload);
    return () =>
      window.removeEventListener("beforeunload", preventUnsafeUnload);
  }, [safety.isBusy, safety.isDirty]);

  function activateDiscardingDrafts() {
    if (
      window.confirm(
        "Discard every unsaved Poker Hero draft and reload the update?",
      )
    ) {
      update.activate(true);
    }
  }

  const updateMessage = update.activated
    ? "Poker Hero has updated. Reload when your work is safe."
    : safety.isBusy
      ? "A Poker Hero update is ready and will wait for active work to finish."
      : safety.isDirty
        ? "A Poker Hero update is ready. Save your drafts or explicitly discard them."
        : "A Poker Hero update is ready to reload.";

  return (
    <div className="pwa-status-stack">
      {!originReachable ? (
        <div className="pwa-status offline" role="status" aria-live="polite">
          Offline — the shell and local recovery view remain available, but
          uploads, analysis, history, benchmarks, backups, and agent access need
          a connection.
        </div>
      ) : null}
      {update.available ? (
        <div className="pwa-status update" role="status" aria-live="polite">
          <span>{updateMessage}</span>
          {!safety.isBusy ? (
            <button
              type="button"
              disabled={update.activating}
              onClick={
                safety.isDirty
                  ? activateDiscardingDrafts
                  : () => update.activate(false)
              }
            >
              {update.activating
                ? "Updating..."
                : safety.isDirty
                  ? "Discard and reload"
                  : "Reload update"}
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
