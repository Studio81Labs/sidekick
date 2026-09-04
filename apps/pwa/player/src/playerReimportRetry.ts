import { fingerprintPlayerImportFile } from "./playerImportRetry";

export const PLAYER_REIMPORT_RETRY_STORAGE_KEY =
  "poker-hero-player-reimport-retry-v1";

interface StoredPlayerReimportRetry {
  schema_version: 1;
  record_key: string;
  request_id: string;
  file_fingerprint: string;
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const RECORD_KEY_PATTERN = /^[0-9a-f]{64}$/;
const FINGERPRINT_PATTERN = /^[0-9a-f]{64}:[0-9]+:[0-9a-f]{64}$/;
const MAX_REIMPORT_FILE_BYTES = 8 * 1024 * 1024;

function readStoredRetry(): StoredPlayerReimportRetry | null {
  const raw = window.localStorage.getItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY);
  if (raw === null) return null;
  try {
    const candidate = JSON.parse(raw) as Partial<StoredPlayerReimportRetry>;
    if (
      candidate.schema_version !== 1 ||
      typeof candidate.record_key !== "string" ||
      !RECORD_KEY_PATTERN.test(candidate.record_key) ||
      typeof candidate.request_id !== "string" ||
      !UUID_PATTERN.test(candidate.request_id) ||
      typeof candidate.file_fingerprint !== "string" ||
      !FINGERPRINT_PATTERN.test(candidate.file_fingerprint)
    ) {
      window.localStorage.removeItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY);
      return null;
    }
    return candidate as StoredPlayerReimportRetry;
  } catch {
    window.localStorage.removeItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY);
    return null;
  }
}

export async function preservePlayerHandReimportRetry(
  recordKey: string,
  file: File,
  proposedRequestId: string,
): Promise<string> {
  if (!RECORD_KEY_PATTERN.test(recordKey)) {
    throw new Error("The selected hand record key is invalid.");
  }
  if (file.size > MAX_REIMPORT_FILE_BYTES) {
    throw new Error("Select one PokerStars text file no larger than 8 MiB.");
  }
  const fileFingerprint = await fingerprintPlayerImportFile(file);
  const stored = readStoredRetry();
  const requestId =
    stored?.record_key === recordKey &&
    stored.file_fingerprint === fileFingerprint
      ? stored.request_id
      : proposedRequestId;
  window.localStorage.setItem(
    PLAYER_REIMPORT_RETRY_STORAGE_KEY,
    JSON.stringify({
      schema_version: 1,
      record_key: recordKey,
      request_id: requestId,
      file_fingerprint: fileFingerprint,
    } satisfies StoredPlayerReimportRetry),
  );
  return requestId;
}

export function clearPlayerHandReimportRetry(): void {
  window.localStorage.removeItem(PLAYER_REIMPORT_RETRY_STORAGE_KEY);
}
