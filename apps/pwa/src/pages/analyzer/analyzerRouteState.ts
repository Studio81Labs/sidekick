export type AnalyzerSurface = "benchmarks" | "job" | "workspace";

export interface AnalyzerRouteState {
  jobId: string | null;
  surface: AnalyzerSurface;
}

export interface AnalyzerRouteNavigation {
  closeSurface: () => void;
  managed: boolean;
  openBenchmarks: () => void;
  openJob: (jobId: string, options?: AnalyzerRouteNavigationOptions) => void;
  openWorkspace: (options?: AnalyzerRouteNavigationOptions) => void;
}

export interface AnalyzerRouteNavigationOptions {
  replace?: boolean;
}

export const analyzerPaths = {
  analyzer: "/analyzer",
  analyzerBenchmarks: "/analyzer/benchmarks",
  analyzerJob: "/analyzer/jobs/:jobId",
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
