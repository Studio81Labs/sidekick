import type { PipelineCapabilities } from "../types/pipeline";
import type { SystemInfo } from "../types/system";
import { apiUrl, readJson } from "./core";

export { restoreApplicationBackup } from "../../domains/backups/api/backupsApi";

export function applicationBackupUrl(): string {
  return apiUrl("/api/backups/export");
}

export async function getSystemInfo(): Promise<SystemInfo> {
  const response = await fetch(apiUrl("/api/health"), {
    credentials: "include",
  });
  return readJson<SystemInfo>(response);
}

export async function getPipelineCapabilities(): Promise<PipelineCapabilities> {
  const response = await fetch(apiUrl("/api/pipeline"), {
    credentials: "include",
  });
  return readJson<PipelineCapabilities>(response);
}
