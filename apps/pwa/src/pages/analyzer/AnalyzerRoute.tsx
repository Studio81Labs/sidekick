import { useMemo } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

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

interface AnalyzerSurfaceLocationState {
  analyzerSurfaceOrigin?: boolean;
}

export default function AnalyzerRoute({ surface }: AnalyzerRouteProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const { jobId } = useParams<{ jobId: string }>();
  const route = useMemo(
    () => analyzerRouteState(surface, jobId),
    [jobId, surface],
  );
  const navigation = useMemo<AnalyzerRouteNavigation>(
    () => ({
      closeSurface: () => {
        const locationState =
          location.state as AnalyzerSurfaceLocationState | null;
        if (locationState?.analyzerSurfaceOrigin) {
          navigate(-1);
        } else if (location.pathname !== analyzerPaths.analyzer) {
          navigate(analyzerPaths.analyzer, { replace: true });
        }
      },
      managed: true,
      openBenchmarks: () => {
        if (location.pathname !== analyzerPaths.analyzerBenchmarks) {
          navigate(analyzerPaths.analyzerBenchmarks, {
            state: { analyzerSurfaceOrigin: true },
          });
        }
      },
      openJob: (nextJobId, options) => {
        const path = analyzerJobPath(nextJobId);
        if (location.pathname !== path) {
          navigate(path, { replace: options?.replace });
        }
      },
      openWorkspace: (options) => {
        if (location.pathname !== analyzerPaths.analyzer) {
          navigate(analyzerPaths.analyzer, { replace: options?.replace });
        }
      },
    }),
    [location.pathname, location.state, navigate],
  );

  return <AnalyzerPage navigation={navigation} route={route} />;
}
