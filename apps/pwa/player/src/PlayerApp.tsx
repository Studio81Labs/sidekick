import { useEffect, useRef, useState } from "react";

import {
  PlayerApiError,
  PlayerRestoreAmbiguousError,
  type PlayerBackupRestoreResult,
  type PlayerCredentials,
  type PlayerStorageStatus,
  bootstrapPlayerSession,
  clearPlayerCredentials,
  exportPlayerBackup,
  loadPlayerStorage,
  restorePlayerBackup,
  revokePlayerSession,
} from "./playerApi";

type BusyAction = "export" | "restore" | "signout" | null;

function friendlyError(error: unknown): string {
  if (error instanceof PlayerApiError && error.status === 401) {
    return "The local player session expired. Start the runtime again to reconnect.";
  }
  return error instanceof Error
    ? error.message
    : "The local player runtime could not complete the request.";
}

function recoveryCount(storage: PlayerStorageStatus): number {
  return storage.recovery.quarantined.length + storage.recovery.failed.length;
}

function RestoreSummary({ result }: { result: PlayerBackupRestoreResult }) {
  return (
    <div className="notice restore-result" role="status">
      <strong>Restore committed.</strong>
      <span>
        {result.imported_records} imported, {result.reused_records} already
        present, {result.skipped_stale_records} stale skipped.
      </span>
      <span>
        {result.imported_decision_artifacts} decision artifacts imported,{" "}
        {result.reused_decision_artifacts} already present,{" "}
        {result.removed_decision_artifacts} removed by restored deletion
        evidence.
      </span>
      <span>{result.total_records} local records now retained.</span>
    </div>
  );
}

export default function PlayerApp() {
  const backupInput = useRef<HTMLInputElement>(null);
  const [credentials, setCredentials] = useState<PlayerCredentials | null>(
    null,
  );
  const [storage, setStorage] = useState<PlayerStorageStatus | null>(null);
  const [selectedBackup, setSelectedBackup] = useState<File | null>(null);
  const [restoreResult, setRestoreResult] =
    useState<PlayerBackupRestoreResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);

  useEffect(() => {
    let active = true;
    void bootstrapPlayerSession()
      .then(async (session) => {
        const status = await loadPlayerStorage(session);
        if (!active) return;
        setCredentials(session);
        setStorage(status);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        clearPlayerCredentials();
        setError(friendlyError(reason));
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (busy !== "restore") return;
    const protectRestore = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", protectRestore);
    return () => window.removeEventListener("beforeunload", protectRestore);
  }, [busy]);

  const handleRequestError = (reason: unknown, context?: string) => {
    if (reason instanceof PlayerApiError && reason.status === 401) {
      clearPlayerCredentials();
      setCredentials(null);
      setStorage(null);
    }
    const message = friendlyError(reason);
    setError(context ? `${context} ${message}` : message);
  };

  const downloadBackup = async () => {
    if (!credentials) return;
    setBusy("export");
    setError(null);
    try {
      await exportPlayerBackup(credentials);
    } catch (reason) {
      handleRequestError(reason);
    } finally {
      setBusy(null);
    }
  };

  const restoreBackup = async () => {
    if (!credentials || !selectedBackup) return;
    setBusy("restore");
    setError(null);
    setRestoreResult(null);
    try {
      const result = await restorePlayerBackup(credentials, selectedBackup);
      setRestoreResult(result);
      setSelectedBackup(null);
      if (backupInput.current) backupInput.current.value = "";
      try {
        setStorage(await loadPlayerStorage(credentials));
      } catch (reason) {
        handleRequestError(
          reason,
          "Restore committed, but storage status could not be refreshed.",
        );
      }
    } catch (reason) {
      if (reason instanceof PlayerRestoreAmbiguousError) {
        setSelectedBackup(null);
        if (backupInput.current) backupInput.current.value = "";
        try {
          setStorage(await loadPlayerStorage(credentials));
          setError(reason.message);
        } catch (refreshError) {
          handleRequestError(
            refreshError,
            `${reason.message} Storage status could not be refreshed.`,
          );
        }
      } else {
        handleRequestError(reason);
      }
    } finally {
      setBusy(null);
    }
  };

  const signOut = async () => {
    if (!credentials) return;
    setBusy("signout");
    setError(null);
    let message = "Session closed. Start the runtime again when you are ready.";
    try {
      await revokePlayerSession(credentials);
    } catch (reason) {
      message = `Local credentials were cleared, but the runtime could not confirm session revocation. ${friendlyError(reason)}`;
    } finally {
      clearPlayerCredentials();
      setCredentials(null);
      setStorage(null);
      setSelectedBackup(null);
      setRestoreResult(null);
      if (backupInput.current) backupInput.current.value = "";
      setError(message);
      setBusy(null);
    }
  };

  const booting = !credentials && !error;
  const attentionItems = storage ? recoveryCount(storage) : 0;

  return (
    <main className="shell">
      <header className="masthead">
        <div>
          <p className="eyebrow">Private local runtime</p>
          <h1>Poker Hero</h1>
          <p className="lede">
            Your player records stay on this machine. This page talks only to
            the authenticated loopback service that opened it.
          </p>
        </div>
        {credentials ? (
          <button
            className="quiet-button"
            type="button"
            disabled={busy !== null}
            onClick={() => void signOut()}
          >
            {busy === "signout" ? "Closing…" : "Close session"}
          </button>
        ) : null}
      </header>

      {booting ? (
        <section className="panel status-panel" aria-live="polite">
          <span className="pulse" aria-hidden="true" />
          <div>
            <h2>Connecting securely</h2>
            <p>Exchanging the one-use launch ticket with the local service.</p>
          </div>
        </section>
      ) : null}

      {error ? (
        <div className="notice error" role="alert">
          {error}
        </div>
      ) : null}

      {restoreResult ? <RestoreSummary result={restoreResult} /> : null}

      {storage ? (
        <>
          <section
            className={`panel storage-panel ${
              storage.status === "ready" ? "ready" : "attention"
            }`}
            aria-labelledby="storage-heading"
          >
            <div className="status-copy">
              <p className="eyebrow">Local storage</p>
              <h2 id="storage-heading">
                {storage.status === "ready"
                  ? "Ready on this machine"
                  : "Recovery attention required"}
              </h2>
              <p className="path-label">Player data directory</p>
              <code>{storage.data_directory}</code>
            </div>
            <dl className="facts">
              <div>
                <dt>Imported hands</dt>
                <dd>{storage.imported_hand_record_count}</dd>
              </div>
              <div>
                <dt>Recovery alerts</dt>
                <dd>{attentionItems}</dd>
              </div>
            </dl>
            {attentionItems > 0 ? (
              <p className="recovery-note" role="alert">
                Import remains unavailable while quarantined or failed recovery
                evidence needs repair. Export the current store before changing
                local files.
              </p>
            ) : null}
          </section>

          <section className="backup-grid" aria-label="Backup and restore">
            <article className="panel action-card">
              <p className="step">01 · Protect your data</p>
              <h2>Export a verified backup</h2>
              <p>
                Download exact imported-hand and retained decision evidence in
                the conflict-safe player backup format.
              </p>
              <button
                className="primary-button"
                type="button"
                disabled={busy !== null}
                onClick={() => void downloadBackup()}
              >
                {busy === "export" ? "Preparing backup…" : "Download backup"}
              </button>
            </article>

            <article className="panel action-card">
              <p className="step">02 · Recover safely</p>
              <h2>Restore a player backup</h2>
              <p>
                Restore validates every checksum and deletion generation before
                one durable write. Conflicts are refused, never overwritten.
              </p>
              <label className="file-field">
                <span>Player backup ZIP</span>
                <input
                  ref={backupInput}
                  type="file"
                  accept=".zip,application/zip,application/octet-stream"
                  disabled={busy !== null}
                  onChange={(event) => {
                    setSelectedBackup(event.target.files?.[0] ?? null);
                    setRestoreResult(null);
                  }}
                />
              </label>
              <button
                className="secondary-button"
                type="button"
                disabled={busy !== null || selectedBackup === null}
                onClick={() => void restoreBackup()}
              >
                {busy === "restore"
                  ? "Validating and restoring…"
                  : "Restore backup"}
              </button>
            </article>
          </section>

          <aside
            className="boundary-note"
            aria-label="Current product boundary"
          >
            <strong>Recovery checkpoint</strong>
            <span>
              Hand-history import, review, and learning are not enabled in this
              build yet. Screenshot capture is not a player feature.
            </span>
          </aside>
        </>
      ) : null}
    </main>
  );
}
