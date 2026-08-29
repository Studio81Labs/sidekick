import { Navigate, Route, Routes } from "react-router-dom";

import AnalyzerRoute from "../pages/analyzer/AnalyzerRoute";
import {
  analyzerJobPath,
  analyzerPaths,
} from "../pages/analyzer/analyzerRouteState";

export const appPaths = analyzerPaths;
export { analyzerJobPath };

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
        path={appPaths.analyzerBenchmarks}
        element={<AnalyzerRoute surface="benchmarks" />}
      />
      <Route path="*" element={<Navigate to={appPaths.analyzer} replace />} />
    </Routes>
  );
}
