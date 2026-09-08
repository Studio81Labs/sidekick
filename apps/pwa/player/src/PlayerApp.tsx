import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

import {
  PlayerApiError,
  PlayerHandRecoveryRequiredError,
  PlayerHandReimportAmbiguousError,
  PlayerImportAmbiguousError,
  PlayerImportRecoveryRequiredError,
  PlayerRestoreAmbiguousError,
  PlayerRestoreRecoveryRequiredError,
  type PlayerBackupRestoreResult,
  type PlayerCredentials,
  type PlayerHandDetail,
  type PlayerHandCloseAction,
  type PlayerHandConflictResolution,
  type PlayerHandList,
  type PlayerHandSummary,
  type PlayerImportBatchOutcome,
  type PlayerStorageStatus,
  approvePlayerHand,
  bootstrapPlayerSession,
  clearPlayerCredentials,
  closePlayerHand,
  deletePlayerHand,
  exportPlayerBackup,
  importPokerStarsFiles,
  loadPlayerHand,
  loadPlayerHands,
  loadPlayerStorage,
  reimportPlayerHand,
  resolvePlayerHandConflict,
  restorePlayerBackup,
  revokePlayerSession,
} from "./playerApi";
import {
  playerUpdateDirtyReasons,
  type PlayerUpdateSafety,
  usePlayerUpdateCoordinator,
} from "./playerUpdateCoordinator";
import {
  clearPlayerImportRetry,
  preservePlayerImportRetry,
} from "./playerImportRetry";
import {
  clearPlayerHandReimportRetry,
  preservePlayerHandReimportRetry,
} from "./playerReimportRetry";

type BusyAction =
  | "export"
  | "import"
  | "restore"
  | "records"
  | "detail"
  | "approve"
  | "resolve"
  | "withdraw"
  | "reject"
  | "delete"
  | "reimport"
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
    ? `${hand.identity.namespace} · ${hand.identity.site} #${hand.identity.source_hand_id}`
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
  const locators: string[] = [];
  if (evidence.line_start) {
    locators.push(
      evidence.line_end && evidence.line_end !== evidence.line_start
        ? `lines ${evidence.line_start}-${evidence.line_end}`
        : `line ${evidence.line_start}`,
    );
  }
  if (evidence.marker) locators.push(`marker ${evidence.marker}`);
  if (locators.length === 0) {
    locators.push("source excerpt redacted; no visible locator retained");
  }
  return `source ${evidence.raw_source_id} · ${locators.join(" · ")}`;
}

interface HandApprovalDraft {
  detectionId: string;
  reviewedState: string;
  correctionReason: string;
}

function approvalDraftFor(
  detail: PlayerHandDetail,
  requestedDetectionId?: string,
): HandApprovalDraft | null {
  const approvalEligibleDetectionIds = new Set(
    detail.detections
      .filter((detection) => detection.approval_eligible)
      .map((detection) => detection.detection_id),
  );
  const latestRevision =
    detail.canonical_revisions[detail.canonical_revisions.length - 1];
  const requestedDetection =
    requestedDetectionId &&
    approvalEligibleDetectionIds.has(requestedDetectionId)
      ? requestedDetectionId
      : null;
  const latestRevisionDetection =
    latestRevision &&
    approvalEligibleDetectionIds.has(latestRevision.detection_id)
      ? latestRevision.detection_id
      : null;
  const latestEligibleDetection = [...detail.detections]
    .reverse()
    .find((detection) => detection.approval_eligible)?.detection_id;
  const detectionId =
    requestedDetection ?? latestRevisionDetection ?? latestEligibleDetection;
  if (!detectionId) return null;
  const matchingRevision = [...detail.canonical_revisions]
    .reverse()
    .find((revision) => revision.detection_id === detectionId);
  const state =
    matchingRevision?.state ??
    detail.detections.find(
      (detection) => detection.detection_id === detectionId,
    )?.state;
  if (!state) return null;
  return {
    detectionId,
    reviewedState: JSON.stringify(state, null, 2),
    correctionReason: "",
  };
}

function normalizedJson(value: unknown): string {
  const normalize = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(normalize);
    if (item !== null && typeof item === "object") {
      return Object.fromEntries(
        Object.entries(item)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, child]) => [key, normalize(child)]),
      );
    }
    return item;
  };
  return JSON.stringify(normalize(value));
}

function approvalRequiresConflictResolution(
  detail: PlayerHandDetail,
  detectionId: string,
): boolean {
  if (detail.summary.unresolved_conflict_count === 0) return false;
  const selectedDetection = detail.detections.find(
    (detection) => detection.detection_id === detectionId,
  );
  const latestRevision =
    detail.canonical_revisions[detail.canonical_revisions.length - 1];
  const canonicalDetection = latestRevision
    ? detail.detections.find(
        (detection) => detection.detection_id === latestRevision.detection_id,
      )
    : null;
  return (
    !selectedDetection ||
    !canonicalDetection ||
    selectedDetection.raw_source_id !== canonicalDetection.raw_source_id
  );
}

function conflictPreservedSource(
  detail: PlayerHandDetail,
  conflict: PlayerHandDetail["conflicts"][number],
): string | null {
  const revisionNumber = conflict.active_canonical_revision_at_creation;
  if (revisionNumber === null) return null;
  const revision = detail.canonical_revisions.find(
    (item) => item.revision === revisionNumber,
  );
  if (!revision) return null;
  return (
    detail.detections.find(
      (detection) => detection.detection_id === revision.detection_id,
    )?.raw_source_id ?? null
  );
}

function conflictReviewDetectionId(
  detail: PlayerHandDetail,
  conflict: PlayerHandDetail["conflicts"][number],
  sourceId: string,
): string | undefined {
  const conflictDetections = new Set(conflict.detected_ids);
  return [...detail.detections]
    .reverse()
    .find(
      (detection) =>
        detection.approval_eligible &&
        detection.raw_source_id === sourceId &&
        conflictDetections.has(detection.detection_id),
    )?.detection_id;
}

interface HandDetailProps {
  approvalDraft: HandApprovalDraft | null;
  busy: BusyAction;
  closeReason: string;
  deleteReason: string;
  detail: PlayerHandDetail;
  reimportFile: File | null;
  reimportInput: RefObject<HTMLInputElement>;
  onApprove: () => void;
  onApprovalDetectionChange: (detectionId: string) => void;
  onCorrectionReasonChange: (reason: string) => void;
  onClose: (action: PlayerHandCloseAction) => void;
  onDelete: () => void;
  onDeleteReasonChange: (reason: string) => void;
  onReimport: () => void;
  onReimportFileChange: (file: File | null) => void;
  onReasonChange: (reason: string) => void;
  onResolveConflict: (
    conflictId: string,
    resolution: PlayerHandConflictResolution,
    selectedRawSourceId: string,
  ) => void;
  onReviewedStateChange: (state: string) => void;
}

function HandDetail({
  approvalDraft,
  busy,
  closeReason,
  deleteReason,
  detail,
  reimportFile,
  reimportInput,
  onApprove,
  onApprovalDetectionChange,
  onCorrectionReasonChange,
  onClose,
  onDelete,
  onDeleteReasonChange,
  onReimport,
  onReimportFileChange,
  onReasonChange,
  onResolveConflict,
  onReviewedStateChange,
}: HandDetailProps) {
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
  const approvalBlockedByConflict = approvalDraft
    ? approvalRequiresConflictResolution(detail, approvalDraft.detectionId)
    : false;
  return (
    <article className="hand-detail" aria-labelledby="hand-detail-heading">
      <div>
        <p className="eyebrow">Audit detail</p>
        <h3 id="hand-detail-heading">{handLabel(summary)}</h3>
        <p>
          Record key <code>{summary.record_key}</code>
        </p>
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
          <dt>Source occurrences</dt>
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
      {approvalDraft &&
      ["pending_review", "active", "withdrawn", "rejected"].includes(
        summary.lifecycle_status,
      ) ? (
        <div className="audit-block lifecycle-actions approval-review">
          <h4>Review and approve canonical state</h4>
          <p>
            Select one retained detection, review every field, and explicitly
            publish the JSON below as canonical ground truth. Parser output
            remains retained as evidence; your approved revision is stored
            separately and becomes the only state eligible for learning.
          </p>
          {summary.unresolved_conflict_count > 0 ? (
            approvalBlockedByConflict ? (
              <p className="deletion-failure" role="alert">
                Resolve the retained source conflict before switching the
                canonical revision to this detection's source.
              </p>
            ) : (
              <p className="field-help">
                A competing source remains unresolved. This reapproval stays on
                the preserved canonical source and does not resolve or replace
                it.
              </p>
            )
          ) : null}
          <label>
            <span>Detection to review</span>
            <select
              value={approvalDraft.detectionId}
              disabled={busy !== null}
              onChange={(event) =>
                onApprovalDetectionChange(event.target.value)
              }
            >
              {detail.detections
                .filter((detection) => detection.approval_eligible)
                .map((detection) => (
                  <option
                    key={detection.detection_id}
                    value={detection.detection_id}
                  >
                    {detection.detection_id} · {detection.detector_id}{" "}
                    {detection.detector_version}
                  </option>
                ))}
            </select>
          </label>
          <label>
            <span>Reviewed canonical state (JSON)</span>
            <textarea
              className="canonical-state-editor"
              required
              rows={18}
              spellCheck={false}
              value={approvalDraft.reviewedState}
              disabled={busy !== null}
              onChange={(event) => onReviewedStateChange(event.target.value)}
            />
          </label>
          <label>
            <span>Correction reason</span>
            <textarea
              maxLength={500}
              rows={3}
              value={approvalDraft.correctionReason}
              disabled={busy !== null}
              onChange={(event) => onCorrectionReasonChange(event.target.value)}
            />
          </label>
          <p className="field-help">
            A reason is required whenever the reviewed JSON differs from the
            selected detection. The service derives corrected fields, detected
            values, and audit timestamps itself.
          </p>
          <button
            className="primary-button"
            type="button"
            disabled={busy !== null || approvalBlockedByConflict}
            onClick={onApprove}
          >
            {busy === "approve"
              ? "Approving reviewed state…"
              : summary.canonical_revision_count > 0
                ? "Approve new canonical revision"
                : "Approve canonical state"}
          </button>
        </div>
      ) : null}
      {summary.lifecycle_status === "active" ? (
        <div className="audit-block lifecycle-actions">
          <h4>Change approval state</h4>
          <p>
            Both actions immediately remove this revision from local learning.
            Raw sources, detections, corrections, and canonical revisions stay
            retained for audit.
          </p>
          <label>
            <span>Reason</span>
            <textarea
              required
              maxLength={256}
              rows={3}
              value={closeReason}
              disabled={busy !== null}
              onChange={(event) => onReasonChange(event.target.value)}
            />
          </label>
          <div className="lifecycle-action-buttons">
            <button
              className="secondary-button"
              type="button"
              disabled={busy !== null || closeReason.trim().length === 0}
              onClick={() => onClose("withdraw")}
            >
              {busy === "withdraw" ? "Withdrawing…" : "Withdraw approval"}
            </button>
            <button
              className="danger-button"
              type="button"
              disabled={busy !== null || closeReason.trim().length === 0}
              onClick={() => onClose("reject")}
            >
              {busy === "reject" ? "Rejecting…" : "Reject as incorrect"}
            </button>
          </div>
        </div>
      ) : null}
      {["deleted", "deletion_pending"].includes(summary.lifecycle_status) ? (
        <div className="audit-block lifecycle-actions authorized-reimport">
          <h4>Reimport deleted hand for review</h4>
          <p>
            Select a PokerStars text file containing this exact hand. This
            explicitly crosses the deletion boundary, advances its deletion
            generation, and creates a fresh unapproved parser proposal. It does
            not restore prior sources, corrections, conflicts, approvals, or
            learning data.
          </p>
          {summary.lifecycle_status === "deletion_pending" ? (
            <p className="field-help">
              Reimporting now cancels the pending cleanup by replacing the old
              incarnation and atomically removing its retained audit artifacts.
            </p>
          ) : null}
          <label className="file-field">
            <span>PokerStars file containing this deleted hand</span>
            <input
              ref={reimportInput}
              type="file"
              accept=".txt,text/plain"
              disabled={busy !== null}
              onChange={(event) =>
                onReimportFileChange(event.target.files?.[0] ?? null)
              }
            />
          </label>
          {reimportFile ? (
            <p className="selected-files">Selected: {reimportFile.name}</p>
          ) : null}
          <button
            className="primary-button"
            type="button"
            disabled={busy !== null || reimportFile === null}
            onClick={onReimport}
          >
            {busy === "reimport"
              ? "Reimporting for review…"
              : "Authorize reimport for review"}
          </button>
        </div>
      ) : null}
      {summary.lifecycle_status !== "deleted" ? (
        <div className="audit-block lifecycle-actions permanent-deletion">
          <h4>Permanently delete retained hand</h4>
          <p>
            This first makes the hand inactive, then permanently removes raw
            sources, detections, conflicts, corrections, canonical revisions,
            and derived audit. Only a non-sensitive receipt and deletion
            generation remain. An older backup cannot undo the deletion.
          </p>
          <label>
            <span>Permanent deletion reason</span>
            <textarea
              required
              maxLength={256}
              rows={3}
              value={deleteReason}
              disabled={busy !== null}
              onChange={(event) => onDeleteReasonChange(event.target.value)}
            />
          </label>
          <div className="lifecycle-action-buttons">
            <button
              className="danger-button"
              type="button"
              disabled={busy !== null || deleteReason.trim().length === 0}
              onClick={onDelete}
            >
              {busy === "delete"
                ? "Deleting permanently…"
                : summary.lifecycle_status === "deletion_pending"
                  ? "Retry deletion cleanup"
                  : "Delete permanently"}
            </button>
          </div>
        </div>
      ) : null}
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
                {detection.approval_eligible ? "" : " · reimport audit only"}
              </summary>
              <pre>{JSON.stringify(detection.state, null, 2)}</pre>
              <p className="receipt-line">
                Normalized proposal checksum{" "}
                <code>{detection.content_sha256}</code>
              </p>
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
                {source.provenance.source_kind} import{" "}
                <code>{source.provenance.import_id}</code> · format{" "}
                {source.provenance.format_revision} ·{" "}
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
                {" · raw source checksum "}
                <code>{source.content_sha256}</code>
                {source.reimports.length > 0 ? (
                  <ul>
                    {source.reimports.map((reimport) => (
                      <li key={reimport.raw_source_id}>
                        Reimport <code>{reimport.raw_source_id}</code> ·{" "}
                        {reimport.provenance.source_filename ??
                          "Unnamed source"}
                        {" · "}
                        {reimport.provenance.source_kind} import{" "}
                        <code>{reimport.provenance.import_id}</code> · format{" "}
                        {reimport.provenance.format_revision} ·{" "}
                        {reimport.provenance.adapter_id}{" "}
                        {reimport.provenance.adapter_version}
                        {" · "}
                        {new Date(
                          reimport.provenance.imported_at,
                        ).toLocaleString()}
                        {reimport.chronology.played_at
                          ? ` · played ${new Date(reimport.chronology.played_at).toLocaleString()} (${reimport.chronology.played_at})`
                          : " · played time not retained"}
                        {` · source timezone ${reimport.chronology.source_timezone ?? "not retained"}`}
                        {` · source session ${reimport.chronology.source_session_id ?? "not retained"}`}
                        {` · source file ${reimport.chronology.source_file_id}`}
                        {` · hand ordinal ${reimport.chronology.hand_ordinal ?? "not retained"}`}
                        {" · detection "}
                        <code>{reimport.detection_id}</code>
                        {" · detected meaning checksum "}
                        <code>{reimport.detected_semantic_sha256}</code>
                      </li>
                    ))}
                  </ul>
                ) : null}
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
            {detail.conflicts.map((conflict) => {
              const preservedSource = conflictPreservedSource(detail, conflict);
              return (
                <li key={conflict.conflict_id}>
                  <span>
                    <strong>{lifecycleLabel(conflict.status)}</strong> ·
                    conflict <code>{conflict.conflict_id}</code>
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
                  {conflict.status === "unresolved" ? (
                    <div className="conflict-actions">
                      <p>
                        Keep the preserved canonical state, or select one source
                        to review before a separate explicit approval. Choosing
                        a source never approves parser output by itself.
                      </p>
                      {preservedSource ? (
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={busy !== null}
                          onClick={() =>
                            onResolveConflict(
                              conflict.conflict_id,
                              "keep_active",
                              preservedSource,
                            )
                          }
                        >
                          {busy === "resolve"
                            ? "Resolving…"
                            : "Keep preserved canonical state"}
                        </button>
                      ) : null}
                      {conflict.raw_source_ids.map((sourceId) => {
                        const detectionId = conflictReviewDetectionId(
                          detail,
                          conflict,
                          sourceId,
                        );
                        return (
                          <button
                            className="quiet-button"
                            type="button"
                            key={sourceId}
                            disabled={busy !== null || !detectionId}
                            title={
                              detectionId
                                ? undefined
                                : "No reviewable detection is retained for this source"
                            }
                            onClick={() =>
                              onResolveConflict(
                                conflict.conflict_id,
                                "use_source",
                                sourceId,
                              )
                            }
                          >
                            Review source {sourceId}
                          </button>
                        );
                      })}
                    </div>
                  ) : null}
                </li>
              );
            })}
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
          Deletion receipt {detail.deletion_receipt.receipt_id} · generation{" "}
          {detail.deletion_receipt.generation} ·{" "}
          {new Date(detail.deletion_receipt.deleted_at).toLocaleString()} ·
          tombstone checksum{" "}
          <code>{detail.deletion_receipt.tombstone_sha256}</code>
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
      <span>
        {result.imported_grade_artifacts} grade artifacts imported,{" "}
        {result.reused_grade_artifacts} already present,{" "}
        {result.removed_grade_artifacts} removed by restored deletion evidence.
      </span>
      <span>{result.total_records} local records now retained.</span>
    </div>
  );
}

function ImportSummary({ result }: { result: PlayerImportBatchOutcome }) {
  return (
    <div className="notice import-result" role="status">
      <strong>
        {result.summary.retry_required
          ? "Import needs a safe retry."
          : "Import finished with reviewable outcomes."}
      </strong>
      <span>
        {result.summary.hands_succeeded} hands retained across{" "}
        {result.summary.files_processed} of {result.summary.files_received}{" "}
        files; {result.summary.diagnostic_count} diagnostics require review.
      </span>
      {result.summary.duplicate_requests > 0 ? (
        <span>
          {result.summary.duplicate_requests} retry outcomes were already
          retained and were not duplicated.
        </span>
      ) : null}
      <ul className="import-outcomes">
        {result.files.map((file, fileIndex) => (
          <li key={`${file.filename}-${fileIndex}`}>
            <strong>
              {file.filename} · {file.status}
            </strong>
            <span>
              {file.hands.length} hands retained · {file.diagnostics.length}{" "}
              diagnostics
            </span>
            {file.hands.map((hand) => (
              <span key={`${hand.record_key}-${hand.hand_ordinal}`}>
                Hand #{hand.source_hand_id} ·{" "}
                {hand.disposition.replace(/_/g, " ")} ·{" "}
                {hand.reconciliation_status} reconciliation ·{" "}
                {hand.lifecycle_status.replace(/_/g, " ")}
              </span>
            ))}
            {file.diagnostics.map((diagnostic, diagnosticIndex) => (
              <span
                key={`${diagnostic.code}-${diagnostic.hand_ordinal}-${diagnosticIndex}`}
              >
                {diagnostic.hand_ordinal
                  ? `Hand ${diagnostic.hand_ordinal} · `
                  : ""}
                {diagnostic.code.replace(/_/g, " ")} · {diagnostic.message}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PlayerApp() {
  const backupInput = useRef<HTMLInputElement>(null);
  const importInput = useRef<HTMLInputElement>(null);
  const reimportInput = useRef<HTMLInputElement>(null);
  const permitNextUnloadRef = useRef(false);
  const [credentials, setCredentials] = useState<PlayerCredentials | null>(
    null,
  );
  const [storage, setStorage] = useState<PlayerStorageStatus | null>(null);
  const [selectedBackup, setSelectedBackup] = useState<File | null>(null);
  const [restoreResult, setRestoreResult] =
    useState<PlayerBackupRestoreResult | null>(null);
  const [selectedImportFiles, setSelectedImportFiles] = useState<File[]>([]);
  const [importRequestId, setImportRequestId] = useState<string | null>(null);
  const [importResult, setImportResult] =
    useState<PlayerImportBatchOutcome | null>(null);
  const [handPage, setHandPage] = useState<PlayerHandList | null>(null);
  const [handDetail, setHandDetail] = useState<PlayerHandDetail | null>(null);
  const [selectedReimportFile, setSelectedReimportFile] = useState<File | null>(
    null,
  );
  const [reimportRequestId, setReimportRequestId] = useState<string | null>(
    null,
  );
  const [approvalDraft, setApprovalDraft] = useState<HandApprovalDraft | null>(
    null,
  );
  const [loadingHandKey, setLoadingHandKey] = useState<string | null>(null);
  const [closeReason, setCloseReason] = useState("");
  const [deleteReason, setDeleteReason] = useState("");
  const [actionNotice, setActionNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [draftRevision, setDraftRevision] = useState(0);

  const clearReimportSelection = () => {
    setSelectedReimportFile(null);
    setReimportRequestId(null);
    if (reimportInput.current) reimportInput.current.value = "";
  };

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

  const handleRequestError = (reason: unknown, context?: string) => {
    if (reason instanceof PlayerApiError && reason.status === 401) {
      clearPlayerCredentials();
      setCredentials(null);
      setStorage(null);
      setHandPage(null);
      setHandDetail(null);
      setApprovalDraft(null);
      setCloseReason("");
      setDeleteReason("");
      clearReimportSelection();
      setActionNotice(null);
    }
    const message = friendlyError(reason);
    setError(context ? `${context} ${message}` : message);
  };

  const requireHandRecovery = (message: string) => {
    clearPlayerCredentials();
    setCredentials(null);
    setStorage(null);
    setHandPage(null);
    setHandDetail(null);
    setApprovalDraft(null);
    setCloseReason("");
    setDeleteReason("");
    clearReimportSelection();
    setActionNotice(null);
    setError(message);
  };

  const downloadBackup = async () => {
    if (!credentials) return;
    setBusy("export");
    setError(null);
    setActionNotice(null);
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
    setActionNotice(null);
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
      if (!append) {
        setHandDetail(null);
        setApprovalDraft(null);
        setCloseReason("");
        setDeleteReason("");
        clearReimportSelection();
      }
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
    setActionNotice(null);
    setHandDetail(null);
    setApprovalDraft(null);
    setCloseReason("");
    setDeleteReason("");
    clearReimportSelection();
    setLoadingHandKey(recordKey);
    try {
      const detail = await loadPlayerHand(credentials, recordKey);
      setHandDetail(detail);
      setApprovalDraft(approvalDraftFor(detail));
      if (detail.summary.lifecycle_status === "deletion_pending") {
        setDeleteReason(detail.lifecycle.reason ?? "");
      }
    } catch (reason) {
      if (reason instanceof PlayerHandRecoveryRequiredError) {
        requireHandRecovery(reason.message);
      } else {
        handleRequestError(reason);
      }
    } finally {
      setLoadingHandKey(null);
      setBusy(null);
    }
  };

  const replaceHandDetail = (
    detail: PlayerHandDetail,
    nextApprovalDraft = approvalDraftFor(detail),
  ) => {
    setHandDetail(detail);
    setApprovalDraft(nextApprovalDraft);
    setHandPage((current) =>
      current
        ? {
            ...current,
            items: current.items.map((item) =>
              item.record_key === detail.summary.record_key
                ? detail.summary
                : item,
            ),
          }
        : current,
    );
  };

  const approveReviewedHand = async () => {
    if (!credentials || !handDetail || !approvalDraft) return;
    if (
      approvalRequiresConflictResolution(handDetail, approvalDraft.detectionId)
    ) {
      setError(
        "Resolve the retained source conflict before switching canonical source.",
      );
      return;
    }
    let approvedState: Record<string, unknown>;
    try {
      const parsed = JSON.parse(approvalDraft.reviewedState) as unknown;
      if (
        parsed === null ||
        typeof parsed !== "object" ||
        Array.isArray(parsed)
      ) {
        throw new Error("not an object");
      }
      approvedState = parsed as Record<string, unknown>;
    } catch {
      setError("Reviewed canonical state must be a valid JSON object.");
      return;
    }
    const detection = handDetail.detections.find(
      (item) => item.detection_id === approvalDraft.detectionId,
    );
    if (!detection) {
      setError(
        "The selected detection is no longer retained. Reload the hand.",
      );
      return;
    }
    const correctionReason = approvalDraft.correctionReason.trim();
    if (
      normalizedJson(approvedState) !== normalizedJson(detection.state) &&
      correctionReason.length === 0
    ) {
      setError(
        "Add a correction reason because the reviewed state differs from the selected detection.",
      );
      return;
    }
    const confirmed = window.confirm(
      `Confirm canonical approval from detection ${approvalDraft.detectionId}. The reviewed state will become explicit ground truth for local learning, while the parser proposal remains retained separately for audit.`,
    );
    if (!confirmed) return;

    const requestedDetail = handDetail;
    const requestId = crypto.randomUUID();
    setBusy("approve");
    setError(null);
    setActionNotice(null);
    try {
      const updated = await approvePlayerHand(
        credentials,
        requestedDetail.summary.record_key,
        requestId,
        approvalDraft.detectionId,
        approvedState,
        correctionReason || null,
        requestedDetail.summary,
      );
      replaceHandDetail(updated);
      setActionNotice(
        `Canonical revision ${updated.summary.active_canonical_revision} approved. The reviewed state is now active for local learning.`,
      );
    } catch (approvalError) {
      if (approvalError instanceof PlayerHandRecoveryRequiredError) {
        requireHandRecovery(approvalError.message);
      } else if (
        approvalError instanceof PlayerApiError &&
        approvalError.status === 401
      ) {
        handleRequestError(approvalError);
      } else {
        try {
          const refreshed = await loadPlayerHand(
            credentials,
            requestedDetail.summary.record_key,
          );
          const latestRevision =
            refreshed.canonical_revisions[
              refreshed.canonical_revisions.length - 1
            ];
          const exactApprovalCommitted =
            refreshed.summary.lifecycle_status === "active" &&
            latestRevision?.approval_id === requestId &&
            refreshed.summary.active_canonical_revision ===
              latestRevision.revision;
          const preservedDraft = refreshed.detections.some(
            (item) => item.detection_id === approvalDraft.detectionId,
          )
            ? approvalDraft
            : approvalDraftFor(refreshed);
          replaceHandDetail(
            refreshed,
            exactApprovalCommitted
              ? approvalDraftFor(refreshed)
              : preservedDraft,
          );
          if (exactApprovalCommitted) {
            setActionNotice(
              `Canonical revision ${latestRevision.revision} committed even though the original response was interrupted. The exact approval audit was refreshed.`,
            );
          } else {
            handleRequestError(
              approvalError,
              "Canonical approval was not confirmed. The audit detail was refreshed.",
            );
          }
        } catch (refreshError) {
          if (refreshError instanceof PlayerHandRecoveryRequiredError) {
            requireHandRecovery(
              `${friendlyError(approvalError)} ${refreshError.message}`,
            );
          } else {
            setHandDetail(null);
            setApprovalDraft(null);
            handleRequestError(
              refreshError,
              `${friendlyError(approvalError)} The approval outcome could not be refreshed; reload the records before retrying.`,
            );
          }
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const resolveImportConflict = async (
    conflictId: string,
    resolution: PlayerHandConflictResolution,
    selectedRawSourceId: string,
  ) => {
    if (!credentials || !handDetail) return;
    const conflict = handDetail.conflicts.find(
      (item) => item.conflict_id === conflictId,
    );
    if (!conflict || conflict.status !== "unresolved") {
      setError("The conflict is no longer unresolved. Reload the hand.");
      return;
    }
    const confirmed = window.confirm(
      resolution === "keep_active"
        ? "Confirm keeping the preserved canonical state. The competing source remains retained for audit, but this conflict will be closed."
        : `Confirm source ${selectedRawSourceId} for review. An active hand will become pending review and stop contributing to learning until you explicitly approve reviewed canonical state.`,
    );
    if (!confirmed) return;

    const requestedDetail = handDetail;
    const targetStatus =
      resolution === "keep_active"
        ? "resolved_keep_active"
        : "resolved_use_source";
    setBusy("resolve");
    setError(null);
    setActionNotice(null);
    try {
      const updated = await resolvePlayerHandConflict(
        credentials,
        requestedDetail.summary.record_key,
        conflictId,
        resolution,
        selectedRawSourceId,
        requestedDetail.summary,
      );
      const updatedConflict = updated.conflicts.find(
        (item) => item.conflict_id === conflictId,
      );
      const reviewDetectionId =
        resolution === "use_source" && updatedConflict
          ? conflictReviewDetectionId(
              updated,
              updatedConflict,
              selectedRawSourceId,
            )
          : undefined;
      replaceHandDetail(updated, approvalDraftFor(updated, reviewDetectionId));
      setActionNotice(
        resolution === "keep_active"
          ? "Conflict resolved. The preserved canonical state remains in effect."
          : "Conflict resolved to the selected source. Review and explicitly approve its detected state before it can contribute to learning.",
      );
    } catch (resolutionError) {
      if (resolutionError instanceof PlayerHandRecoveryRequiredError) {
        requireHandRecovery(resolutionError.message);
      } else if (
        resolutionError instanceof PlayerApiError &&
        resolutionError.status === 401
      ) {
        handleRequestError(resolutionError);
      } else {
        try {
          const refreshed = await loadPlayerHand(
            credentials,
            requestedDetail.summary.record_key,
          );
          const refreshedConflict = refreshed.conflicts.find(
            (item) => item.conflict_id === conflictId,
          );
          const exactResolutionCommitted =
            refreshedConflict?.status === targetStatus &&
            refreshedConflict.selected_raw_source_id === selectedRawSourceId;
          const reviewDetectionId =
            resolution === "use_source" && refreshedConflict
              ? conflictReviewDetectionId(
                  refreshed,
                  refreshedConflict,
                  selectedRawSourceId,
                )
              : undefined;
          replaceHandDetail(
            refreshed,
            approvalDraftFor(refreshed, reviewDetectionId),
          );
          if (exactResolutionCommitted) {
            setActionNotice(
              "The conflict resolution committed even though the original response was interrupted. The audit detail was refreshed.",
            );
          } else {
            handleRequestError(
              resolutionError,
              "The conflict was not resolved. The audit detail was refreshed.",
            );
          }
        } catch (refreshError) {
          if (refreshError instanceof PlayerHandRecoveryRequiredError) {
            requireHandRecovery(
              `${friendlyError(resolutionError)} ${refreshError.message}`,
            );
          } else {
            setHandDetail(null);
            setApprovalDraft(null);
            handleRequestError(
              refreshError,
              `${friendlyError(resolutionError)} The conflict outcome could not be refreshed; reload the records before retrying.`,
            );
          }
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const closeHandApproval = async (action: PlayerHandCloseAction) => {
    if (!credentials || !handDetail || closeReason.trim().length === 0) return;
    const verb =
      action === "withdraw" ? "withdraw approval" : "reject this hand";
    const confirmed = window.confirm(
      `Confirm ${verb}. The hand will stop contributing to local learning, while its audit evidence remains retained.`,
    );
    if (!confirmed) return;

    const requestedDetail = handDetail;
    const reason = closeReason.trim();
    setBusy(action);
    setError(null);
    setActionNotice(null);
    try {
      const updated = await closePlayerHand(
        credentials,
        requestedDetail.summary.record_key,
        action,
        reason,
        requestedDetail.summary,
      );
      replaceHandDetail(updated);
      setCloseReason("");
      setActionNotice(
        action === "withdraw"
          ? "Approval withdrawn. Retained evidence is now inactive."
          : "Hand rejected. Retained evidence is now inactive.",
      );
    } catch (reasonError) {
      if (reasonError instanceof PlayerHandRecoveryRequiredError) {
        requireHandRecovery(reasonError.message);
      } else if (
        reasonError instanceof PlayerApiError &&
        reasonError.status === 401
      ) {
        handleRequestError(reasonError);
      } else {
        try {
          const refreshed = await loadPlayerHand(
            credentials,
            requestedDetail.summary.record_key,
          );
          replaceHandDetail(refreshed);
          const expectedStatus =
            action === "withdraw" ? "withdrawn" : "rejected";
          const refreshedRevision =
            refreshed.canonical_revisions[
              refreshed.canonical_revisions.length - 1
            ]?.revision ?? null;
          if (
            refreshed.summary.lifecycle_status === expectedStatus &&
            refreshed.lifecycle.reason === reason &&
            refreshedRevision ===
              requestedDetail.summary.active_canonical_revision &&
            refreshed.summary.deletion_generation ===
              requestedDetail.summary.deletion_generation
          ) {
            setCloseReason("");
            setActionNotice(
              `The ${expectedStatus} state committed even though the original response was interrupted. The audit detail was refreshed.`,
            );
          } else {
            handleRequestError(
              reasonError,
              "Approval state was not changed. The audit detail was refreshed.",
            );
          }
        } catch (refreshError) {
          if (refreshError instanceof PlayerHandRecoveryRequiredError) {
            requireHandRecovery(
              `${friendlyError(reasonError)} ${refreshError.message}`,
            );
          } else {
            setHandDetail(null);
            handleRequestError(
              refreshError,
              `${friendlyError(reasonError)} The lifecycle outcome could not be refreshed; reload the records before retrying.`,
            );
          }
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const permanentlyDeleteHand = async () => {
    if (!credentials || !handDetail || deleteReason.trim().length === 0) return;
    const confirmed = window.confirm(
      "Confirm permanent deletion. Raw sources, detected and approved state, conflicts, corrections, and derived audit will be removed. Only a deletion receipt remains, and this cannot be undone by restoring an older backup.",
    );
    if (!confirmed) return;

    const requestedDetail = handDetail;
    const reason = deleteReason.trim();
    const requestId = crypto.randomUUID();
    const targetGeneration =
      requestedDetail.summary.lifecycle_status === "deletion_pending"
        ? requestedDetail.summary.deletion_generation
        : requestedDetail.summary.deletion_generation + 1;
    setBusy("delete");
    setError(null);
    setActionNotice(null);
    try {
      const updated = await deletePlayerHand(
        credentials,
        requestedDetail.summary.record_key,
        requestId,
        reason,
        requestedDetail.summary,
      );
      replaceHandDetail(updated);
      setCloseReason("");
      setDeleteReason("");
      setActionNotice(
        "Permanent deletion completed. Only the deletion receipt and generation remain.",
      );
    } catch (deleteError) {
      if (deleteError instanceof PlayerHandRecoveryRequiredError) {
        requireHandRecovery(deleteError.message);
      } else if (
        deleteError instanceof PlayerApiError &&
        deleteError.status === 401
      ) {
        handleRequestError(deleteError);
      } else {
        try {
          const refreshed = await loadPlayerHand(
            credentials,
            requestedDetail.summary.record_key,
          );
          replaceHandDetail(refreshed);
          if (
            refreshed.summary.lifecycle_status === "deleted" &&
            refreshed.summary.deletion_generation === targetGeneration &&
            refreshed.deletion_receipt?.receipt_id === requestId
          ) {
            setCloseReason("");
            setDeleteReason("");
            setActionNotice(
              "Permanent deletion committed even though the original response was interrupted. The receipt was refreshed.",
            );
          } else if (
            refreshed.summary.lifecycle_status === "deletion_pending"
          ) {
            setCloseReason("");
            setDeleteReason(refreshed.lifecycle.reason ?? "");
            handleRequestError(
              deleteError,
              "The hand is inactive and deletion cleanup is pending. Review the refreshed detail and retry cleanup.",
            );
          } else {
            setDeleteReason("");
            handleRequestError(
              deleteError,
              "Permanent deletion was not confirmed. The audit detail was refreshed.",
            );
          }
        } catch (refreshError) {
          if (refreshError instanceof PlayerHandRecoveryRequiredError) {
            requireHandRecovery(
              `${friendlyError(deleteError)} ${refreshError.message}`,
            );
          } else {
            setHandDetail(null);
            setDeleteReason("");
            handleRequestError(
              refreshError,
              `${friendlyError(deleteError)} The deletion outcome could not be refreshed; reload the records before retrying.`,
            );
          }
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const reimportDeletedHand = async () => {
    if (!credentials || !handDetail || !selectedReimportFile) return;
    if (
      handDetail.summary.lifecycle_status !== "deleted" &&
      handDetail.summary.lifecycle_status !== "deletion_pending"
    ) {
      return;
    }
    const confirmed = window.confirm(
      "Authorize this exact PokerStars hand reimport. The deleted incarnation will not return: a new deletion generation with fresh parser evidence will be created as pending review, with no approval or learning eligibility.",
    );
    if (!confirmed) return;

    const requestedDetail = handDetail;
    const file = selectedReimportFile;
    setBusy("reimport");
    setError(null);
    setActionNotice(null);
    try {
      const requestId = await preservePlayerHandReimportRetry(
        requestedDetail.summary.record_key,
        file,
        reimportRequestId ?? crypto.randomUUID(),
      );
      setReimportRequestId(requestId);
      const submit = () =>
        reimportPlayerHand(
          credentials,
          requestedDetail.summary.record_key,
          file,
          requestId,
          requestedDetail.summary,
        );
      let result;
      try {
        result = await submit();
      } catch (reason) {
        if (!(reason instanceof PlayerHandReimportAmbiguousError)) throw reason;
        result = await submit();
      }
      replaceHandDetail(result.hand);
      clearPlayerHandReimportRetry();
      clearReimportSelection();
      setDeleteReason("");
      setActionNotice(
        result.disposition === "duplicate_request"
          ? "The authorized reimport had already committed. Its fresh pending-review evidence was loaded without duplication."
          : "Authorized reimport completed. Fresh parser evidence is pending explicit canonical review and remains ineligible for learning.",
      );
    } catch (reason) {
      if (reason instanceof PlayerHandRecoveryRequiredError) {
        requireHandRecovery(reason.message);
      } else if (reason instanceof PlayerHandReimportAmbiguousError) {
        setError(reason.message);
      } else if (reason instanceof PlayerApiError && reason.status === 401) {
        handleRequestError(reason);
      } else {
        try {
          const refreshed = await loadPlayerHand(
            credentials,
            requestedDetail.summary.record_key,
          );
          replaceHandDetail(refreshed);
          if (
            refreshed.summary.lifecycle_status !== "deleted" &&
            refreshed.summary.lifecycle_status !== "deletion_pending"
          ) {
            clearPlayerHandReimportRetry();
            clearReimportSelection();
          }
          handleRequestError(
            reason,
            "Authorized reimport was not confirmed. The audit detail was refreshed.",
          );
        } catch (refreshError) {
          if (refreshError instanceof PlayerHandRecoveryRequiredError) {
            requireHandRecovery(
              `${friendlyError(reason)} ${refreshError.message}`,
            );
          } else {
            setHandDetail(null);
            handleRequestError(
              refreshError,
              `${friendlyError(reason)} The reimport outcome could not be refreshed; reload the records before retrying.`,
            );
          }
        }
      }
    } finally {
      setBusy(null);
    }
  };

  const importHandHistories = async () => {
    if (!credentials || selectedImportFiles.length === 0 || !importRequestId) {
      return;
    }
    setBusy("import");
    setError(null);
    setActionNotice(null);
    setImportResult(null);
    try {
      const retainedRequestId = await preservePlayerImportRetry(
        selectedImportFiles,
        importRequestId,
      );
      setImportRequestId(retainedRequestId);
      const result = await importPokerStarsFiles(
        credentials,
        selectedImportFiles,
        retainedRequestId,
      );
      setImportResult(result);
      if (!result.summary.retry_required) {
        clearPlayerImportRetry();
        setSelectedImportFiles([]);
        setImportRequestId(null);
        if (importInput.current) importInput.current.value = "";
      }
      setHandPage(null);
      setHandDetail(null);
      setApprovalDraft(null);
      setCloseReason("");
      setDeleteReason("");
      clearReimportSelection();
      try {
        setStorage(await loadPlayerStorage(credentials));
        if (result.summary.retry_required) {
          setError(
            "Some hand outcomes were not confirmed. The same request ID and selected files remain ready for a safe retry.",
          );
        }
      } catch (reason) {
        setStorage(null);
        handleRequestError(
          reason,
          "Import finished, but storage status could not be refreshed.",
        );
      }
    } catch (reason) {
      if (reason instanceof PlayerImportRecoveryRequiredError) {
        clearPlayerCredentials();
        setCredentials(null);
        setStorage(null);
        setHandPage(null);
        setHandDetail(null);
        setApprovalDraft(null);
        setCloseReason("");
        setDeleteReason("");
        clearReimportSelection();
        setSelectedImportFiles([]);
        setImportRequestId(null);
        if (importInput.current) importInput.current.value = "";
        setError(
          `${reason.message} Reselect the same files in the same order to reuse the retained safe-retry identity.`,
        );
      } else if (reason instanceof PlayerImportAmbiguousError) {
        setHandPage(null);
        setHandDetail(null);
        setApprovalDraft(null);
        setCloseReason("");
        setDeleteReason("");
        clearReimportSelection();
        try {
          setStorage(await loadPlayerStorage(credentials));
          setError(
            `${reason.message} The same request ID and selected files remain ready for a safe retry.`,
          );
        } catch (refreshError) {
          setStorage(null);
          handleRequestError(
            refreshError,
            `${reason.message} A stable storage status could not be obtained. Restart the local player runtime before retrying.`,
          );
        }
      } else {
        handleRequestError(reason);
      }
    } finally {
      setBusy(null);
    }
  };

  const restoreBackup = async () => {
    if (!credentials || !selectedBackup) return;
    setBusy("restore");
    setError(null);
    setActionNotice(null);
    setRestoreResult(null);
    try {
      const result = await restorePlayerBackup(credentials, selectedBackup);
      setRestoreResult(result);
      setHandPage(null);
      setHandDetail(null);
      setApprovalDraft(null);
      setCloseReason("");
      setDeleteReason("");
      clearReimportSelection();
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
        setApprovalDraft(null);
        setCloseReason("");
        setDeleteReason("");
        clearReimportSelection();
        setSelectedBackup(null);
        if (backupInput.current) backupInput.current.value = "";
        setError(reason.message);
      } else if (reason instanceof PlayerRestoreAmbiguousError) {
        setHandPage(null);
        setHandDetail(null);
        setApprovalDraft(null);
        setCloseReason("");
        setDeleteReason("");
        clearReimportSelection();
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
      setSelectedImportFiles([]);
      setImportRequestId(null);
      setImportResult(null);
      setHandPage(null);
      setHandDetail(null);
      setApprovalDraft(null);
      setCloseReason("");
      setDeleteReason("");
      clearReimportSelection();
      setActionNotice(null);
      if (backupInput.current) backupInput.current.value = "";
      if (importInput.current) importInput.current.value = "";
      setError(message);
      setBusy(null);
    }
  };

  const booting = !credentials && !error;
  const attentionItems = storage ? recoveryCount(storage) : 0;
  const defaultApprovalDraft = handDetail ? approvalDraftFor(handDetail) : null;
  const defaultDeleteReason =
    handDetail?.summary.lifecycle_status === "deletion_pending"
      ? (handDetail.lifecycle.reason ?? "")
      : "";
  const approvalDraftDirty =
    approvalDraft !== null &&
    (defaultApprovalDraft === null ||
      approvalDraft.detectionId !== defaultApprovalDraft.detectionId ||
      approvalDraft.reviewedState !== defaultApprovalDraft.reviewedState ||
      approvalDraft.correctionReason !== defaultApprovalDraft.correctionReason);
  const dirtyReasons = playerUpdateDirtyReasons({
    approvalChanged: approvalDraftDirty,
    approvalStateReasonChanged: closeReason !== "",
    backupSelected: selectedBackup !== null,
    importFilesSelected: selectedImportFiles.length > 0,
    permanentDeletionReasonChanged: deleteReason !== defaultDeleteReason,
    reimportFileSelected: selectedReimportFile !== null,
  });
  const updateSafety: PlayerUpdateSafety = {
    dirtyRevision: draftRevision,
    isBusy: booting || busy !== null,
    isDirty: dirtyReasons.length > 0,
  };
  const prepareForUpdateReload = useCallback(() => {
    permitNextUnloadRef.current = true;
    window.setTimeout(() => {
      permitNextUnloadRef.current = false;
    }, 0);
  }, []);
  const update = usePlayerUpdateCoordinator(
    updateSafety,
    prepareForUpdateReload,
  );

  useLayoutEffect(() => {
    if (!updateSafety.isBusy && !updateSafety.isDirty) return;
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
  }, [updateSafety.isBusy, updateSafety.isDirty]);

  const markDraftChanged = () => {
    setDraftRevision((current) => current + 1);
  };
  const activateDiscardingDrafts = () => {
    if (
      window.confirm(
        "Discard every unsaved local player draft and reload the update?",
      )
    ) {
      update.activate(true);
    }
  };
  const updateMessage = update.activated
    ? "Poker Hero Local Player has updated. Reload when your work is safe."
    : updateSafety.isBusy
      ? "A local player update is ready and will wait for active work to finish."
      : updateSafety.isDirty
        ? "A local player update is ready. Finish your drafts or explicitly discard them."
        : "A local player update is ready to reload.";

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

      {update.available ? (
        <div className="notice player-update" role="status" aria-live="polite">
          <span>{updateMessage}</span>
          {!updateSafety.isBusy ? (
            <button
              className="secondary-button"
              type="button"
              disabled={update.activating}
              onClick={
                updateSafety.isDirty
                  ? activateDiscardingDrafts
                  : () => update.activate(false)
              }
            >
              {update.activating
                ? "Updating…"
                : updateSafety.isDirty
                  ? "Discard and reload"
                  : "Reload update"}
            </button>
          ) : null}
        </div>
      ) : null}

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

      {importResult ? <ImportSummary result={importResult} /> : null}

      {actionNotice ? (
        <div className="notice restore-result" role="status">
          {actionNotice}
        </div>
      ) : null}

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
                <dt>Storage layout</dt>
                <dd>Version {storage.layout_version}</dd>
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
            className="panel import-panel"
            aria-labelledby="import-heading"
          >
            <div>
              <p className="eyebrow">Local hand-history import</p>
              <h2 id="import-heading">Import PokerStars text histories</h2>
              <p>
                Select one or more UTF-8 .txt exports. The current adapter
                supports a bounded English no-limit cash subset plus one
                reviewed historical tournament-header form. Every parser
                proposal remains unapproved; new hand identities stay pending
                review until you explicitly approve canonical state.
              </p>
            </div>
            <label className="file-field">
              <span>PokerStars hand-history files</span>
              <input
                ref={importInput}
                type="file"
                multiple
                accept=".txt,text/plain"
                disabled={busy !== null || attentionItems > 0}
                onChange={(event) => {
                  markDraftChanged();
                  const selected = Array.from(event.target.files ?? []);
                  if (selected.length === 0) clearPlayerImportRetry();
                  setSelectedImportFiles(selected);
                  setImportRequestId(
                    selected.length > 0 ? crypto.randomUUID() : null,
                  );
                  setImportResult(null);
                }}
              />
            </label>
            {selectedImportFiles.length > 0 ? (
              <p className="selected-files">
                {selectedImportFiles.length} file
                {selectedImportFiles.length === 1 ? "" : "s"} selected:{" "}
                {selectedImportFiles.map((file) => file.name).join(", ")}
              </p>
            ) : null}
            <button
              className="primary-button"
              type="button"
              disabled={
                busy !== null ||
                attentionItems > 0 ||
                selectedImportFiles.length === 0
              }
              onClick={() => void importHandHistories()}
            >
              {busy === "import"
                ? "Parsing and retaining…"
                : "Import for review"}
            </button>
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
                  histories in the collection response. Review a retained
                  detection to approve canonical ground truth, change an active
                  approval, or permanently delete a hand from its audit detail.
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
                          Record key <code>{hand.record_key}</code>
                        </span>
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
                for authenticated audit inspection.
              </p>
            )}
            {handDetail ? (
              <HandDetail
                approvalDraft={approvalDraft}
                busy={busy}
                closeReason={closeReason}
                deleteReason={deleteReason}
                detail={handDetail}
                reimportFile={selectedReimportFile}
                reimportInput={reimportInput}
                onApprove={() => void approveReviewedHand()}
                onApprovalDetectionChange={(detectionId) => {
                  markDraftChanged();
                  setApprovalDraft(approvalDraftFor(handDetail, detectionId));
                }}
                onCorrectionReasonChange={(correctionReason) => {
                  markDraftChanged();
                  setApprovalDraft((current) =>
                    current ? { ...current, correctionReason } : current,
                  );
                }}
                onClose={(action) => void closeHandApproval(action)}
                onDelete={() => void permanentlyDeleteHand()}
                onDeleteReasonChange={(reason) => {
                  markDraftChanged();
                  setDeleteReason(reason);
                }}
                onReimport={() => void reimportDeletedHand()}
                onReimportFileChange={(file) => {
                  markDraftChanged();
                  if (file === null) clearPlayerHandReimportRetry();
                  setSelectedReimportFile(file);
                  setReimportRequestId(
                    file === null ? null : crypto.randomUUID(),
                  );
                }}
                onReasonChange={(reason) => {
                  markDraftChanged();
                  setCloseReason(reason);
                }}
                onResolveConflict={(conflictId, resolution, sourceId) =>
                  void resolveImportConflict(conflictId, resolution, sourceId)
                }
                onReviewedStateChange={(reviewedState) => {
                  markDraftChanged();
                  setApprovalDraft((current) =>
                    current ? { ...current, reviewedState } : current,
                  );
                }}
              />
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
                    markDraftChanged();
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
              Bounded PokerStars text import, correction, and explicit approval
              are enabled in this local runtime. Imported parser output remains
              pending review and never becomes canonical ground truth
              automatically. The V2 learning loop is not enabled yet. Existing
              approvals can be revised, withdrawn, or rejected while evidence
              remains auditable, and retained hands can be permanently deleted
              to receipt-only tombstones. Screenshot capture is not a player
              feature.
            </span>
          </aside>
        </>
      ) : null}
    </main>
  );
}
