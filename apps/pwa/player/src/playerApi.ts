export const PLAYER_SESSION_STORAGE_KEY = "poker-hero-player-session-v1";
export const PLAYER_CSRF_STORAGE_KEY = "poker-hero-player-csrf-v1";

export interface PlayerCredentials {
  sessionToken: string;
  csrfToken: string;
}

export interface PlayerStorageStatus {
  status: "ready" | "attention_required";
  storage: "player-local-file";
  layout_version: 1;
  data_directory: string;
  imported_hand_record_count: number;
  recovery: {
    completed: string[];
    quarantined: string[];
    failed: string[];
  };
}

export interface PlayerBackupRestoreResult {
  imported_records: number;
  reused_records: number;
  skipped_stale_records: number;
  imported_decision_artifacts: number;
  reused_decision_artifacts: number;
  removed_decision_artifacts: number;
  imported_grade_artifacts: number;
  reused_grade_artifacts: number;
  removed_grade_artifacts: number;
  total_records: number;
}

export type PlayerImportDisposition =
  | "created_pending_review"
  | "recorded_exact_reimport"
  | "recorded_identity_conflict"
  | "duplicate_request";

export interface PlayerImportDiagnostic {
  code: string;
  message: string;
  hand_ordinal: number | null;
  source_hand_id: string | null;
  line_start: number | null;
  line_end: number | null;
}

export interface PlayerImportBatchOutcome {
  request_id: string;
  files: Array<{
    file_slot: number;
    filename: string;
    status: "processed" | "partial" | "rejected";
    hands: Array<{
      hand_ordinal: number;
      source_hand_id: string;
      record_key: string;
      disposition: PlayerImportDisposition;
      parser_disposition:
        | "clean"
        | "reconciliation_failed"
        | "reconciliation_indeterminate";
      reconciliation_status: "pass" | "fail" | "indeterminate";
      lifecycle_status: string;
      warning_count: number;
    }>;
    diagnostics: PlayerImportDiagnostic[];
  }>;
  summary: {
    files_received: number;
    files_processed: number;
    hands_succeeded: number;
    diagnostic_count: number;
    duplicate_requests: number;
    retry_required: boolean;
  };
}

export interface PlayerHandReimportOutcome {
  request_id: string;
  disposition: "restored_pending_review" | "duplicate_request";
  parser_disposition:
    | "clean"
    | "reconciliation_failed"
    | "reconciliation_indeterminate";
  reconciliation_status: "pass" | "fail" | "indeterminate";
  hand: PlayerHandDetail;
}

export type PlayerHandLifecycleStatus =
  | "pending_review"
  | "active"
  | "withdrawn"
  | "rejected"
  | "deletion_pending"
  | "deleted";

export interface PlayerHandSummary {
  record_key: string;
  record_version: string;
  identity: {
    namespace: string;
    site: string;
    source_hand_id: string;
  } | null;
  played_at: string | null;
  lifecycle_status: PlayerHandLifecycleStatus;
  lifecycle_changed_at: string;
  active_canonical_revision: number | null;
  learning_eligible: boolean;
  deletion_generation: number;
  raw_source_count: number;
  detection_count: number;
  warning_count: number;
  unresolved_conflict_count: number;
  canonical_revision_count: number;
}

export interface PlayerHandList {
  items: PlayerHandSummary[];
  unreadable: Array<{ record_key: string; detail: string }>;
  next_cursor: string | null;
}

export type PlayerHandCloseAction = "withdraw" | "reject";
export type PlayerHandConflictResolution = "keep_active" | "use_source";

export interface PlayerHandDetail {
  summary: PlayerHandSummary;
  lifecycle: {
    status: PlayerHandLifecycleStatus;
    active_canonical_revision: number | null;
    deletion_generation: number;
    changed_at: string;
    reason: string | null;
    deletion_request: {
      generation: number;
      requested_at: string;
      cleanup_status: "pending" | "failed";
      last_error: string | null;
    } | null;
  };
  raw_sources: Array<{
    raw_source_id: string;
    chronology: {
      played_at: string | null;
      source_timezone: string | null;
      source_session_id: string | null;
      source_file_id: string;
      hand_ordinal: number | null;
    };
    provenance: {
      source_kind: "hand_history";
      import_id: string;
      imported_at: string;
      adapter_id: string;
      adapter_version: string;
      format_revision: string;
      source_filename: string | null;
    };
    content_sha256: string;
    reimports: Array<{
      raw_source_id: string;
      chronology: {
        played_at: string | null;
        source_timezone: string | null;
        source_session_id: string | null;
        source_file_id: string;
        hand_ordinal: number | null;
      };
      provenance: {
        source_kind: "hand_history";
        import_id: string;
        imported_at: string;
        adapter_id: string;
        adapter_version: string;
        format_revision: string;
        source_filename: string | null;
      };
      detection_id: string;
      detected_semantic_sha256: string;
    }>;
  }>;
  detections: Array<{
    detection_id: string;
    raw_source_id: string;
    detector_id: string;
    detector_version: string;
    detected_at: string;
    state: Record<string, unknown>;
    field_evidence: Record<
      string,
      {
        confidence: string | null;
        evidence: Array<{
          raw_source_id: string;
          line_start: number | null;
          line_end: number | null;
          marker: string | null;
        }>;
        warnings: string[];
      }
    >;
    warnings: string[];
    content_sha256: string;
    approval_eligible: boolean;
  }>;
  conflicts: Array<{
    conflict_id: string;
    raw_source_ids: string[];
    detected_ids: string[];
    active_canonical_revision_at_creation: number | null;
    status: "unresolved" | "resolved_keep_active" | "resolved_use_source";
    selected_raw_source_id: string | null;
    resolved_at: string | null;
  }>;
  canonical_revisions: Array<{
    approval_id: string | null;
    revision: number;
    detection_id: string;
    approved_at: string;
    state: Record<string, unknown>;
    corrections: Array<{
      field_pointer: string;
      detected_value: unknown;
      approved_value: unknown;
      corrected_at: string;
      reason: string | null;
    }>;
  }>;
  deletion_receipt: {
    receipt_id: string;
    generation: number;
    deleted_at: string;
    tombstone_sha256: string;
  } | null;
}

interface PlayerSessionResponse {
  session_token: string;
  csrf_token: string;
  expires_in_seconds: number;
}

export class PlayerApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "PlayerApiError";
  }
}

export class PlayerRestoreAmbiguousError extends Error {
  constructor() {
    super(
      "The restore may have committed, but the browser did not receive a complete response. Local data may already have changed.",
    );
    this.name = "PlayerRestoreAmbiguousError";
  }
}

export class PlayerRestoreRecoveryRequiredError extends Error {
  constructor() {
    super(
      "The restore did not complete and may have partially changed local data. Restart the local player runtime so journal recovery can finish before exporting a backup or retrying.",
    );
    this.name = "PlayerRestoreRecoveryRequiredError";
  }
}

export class PlayerImportAmbiguousError extends Error {
  constructor() {
    super(
      "The import may have committed, but the browser did not receive a complete response. Retry the same selected files to recover the per-hand outcomes safely.",
    );
    this.name = "PlayerImportAmbiguousError";
  }
}

export class PlayerImportRecoveryRequiredError extends Error {
  constructor() {
    super(
      "Local storage requires recovery before another import. Restart the local player runtime, then select the files again.",
    );
    this.name = "PlayerImportRecoveryRequiredError";
  }
}

export class PlayerHandRecoveryRequiredError extends Error {
  constructor() {
    super(
      "The hand lifecycle outcome is unresolved. Restart the local player runtime so journal recovery can finish, then reload the hand before retrying.",
    );
    this.name = "PlayerHandRecoveryRequiredError";
  }
}

export class PlayerHandReimportAmbiguousError extends Error {
  constructor() {
    super(
      "The authorized reimport may have committed, but the browser did not receive a complete response. The same file and request identity remain ready for a safe retry.",
    );
    this.name = "PlayerHandReimportAmbiguousError";
  }
}

function takeLaunchTicket(): string | null {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const ticket = fragment.get("ticket");
  if (window.location.hash) {
    window.history.replaceState(
      null,
      "",
      window.location.pathname + window.location.search,
    );
  }
  return ticket;
}

function readStoredCredentials(): PlayerCredentials | null {
  const sessionToken = sessionStorage.getItem(PLAYER_SESSION_STORAGE_KEY);
  const csrfToken = sessionStorage.getItem(PLAYER_CSRF_STORAGE_KEY);
  return sessionToken && csrfToken ? { sessionToken, csrfToken } : null;
}

function storeCredentials(credentials: PlayerCredentials): void {
  sessionStorage.setItem(PLAYER_SESSION_STORAGE_KEY, credentials.sessionToken);
  sessionStorage.setItem(PLAYER_CSRF_STORAGE_KEY, credentials.csrfToken);
}

export function clearPlayerCredentials(): void {
  sessionStorage.removeItem(PLAYER_SESSION_STORAGE_KEY);
  sessionStorage.removeItem(PLAYER_CSRF_STORAGE_KEY);
}

async function errorFrom(response: Response): Promise<PlayerApiError> {
  let detail = `The local player API returned ${response.status}.`;
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      detail = payload.detail;
    }
  } catch {
    // The status remains authoritative when the response is not JSON.
  }
  return new PlayerApiError(detail, response.status);
}

async function exchangeLaunchTicket(
  ticket: string,
): Promise<PlayerCredentials> {
  const response = await fetch("/api/player/session", {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: { Authorization: `Bearer ${ticket}` },
  });
  if (!response.ok) throw await errorFrom(response);
  const session = (await response.json()) as PlayerSessionResponse;
  if (!session.session_token || !session.csrf_token) {
    throw new Error("The local runtime returned an invalid player session.");
  }
  return {
    sessionToken: session.session_token,
    csrfToken: session.csrf_token,
  };
}

export async function bootstrapPlayerSession(): Promise<PlayerCredentials> {
  const ticket = takeLaunchTicket();
  try {
    if (ticket) {
      const credentials = await exchangeLaunchTicket(ticket);
      storeCredentials(credentials);
      return credentials;
    }
    const stored = readStoredCredentials();
    if (stored) return stored;
  } catch (error) {
    clearPlayerCredentials();
    throw error;
  }
  throw new Error("Start the local player runtime again to create a session.");
}

async function playerRequest(
  credentials: PlayerCredentials,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${credentials.sessionToken}`);
  if (["DELETE", "PATCH", "POST", "PUT"].includes(method)) {
    headers.set("X-Poker-CSRF-Token", credentials.csrfToken);
  }
  const response = await fetch(path, {
    ...init,
    method,
    cache: "no-store",
    credentials: "same-origin",
    headers,
  });
  if (!response.ok) throw await errorFrom(response);
  return response;
}

export async function loadPlayerStorage(
  credentials: PlayerCredentials,
): Promise<PlayerStorageStatus> {
  const response = await playerRequest(credentials, "/api/player/storage");
  return (await response.json()) as PlayerStorageStatus;
}

export async function loadPlayerHands(
  credentials: PlayerCredentials,
  cursor?: string,
): Promise<PlayerHandList> {
  const query = new URLSearchParams({ limit: "25" });
  if (cursor) query.set("cursor", cursor);
  const response = await playerRequest(
    credentials,
    `/api/player/hands?${query.toString()}`,
  );
  return (await response.json()) as PlayerHandList;
}

export async function loadPlayerHand(
  credentials: PlayerCredentials,
  recordKey: string,
): Promise<PlayerHandDetail> {
  let response: Response;
  try {
    response = await playerRequest(
      credentials,
      `/api/player/hands/${encodeURIComponent(recordKey)}`,
    );
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerHandRecoveryRequiredError();
    }
    throw error;
  }
  return (await response.json()) as PlayerHandDetail;
}

export async function closePlayerHand(
  credentials: PlayerCredentials,
  recordKey: string,
  action: PlayerHandCloseAction,
  reason: string,
  expected: PlayerHandSummary,
): Promise<PlayerHandDetail> {
  if (expected.active_canonical_revision === null) {
    throw new Error("Only an active approved hand can change approval state.");
  }
  let response: Response;
  try {
    response = await playerRequest(
      credentials,
      `/api/player/hands/${encodeURIComponent(recordKey)}/${action}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          reason,
          expected_active_canonical_revision:
            expected.active_canonical_revision,
          expected_deletion_generation: expected.deletion_generation,
          expected_lifecycle_changed_at: expected.lifecycle_changed_at,
        }),
      },
    );
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerHandRecoveryRequiredError();
    }
    throw error;
  }
  return (await response.json()) as PlayerHandDetail;
}

export async function approvePlayerHand(
  credentials: PlayerCredentials,
  recordKey: string,
  requestId: string,
  detectionId: string,
  approvedState: Record<string, unknown>,
  correctionReason: string | null,
  expected: PlayerHandSummary,
): Promise<PlayerHandDetail> {
  if (
    expected.lifecycle_status === "deletion_pending" ||
    expected.lifecycle_status === "deleted"
  ) {
    throw new Error(
      "A hand pending or completing deletion cannot be approved.",
    );
  }
  let response: Response;
  try {
    response = await playerRequest(
      credentials,
      `/api/player/hands/${encodeURIComponent(recordKey)}/approve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          detection_id: detectionId,
          approved_state: approvedState,
          correction_reason: correctionReason,
          expected_record_version: expected.record_version,
          expected_lifecycle_status: expected.lifecycle_status,
          expected_active_canonical_revision:
            expected.active_canonical_revision,
          expected_canonical_revision_count: expected.canonical_revision_count,
          expected_deletion_generation: expected.deletion_generation,
          expected_lifecycle_changed_at: expected.lifecycle_changed_at,
        }),
      },
    );
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerHandRecoveryRequiredError();
    }
    throw error;
  }
  return (await response.json()) as PlayerHandDetail;
}

export async function resolvePlayerHandConflict(
  credentials: PlayerCredentials,
  recordKey: string,
  conflictId: string,
  resolution: PlayerHandConflictResolution,
  selectedRawSourceId: string,
  expected: PlayerHandSummary,
): Promise<PlayerHandDetail> {
  if (
    expected.lifecycle_status === "deletion_pending" ||
    expected.lifecycle_status === "deleted"
  ) {
    throw new Error(
      "A hand pending or completing deletion cannot resolve conflicts.",
    );
  }
  let response: Response;
  try {
    response = await playerRequest(
      credentials,
      `/api/player/hands/${encodeURIComponent(recordKey)}/conflicts/${encodeURIComponent(conflictId)}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resolution,
          selected_raw_source_id: selectedRawSourceId,
          expected_record_version: expected.record_version,
          expected_lifecycle_status: expected.lifecycle_status,
          expected_active_canonical_revision:
            expected.active_canonical_revision,
          expected_canonical_revision_count: expected.canonical_revision_count,
          expected_deletion_generation: expected.deletion_generation,
          expected_lifecycle_changed_at: expected.lifecycle_changed_at,
        }),
      },
    );
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerHandRecoveryRequiredError();
    }
    throw error;
  }
  return (await response.json()) as PlayerHandDetail;
}

export async function deletePlayerHand(
  credentials: PlayerCredentials,
  recordKey: string,
  requestId: string,
  reason: string,
  expected: PlayerHandSummary,
): Promise<PlayerHandDetail> {
  if (expected.lifecycle_status === "deleted") {
    throw new Error("This retained hand has already been permanently deleted.");
  }
  let response: Response;
  try {
    response = await playerRequest(
      credentials,
      `/api/player/hands/${encodeURIComponent(recordKey)}/delete`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request_id: requestId,
          reason,
          expected_record_version: expected.record_version,
          expected_lifecycle_status: expected.lifecycle_status,
          expected_active_canonical_revision:
            expected.active_canonical_revision,
          expected_deletion_generation: expected.deletion_generation,
          expected_lifecycle_changed_at: expected.lifecycle_changed_at,
        }),
      },
    );
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerHandRecoveryRequiredError();
    }
    throw error;
  }
  return (await response.json()) as PlayerHandDetail;
}

function isPlayerHandReimportOutcome(
  value: unknown,
  requestId: string,
  recordKey: string,
  expectedDeletionGeneration: number,
): value is PlayerHandReimportOutcome {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  const hand = payload.hand as PlayerHandDetail | undefined;
  return (
    payload.request_id === requestId &&
    ["restored_pending_review", "duplicate_request"].includes(
      String(payload.disposition),
    ) &&
    ["clean", "reconciliation_failed", "reconciliation_indeterminate"].includes(
      String(payload.parser_disposition),
    ) &&
    ["pass", "fail", "indeterminate"].includes(
      String(payload.reconciliation_status),
    ) &&
    !!hand &&
    hand.summary?.record_key === recordKey &&
    hand.summary.lifecycle_status === "pending_review" &&
    hand.summary.learning_eligible === false &&
    hand.summary.active_canonical_revision === null &&
    hand.summary.deletion_generation === expectedDeletionGeneration + 1 &&
    hand.summary.raw_source_count === 1 &&
    hand.summary.detection_count === 1 &&
    hand.summary.unresolved_conflict_count === 0 &&
    hand.summary.canonical_revision_count === 0 &&
    hand.lifecycle?.status === "pending_review" &&
    hand.lifecycle.deletion_generation === expectedDeletionGeneration + 1 &&
    hand.lifecycle.reason === "authorized reimport" &&
    hand.raw_sources?.length === 1 &&
    hand.detections?.length === 1 &&
    hand.conflicts?.length === 0 &&
    hand.canonical_revisions?.length === 0 &&
    hand.deletion_receipt === null
  );
}

export async function reimportPlayerHand(
  credentials: PlayerCredentials,
  recordKey: string,
  file: File,
  requestId: string,
  expected: PlayerHandSummary,
): Promise<PlayerHandReimportOutcome> {
  if (
    expected.lifecycle_status !== "deleted" &&
    expected.lifecycle_status !== "deletion_pending"
  ) {
    throw new Error("Only a deleted hand incarnation can be reimported.");
  }
  const body = new FormData();
  body.set("request_id", requestId);
  body.set("expected_record_version", expected.record_version);
  body.set("expected_lifecycle_status", expected.lifecycle_status);
  body.set(
    "expected_deletion_generation",
    String(expected.deletion_generation),
  );
  body.set("expected_lifecycle_changed_at", expected.lifecycle_changed_at);
  body.set("file", file, file.name);
  let response: Response;
  try {
    response = await playerRequest(
      credentials,
      `/api/player/hands/${encodeURIComponent(recordKey)}/reimport`,
      { method: "POST", body },
    );
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerHandRecoveryRequiredError();
    }
    if (error instanceof PlayerApiError && error.status >= 500) {
      throw new PlayerHandReimportAmbiguousError();
    }
    if (error instanceof PlayerApiError) throw error;
    throw new PlayerHandReimportAmbiguousError();
  }
  try {
    const payload = (await response.json()) as unknown;
    if (
      !isPlayerHandReimportOutcome(
        payload,
        requestId,
        recordKey,
        expected.deletion_generation,
      )
    ) {
      throw new PlayerHandReimportAmbiguousError();
    }
    return payload;
  } catch (error) {
    if (error instanceof PlayerHandReimportAmbiguousError) throw error;
    throw new PlayerHandReimportAmbiguousError();
  }
}

function backupFilename(response: Response): string {
  const disposition = response.headers.get("content-disposition") ?? "";
  const match = /filename="([A-Za-z0-9._-]+)"/.exec(disposition);
  return match?.[1] ?? "poker-hero-player-backup.zip";
}

export async function exportPlayerBackup(
  credentials: PlayerCredentials,
): Promise<void> {
  const response = await playerRequest(
    credentials,
    "/api/player/backups/export",
  );
  const downloadUrl = URL.createObjectURL(await response.blob());
  try {
    const link = document.createElement("a");
    link.href = downloadUrl;
    link.download = backupFilename(response);
    link.click();
  } finally {
    URL.revokeObjectURL(downloadUrl);
  }
}

export async function restorePlayerBackup(
  credentials: PlayerCredentials,
  backup: File,
): Promise<PlayerBackupRestoreResult> {
  let response: Response;
  try {
    response = await playerRequest(credentials, "/api/player/backups/restore", {
      method: "POST",
      headers: { "Content-Type": "application/zip" },
      body: backup,
    });
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerRestoreRecoveryRequiredError();
    }
    if (error instanceof PlayerApiError) throw error;
    throw new PlayerRestoreAmbiguousError();
  }
  try {
    const payload = (await response.json()) as Record<string, unknown>;
    const integerFields = [
      "imported_records",
      "reused_records",
      "skipped_stale_records",
      "imported_decision_artifacts",
      "reused_decision_artifacts",
      "removed_decision_artifacts",
      "imported_grade_artifacts",
      "reused_grade_artifacts",
      "removed_grade_artifacts",
      "total_records",
    ] as const;
    if (
      !payload ||
      typeof payload !== "object" ||
      integerFields.some(
        (field) =>
          !Number.isInteger(payload[field]) || Number(payload[field]) < 0,
      )
    ) {
      throw new PlayerRestoreAmbiguousError();
    }
    return payload as unknown as PlayerBackupRestoreResult;
  } catch (error) {
    if (error instanceof PlayerRestoreAmbiguousError) throw error;
    throw new PlayerRestoreAmbiguousError();
  }
}

function isPlayerImportBatchOutcome(
  value: unknown,
  requestId: string,
  files: File[],
): value is PlayerImportBatchOutcome {
  if (!value || typeof value !== "object") return false;
  const payload = value as Record<string, unknown>;
  const summary = payload.summary as Record<string, unknown> | undefined;
  const isNullableString = (item: unknown) =>
    item === null || typeof item === "string";
  const isNullableInteger = (item: unknown) =>
    item === null || (Number.isInteger(item) && Number(item) >= 1);
  const isDiagnostic = (item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const diagnostic = item as Record<string, unknown>;
    return (
      typeof diagnostic.code === "string" &&
      typeof diagnostic.message === "string" &&
      isNullableInteger(diagnostic.hand_ordinal) &&
      isNullableString(diagnostic.source_hand_id) &&
      isNullableInteger(diagnostic.line_start) &&
      isNullableInteger(diagnostic.line_end)
    );
  };
  const dispositions = new Set<PlayerImportDisposition>([
    "created_pending_review",
    "recorded_exact_reimport",
    "recorded_identity_conflict",
    "duplicate_request",
  ]);
  const parserDispositions = new Set([
    "clean",
    "reconciliation_failed",
    "reconciliation_indeterminate",
  ]);
  const reconciliationStatuses = new Set(["pass", "fail", "indeterminate"]);
  const isHand = (item: unknown) => {
    if (!item || typeof item !== "object") return false;
    const hand = item as Record<string, unknown>;
    return (
      Number.isInteger(hand.hand_ordinal) &&
      Number(hand.hand_ordinal) >= 1 &&
      typeof hand.source_hand_id === "string" &&
      typeof hand.record_key === "string" &&
      /^[a-f0-9]{64}$/.test(hand.record_key) &&
      dispositions.has(hand.disposition as PlayerImportDisposition) &&
      parserDispositions.has(hand.parser_disposition as string) &&
      reconciliationStatuses.has(hand.reconciliation_status as string) &&
      typeof hand.lifecycle_status === "string" &&
      Number.isInteger(hand.warning_count) &&
      Number(hand.warning_count) >= 0
    );
  };
  const fileStatuses = new Set(["processed", "partial", "rejected"]);
  const isFile = (item: unknown, index: number) => {
    if (!item || typeof item !== "object") return false;
    const file = item as Record<string, unknown>;
    return (
      file.file_slot === index + 1 &&
      typeof file.filename === "string" &&
      fileStatuses.has(file.status as string) &&
      Array.isArray(file.hands) &&
      file.hands.every(isHand) &&
      Array.isArray(file.diagnostics) &&
      file.diagnostics.every(isDiagnostic)
    );
  };
  const integerFields = [
    "files_received",
    "files_processed",
    "hands_succeeded",
    "diagnostic_count",
    "duplicate_requests",
  ] as const;
  return (
    payload.request_id === requestId &&
    Array.isArray(payload.files) &&
    payload.files.length === files.length &&
    payload.files.every(isFile) &&
    !!summary &&
    typeof summary === "object" &&
    integerFields.every(
      (field) =>
        Number.isInteger(summary[field]) && Number(summary[field]) >= 0,
    ) &&
    typeof summary.retry_required === "boolean" &&
    summary.files_received === payload.files.length &&
    Number(summary.files_processed) <= payload.files.length &&
    Number(summary.hands_succeeded) ===
      payload.files.reduce(
        (count, file) =>
          count +
          (file as PlayerImportBatchOutcome["files"][number]).hands.length,
        0,
      ) &&
    Number(summary.diagnostic_count) ===
      payload.files.reduce(
        (count, file) =>
          count +
          (file as PlayerImportBatchOutcome["files"][number]).diagnostics
            .length,
        0,
      )
  );
}

export async function importPokerStarsFiles(
  credentials: PlayerCredentials,
  files: File[],
  requestId: string,
): Promise<PlayerImportBatchOutcome> {
  const body = new FormData();
  body.set("request_id", requestId);
  files.forEach((file) => body.append("files", file, file.name));
  let response: Response;
  try {
    response = await playerRequest(credentials, "/api/player/imports", {
      method: "POST",
      body,
    });
  } catch (error) {
    if (error instanceof PlayerApiError && error.status === 503) {
      throw new PlayerImportRecoveryRequiredError();
    }
    if (error instanceof PlayerApiError) throw error;
    throw new PlayerImportAmbiguousError();
  }
  try {
    const payload = (await response.json()) as unknown;
    if (!isPlayerImportBatchOutcome(payload, requestId, files)) {
      throw new PlayerImportAmbiguousError();
    }
    return payload;
  } catch (error) {
    if (error instanceof PlayerImportAmbiguousError) throw error;
    throw new PlayerImportAmbiguousError();
  }
}

export async function revokePlayerSession(
  credentials: PlayerCredentials,
): Promise<void> {
  try {
    await playerRequest(credentials, "/api/player/session", {
      method: "DELETE",
    });
  } finally {
    clearPlayerCredentials();
  }
}
