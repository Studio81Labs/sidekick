import { useMemo } from "react";
import { useParams } from "react-router-dom";

import AnalyzerPage from "./AnalyzerPage";
import { analyzerRouteState, type AnalyzerSurface } from "./analyzerRouteState";

interface AnalyzerRouteProps {
  surface: AnalyzerSurface;
}

export default function AnalyzerRoute({ surface }: AnalyzerRouteProps) {
  const { jobId } = useParams<{ jobId: string }>();
  const route = useMemo(
    () => analyzerRouteState(surface, jobId),
    [jobId, surface],
  );

  return <AnalyzerPage route={route} />;
}
