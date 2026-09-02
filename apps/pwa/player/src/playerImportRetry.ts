export const PLAYER_IMPORT_RETRY_STORAGE_KEY =
  "poker-hero-player-import-retry-v1";

interface StoredPlayerImportRetry {
  schema_version: 1;
  request_id: string;
  file_fingerprints: string[];
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const FINGERPRINT_PATTERN = /^[0-9a-f]{64}:[0-9]+:[0-9a-f]{64}$/;
const MAX_IMPORT_FILES = 20;
const MAX_IMPORT_BATCH_BYTES = 32 * 1024 * 1024;

function bytesToHex(bytes: ArrayBuffer): string {
  return Array.from(new Uint8Array(bytes), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function sha256(value: BufferSource): Promise<string> {
  return bytesToHex(await window.crypto.subtle.digest("SHA-256", value));
}

async function fingerprintFile(file: File): Promise<string> {
  const filenameHash = await sha256(new TextEncoder().encode(file.name));
  const contentHash = await sha256(await file.arrayBuffer());
  return `${filenameHash}:${file.size}:${contentHash}`;
}

async function fingerprintFiles(files: File[]): Promise<string[]> {
  const fingerprints: string[] = [];
  for (const file of files) {
    fingerprints.push(await fingerprintFile(file));
  }
  return fingerprints;
}

function readStoredRetry(): StoredPlayerImportRetry | null {
  const raw = window.localStorage.getItem(PLAYER_IMPORT_RETRY_STORAGE_KEY);
  if (raw === null) return null;
  try {
    const candidate = JSON.parse(raw) as Partial<StoredPlayerImportRetry>;
    if (
      candidate.schema_version !== 1 ||
      typeof candidate.request_id !== "string" ||
      !UUID_PATTERN.test(candidate.request_id) ||
      !Array.isArray(candidate.file_fingerprints) ||
      candidate.file_fingerprints.length === 0 ||
      candidate.file_fingerprints.length > 20 ||
      !candidate.file_fingerprints.every(
        (fingerprint) =>
          typeof fingerprint === "string" &&
          FINGERPRINT_PATTERN.test(fingerprint),
      )
    ) {
      window.localStorage.removeItem(PLAYER_IMPORT_RETRY_STORAGE_KEY);
      return null;
    }
    return candidate as StoredPlayerImportRetry;
  } catch {
    window.localStorage.removeItem(PLAYER_IMPORT_RETRY_STORAGE_KEY);
    return null;
  }
}

function fingerprintsMatch(left: string[], right: string[]): boolean {
  return (
    left.length === right.length &&
    left.every((fingerprint, index) => fingerprint === right[index])
  );
}

export async function preservePlayerImportRetry(
  files: File[],
  proposedRequestId: string,
): Promise<string> {
  const totalBytes = files.reduce((total, file) => total + file.size, 0);
  if (
    files.length === 0 ||
    files.length > MAX_IMPORT_FILES ||
    totalBytes > MAX_IMPORT_BATCH_BYTES
  ) {
    throw new Error(
      "Select at most 20 files totaling no more than 32 MiB before importing.",
    );
  }
  const fileFingerprints = await fingerprintFiles(files);
  const stored = readStoredRetry();
  const requestId =
    stored && fingerprintsMatch(stored.file_fingerprints, fileFingerprints)
      ? stored.request_id
      : proposedRequestId;
  const retry: StoredPlayerImportRetry = {
    schema_version: 1,
    request_id: requestId,
    file_fingerprints: fileFingerprints,
  };
  window.localStorage.setItem(
    PLAYER_IMPORT_RETRY_STORAGE_KEY,
    JSON.stringify(retry),
  );
  return requestId;
}

export function clearPlayerImportRetry(): void {
  window.localStorage.removeItem(PLAYER_IMPORT_RETRY_STORAGE_KEY);
}
