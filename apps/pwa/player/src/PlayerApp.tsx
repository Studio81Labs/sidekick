import { useEffect, useRef, useState } from "react";

import {
  PlayerApiError,
  PlayerRestoreAmbiguousError,
  PlayerRestoreRecoveryRequiredError,
  type PlayerBackupRestoreResult,
  type PlayerCredentials,
  type PlayerHandDetail,
  type PlayerHandList,
  type PlayerHandSummary,
  type PlayerStorageStatus,
  bootstrapPlayerSession,
  clearPlayerCredentials,
  exportPlayerBackup,
  loadPlayerHand,
  loadPlayerHands,
  loadPlayerStorage,
  restorePlayerBackup,
  revokePlayerSession,
} from "./playerApi";

type BusyAction =
  | "export"
  | "restore"
  | "records"
  | "detail"
  | "signout"
  | null;

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

function lifecycleLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function handLabel(hand: PlayerHandSummary): string {
  return hand.identity
    ? `${hand.identity.site} #${hand.identity.source_hand_id}`
    : `Deleted record · generation ${hand.deletion_generation}`;
}

function confidenceLabel(confidence: string | null): string {
  if (confidence === null) return "confidence not scored";
  const value = Number(confidence);
  return Number.isFinite(value)
    ? `${Math.round(value * 100)}% confidence`
    : "confidence unavailable";
}

function evidenceLocation(
  evidence: PlayerHandDetail["detections"][number]["field_evidence"][string]["evidence"][number],
): string {
  const lines = evidence.line_start
    ? evidence.line_end && evidence.line_end !== evidence.line_start
      ? `lines ${evidence.line_start}-${evidence.line_end}`
      : `line ${evidence.line_start}`
    : "source location retained";
  return `source ${evidence.raw_source_id} · ${lines}${
    evidence.marker ? ` · marker ${evidence.marker}` : ""
  }`;
}

function HandDetail({ detail }: { detail: PlayerHandDetail }) {
  const { summary } = detail;
  const recognitionWarnings = detail.detections.flatMap((detection) => [
    ...detection.warnings.map((warning) => ({
      detectionId: detection.detection_id,
      field: null,
      warning,
    })),
    ...Object.entries(detection.field_evidence).flatMap(([field, evidence]) =>
      evidence.warnings.map((warning) => ({
        detectionId: detection.detection_id,
        field,
        warning,
      })),
    ),
  ]);
  const fieldConfidence = detail.detections.flatMap((detection) =>
    Object.entries(detection.field_evidence).map(([field, evidence]) => ({
      confidence: evidence.confidence,
      detectionId: detection.detection_id,
      evidence: evidence.evidence,
      field,
    })),
  );
  const deletionRequest = detail.lifecycle.deletion_request;
  return (
    <article className="hand-detail" aria-labelledby="hand-detail-heading">
      <div>
        <p className="eyebrow">Read-only audit detail</p>
        <h3 id="hand-detail-heading">{handLabel(summary)}</h3>
        <p>
          Lifecycle: <strong>{lifecycleLabel(summary.lifecycle_status)}</strong>
          . Changed {new Date(summary.lifecycle_changed_at).toLocaleString()}.
        </p>
        {detail.lifecycle.reason ? (
          <p>Lifecycle reason: {detail.lifecycle.reason}</p>
        ) : null}
        {summary.lifecycle_status === "deleted" ? (
          <p>
            The tombstone retains only deletion generation and receipt evidence;
            hand-linked content is gone.
          </p>
        ) : summary.lifecycle_status === "deletion_pending" ? (
          deletionRequest?.cleanup_status === "failed" ? (
            <p className="deletion-failure" role="alert">
              Deletion cleanup failed: {deletionRequest.last_error}. This record
              remains inactive and needs repair before cleanup can finish.
              Requested{" "}
              {new Date(deletionRequest.requested_at).toLocaleString()}.
            </p>
          ) : (
            <p>
              Deletion cleanup is pending. This record is inactive and is not
              used for learning.
            </p>
          )
        ) : summary.learning_eligible ? (
          <p>
            Canonical revision {summary.active_canonical_revision} is active and
            eligible for local learning.
          </p>
        ) : summary.lifecycle_status === "withdrawn" ? (
          <p>
            This hand was previously approved, but its approval is now
            withdrawn. Its retained canonical revisions are inactive and not
            used for learning.
          </p>
        ) : summary.lifecycle_status === "rejected" ? (
          <p>
            This hand was previously approved, then rejected. Its retained
            canonical revisions are inactive and not used for learning.
          </p>
        ) : (
          <p>
            This record is not approved for learning. Detected evidence remains
            a proposal until a later review workflow explicitly approves it.
          </p>
        )}
      </div>
      <dl className="audit-facts">
        <div>
          <dt>Raw sources</dt>
          <dd>{summary.raw_source_count}</dd>
        </div>
        <div>
          <dt>Detections</dt>
          <dd>{summary.detection_count}</dd>
        </div>
        <div>
          <dt>Warnings</dt>
          <dd>{summary.warning_count}</dd>
        </div>
        <div>
          <dt>Open conflicts</dt>
          <dd>{summary.unresolved_conflict_count}</dd>
        </div>
      </dl>
      {detail.detections.length > 0 ? (
        <div className="audit-block state-block">
          <h4>Detected proposals</h4>
          {detail.detections.map((detection) => (
            <details key={detection.detection_id}>
              <summary>
                Detection {detection.detection_id} · source{" "}
                {detection.raw_source_id} · {detection.detector_id}{" "}
                {detection.detector_version} · detected{" "}
                {new Date(detection.detected_at).toLocaleString()}
              </summary>
              <pre>{JSON.stringify(detection.state, null, 2)}</pre>
            </details>
          ))}
        </div>
      ) : null}
      {fieldConfidence.length > 0 ? (
        <div className="audit-block confidence-block">
          <h4>Detected field confidence</h4>
          <ul>
            {fieldConfidence.map((field) => (
              <li key={`${field.detectionId}-${field.field}`}>
                Detection {field.detectionId} · <code>{field.field}</code> ·{" "}
                {confidenceLabel(field.confidence)}
                {field.evidence.map((evidence, index) => (
                  <span key={`${evidence.raw_source_id}-${index}`}>
                    {evidenceLocation(evidence)}
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {detail.raw_sources.length > 0 ? (
        <div className="audit-block">
          <h4>Import provenance</h4>
          <ul>
            {detail.raw_sources.map((source) => (
              <li key={source.raw_source_id}>
                Source <code>{source.raw_source_id}</code> ·{" "}
                {source.provenance.source_filename ?? "Unnamed source"} ·{" "}
                {source.provenance.adapter_id}{" "}
                {source.provenance.adapter_version}
                {" · "}
                {new Date(source.provenance.imported_at).toLocaleString()}
                {source.chronology.played_at
                  ? ` · played ${new Date(source.chronology.played_at).toLocaleString()} (${source.chronology.played_at})`
                  : " · played time not retained"}
                {` · source timezone ${source.chronology.source_timezone ?? "not retained"}`}
                {` · source session ${source.chronology.source_session_id ?? "not retained"}`}
                {` · source file ${source.chronology.source_file_id}`}
                {` · hand ordinal ${source.chronology.hand_ordinal ?? "not retained"}`}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {recognitionWarnings.length > 0 ? (
        <div className="audit-block warning-block">
          <h4>Recognition warnings</h4>
          <ul>
            {recognitionWarnings.map((warning, index) => (
              <li key={`${warning.detectionId}-${warning.field}-${index}`}>
                <span>
                  Detection {warning.detectionId} ·{" "}
                  {warning.field
                    ? `field ${warning.field}`
                    : "proposal warning"}
                </span>
                <span>{warning.warning}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {detail.conflicts.length > 0 ? (
        <div className="audit-block conflict-block">
          <h4>Import conflict history</h4>
          <ul>
            {detail.conflicts.map((conflict) => (
              <li key={conflict.conflict_id}>
                <span>
                  <strong>{lifecycleLabel(conflict.status)}</strong> · conflict{" "}
                  <code>{conflict.conflict_id}</code>
                </span>
                <span>
                  Sources: {conflict.raw_source_ids.join(", ")}. Detections:{" "}
                  {conflict.detected_ids.length > 0
                    ? conflict.detected_ids.join(", ")
                    : "none retained at creation"}
                  .
                </span>
                {conflict.active_canonical_revision_at_creation !== null ? (
                  <span>
                    Active revision at creation:{" "}
                    {conflict.active_canonical_revision_at_creation}.
                  </span>
                ) : null}
                {conflict.selected_raw_source_id ? (
                  <span>
                    Selected source: {conflict.selected_raw_source_id}
                    {conflict.resolved_at
                      ? ` · resolved ${new Date(conflict.resolved_at).toLocaleString()}`
                      : ""}
                    .
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {detail.canonical_revisions.length > 0 ? (
        <div className="audit-block state-block">
          <h4>Approved canonical revisions</h4>
          {detail.canonical_revisions.map((revision) => (
            <details key={revision.revision}>
              <summary>
                Revision {revision.revision} · detection {revision.detection_id}{" "}
                · approved {new Date(revision.approved_at).toLocaleString()}
              </summary>
              <pre>{JSON.stringify(revision.state, null, 2)}</pre>
              {revision.corrections.length > 0 ? (
                <div className="corrections-block">
                  <h5>User corrections</h5>
                  <ul>
                    {revision.corrections.map((correction) => (
                      <li
                        key={`${revision.revision}-${correction.field_pointer}`}
                      >
                        <strong>
                          <code>{correction.field_pointer}</code> ·{" "}
                          {new Date(correction.corrected_at).toLocaleString()}
                        </strong>
                        {correction.reason ? (
                          <span>{correction.reason}</span>
                        ) : null}
                        <pre>
                          {JSON.stringify(
                            {
                              approved: correction.approved_value,
                              detected: correction.detected_value,
                            },
                            null,
                            2,
                          )}
                        </pre>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </details>
          ))}
        </div>
      ) : null}
      {detail.deletion_receipt ? (
        <p className="receipt-line">
          Deletion receipt {detail.deletion_receipt.receipt_id} ·{" "}
          {new Date(detail.deletion_receipt.deleted_at).toLocaleString()}
        </p>
      ) : null}
    </article>
  );
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
  const [handPage, setHandPage] = useState<PlayerHandList | null>(null);
  const [handDetail, setHandDetail] = useState<PlayerHandDetail | null>(null);
  const [loadingHandKey, setLoadingHandKey] = useState<string | null>(null);
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
        if (reason instanceof PlayerApiError && reason.status === 401) {
          clearPlayerCredentials();
        }
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
      setHandPage(null);
      setHandDetail(null);
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

  const loadHands = async (append: boolean) => {
    if (!credentials) return;
    setBusy("records");
    setError(null);
    try {
      const page = await loadPlayerHands(
        credentials,
        append ? (handPage?.next_cursor ?? undefined) : undefined,
      );
      setHandPage((current) =>
        append && current
          ? {
              items: [...current.items, ...page.items],
              unreadable: [...current.unreadable, ...page.unreadable],
              next_cursor: page.next_cursor,
            }
          : page,
      );
      if (!append) setHandDetail(null);
    } catch (reason) {
      handleRequestError(reason);
    } finally {
      setBusy(null);
    }
  };

  const inspectHand = async (recordKey: string) => {
    if (!credentials) return;
    setBusy("detail");
    setError(null);
    setHandDetail(null);
    setLoadingHandKey(recordKey);
    try {
      setHandDetail(await loadPlayerHand(credentials, recordKey));
    } catch (reason) {
      handleRequestError(reason);
    } finally {
      setLoadingHandKey(null);
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
      setHandPage(null);
      setHandDetail(null);
      setSelectedBackup(null);
      if (backupInput.current) backupInput.current.value = "";
      try {
        setStorage(await loadPlayerStorage(credentials));
      } catch (reason) {
        setStorage(null);
        handleRequestError(
          reason,
          "Restore committed, but storage status could not be refreshed.",
        );
      }
    } catch (reason) {
      if (reason instanceof PlayerRestoreRecoveryRequiredError) {
        clearPlayerCredentials();
        setCredentials(null);
        setStorage(null);
        setHandPage(null);
        setHandDetail(null);
        setSelectedBackup(null);
        if (backupInput.current) backupInput.current.value = "";
        setError(reason.message);
      } else if (reason instanceof PlayerRestoreAmbiguousError) {
        setHandPage(null);
        setHandDetail(null);
        setSelectedBackup(null);
        if (backupInput.current) backupInput.current.value = "";
        try {
          setStorage(await loadPlayerStorage(credentials));
          setError(
            `${reason.message} Review the refreshed storage totals and export a backup before deciding whether to retry.`,
          );
        } catch (refreshError) {
          setStorage(null);
          handleRequestError(
            refreshError,
            `${reason.message} A stable storage status could not be obtained. Restart the local player runtime before exporting a backup or retrying.`,
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
      setHandPage(null);
      setHandDetail(null);
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

          <section
            className="panel records-panel"
            aria-labelledby="records-heading"
          >
            <div className="records-heading-row">
              <div>
                <p className="eyebrow">Retained evidence</p>
                <h2 id="records-heading">Local hand records</h2>
                <p>
                  Inspect lifecycle and provenance without exposing raw hand
                  histories in the collection response.
                </p>
              </div>
              {storage.imported_hand_record_count > 0 ? (
                <button
                  className="secondary-button records-load-button"
                  type="button"
                  disabled={busy !== null}
                  onClick={() => void loadHands(false)}
                >
                  {busy === "records" && handPage === null
                    ? "Loading records…"
                    : handPage
                      ? "Refresh records"
                      : "Load hand records"}
                </button>
              ) : null}
            </div>
            {storage.imported_hand_record_count === 0 ? (
              <p className="empty-records">
                No imported hand records are retained yet.
              </p>
            ) : handPage ? (
              <>
                <ul className="hand-list">
                  {handPage.items.map((hand) => (
                    <li key={hand.record_key}>
                      <div>
                        <strong>{handLabel(hand)}</strong>
                        <span>
                          {lifecycleLabel(hand.lifecycle_status)} ·{" "}
                          {hand.warning_count} warnings
                          {" · "}
                          {hand.unresolved_conflict_count} open conflicts
                        </span>
                        <span>
                          {hand.learning_eligible
                            ? `Active revision ${hand.active_canonical_revision} · learning eligible`
                            : "Not used for learning"}
                        </span>
                        {hand.played_at ? (
                          <span>
                            Played {new Date(hand.played_at).toLocaleString()}
                          </span>
                        ) : null}
                      </div>
                      <button
                        className="quiet-button"
                        type="button"
                        disabled={busy !== null}
                        onClick={() => void inspectHand(hand.record_key)}
                      >
                        {busy === "detail" && loadingHandKey === hand.record_key
                          ? "Loading…"
                          : "View audit detail"}
                      </button>
                    </li>
                  ))}
                </ul>
                {handPage.unreadable.length > 0 ? (
                  <div className="notice error" role="alert">
                    <p>
                      Some retained records could not be read safely. Their keys
                      remain visible so later records stay reachable.
                    </p>
                    <ul>
                      {handPage.unreadable.map((failure) => (
                        <li key={failure.record_key}>
                          <code>{failure.record_key}</code> · {failure.detail}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                {handPage.next_cursor ? (
                  <button
                    className="secondary-button"
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void loadHands(true)}
                  >
                    {busy === "records" ? "Loading more…" : "Load more"}
                  </button>
                ) : null}
              </>
            ) : (
              <p className="empty-records">
                {storage.imported_hand_record_count} retained records are ready
                for authenticated, read-only inspection.
              </p>
            )}
            {handDetail ? <HandDetail detail={handDetail} /> : null}
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
              Direct hand-history import, correction, approval, and learning are
              not enabled in this build yet. Retained backup records can be
              inspected read-only. Screenshot capture is not a player feature.
            </span>
          </aside>
        </>
      ) : null}
    </main>
  );
}
