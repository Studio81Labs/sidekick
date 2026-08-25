export type AnalyzerSurface = "benchmarks" | "job" | "training" | "workspace";

export interface AnalyzerRouteState {
  jobId: string | null;
  surface: AnalyzerSurface;
}

export interface AnalyzerRouteNavigation {
  openBenchmarks: () => void;
  openJob: (jobId: string) => void;
  openTraining: () => void;
  openWorkspace: () => void;
}

export const analyzerPaths = {
  analyzer: "/analyzer",
  analyzerBenchmarks: "/analyzer/benchmarks",
  analyzerJob: "/analyzer/jobs/:jobId",
  analyzerTraining: "/analyzer/training",
} as const;

export function analyzerJobPath(jobId: string): string {
  return `/analyzer/jobs/${encodeURIComponent(jobId)}`;
}

export function analyzerRouteState(
  surface: AnalyzerSurface,
  jobId?: string,
): AnalyzerRouteState {
  return {
    jobId: surface === "job" ? (jobId ?? null) : null,
    surface,
  };
}
