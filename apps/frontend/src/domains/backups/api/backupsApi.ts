import type { components } from "../../../shared/api/generated/openapi";
import { requestJson } from "../../../shared/api/transport";
import type { ApplicationBackupRestoreResult } from "../../../shared/types/backups";

type ApplicationBackupRestoreResponse =
  components["schemas"]["ApplicationBackupRestoreResult"];

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
