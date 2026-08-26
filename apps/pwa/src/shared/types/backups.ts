export interface ApplicationBackupRestoreResult {
  imported_jobs: number;
  reused_jobs: number;
  imported_benchmark_reports: number;
  reused_benchmark_reports: number;
  total_jobs: number;
  total_benchmark_reports: number;
}
