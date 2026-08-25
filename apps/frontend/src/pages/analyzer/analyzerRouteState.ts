export type AnalyzerSurface = "benchmarks" | "job" | "training" | "workspace";

export interface AnalyzerRouteState {
  jobId: string | null;
  surface: AnalyzerSurface;
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
