import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import AnalyzerPage from "./AnalyzerPage";
import {
  analyzerJobPath,
  analyzerPaths,
  analyzerRouteState,
  type AnalyzerRouteNavigation,
  type AnalyzerSurface,
} from "./analyzerRouteState";

interface AnalyzerRouteProps {
  surface: AnalyzerSurface;
}

export default function AnalyzerRoute({ surface }: AnalyzerRouteProps) {
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const route = useMemo(
    () => analyzerRouteState(surface, jobId),
    [jobId, surface],
  );
  const navigation = useMemo<AnalyzerRouteNavigation>(
    () => ({
      managed: true,
      openBenchmarks: () => navigate(analyzerPaths.analyzerBenchmarks),
      openJob: (nextJobId, options) =>
        navigate(analyzerJobPath(nextJobId), { replace: options?.replace }),
      openTraining: () => navigate(analyzerPaths.analyzerTraining),
      openWorkspace: (options) =>
        navigate(analyzerPaths.analyzer, { replace: options?.replace }),
    }),
    [navigate],
  );

  return <AnalyzerPage navigation={navigation} route={route} />;
}
