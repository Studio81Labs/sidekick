import { Navigate, Route, Routes } from "react-router-dom";

import AnalyzerRoute from "../pages/analyzer/AnalyzerRoute";

export const appPaths = {
  analyzer: "/analyzer",
  analyzerBenchmarks: "/analyzer/benchmarks",
  analyzerJob: "/analyzer/jobs/:jobId",
  analyzerTraining: "/analyzer/training",
} as const;

export function analyzerJobPath(jobId: string): string {
  return `/analyzer/jobs/${encodeURIComponent(jobId)}`;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={appPaths.analyzer} replace />} />
      <Route
        path={appPaths.analyzer}
        element={<AnalyzerRoute surface="workspace" />}
      />
      <Route
        path={appPaths.analyzerJob}
        element={<AnalyzerRoute surface="job" />}
      />
      <Route
        path={appPaths.analyzerTraining}
        element={<AnalyzerRoute surface="training" />}
      />
      <Route
        path={appPaths.analyzerBenchmarks}
        element={<AnalyzerRoute surface="benchmarks" />}
      />
      <Route path="*" element={<Navigate to={appPaths.analyzer} replace />} />
    </Routes>
  );
}
