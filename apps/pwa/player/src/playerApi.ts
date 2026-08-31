export const PLAYER_SESSION_STORAGE_KEY = "poker-hero-player-session-v1";
export const PLAYER_CSRF_STORAGE_KEY = "poker-hero-player-csrf-v1";

export interface PlayerCredentials {
  sessionToken: string;
  csrfToken: string;
}

export interface PlayerStorageStatus {
  status: "ready" | "attention_required";
  storage: "player-local-file";
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
  total_records: number;
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
  identity: { site: string; source_hand_id: string } | null;
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
  next_cursor: string | null;
}

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
    chronology: { played_at: string | null };
    provenance: {
      imported_at: string;
      adapter_id: string;
      adapter_version: string;
      format_revision: string;
      source_filename: string | null;
    };
    content_sha256: string;
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
  const response = await playerRequest(
    credentials,
    `/api/player/hands/${encodeURIComponent(recordKey)}`,
  );
  return (await response.json()) as PlayerHandDetail;
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
