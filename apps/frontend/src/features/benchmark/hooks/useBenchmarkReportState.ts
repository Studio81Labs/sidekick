import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { getBenchmarkOverview } from "../../../domains/benchmarks/api/benchmarksApi";
import type {
  BenchmarkOverview,
  BenchmarkReport,
  PipelineSelection,
} from "../../../shared/types";
import { messageFromError } from "../../workspace/lib/workflow";
import {
  benchmarkReportSummary,
  benchmarkReportsAreComparable,
  cacheBenchmarkReport,
  loadCachedBenchmarkReport,
  previousComparableBenchmarkReport,
} from "../lib/benchmarkPresentation";

interface UseBenchmarkReportStateOptions {
  dialogOpen: boolean;
  onError: (message: string | null) => void;
}

interface RefreshBenchmarkOptions {
  failureMessage: string;
  selection: PipelineSelection | null;
}

export function useBenchmarkReportState({
  dialogOpen,
  onError,
}: UseBenchmarkReportStateOptions) {
  const [overview, setOverview] = useState<BenchmarkOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [reportLoading, setReportLoading] = useState(false);
  const [selectedReport, setSelectedReport] = useState<BenchmarkReport | null>(
    null,
  );
  const [comparisonReport, setComparisonReport] =
    useState<BenchmarkReport | null>(null);
  const [comparisonReportLoading, setComparisonReportLoading] = useState(false);
  const mountedRef = useRef(true);
  const overviewRequestRef = useRef(0);
  const comparisonReportRequestRef = useRef(0);
  const reportCacheRef = useRef(new Map<string, BenchmarkReport>());
  const reportRequestsRef = useRef(new Map<string, Promise<BenchmarkReport>>());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const recentReports = useMemo(() => {
    if (overview?.recent_reports?.length) {
      return overview.recent_reports;
    }
    return overview?.latest_report
      ? [benchmarkReportSummary(overview.latest_report)]
      : [];
  }, [overview]);
  const report = selectedReport ?? overview?.latest_report ?? null;
  const previousReport = useMemo(
    () =>
      previousComparableBenchmarkReport(
        report,
        recentReports,
        overview?.parser_pipelines,
      ),
    [overview?.parser_pipelines, recentReports, report],
  );

  useEffect(() => {
    const requestId = ++comparisonReportRequestRef.current;
    setComparisonReport(null);
    if (!dialogOpen || !report || !previousReport) {
      setComparisonReportLoading(false);
      return;
    }
    cacheBenchmarkReport(reportCacheRef.current, report);
    setComparisonReportLoading(true);
    void loadCachedBenchmarkReport(
      previousReport.id,
      reportCacheRef.current,
      reportRequestsRef.current,
    )
      .then((loadedReport) => {
        if (
          requestId !== comparisonReportRequestRef.current ||
          loadedReport.id !== previousReport.id
        ) {
          return;
        }
        if (!benchmarkReportsAreComparable(report, loadedReport)) {
          throw new Error(
            "The previous benchmark report no longer matches this run",
          );
        }
        setComparisonReport(loadedReport);
      })
      .catch((error) => {
        if (requestId === comparisonReportRequestRef.current) {
          toast.warning(
            messageFromError(error, "Could not compare benchmark cases"),
          );
        }
      })
      .finally(() => {
        if (requestId === comparisonReportRequestRef.current) {
          setComparisonReportLoading(false);
        }
      });
  }, [dialogOpen, previousReport, report]);

  function cacheOverviewReport(nextOverview: BenchmarkOverview) {
    if (nextOverview.latest_report) {
      cacheBenchmarkReport(reportCacheRef.current, nextOverview.latest_report);
    }
  }

  function loadOverview(
    selection: PipelineSelection | null,
    preservePipelineComparison = false,
  ) {
    const requestId = ++overviewRequestRef.current;
    comparisonReportRequestRef.current += 1;
    setComparisonReport(null);
    setComparisonReportLoading(false);
    setSelectedReport(null);
    setOverview((current) =>
      current
        ? {
            ...current,
            latest_report: null,
            recent_reports: [],
            parser_pipelines: preservePipelineComparison
              ? current.parser_pipelines
              : [],
          }
        : null,
    );
    setLoading(true);
    void getBenchmarkOverview(selection ?? undefined)
      .then((nextOverview) => {
        if (requestId !== overviewRequestRef.current) {
          return;
        }
        cacheOverviewReport(nextOverview);
        setOverview(nextOverview);
        setSelectedReport(nextOverview.latest_report);
      })
      .catch((error) => {
        if (requestId === overviewRequestRef.current) {
          onError(messageFromError(error, "Could not load parser benchmark"));
        }
      })
      .finally(() => {
        if (requestId === overviewRequestRef.current) {
          setLoading(false);
        }
      });
  }

  async function refreshOverview({
    failureMessage,
    selection,
  }: RefreshBenchmarkOptions): Promise<BenchmarkOverview | null> {
    const requestId = ++overviewRequestRef.current;
    try {
      const nextOverview = await getBenchmarkOverview(selection ?? undefined);
      if (!mountedRef.current || requestId !== overviewRequestRef.current) {
        return null;
      }
      cacheOverviewReport(nextOverview);
      setOverview(nextOverview);
      return nextOverview;
    } catch (error) {
      if (mountedRef.current && requestId === overviewRequestRef.current) {
        onError(messageFromError(error, failureMessage));
      }
      return null;
    }
  }

  function cancelLoads() {
    overviewRequestRef.current += 1;
    comparisonReportRequestRef.current += 1;
    setLoading(false);
    setComparisonReportLoading(false);
  }

  function reset() {
    cancelLoads();
    setOverview(null);
    setSelectedReport(null);
    setComparisonReport(null);
    setReportLoading(false);
  }

  function applyReport(latestReport: BenchmarkReport, selectReport: boolean) {
    const latestSummary = benchmarkReportSummary(latestReport);
    cacheBenchmarkReport(reportCacheRef.current, latestReport);
    if (selectReport) {
      setSelectedReport(latestReport);
    }
    setOverview((current) => ({
      included_cases: current?.included_cases ?? latestReport.total_cases,
      included_cases_by_layout: current?.included_cases_by_layout,
      corpus_fingerprint: undefined,
      default_layout_profile:
        current?.default_layout_profile ?? latestReport.layout_profile,
      latest_report: selectReport
        ? latestReport
        : (current?.latest_report ?? null),
      recent_reports: selectReport
        ? [
            latestSummary,
            ...(current?.recent_reports ?? []).filter(
              (summary) => summary.id !== latestReport.id,
            ),
          ].slice(0, 10)
        : (current?.recent_reports ?? []),
      parser_pipelines: current?.parser_pipelines?.map((pipeline) =>
        pipeline.parser.id === latestReport.parser_provider &&
        pipeline.layout_profile === latestReport.layout_profile
          ? { ...pipeline, latest_report: latestSummary }
          : pipeline,
      ),
    }));
  }

  async function selectReport(reportId: string) {
    if (reportId === report?.id) {
      return;
    }
    setReportLoading(true);
    onError(null);
    try {
      setSelectedReport(
        await loadCachedBenchmarkReport(
          reportId,
          reportCacheRef.current,
          reportRequestsRef.current,
        ),
      );
    } catch (error) {
      onError(messageFromError(error, "Could not load benchmark report"));
    } finally {
      setReportLoading(false);
    }
  }

  return {
    applyReport,
    cancelLoads,
    comparisonReport,
    comparisonReportLoading,
    loadOverview,
    loading,
    overview,
    previousReport,
    recentReports,
    refreshOverview,
    report,
    reportLoading,
    reset,
    selectReport,
    setOverview,
  };
}
