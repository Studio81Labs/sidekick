import { useEffect, useRef } from "react";

import { isLocalUploadError } from "../../features/workspace/lib/reconciliation";
import type { JobRecord } from "../../shared/types";
import type { AnalyzerRouteState, AnalyzerSurface } from "./analyzerRouteState";

export interface AnalyzerRouteRestoreOptions {
  activateJob: (job: JobRecord) => void;
  activeJobId: string | null;
  benchmarksOpen: boolean;
  closeBenchmarks: () => void;
  closeTraining: () => void;
  jobs: readonly JobRecord[];
  loadJob: (jobId: string) => Promise<JobRecord>;
  onError: (error: unknown) => void;
  onJobLoading: (jobId: string) => void;
  onJobUnavailable: () => void;
  openBenchmarks: () => void;
  openTraining: () => void;
  route: AnalyzerRouteState;
  restoreWorkspace: () => void;
  trainingOpen: boolean;
}

export function useAnalyzerRouteRestore(
  options: AnalyzerRouteRestoreOptions,
): void {
  const optionsRef = useRef(options);
  const restoredSurfaceRef = useRef<AnalyzerSurface | null>(null);
  optionsRef.current = options;

  useEffect(() => {
    let active = true;
    const current = optionsRef.current;
    const surfaceChanged = restoredSurfaceRef.current !== current.route.surface;
    restoredSurfaceRef.current = current.route.surface;

    if (current.route.surface !== "training") {
      current.closeTraining();
    }
    if (current.route.surface !== "benchmarks") {
      current.closeBenchmarks();
    }
    if (current.route.surface === "workspace") {
      current.restoreWorkspace();
    } else if (
      current.route.surface === "training" &&
      !current.trainingOpen &&
      surfaceChanged
    ) {
      current.openTraining();
    } else if (
      current.route.surface === "benchmarks" &&
      !current.benchmarksOpen &&
      surfaceChanged
    ) {
      current.openBenchmarks();
    } else if (current.route.surface === "job" && current.route.jobId) {
      const cachedJob = current.jobs.find(
        (job) => job.id === current.route.jobId,
      );
      if (cachedJob) {
        if (isLocalUploadError(cachedJob)) {
          current.onJobUnavailable();
        } else if (current.activeJobId !== current.route.jobId) {
          current.activateJob(cachedJob);
        }
      } else {
        current.onJobLoading(current.route.jobId);
        void current
          .loadJob(current.route.jobId)
          .then((job) => {
            if (active) {
              current.activateJob(job);
            }
          })
          .catch((error: unknown) => {
            if (active) {
              current.onJobUnavailable();
              current.onError(error);
            }
          });
      }
    }

    return () => {
      active = false;
    };
  }, [options.route.jobId, options.route.surface]);
}
