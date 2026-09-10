import { downloadApplicationBackup } from "../../../domains/backups/api/backupsApi";

/** Fetch the protected archive before handing it to the browser download API. */
export function downloadApplicationBackupCommand(
  administratorToken: string,
): Promise<Blob> {
  return downloadApplicationBackup(administratorToken);
}
