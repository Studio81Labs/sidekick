import type { components } from "@poker-hero/openapi-client";
import { apiUrl, readJson } from "../../../shared/api/core";
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
  administratorToken: string,
): Promise<ApplicationBackupRestoreResult> {
  const form = new FormData();
  form.append("file", file);
  const response = await requestJson<ApplicationBackupRestoreResponse>(
    "/api/admin/ocr/backups/restore",
    {
      method: "POST",
      headers: { Authorization: `Bearer ${administratorToken}` },
      body: form,
    },
  );
  return toApplicationBackupRestoreResult(response);
}

export async function downloadApplicationBackup(
  administratorToken: string,
): Promise<Blob> {
  const response = await fetch(apiUrl("/api/admin/ocr/backups/export"), {
    credentials: "include",
    headers: { Authorization: `Bearer ${administratorToken}` },
  });
  if (!response.ok) {
    await readJson<never>(response);
  }
  return response.blob();
}
