import { useEffect, useLayoutEffect, useRef, useState } from "react";

import "./PwaRuntime.css";
import { useServiceWorkerLifecycle } from "./useServiceWorkerLifecycle";
import { useUpdateSafetySnapshot } from "../../shared/pwa/updateSafety";

export function PwaRuntime() {
  const safety = useUpdateSafetySnapshot();
  const update = useServiceWorkerLifecycle(safety);
  const [online, setOnline] = useState(() => navigator.onLine);
  const permitNextUnloadRef = useRef(false);

  useEffect(() => {
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
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
      permitNextUnloadRef.current = true;
      if (!update.activate(true)) {
        permitNextUnloadRef.current = false;
      }
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
      {!online ? (
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
