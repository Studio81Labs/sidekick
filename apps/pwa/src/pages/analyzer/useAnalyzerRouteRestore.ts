import { useEffect, useRef } from "react";

import { PERSISTED_JOB_ID_PATTERN } from "../../shared/lib/jobIdentity";
import { isLocalUploadError } from "../../features/workspace/lib/reconciliation";
import type { JobRecord } from "../../shared/types/jobs";
import type { AnalyzerRouteState, AnalyzerSurface } from "./analyzerRouteState";

export interface AnalyzerRouteRestoreOptions {
  activateJob: (job: JobRecord) => void;
  activeJobId: string | null;
  benchmarksOpen: boolean;
  closeBenchmarks: () => void;
  jobs: readonly JobRecord[];
  loadJob: (jobId: string) => Promise<JobRecord>;
  onError: (error: unknown) => void;
  onJobLoading: (jobId: string) => void;
  onJobUnavailable: () => void;
  openBenchmarks: () => void;
  route: AnalyzerRouteState;
  restoreWorkspace: () => void;
}

export function useAnalyzerRouteRestore(
  options: AnalyzerRouteRestoreOptions,
): void {
  const jobLoadsRef = useRef(new Map<string, Promise<JobRecord>>());
  const optionsRef = useRef(options);
  const restoredSurfaceRef = useRef<AnalyzerSurface | null>(null);
  optionsRef.current = options;

  useEffect(() => {
    let active = true;
    const current = optionsRef.current;
    const surfaceChanged = restoredSurfaceRef.current !== current.route.surface;
    restoredSurfaceRef.current = current.route.surface;

    if (current.route.surface !== "benchmarks") {
      current.closeBenchmarks();
    }
    if (current.route.surface === "workspace") {
      current.restoreWorkspace();
    } else if (
      current.route.surface === "benchmarks" &&
      !current.benchmarksOpen &&
      surfaceChanged
    ) {
      current.openBenchmarks();
    } else if (current.route.surface === "job" && current.route.jobId) {
      const routeJobId = current.route.jobId;
      if (!PERSISTED_JOB_ID_PATTERN.test(routeJobId)) {
        current.onJobUnavailable();
      } else {
        const cachedJob = current.jobs.find((job) => job.id === routeJobId);
        if (cachedJob) {
          if (isLocalUploadError(cachedJob)) {
            current.onJobUnavailable();
          } else if (current.activeJobId !== routeJobId) {
            current.activateJob(cachedJob);
          }
        } else {
          current.onJobLoading(routeJobId);
          let jobLoad = jobLoadsRef.current.get(routeJobId);
          if (!jobLoad) {
            jobLoad = current.loadJob(routeJobId);
            jobLoadsRef.current.set(routeJobId, jobLoad);
          }
          const pendingJobLoad = jobLoad;
          void pendingJobLoad
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
            })
            .finally(() => {
              if (jobLoadsRef.current.get(routeJobId) === pendingJobLoad) {
                jobLoadsRef.current.delete(routeJobId);
              }
            });
        }
      }
    }

    return () => {
      active = false;
    };
  }, [options.route.jobId, options.route.surface]);
}
