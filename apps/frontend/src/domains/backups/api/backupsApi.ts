import type { components } from "../../../shared/api/generated/openapi";
import { apiUrl } from "../../../shared/api/core";
import { requestJson } from "../../../shared/api/transport";
import type { ApplicationBackupRestoreResult } from "../../../shared/types/backups";

type ApplicationBackupRestoreResponse =
  components["schemas"]["ApplicationBackupRestoreResult"];

export function applicationBackupUrl(): string {
  return apiUrl("/api/backups/export");
}

export function toApplicationBackupRestoreResult(
  response: ApplicationBackupRestoreResponse,
): ApplicationBackupRestoreResult {
  return response;
}

export async function restoreApplicationBackup(
  file: File,
): Promise<ApplicationBackupRestoreResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await requestJson<ApplicationBackupRestoreResponse>(
    "/api/backups/restore",
    { method: "POST", body: form },
  );
  return toApplicationBackupRestoreResult(response);
}
