import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import AnalyzerPage from "./AnalyzerPage";

export type AnalyzerSurface = "benchmarks" | "job" | "training" | "workspace";

export interface AnalyzerRouteState {
  jobId: string | null;
  surface: AnalyzerSurface;
}

const AnalyzerRouteContext = createContext<AnalyzerRouteState | null>(null);

export function analyzerRouteState(
  surface: AnalyzerSurface,
  jobId?: string,
): AnalyzerRouteState {
  return {
    jobId: surface === "job" ? (jobId ?? null) : null,
    surface,
  };
}

export function useAnalyzerRoute(): AnalyzerRouteState {
  const route = useContext(AnalyzerRouteContext);
  if (!route) {
    throw new Error("useAnalyzerRoute must be used within AnalyzerRoute");
  }
  return route;
}

interface AnalyzerRouteProps {
  surface: AnalyzerSurface;
}

export default function AnalyzerRoute({ surface }: AnalyzerRouteProps) {
  const { jobId } = useParams<{ jobId: string }>();
  const route = useMemo(
    () => analyzerRouteState(surface, jobId),
    [jobId, surface],
  );

  return (
    <AnalyzerRouteContext.Provider value={route}>
      <AnalyzerPage />
    </AnalyzerRouteContext.Provider>
  );
}

export function AnalyzerRouteProvider({
  children,
  value,
}: {
  children: ReactNode;
  value: AnalyzerRouteState;
}) {
  return (
    <AnalyzerRouteContext.Provider value={value}>
      {children}
    </AnalyzerRouteContext.Provider>
  );
}
