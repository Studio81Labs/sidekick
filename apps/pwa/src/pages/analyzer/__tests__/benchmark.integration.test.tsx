import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  BenchmarkCaseResult,
  BenchmarkReport,
} from "../../../shared/types/benchmarks";
import type { DetectedState } from "../../../shared/types/poker";
import type { JobRecord } from "../../../shared/types/jobs";
import {
  AnalyzerTestApp as App,
  approvedJob,
  benchmarkOverviewForJob,
  canonicalState,
  deferredResponse,
  detectedState,
  disableAutomation,
  fetchMock,
  jobRecord,
  jsonResponse,
  processingQueueResponse,
  recommendation,
  recommendedJob,
  uploadScreenshot,
} from "../../../test/analyzerHarness";

describe("Analyzer benchmarks", () => {
  it("adds an approved hand to ground truth and runs the parser benchmark", async () => {
    const pendingOverview = deferredResponse();
    const pendingInclusion = deferredResponse();
    const pendingBenchmark = deferredResponse();
    const benchmarkJob = {
      ...approvedJob(),
      parser_layout_profile: "fortuna",
      benchmark_included: true,
    };
    const benchmarkReport = {
      id: "benchmark-1",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      created_at: "2026-07-20T12:00:00Z",
      total_cases: 1,
      successful_cases: 1,
      failed_cases: 0,
      correct_fields: 9,
      evaluated_fields: 10,
      accuracy: 0.9,
      field_metrics: [
        { field: "hero_cards", correct: 1, total: 1, accuracy: 1 },
      ],
      cases: [
        {
          job_id: "job-123",
          original_filename: "table.png",
          status: "completed",
          correct_fields: 9,
          evaluated_fields: 10,
          accuracy: 0.9,
          warnings: [],
          error: null,
          comparisons: [
            {
              field: "pot_size",
              expected: 12.5,
              detected: 10,
              matched: false,
              confidence: 0.73,
            },
          ],
        },
      ],
    };
    const rerunReport = {
      ...benchmarkReport,
      id: "benchmark-2",
      created_at: "2026-07-20T12:05:00Z",
    };
    const created = jobRecord({ parser_layout_profile: "fortuna" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(created, 201))
      .mockResolvedValueOnce(processingQueueResponse([created]))
      .mockResolvedValueOnce(jsonResponse(approvedJob()))
      .mockResolvedValueOnce(
        jsonResponse({
          defaults: {
            parser_provider: "ocr_cv",
            parser_layout_profile: "fortuna",
            recommendation_provider: "mock",
            recommendation_engine: null,
          },
          parser_providers: [
            {
              id: "mock",
              label: "Mock parser",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "ocr_cv",
              label: "Template OCR",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_profiles: [
            {
              id: "generic",
              label: "Generic",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "fortuna",
              label: "Fortuna",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_compatibility: {
            mock: ["generic", "fortuna"],
            ocr_cv: ["generic", "fortuna"],
          },
          recommendation_providers: [
            {
              id: "mock",
              label: "Mock recommendation",
              available: true,
              unavailable_reason: null,
            },
          ],
          recommendation_engines: [],
        }),
      )
      .mockReturnValueOnce(pendingOverview.promise)
      .mockReturnValueOnce(pendingInclusion.promise)
      .mockReturnValueOnce(pendingBenchmark.promise)
      .mockResolvedValueOnce(
        jsonResponse({ included_cases: 2, latest_report: benchmarkReport }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ ...approvedJob(), benchmark_included: false }),
      )
      .mockResolvedValueOnce(jsonResponse(rerunReport))
      .mockRejectedValueOnce(
        new TypeError("Legacy overview refresh unavailable"),
      );
    render(<App />);

    const user = await uploadScreenshot();
    await user.click(screen.getByRole("button", { name: "Approve state" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Request recommendation" }),
      ).toBeEnabled(),
    );

    await user.click(
      screen.getByRole("button", {
        name: "Configure analysis plugins",
      }),
    );
    const pipelineDialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Recognition"),
      "ocr_cv",
    );
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Table layout"),
      "fortuna",
    );
    await user.click(
      within(pipelineDialog).getByRole("button", { name: "Done" }),
    );

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(dialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    const exportDataset = within(dialog).getByRole("link", {
      name: "Export dataset",
    });
    const datasetInput = within(dialog).getByLabelText("Parser dataset ZIP");
    expect(groundTruthSwitch).toHaveAttribute("aria-checked", "false");
    expect(groundTruthSwitch).toBeDisabled();
    expect(datasetInput).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Run benchmark" }),
    ).toBeDisabled();
    expect(exportDataset).toHaveAttribute("aria-disabled", "true");
    expect(exportDataset).toHaveAttribute(
      "href",
      "http://localhost:8000/api/benchmarks/export?parser_provider=ocr_cv&parser_layout_profile=fortuna",
    );

    pendingOverview.resolve(
      jsonResponse({
        included_cases: 2,
        included_cases_by_layout: { pokerstars: 2 },
        default_layout_profile: "fortuna",
        latest_report: null,
      }),
    );
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    expect(datasetInput).toBeEnabled();
    expect(exportDataset).toHaveAttribute("aria-disabled", "true");
    expect(
      within(dialog).getByRole("button", { name: "Run benchmark" }),
    ).toBeDisabled();
    await user.click(groundTruthSwitch);
    expect(datasetInput).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Run benchmark" }),
    ).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Close parser benchmark" }),
    ).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDisabled();
    pendingInclusion.resolve(jsonResponse(benchmarkJob));
    await waitFor(() =>
      expect(groundTruthSwitch).toHaveAttribute("aria-checked", "true"),
    );
    expect(datasetInput).toBeEnabled();
    expect(exportDataset).toHaveAttribute("aria-disabled", "false");
    expect(
      within(dialog).getByRole("button", { name: "Close parser benchmark" }),
    ).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeEnabled();
    const runBenchmark = within(dialog).getByRole("button", {
      name: "Run benchmark",
    });
    await waitFor(() => expect(runBenchmark).toBeEnabled());
    await user.click(runBenchmark);
    expect(groundTruthSwitch).toBeDisabled();
    expect(datasetInput).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Close parser benchmark" }),
    ).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDisabled();
    pendingBenchmark.resolve(jsonResponse(benchmarkReport));

    expect(
      await within(dialog).findByLabelText("Benchmark summary"),
    ).toHaveTextContent("90%");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Done" }),
      ).toBeEnabled(),
    );
    expect(within(dialog).getByText("hero cards")).toBeInTheDocument();
    expect(within(dialog).getByText("1 mismatch")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await user.click(screen.getByRole("button", { name: "Reset to parser" }));
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const reopenedDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const retainedGroundTruth = within(reopenedDialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    expect(retainedGroundTruth).toHaveAttribute("aria-checked", "true");
    expect(retainedGroundTruth).toBeEnabled();
    await user.click(retainedGroundTruth);
    await waitFor(() =>
      expect(retainedGroundTruth).toHaveAttribute("aria-checked", "false"),
    );
    expect(
      within(reopenedDialog).getByRole("button", {
        name: "Run benchmark",
      }),
    ).toBeEnabled();
    await user.click(
      within(reopenedDialog).getByRole("button", {
        name: "Run benchmark",
      }),
    );
    await waitFor(() =>
      expect(
        within(reopenedDialog).getByRole("button", {
          name: "Done",
        }),
      ).toBeEnabled(),
    );
    await user.click(
      within(reopenedDialog).getByRole("button", {
        name: "Done",
      }),
    );

    await user.click(
      screen.getByRole("button", {
        name: "Configure analysis plugins",
      }),
    );
    const reopenedPipelineDialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    await user.selectOptions(
      within(reopenedPipelineDialog).getByLabelText("Table layout"),
      "generic",
    );
    await user.click(
      within(reopenedPipelineDialog).getByRole("button", {
        name: "Done",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const fallbackDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    expect(
      await screen.findByText("Legacy overview refresh unavailable"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(fallbackDialog).getByRole("button", {
          name: "Run benchmark",
        }),
      ).toBeEnabled(),
    );

    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs",
      "http://localhost:8000/api/jobs/job-123/approve",
      "http://localhost:8000/api/pipeline",
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna",
      "http://localhost:8000/api/jobs/job-123/benchmark",
      "http://localhost:8000/api/benchmarks/run",
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna",
      "http://localhost:8000/api/jobs/job-123/benchmark",
      "http://localhost:8000/api/benchmarks/run",
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=generic",
    ]);
    const benchmarkRequest = fetchMock().mock.calls.find(
      ([url]) => url === "http://localhost:8000/api/benchmarks/run",
    )?.[1];
    expect(benchmarkRequest).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parser_provider: "ocr_cv",
        parser_layout_profile: "fortuna",
      }),
      credentials: "include",
    });
  });

  it("preserves the selected corpus fingerprint when another layout changes", async () => {
    const corpusFingerprint = "a".repeat(64);
    const activeJob = {
      ...approvedJob(),
      id: "9".repeat(32),
      original_filename: "pokerstars-ground-truth.png",
      parser_layout_profile: "pokerstars",
      benchmark_included: false,
    };
    const includedJob = {
      ...activeJob,
      benchmark_included: true,
    };
    const overview = benchmarkOverviewForJob(
      "8".repeat(32),
      "fortuna-benchmark.png",
    );
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([activeJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          ...overview,
          included_cases: 3,
          included_cases_by_layout: { fortuna: 2, pokerstars: 1 },
          corpus_fingerprint: corpusFingerprint,
          default_layout_profile: "fortuna",
          latest_report: {
            ...overview.latest_report,
            corpus_fingerprint: corpusFingerprint,
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(includedJob));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(dialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    expect(
      within(dialog).queryByText(
        "This run is not verified against the current ground truth.",
      ),
    ).not.toBeInTheDocument();

    await user.click(groundTruthSwitch);

    await waitFor(() =>
      expect(groundTruthSwitch).toHaveAttribute("aria-checked", "true"),
    );
    expect(
      within(dialog).queryByText(
        "This run is not verified against the current ground truth.",
      ),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 100%",
      }),
    ).toBeInTheDocument();
  });

  it("preserves the selected corpus fingerprint when another layout is re-approved", async () => {
    const corpusFingerprint = "b".repeat(64);
    const activeJob = {
      ...approvedJob(),
      id: "6".repeat(32),
      original_filename: "pokerstars-correction.png",
      parser_layout_profile: "pokerstars",
      benchmark_included: true,
    };
    const correctedJob = {
      ...activeJob,
      approved_state: canonicalState({ pot_size: 20 }),
    };
    const baseOverview = benchmarkOverviewForJob(
      "5".repeat(32),
      "fortuna-benchmark.png",
    );
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([activeJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          ...baseOverview,
          included_cases: 2,
          included_cases_by_layout: { fortuna: 1, pokerstars: 1 },
          corpus_fingerprint: corpusFingerprint,
          default_layout_profile: "fortuna",
          latest_report: {
            ...baseOverview.latest_report,
            corpus_fingerprint: corpusFingerprint,
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(correctedJob));
    render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("option", {
          name: "Latest · OCR + computer vision · Fortuna · 100%",
        }),
      ).toBeInTheDocument(),
    );

    const approveState = screen.getByRole("button", { name: "Approve state" });
    await user.click(approveState);

    await waitFor(() => expect(approveState).toBeDisabled());
    expect(
      within(dialog).queryByText(
        "This run is not verified against the current ground truth.",
      ),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 100%",
      }),
    ).toBeInTheDocument();
  });

  it("preserves the corpus fingerprint when only solver inputs are re-approved", async () => {
    const corpusFingerprint = "f".repeat(64);
    const initialState = canonicalState({
      opponents_at_current_bet: 1,
      opponent_wager: 2.5,
    });
    const activeJob = {
      ...approvedJob(initialState),
      id: "3".repeat(32),
      original_filename: "solver-input-correction.png",
      parser_layout_profile: "fortuna",
      benchmark_included: true,
    };
    const correctedJob = {
      ...activeJob,
      approved_state: canonicalState({
        opponents_at_current_bet: 2,
        opponent_wager: 2.5,
      }),
    };
    const baseOverview = benchmarkOverviewForJob(
      activeJob.id,
      activeJob.original_filename,
    );
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([activeJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          ...baseOverview,
          included_cases_by_layout: { fortuna: 1 },
          corpus_fingerprint: corpusFingerprint,
          default_layout_profile: "fortuna",
          latest_report: {
            ...baseOverview.latest_report,
            corpus_fingerprint: corpusFingerprint,
          },
        }),
      )
      .mockResolvedValueOnce(jsonResponse(correctedJob));
    render(<App />);
    const user = userEvent.setup();

    const committedOpponents =
      await screen.findByLabelText(/Opponents at wager/);
    await user.clear(committedOpponents);
    await user.type(committedOpponents, "2");
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("option", {
          name: "Latest · OCR + computer vision · Fortuna · 100%",
        }),
      ).toBeInTheDocument(),
    );

    const approveState = screen.getByRole("button", { name: "Approve state" });
    await user.click(approveState);

    await waitFor(() => expect(approveState).toBeDisabled());
    expect(
      within(dialog).queryByText(
        "This run is not verified against the current ground truth.",
      ),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 100%",
      }),
    ).toBeInTheDocument();
  });

  it("revalidates the corpus after a benchmark run", async () => {
    const runFingerprint = "d".repeat(64);
    const currentFingerprint = "e".repeat(64);
    const baseOverview = benchmarkOverviewForJob(
      "4".repeat(32),
      "benchmark-run.png",
    );
    const previousReport = {
      ...baseOverview.latest_report,
      corpus_fingerprint: runFingerprint,
    };
    const latestReport = {
      ...previousReport,
      id: "benchmark-after-concurrent-correction",
      created_at: "2026-08-11T10:00:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          ...baseOverview,
          included_cases_by_layout: { fortuna: 1 },
          corpus_fingerprint: runFingerprint,
          default_layout_profile: "fortuna",
          latest_report: previousReport,
          recent_reports: [previousReport],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(latestReport))
      .mockResolvedValueOnce(
        jsonResponse({
          ...baseOverview,
          included_cases_by_layout: { fortuna: 1 },
          corpus_fingerprint: currentFingerprint,
          default_layout_profile: "fortuna",
          latest_report: latestReport,
          recent_reports: [latestReport, previousReport],
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const runBenchmark = await within(dialog).findByRole("button", {
      name: "Run benchmark",
    });
    await user.click(runBenchmark);

    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "This run is not verified against the current ground truth",
    );
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 100% · rerun needed",
      }),
    ).toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/benchmarks/run",
      "http://localhost:8000/api/benchmarks",
    ]);
  });

  it("compares compatible parsers and switches benchmark history in place", async () => {
    const mockReport = {
      id: "benchmark-mock",
      parser_provider: "mock",
      layout_profile: "generic",
      created_at: "2026-08-11T08:00:00Z",
      total_cases: 2,
      successful_cases: 2,
      failed_cases: 0,
      correct_fields: 16,
      evaluated_fields: 20,
      accuracy: 0.8,
      field_metrics: [
        { field: "hero_cards", correct: 2, total: 2, accuracy: 1 },
      ],
      cases: [],
    };
    const visionReport = {
      ...mockReport,
      id: "benchmark-vision",
      parser_provider: "llm_vision",
      created_at: "2026-08-11T08:05:00Z",
      correct_fields: 18,
      accuracy: 0.9,
    };
    const mockSummary = {
      id: mockReport.id,
      parser_provider: mockReport.parser_provider,
      layout_profile: mockReport.layout_profile,
      created_at: mockReport.created_at,
      total_cases: mockReport.total_cases,
      failed_cases: mockReport.failed_cases,
      accuracy: mockReport.accuracy,
      field_metrics: mockReport.field_metrics,
    };
    const visionSummary = {
      ...mockSummary,
      id: visionReport.id,
      parser_provider: visionReport.parser_provider,
      created_at: visionReport.created_at,
      accuracy: visionReport.accuracy,
    };
    const parserPipelines = [
      {
        parser: {
          id: "mock",
          label: "Mock parser",
          available: true,
          unavailable_reason: null,
        },
        layout_profile: "generic",
        latest_report: mockSummary,
      },
      {
        parser: {
          id: "llm_vision",
          label: "External vision",
          available: true,
          unavailable_reason: null,
        },
        layout_profile: "generic",
        latest_report: visionSummary,
      },
    ];
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 2,
          included_cases_by_layout: { generic: 2 },
          default_layout_profile: "generic",
          latest_report: mockReport,
          recent_reports: [mockSummary],
          parser_pipelines: parserPipelines,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          defaults: {
            parser_provider: "mock",
            parser_layout_profile: "generic",
            recommendation_provider: "mock",
            recommendation_engine: null,
          },
          parser_providers: parserPipelines.map(({ parser }) => parser),
          parser_layout_profiles: [
            {
              id: "generic",
              label: "Generic",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_compatibility: {
            mock: ["generic"],
            llm_vision: ["generic"],
          },
          recommendation_providers: [
            {
              id: "mock",
              label: "Mock recommendation",
              available: true,
              unavailable_reason: null,
            },
          ],
          recommendation_engines: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 2,
          included_cases_by_layout: { generic: 2 },
          default_layout_profile: "generic",
          latest_report: visionReport,
          recent_reports: [visionSummary],
          parser_pipelines: parserPipelines,
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    let dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    expect(
      await within(dialog).findByText("Parser comparison"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Use Mock parser benchmark pipeline",
      }),
    ).toBeDisabled();
    const useVision = within(dialog).getByRole("button", {
      name: "Use External vision benchmark pipeline",
    });
    expect(useVision).toHaveTextContent("90%");
    expect(useVision).toBeEnabled();

    await user.click(useVision);

    expect(
      await within(dialog).findByText("External vision · generic"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("Benchmark summary"),
    ).toHaveTextContent("90%");
    expect(fetchMock()).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/api/benchmarks?parser_provider=llm_vision&parser_layout_profile=generic",
      { credentials: "include" },
    );
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    await user.click(
      screen.getByRole("button", {
        name: "Configure analysis plugins",
      }),
    );
    dialog = await screen.findByRole("dialog", { name: "Analysis plugins" });
    expect(within(dialog).getByLabelText("Recognition")).toHaveValue(
      "llm_vision",
    );
  });

  it("runs every available parser comparison independently", async () => {
    const pendingMockRun = deferredResponse();
    const currentCorpusFingerprint = "a".repeat(64);
    const baseReport = {
      id: "benchmark-old-mock",
      parser_provider: "mock",
      layout_profile: "generic",
      corpus_fingerprint: "b".repeat(64),
      created_at: "2026-08-11T08:00:00Z",
      total_cases: 2,
      successful_cases: 2,
      failed_cases: 0,
      correct_fields: 14,
      evaluated_fields: 20,
      accuracy: 0.7,
      field_metrics: [
        { field: "hero_cards", correct: 2, total: 2, accuracy: 1 },
      ],
      cases: [],
    };
    const mockReport = {
      ...baseReport,
      id: "benchmark-new-mock",
      created_at: "2026-08-11T09:00:00Z",
      correct_fields: 16,
      accuracy: 0.8,
      corpus_fingerprint: currentCorpusFingerprint,
    };
    const previousMockReport = {
      ...mockReport,
      id: "benchmark-previous-mock",
      created_at: "2026-08-11T08:30:00Z",
      correct_fields: 17,
      accuracy: 0.85,
    };
    const visionReport = {
      ...baseReport,
      id: "benchmark-new-vision",
      parser_provider: "llm_vision",
      created_at: "2026-08-11T09:02:00Z",
      correct_fields: 19,
      accuracy: 0.95,
      corpus_fingerprint: currentCorpusFingerprint,
    };
    const previousVisionReport = {
      ...visionReport,
      id: "benchmark-previous-vision",
      created_at: "2026-08-11T08:32:00Z",
      correct_fields: 18,
      accuracy: 0.9,
    };
    const summary = (report: typeof baseReport) => ({
      id: report.id,
      parser_provider: report.parser_provider,
      layout_profile: report.layout_profile,
      corpus_fingerprint: report.corpus_fingerprint,
      created_at: report.created_at,
      total_cases: report.total_cases,
      failed_cases: report.failed_cases,
      accuracy: report.accuracy,
      field_metrics: report.field_metrics,
    });
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 2,
          included_cases_by_layout: { generic: 2 },
          corpus_fingerprint: currentCorpusFingerprint,
          default_layout_profile: "generic",
          latest_report: baseReport,
          recent_reports: [summary(baseReport)],
          parser_pipelines: [
            {
              parser: {
                id: "mock",
                label: "Mock parser",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "generic",
              latest_report: summary(baseReport),
            },
            {
              parser: {
                id: "ocr_cv",
                label: "Template OCR",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "generic",
              latest_report: null,
            },
            {
              parser: {
                id: "llm_vision",
                label: "External vision",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "generic",
              latest_report: null,
            },
          ],
        }),
      )
      .mockReturnValueOnce(pendingMockRun.promise)
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: "OCR worker is temporarily unavailable",
          },
          503,
        ),
      )
      .mockResolvedValueOnce(jsonResponse(visionReport))
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 2,
          included_cases_by_layout: { generic: 2 },
          corpus_fingerprint: currentCorpusFingerprint,
          default_layout_profile: "generic",
          latest_report: mockReport,
          recent_reports: [summary(mockReport), summary(baseReport)],
          parser_pipelines: [
            {
              parser: {
                id: "mock",
                label: "Mock parser",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "generic",
              latest_report: summary(mockReport),
              previous_report: summary(previousMockReport),
            },
            {
              parser: {
                id: "ocr_cv",
                label: "Template OCR",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "generic",
              latest_report: null,
            },
            {
              parser: {
                id: "llm_vision",
                label: "External vision",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "generic",
              latest_report: summary(visionReport),
              previous_report: summary(previousVisionReport),
            },
          ],
        }),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const runComparison = await within(dialog).findByRole("button", {
      name: "Run comparison",
    });
    expect(
      within(dialog).getByRole("button", {
        name: "Use Mock parser benchmark pipeline",
      }),
    ).toHaveTextContent("Current corpus not verified · rerun");
    expect(within(dialog).getByRole("status")).toHaveTextContent(
      "This run is not verified against the current ground truth",
    );
    await user.click(runComparison);

    expect(runComparison).toBeDisabled();
    expect(runComparison).toHaveTextContent("1/3");
    expect(
      within(dialog).getByRole("button", {
        name: "Use Mock parser benchmark pipeline",
      }),
    ).toHaveTextContent("Running benchmark...");
    pendingMockRun.resolve(jsonResponse(mockReport));

    expect(
      await screen.findByText(
        /Benchmark comparison completed for 2 of 3 parsers/,
      ),
    ).toHaveTextContent("Template OCR: OCR worker is temporarily unavailable");
    const mockPipeline = within(dialog).getByRole("button", {
      name: "Use Mock parser benchmark pipeline",
    });
    expect(mockPipeline).toHaveTextContent("80%");
    expect(mockPipeline).toHaveTextContent("-5 pts");
    expect(
      within(dialog).getByRole("button", {
        name: "Use Mock parser benchmark pipeline",
      }),
    ).not.toHaveTextContent("not verified");
    expect(
      within(dialog).getByRole("button", {
        name: "Use Template OCR benchmark pipeline",
      }),
    ).toHaveTextContent("--");
    const visionPipeline = within(dialog).getByRole("button", {
      name: "Use External vision benchmark pipeline",
    });
    expect(visionPipeline).toHaveTextContent("95%");
    expect(visionPipeline).toHaveTextContent("+5 pts");
    expect(
      within(dialog).getByLabelText("Benchmark summary"),
    ).toHaveTextContent("80%");
    expect(within(dialog).queryByRole("status")).not.toBeInTheDocument();
    expect(runComparison).toBeEnabled();

    const runBodies = fetchMock()
      .mock.calls.filter(
        ([url]) => url === "http://localhost:8000/api/benchmarks/run",
      )
      .map(([, request]) => JSON.parse(String(request?.body)));
    expect(runBodies).toEqual([
      { parser_provider: "mock", parser_layout_profile: "generic" },
      { parser_provider: "ocr_cv", parser_layout_profile: "generic" },
      { parser_provider: "llm_vision", parser_layout_profile: "generic" },
    ]);
  });

  it("imports a parser dataset and enables corpus actions", async () => {
    const pendingImport = deferredResponse();
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockReturnValueOnce(pendingImport.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 2,
          included_cases_by_layout: { generic: 2 },
          default_layout_profile: "generic",
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([], "dataset-import-snapshot"),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const importDataset = within(dialog).getByRole("button", {
      name: "Import dataset",
    });
    const exportDataset = within(dialog).getByRole("link", {
      name: "Export dataset",
    });
    await waitFor(() => expect(importDataset).toBeEnabled());
    expect(exportDataset).toHaveAttribute("aria-disabled", "true");

    const dataset = new File(["dataset-zip"], "parser-dataset.zip", {
      type: "application/zip",
    });
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      dataset,
    );

    expect(importDataset).toBeDisabled();
    expect(within(dialog).getByLabelText("Parser dataset ZIP")).toBeDisabled();
    expect(
      within(dialog).getByRole("button", { name: "Close parser benchmark" }),
    ).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Done" })).toBeDisabled();
    pendingImport.resolve(
      jsonResponse({
        imported_cases: 2,
        reused_cases: 0,
        included_cases: 2,
        job_ids: ["a".repeat(32), "b".repeat(32)],
      }),
    );

    expect(
      await screen.findByText("Dataset ready: 2 hands"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("2").closest("span")).toHaveTextContent(
      "2 ground-truth hands",
    );
    expect(exportDataset).toHaveAttribute("aria-disabled", "false");
    expect(
      within(dialog).getByRole("button", { name: "Run benchmark" }),
    ).toBeEnabled();
    expect(importDataset).toBeEnabled();

    expect(fetchMock().mock.calls[1][0]).toBe(
      "http://localhost:8000/api/benchmarks/import",
    );
    expect(fetchMock().mock.calls[1][1]).toMatchObject({
      method: "POST",
      headers: {
        "X-Benchmark-Import-Request-ID": expect.any(String),
      },
    });
    const form = fetchMock().mock.calls[1][1]?.body as FormData;
    expect(form.get("file")).toBe(dataset);
    expect(fetchMock()).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/api/benchmarks",
      { credentials: "include" },
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        4,
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
  });

  it("keeps a verified report current after an idempotent dataset import", async () => {
    const corpusFingerprint = "c".repeat(64);
    const activeJob = {
      ...approvedJob(),
      id: "7".repeat(32),
      original_filename: "already-included.png",
      parser_layout_profile: "fortuna",
      benchmark_included: true,
    };
    const baseOverview = benchmarkOverviewForJob(
      activeJob.id,
      activeJob.original_filename,
    );
    const overview = {
      ...baseOverview,
      included_cases_by_layout: { fortuna: 1 },
      corpus_fingerprint: corpusFingerprint,
      default_layout_profile: "fortuna",
      latest_report: {
        ...baseOverview.latest_report,
        corpus_fingerprint: corpusFingerprint,
      },
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([activeJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "http://localhost:8000/api/benchmarks") {
          return Promise.resolve(jsonResponse(overview));
        }
        if (
          url === "http://localhost:8000/api/benchmarks/import" &&
          init?.method === "POST"
        ) {
          return Promise.resolve(
            jsonResponse({
              imported_cases: 0,
              reused_cases: 1,
              included_cases: 1,
              included_cases_by_layout: { fortuna: 1 },
              job_ids: [activeJob.id],
            }),
          );
        }
        if (url === "http://localhost:8000/api/jobs") {
          return Promise.resolve(processingQueueResponse([activeJob]));
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      new File(["dataset-zip"], "parser-dataset.zip", {
        type: "application/zip",
      }),
    );

    expect(
      await screen.findByText("Dataset ready: 1 hand"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        fetchMock().mock.calls.filter(
          ([url]) => String(url) === "http://localhost:8000/api/benchmarks",
        ),
      ).toHaveLength(2),
    );
    expect(
      within(dialog).queryByText(
        "This run is not verified against the current ground truth.",
      ),
    ).not.toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 100%",
      }),
    ).toBeInTheDocument();
  });

  it("releases dataset import leases after a deterministic rejection", async () => {
    const benchmarkJobId = "6".repeat(32);
    const pristineImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "unrelated-benchmark-hand.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const overview = benchmarkOverviewForJob(
      benchmarkJobId,
      pristineImport.original_filename,
    );
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(overview))
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockResolvedValueOnce(jsonResponse(overview))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: "Dataset ZIP exceeds maximum size",
          },
          413,
        ),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([], "rejected-dataset-import-snapshot"),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const reviewDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(reviewDialog).getByRole("button", {
        name: "Toggle unrelated-benchmark-hand.png benchmark details",
      }),
    );
    await user.click(
      within(reviewDialog).getByRole("button", {
        name: "Review hand",
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", {
          name: "Parser benchmark",
        }),
      ).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      new File(["oversized-dataset"], "oversized.zip", {
        type: "application/zip",
      }),
    );

    expect(
      await screen.findByText("Dataset ZIP exceeds maximum size"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
    expect(
      within(dialog).getByRole("button", {
        name: "Import dataset",
      }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: unrelated-benchmark-hand.png",
      }),
    ).toBeInTheDocument();
    await waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(5));
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/benchmarks/import",
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("removes a reused pristine dataset case from processing immediately", async () => {
    const benchmarkJobId = "3".repeat(32);
    const processingImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "reused-pristine-import.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: false,
      parser_result: null,
    };
    const nextState: DetectedState = {
      ...detectedState,
      hero_cards: [
        { rank: "Q", suit: "clubs" },
        { rank: "Q", suit: "hearts" },
      ],
      pot_size: 8,
    };
    const nextJob = jobRecord({
      id: "1".repeat(32),
      original_filename: "next-processing-hand.png",
      image_filename: `${"1".repeat(32)}.png`,
      parser_result: {
        ...jobRecord().parser_result!,
        state: nextState,
      },
    });
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingImport, nextJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "2");
    const pendingQueue = deferredResponse();
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          imported_cases: 0,
          reused_cases: 1,
          included_cases: 1,
          job_ids: [benchmarkJobId],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { generic: 1 },
          default_layout_profile: "generic",
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockReturnValueOnce(pendingQueue.promise);
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      new File(["dataset-zip"], "parser-dataset.zip", {
        type: "application/zip",
      }),
    );

    expect(
      await screen.findByText("Dataset ready: 1 hand"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([nextJob]),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: reused-pristine-import.png",
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: next-processing-hand.png",
      }),
    ).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(screen.getByDisplayValue("Qc Qh")).toBeInTheDocument();
    expect(screen.getByDisplayValue("8")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Ah Kd")).not.toBeInTheDocument();

    pendingQueue.resolve(
      processingQueueResponse([nextJob], "reused-pristine-import-snapshot"),
    );

    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true"),
    );
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/benchmarks/import",
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("preserves unsaved corrections when importing the active dataset case", async () => {
    const benchmarkJobId = "4".repeat(32);
    const processingImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "dirty-reused-import.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: false,
      parser_result: null,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    const pendingQueue = deferredResponse();
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          imported_cases: 0,
          reused_cases: 1,
          included_cases: 1,
          job_ids: [benchmarkJobId],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { generic: 1 },
          default_layout_profile: "generic",
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockReturnValueOnce(pendingQueue.promise);
    render(<App />);
    const user = userEvent.setup();

    const heroCards = await screen.findByLabelText(/Hero cards/);
    await user.clear(heroCards);
    await user.type(heroCards, "7d Ah");
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      new File(["dataset-zip"], "parser-dataset.zip", {
        type: "application/zip",
      }),
    );

    expect(
      await screen.findByText("Dataset ready: 1 hand"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("switch", {
        name: /Use current hand as ground truth/,
      }),
    ).toHaveAttribute("aria-checked", "true");
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([]),
    );
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: dirty-reused-import.png",
      }),
    ).toHaveClass("active");
    await user.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(heroCards).toHaveValue("7d Ah");
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBeNull();

    pendingQueue.resolve(
      processingQueueResponse([], "dirty-reused-import-snapshot"),
    );

    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true"),
    );
    expect(
      screen.getByRole("button", {
        name: "Open screenshot 1: dirty-reused-import.png",
      }),
    ).toHaveClass("active");
    expect(heroCards).toHaveValue("7d Ah");
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/benchmarks/import",
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("reconciles a reused pristine dataset case after a lost import response", async () => {
    const benchmarkJobId = "2".repeat(32);
    const processingImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "reimport-response-lost.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: false,
      parser_result: null,
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockRejectedValueOnce(
        new TypeError("Connection lost after dataset import"),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          request_id: "reused-import-recovery",
          archive_sha256: "a".repeat(64),
          status: "completed",
          result: {
            imported_cases: 0,
            reused_cases: 1,
            included_cases: 1,
            job_ids: [benchmarkJobId],
          },
          error: null,
          error_status: null,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { generic: 1 },
          default_layout_profile: "generic",
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([], "lost-dataset-import-snapshot"),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "lost-dataset-history-snapshot",
        }),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      new File(["dataset-zip"], "parser-dataset.zip", {
        type: "application/zip",
      }),
    );

    expect(
      await screen.findByText("Dataset recovered: 1 hand"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
        "[]",
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: reimport-response-lost.png",
      }),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: reimport-response-lost.png",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/benchmarks/import",
      expect.stringMatching(
        /^http:\/\/localhost:8000\/api\/benchmarks\/imports\/.+/,
      ),
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/history",
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("recovers a new dataset-only case by request identity after reload", async () => {
    const importedJobId = "7".repeat(32);
    let recoveryAttempts = 0;
    fetchMock().mockImplementation(
      (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "http://localhost:8000/api/benchmarks") {
          return Promise.resolve(
            jsonResponse({
              included_cases: 0,
              latest_report: null,
              recent_reports: [],
            }),
          );
        }
        if (
          url === "http://localhost:8000/api/benchmarks/import" &&
          init?.method === "POST"
        ) {
          return Promise.reject(
            new TypeError("Connection lost after dataset import"),
          );
        }
        if (url.startsWith("http://localhost:8000/api/benchmarks/imports/")) {
          recoveryAttempts += 1;
          const requestId = decodeURIComponent(url.split("/").pop() ?? "");
          return recoveryAttempts === 1
            ? Promise.resolve(
                jsonResponse({
                  request_id: requestId,
                  archive_sha256: "b".repeat(64),
                  status: "pending",
                  result: null,
                  error: null,
                  error_status: null,
                }),
              )
            : Promise.resolve(
                jsonResponse({
                  request_id: requestId,
                  archive_sha256: "b".repeat(64),
                  status: "completed",
                  result: {
                    imported_cases: 1,
                    reused_cases: 0,
                    included_cases: 1,
                    job_ids: [importedJobId],
                  },
                  error: null,
                  error_status: null,
                }),
              );
        }
        if (url === "http://localhost:8000/api/jobs") {
          return Promise.resolve(
            processingQueueResponse(
              [],
              "new-dataset-import-processing-snapshot",
            ),
          );
        }
        if (url === "http://localhost:8000/api/history") {
          return Promise.resolve(
            jsonResponse({
              total: 0,
              jobs: [],
              snapshot_version: "new-dataset-import-history-snapshot",
            }),
          );
        }
        throw new Error(`Unexpected request: ${url}`);
      },
    );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      new File(["dataset-zip"], "parser-dataset.zip", {
        type: "application/zip",
      }),
    );

    await waitFor(() => expect(recoveryAttempts).toBe(1));
    const importRequest = fetchMock().mock.calls.find(
      ([url]) => String(url) === "http://localhost:8000/api/benchmarks/import",
    );
    const importRequestId = (
      importRequest?.[1]?.headers as Record<string, string>
    )["X-Benchmark-Import-Request-ID"];
    expect(importRequestId).toEqual(expect.any(String));
    expect(fetchMock()).toHaveBeenCalledWith(
      `http://localhost:8000/api/benchmarks/imports/${importRequestId}`,
      { credentials: "include" },
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toContain(importRequestId);
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toContain('"benchmarkImportReceiptObserved":true');
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toContain(importRequestId);

    firstRender.unmount();
    for (const leaseKey of [
      "poker-training-processing-mutation-v1",
      "poker-training-history-mutation-v1",
    ]) {
      const lease = JSON.parse(String(window.sessionStorage.getItem(leaseKey)));
      window.sessionStorage.setItem(
        leaseKey,
        JSON.stringify({ ...lease, expiresAt: Date.now() - 1 }),
      );
    }
    render(<App />);

    expect(
      await screen.findByText("Dataset recovered: 1 hand"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
    expect(recoveryAttempts).toBe(2);
  });

  it("blocks benchmark runs while a recovered dataset import is pending", async () => {
    const importRequestId = "pending-import-before-benchmark";
    const pendingImportLease = {
      kind: "projection",
      ownerId: "previous-page",
      baselineJobIds: [],
      expectedRemovalJobIds: [],
      benchmarkImportRequestId: importRequestId,
      benchmarkImportReceiptObserved: true,
      expectedUploads: [],
      expiresAt: Date.now() + 30_000,
    };
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify(pendingImportLease),
    );
    window.sessionStorage.setItem(
      "poker-training-history-mutation-v1",
      JSON.stringify(pendingImportLease),
    );
    const pendingReceipt = deferredResponse();
    fetchMock().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (
        url ===
        `http://localhost:8000/api/benchmarks/imports/${importRequestId}`
      ) {
        return pendingReceipt.promise;
      }
      if (url === "http://localhost:8000/api/benchmarks") {
        return Promise.resolve(
          jsonResponse({
            included_cases: 1,
            latest_report: null,
            recent_reports: [],
          }),
        );
      }
      if (url === "http://localhost:8000/api/jobs") {
        return Promise.resolve(
          processingQueueResponse([], "completed-import-processing-snapshot"),
        );
      }
      if (url === "http://localhost:8000/api/history") {
        return Promise.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "completed-import-history-snapshot",
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const runButton = within(dialog).getByRole("button", {
      name: "Run benchmark",
    });
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        `http://localhost:8000/api/benchmarks/imports/${importRequestId}`,
        { credentials: "include" },
      ),
    );
    expect(runButton).toBeDisabled();
    await user.click(runButton);
    expect(
      fetchMock().mock.calls.some(
        ([url]) => String(url) === "http://localhost:8000/api/benchmarks/run",
      ),
    ).toBe(false);

    pendingReceipt.resolve(
      jsonResponse({
        request_id: importRequestId,
        archive_sha256: "c".repeat(64),
        status: "completed",
        result: {
          imported_cases: 1,
          reused_cases: 0,
          included_cases: 1,
          job_ids: [],
        },
        error: null,
        error_status: null,
      }),
    );

    await waitFor(() => expect(runButton).toBeEnabled());
    expect(
      window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
    ).toBeNull();
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
  });

  it("honors Retry-After while recovering a benchmark import", async () => {
    vi.useFakeTimers();
    const importRequestId = "rate-limited-import-recovery";
    const pendingImportLease = {
      kind: "projection",
      ownerId: "previous-page",
      baselineJobIds: [],
      expectedRemovalJobIds: [],
      benchmarkImportRequestId: importRequestId,
      benchmarkImportReceiptObserved: true,
      expectedUploads: [],
      expiresAt: Date.now() + 120_000,
    };
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify(pendingImportLease),
    );
    window.sessionStorage.setItem(
      "poker-training-history-mutation-v1",
      JSON.stringify(pendingImportLease),
    );
    let recoveryAttempts = 0;
    fetchMock().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (
        url ===
        `http://localhost:8000/api/benchmarks/imports/${importRequestId}`
      ) {
        recoveryAttempts += 1;
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: "Rate limit exceeded for data transfers",
            }),
            {
              status: 429,
              headers: {
                "Content-Type": "application/json",
                "Retry-After": "60",
              },
            },
          ),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    const view = render(<App />);

    try {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(250);
      });
      expect(recoveryAttempts).toBe(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(59_999);
      });
      expect(recoveryAttempts).toBe(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(2);
      });
      expect(recoveryAttempts).toBe(2);
    } finally {
      view.unmount();
      vi.useRealTimers();
    }
  });

  it("expires unobserved dataset import leases after recovery request failures", async () => {
    const importRequestId = "expired-unobserved-import";
    const expiredLease = {
      kind: "projection",
      ownerId: "previous-page",
      baselineJobIds: [],
      expectedRemovalJobIds: [],
      benchmarkImportRequestId: importRequestId,
      benchmarkImportReceiptObserved: false,
      expectedUploads: [],
      expiresAt: Date.now() - 1,
    };
    window.localStorage.setItem("poker-training-processing-v1", "[]");
    window.localStorage.setItem("poker-training-processing-total-v1", "0");
    window.localStorage.setItem("poker-training-history-v1", "[]");
    window.localStorage.setItem("poker-training-history-total-v1", "0");
    window.sessionStorage.setItem(
      "poker-training-processing-mutation-v1",
      JSON.stringify(expiredLease),
    );
    window.sessionStorage.setItem(
      "poker-training-history-mutation-v1",
      JSON.stringify(expiredLease),
    );
    let receiptAttempts = 0;
    fetchMock().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("http://localhost:8000/api/benchmarks/imports/")) {
        receiptAttempts += 1;
        return Promise.reject(new TypeError("Receipt endpoint unavailable"));
      }
      if (url === "http://localhost:8000/api/jobs") {
        return Promise.resolve(
          processingQueueResponse([], "expired-import-processing-snapshot"),
        );
      }
      if (url === "http://localhost:8000/api/history") {
        return Promise.resolve(
          jsonResponse({
            total: 0,
            jobs: [],
            snapshot_version: "expired-import-history-snapshot",
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });

    render(<App />);

    await waitFor(() => expect(receiptAttempts).toBeGreaterThan(0));
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(
      window.sessionStorage.getItem("poker-training-history-mutation-v1"),
    ).toBeNull();
  });

  it("preserves a confirmed dataset import during pending queue reconciliation", async () => {
    const cachedJob = {
      ...approvedJob(),
      id: "c".repeat(32),
      original_filename: "reused-dataset-hand.png",
    };
    const includedJob = {
      ...cachedJob,
      benchmark_included: true,
      updated_at: "2026-07-20T12:10:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([cachedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    window.sessionStorage.removeItem("poker-training-processing-synced");
    const pendingQueue = deferredResponse();
    const pendingImport = deferredResponse();
    fetchMock()
      .mockReturnValueOnce(pendingQueue.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockReturnValueOnce(pendingImport.promise)
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { generic: 1 },
          default_layout_profile: "generic",
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([includedJob], "confirmed-import-snapshot"),
      );
    render(<App />);
    const user = userEvent.setup();

    await waitFor(() =>
      expect(fetchMock()).toHaveBeenCalledWith(
        "http://localhost:8000/api/jobs",
        { credentials: "include" },
      ),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const dataset = new File(["dataset-zip"], "parser-dataset.zip", {
      type: "application/zip",
    });
    await user.upload(
      within(dialog).getByLabelText("Parser dataset ZIP"),
      dataset,
    );
    await waitFor(() =>
      expect(fetchMock()).toHaveBeenNthCalledWith(
        3,
        "http://localhost:8000/api/benchmarks/import",
        expect.objectContaining({ method: "POST" }),
      ),
    );

    await act(async () => {
      pendingImport.resolve(
        jsonResponse({
          imported_cases: 0,
          reused_cases: 1,
          included_cases: 1,
          job_ids: [cachedJob.id],
        }),
      );
      await pendingImport.promise;
      await Promise.resolve();
      await Promise.resolve();
      pendingQueue.resolve(
        jsonResponse({
          total: 1,
          jobs: [cachedJob],
          snapshot_version: "stale-processing-snapshot",
        }),
      );
      await pendingQueue.promise;
    });

    await waitFor(() =>
      expect(
        within(dialog).getByRole("switch", {
          name: /Use current hand as ground truth/,
        }),
      ).toHaveAttribute("aria-checked", "true"),
    );
    expect(
      JSON.parse(
        String(window.localStorage.getItem("poker-training-processing-v1")),
      )[0].benchmark_included,
    ).toBe(true);
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(fetchMock()).toHaveBeenCalledTimes(5);
  });

  it("updates an imported hand held only by the history search projection", async () => {
    const archivedJob: JobRecord = {
      ...recommendedJob(),
      id: "archived-import-job",
      original_filename: "archived-import.png",
      benchmark_included: false,
      archived_at: "2026-07-10T00:02:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          total: 1,
          jobs: [archivedJob],
          snapshot_version: "before-import",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          imported_cases: 0,
          reused_cases: 1,
          included_cases: 1,
          job_ids: [archivedJob.id],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { generic: 1 },
          default_layout_profile: "generic",
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([], "archived-dataset-import-snapshot"),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          latest_report: null,
          recent_reports: [],
        }),
      );
    render(<App />);
    const user = userEvent.setup();
    const historyPanel = screen.getByLabelText("Session history");

    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Search saved history",
      }),
    );
    await user.type(
      within(historyPanel).getByLabelText("History search query"),
      "flop",
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Run history search",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const importDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await waitFor(() =>
      expect(
        within(importDialog).getByRole("button", { name: "Import dataset" }),
      ).toBeEnabled(),
    );
    await user.upload(
      within(importDialog).getByLabelText("Parser dataset ZIP"),
      new File(["dataset-zip"], "parser-dataset.zip", {
        type: "application/zip",
      }),
    );

    expect(
      await screen.findByText("Dataset ready: 1 hand"),
    ).toBeInTheDocument();
    await user.click(
      within(importDialog).getByRole("button", { name: "Done" }),
    );
    await user.click(
      within(historyPanel).getByRole("button", {
        name: "Reopen history item 1",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const reopenedDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    expect(
      await within(reopenedDialog).findByRole("switch", {
        name: /Use current hand as ground truth/,
      }),
    ).toHaveAttribute("aria-checked", "true");
    expect(fetchMock()).toHaveBeenCalledTimes(6);
  });

  it("shows benchmark mismatches and opens the stored hand for correction", async () => {
    const pendingReviewJob = deferredResponse();
    const benchmarkJobId = "b".repeat(32);
    const activeJob = {
      ...approvedJob(),
      id: "active-job",
      original_filename: "active.png",
      image_filename: "active-job.png",
      benchmark_included: true,
    };
    const reviewedState = canonicalState({ pot_size: 12.5 });
    const reviewedJob = {
      ...approvedJob(reviewedState),
      id: benchmarkJobId,
      original_filename: "mismatch.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const benchmarkReport = {
      id: "benchmark-review",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      created_at: "2026-07-20T12:00:00Z",
      total_cases: 1,
      successful_cases: 1,
      failed_cases: 0,
      correct_fields: 9,
      evaluated_fields: 10,
      accuracy: 0.9,
      field_metrics: [
        { field: "pot_size", correct: 0, total: 1, accuracy: 0 },
        { field: "postflop_action_history", correct: 0, total: 1, accuracy: 0 },
      ],
      cases: [
        {
          job_id: benchmarkJobId,
          original_filename: "mismatch.png",
          status: "completed",
          correct_fields: 9,
          evaluated_fields: 10,
          accuracy: 0.9,
          warnings: [],
          error: null,
          comparisons: [
            {
              field: "pot_size",
              expected: 12.5,
              detected: 10,
              matched: false,
              confidence: 0.73,
            },
            {
              field: "postflop_action_history",
              expected: [
                { actor: "oop", action: "bet", amount: 2 },
                { actor: "ip", action: "raise", amount: 7 },
              ],
              detected: [
                { actor: "oop", action: "bet", amount: 2 },
                { actor: "ip", action: "raise", amount: 6 },
              ],
              matched: false,
              confidence: null,
            },
          ],
        },
      ],
    };
    window.localStorage.setItem(
      "poker-training-history-v1",
      JSON.stringify([
        { id: activeJob.id, job: activeJob, savedAt: "2026-07-20T12:00:00Z" },
      ]),
    );
    window.localStorage.setItem("poker-training-history-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({ included_cases: 1, latest_report: benchmarkReport }),
      )
      .mockReturnValueOnce(pendingReviewJob.promise);
    render(<App />);

    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "Reopen history item 1" }),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(dialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle mismatch.png benchmark details",
      }),
    );

    const details = within(dialog)
      .getAllByText("Expected")[0]
      .closest(".benchmark-case-details");
    expect(details).not.toBeNull();
    expect(
      within(details as HTMLElement).getByText("12.5"),
    ).toBeInTheDocument();
    expect(within(details as HTMLElement).getByText("10")).toBeInTheDocument();
    expect(
      within(details as HTMLElement).getByText(
        "OOP bet 2 BB; IP raise to 7 BB",
      ),
    ).toBeInTheDocument();
    expect(
      within(details as HTMLElement).getByText(
        "OOP bet 2 BB; IP raise to 6 BB",
      ),
    ).toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    expect(groundTruthSwitch).toBeDisabled();
    pendingReviewJob.resolve(jsonResponse(reviewedJob));

    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByAltText("Uploaded poker table screenshot"),
    ).toHaveAttribute(
      "src",
      `http://localhost:8000/api/jobs/${benchmarkJobId}/image`,
    );
    expect(screen.getByLabelText(/Pot/)).toHaveValue("12.5");
    await waitFor(() =>
      expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
        "[]",
      ),
    );
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
    ]);
  });

  it("shows the selected parser and fallback evidence for benchmark cases", async () => {
    const benchmarkJobId = "a".repeat(32);
    const baseOverview = benchmarkOverviewForJob(
      benchmarkJobId,
      "automatic-route.png",
    );
    const baseCase = baseOverview.latest_report.cases[0];
    const overview = {
      ...baseOverview,
      latest_report: {
        ...baseOverview.latest_report,
        parser_provider: "auto",
        layout_profile: "fortuna_nations",
        total_cases: 3,
        successful_cases: 2,
        failed_cases: 1,
        correct_fields: 18,
        evaluated_fields: 30,
        accuracy: 0.6,
        cases: [
          {
            ...baseCase,
            parser_routing: {
              provider: "auto",
              selected_provider: "llm_vision",
              layout_profile: "fortuna_nations",
              fallback_from: "ocr_cv",
              fallback_reason:
                "Capture geometry did not match the table profile",
            },
          },
          {
            ...baseCase,
            job_id: "b".repeat(32),
            original_filename: "local-route.png",
            correct_fields: 8,
            accuracy: 0.8,
            parser_routing: {
              provider: "auto",
              selected_provider: "ocr_cv",
              layout_profile: "fortuna_nations",
              fallback_from: null,
              fallback_reason: null,
            },
          },
          {
            ...baseCase,
            job_id: "c".repeat(32),
            original_filename: "unattributed-error.png",
            status: "error",
            correct_fields: 0,
            accuracy: 0,
            error: "Automatic recognition could not parse the screenshot",
          },
        ],
      },
    };
    fetchMock().mockResolvedValueOnce(jsonResponse(overview));
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    const routes = within(dialog).getByRole("region", {
      name: "Parser routes",
    });
    const externalRoute = within(routes).getByLabelText(
      "External vision model parser route",
    );
    expect(externalRoute).toHaveTextContent(
      "1 case · 10/10 fields · 1 fallback",
    );
    expect(externalRoute).toHaveTextContent("100%");
    const localRoute = within(routes).getByLabelText(
      "OCR + computer vision parser route",
    );
    expect(localRoute).toHaveTextContent("1 case · 8/10 fields");
    expect(localRoute).toHaveTextContent("80%");
    expect(
      within(routes).getByText("2 of 3 cases attributed"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "External vision model · All labeled fields matched",
      ),
    ).toBeInTheDocument();
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle automatic-route.png benchmark details",
      }),
    );
    const routing = within(dialog).getByLabelText("Parser routing");
    expect(
      within(routing).getByText("External vision model"),
    ).toBeInTheDocument();
    expect(
      within(routing).getByText(
        "via Automatic recognition · fallback from OCR + computer vision",
      ),
    ).toBeInTheDocument();
    expect(
      within(routing).getByText(
        "Capture geometry did not match the table profile",
      ),
    ).toBeInTheDocument();
  });

  it("restores a provider failure after recommending a pristine benchmark import", async () => {
    const benchmarkJobId = "c".repeat(32);
    const recommendationRequestId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      recommendationRequestId,
    );
    const pristineImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "provider-failure.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const failedImport = {
      ...pristineImport,
      status: "error" as const,
      error: "provider exploded",
      recommendation_request_id: recommendationRequestId,
      updated_at: "2026-07-10T00:01:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(benchmarkJobId, "provider-failure.png"),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockResolvedValueOnce(jsonResponse({ detail: "provider exploded" }, 502))
      .mockResolvedValueOnce(
        processingQueueResponse([failedImport], "failed-import-snapshot"),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle provider-failure.png benchmark details",
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    expect(await screen.findAllByText("provider exploded")).not.toHaveLength(0);
    const failedQueueItem = await screen.findByRole("button", {
      name: "Open screenshot 1: provider-failure.png",
    });
    expect(within(failedQueueItem).getByText("error")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([failedImport]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    const restoredQueueItem = await screen.findByRole("button", {
      name: "Open screenshot 1: provider-failure.png",
    });
    expect(
      within(restoredQueueItem).getByText("provider exploded"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeEnabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
      `http://localhost:8000/api/jobs/${benchmarkJobId}/recommend`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("keeps a correctable benchmark recommendation in processing across reloads", async () => {
    const benchmarkJobId = "e".repeat(32);
    const recommendationRequestId = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
    vi.spyOn(globalThis.crypto, "randomUUID").mockReturnValue(
      recommendationRequestId,
    );
    const pristineImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "correctable-recommendation.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const revalidatedImport = {
      ...pristineImport,
      recommendation_request_id: recommendationRequestId,
      updated_at: "2026-07-10T00:01:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(
            benchmarkJobId,
            "correctable-recommendation.png",
          ),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: { missing_fields: ["effective_stack"] },
          },
          422,
        ),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [revalidatedImport],
          "correctable-import-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle correctable-recommendation.png benchmark details",
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );

    await user.click(
      screen.getByRole("button", { name: "Request recommendation" }),
    );

    expect(await screen.findAllByText(/Effective stack/)).not.toHaveLength(0);
    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: correctable-recommendation.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeEnabled();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );

    firstRender.unmount();
    render(<App />);

    expect(
      await screen.findByRole("button", {
        name: "Open screenshot 1: correctable-recommendation.png",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Request recommendation",
      }),
    ).toBeEnabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
      `http://localhost:8000/api/jobs/${benchmarkJobId}/recommend`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("restores a lost standalone decision response for a pristine benchmark import", async () => {
    const benchmarkJobId = "7".repeat(32);
    const pristineImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "decision-response-lost.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const persistedDecision = {
      ...pristineImport,
      training_decision: {
        action: "call" as const,
        sizing: null,
        certainty: "medium" as const,
        recorded_at: "2026-07-20T12:05:00Z",
      },
      updated_at: "2026-07-20T12:05:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(benchmarkJobId, "decision-response-lost.png"),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockRejectedValueOnce(
        new TypeError("Connection lost after saving answer"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [persistedDecision],
          "persisted-decision-snapshot",
        ),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle decision-response-lost.png benchmark details",
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );
    const decisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "call" }),
    );
    await user.click(
      within(decisionPanel).getByRole("button", { name: "medium" }),
    );

    await user.click(
      within(decisionPanel).getByRole("button", { name: "Lock answer" }),
    );

    expect(
      await screen.findByText("Connection lost after saving answer"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([persistedDecision]),
    );
    expect(
      await within(decisionPanel).findByText("Answer locked"),
    ).toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    const restoredQueueItem = await screen.findByRole("button", {
      name: "Open screenshot 1: decision-response-lost.png",
    });
    expect(within(restoredQueueItem).getByText("approved")).toBeInTheDocument();
    const restoredDecisionPanel = await screen.findByLabelText(
      "Your training decision",
    );
    expect(
      within(restoredDecisionPanel).getByText("Answer locked"),
    ).toBeInTheDocument();
    expect(
      within(restoredDecisionPanel).getByRole("button", {
        name: "medium",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
      `http://localhost:8000/api/jobs/${benchmarkJobId}/decision`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it.each([
    { operation: "recommendation" as const },
    { operation: "decision" as const },
  ])(
    "restores stable queue order after a successful benchmark $operation",
    async ({ operation }) => {
      const benchmarkJobId =
        operation === "recommendation" ? "a".repeat(32) : "b".repeat(32);
      const promotedFilename = `${operation}-promoted.png`;
      const olderJob = jobRecord({
        id: "0".repeat(32),
        original_filename: `${operation}-older.png`,
        image_filename: `${"0".repeat(32)}.png`,
        created_at: "2026-07-20T12:00:00Z",
        updated_at: "2026-07-20T12:00:00Z",
      });
      const pristineImport = {
        ...approvedJob(),
        id: benchmarkJobId,
        original_filename: promotedFilename,
        image_filename: `${benchmarkJobId}.png`,
        benchmark_included: true,
        parser_result: null,
        created_at: "2026-07-20T12:01:00Z",
        updated_at: "2026-07-20T12:01:00Z",
      };
      const newerJob = jobRecord({
        id: "f".repeat(32),
        original_filename: `${operation}-newer.png`,
        image_filename: `${"f".repeat(32)}.png`,
        created_at: "2026-07-20T12:02:00Z",
        updated_at: "2026-07-20T12:02:00Z",
      });
      const promotedJob: JobRecord =
        operation === "recommendation"
          ? {
              ...pristineImport,
              status: "recommended",
              recommendation,
              updated_at: "2026-07-20T12:03:00Z",
            }
          : {
              ...pristineImport,
              training_decision: {
                action: "call",
                sizing: null,
                certainty: "medium",
                recorded_at: "2026-07-20T12:03:00Z",
              },
              updated_at: "2026-07-20T12:03:00Z",
            };
      window.localStorage.setItem(
        "poker-training-processing-v1",
        JSON.stringify([olderJob, newerJob]),
      );
      window.localStorage.setItem("poker-training-processing-total-v1", "2");
      fetchMock()
        .mockResolvedValueOnce(
          jsonResponse(
            benchmarkOverviewForJob(benchmarkJobId, promotedFilename),
          ),
        )
        .mockResolvedValueOnce(jsonResponse(pristineImport))
        .mockResolvedValueOnce(jsonResponse(promotedJob))
        .mockResolvedValueOnce(
          processingQueueResponse(
            [olderJob, promotedJob, newerJob],
            `${operation}-promoted-snapshot`,
          ),
        );
      const firstRender = render(<App />);
      const user = userEvent.setup();

      await user.click(
        screen.getByRole("button", { name: "Parser benchmark" }),
      );
      const dialog = await screen.findByRole("dialog", {
        name: "Parser benchmark",
      });
      await user.click(
        within(dialog).getByRole("button", {
          name: `Toggle ${promotedFilename} benchmark details`,
        }),
      );
      await user.click(
        within(dialog).getByRole("button", { name: "Review hand" }),
      );
      await waitFor(() =>
        expect(
          screen.queryByRole("dialog", { name: "Parser benchmark" }),
        ).not.toBeInTheDocument(),
      );
      expect(
        screen.getByRole("button", {
          name: `Open screenshot 1: ${promotedFilename}`,
        }),
      ).toBeInTheDocument();

      if (operation === "recommendation") {
        await user.click(
          screen.getByRole("button", {
            name: "Request recommendation",
          }),
        );
      } else {
        const decisionPanel = await screen.findByLabelText(
          "Your training decision",
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "call" }),
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "medium" }),
        );
        await user.click(
          within(decisionPanel).getByRole("button", { name: "Lock answer" }),
        );
      }

      await waitFor(() =>
        expect(
          JSON.parse(
            String(window.localStorage.getItem("poker-training-processing-v1")),
          ),
        ).toEqual([olderJob, promotedJob, newerJob]),
      );
      expect(
        screen.getByRole("button", {
          name: `Open screenshot 1: ${operation}-older.png`,
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: `Open screenshot 2: ${promotedFilename}`,
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: `Open screenshot 3: ${operation}-newer.png`,
        }),
      ).toBeInTheDocument();
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true");

      firstRender.unmount();
      render(<App />);

      expect(
        screen.getByRole("button", {
          name: `Open screenshot 1: ${operation}-older.png`,
        }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name: `Open screenshot 2: ${promotedFilename}`,
        }),
      ).toBeInTheDocument();
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        "http://localhost:8000/api/benchmarks",
        `http://localhost:8000/api/jobs/${benchmarkJobId}`,
        `http://localhost:8000/api/jobs/${benchmarkJobId}/${operation === "recommendation" ? "recommend" : "decision"}`,
        "http://localhost:8000/api/jobs",
      ]);
    },
  );

  it("removes an import from processing after successful benchmark inclusion", async () => {
    const benchmarkJobId = "6".repeat(32);
    const processingImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "include-success.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: false,
      parser_result: null,
    };
    const pristineImport = {
      ...processingImport,
      benchmark_included: true,
      updated_at: "2026-07-20T12:10:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockResolvedValueOnce(
        processingQueueResponse([], "included-import-success-snapshot"),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(dialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    await user.click(groundTruthSwitch);

    await waitFor(() =>
      expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
        "[]",
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: include-success.png",
      }),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: include-success.png",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}/benchmark`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("releases a benchmark lease after deterministic inclusion rejection", async () => {
    const parsedJob = {
      ...approvedJob(),
      id: "5".repeat(32),
      original_filename: "benchmark-conflict.png",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([parsedJob]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 250,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: "Parser datasets support at most 250 cases",
          },
          409,
        ),
      )
      .mockResolvedValueOnce(
        processingQueueResponse(
          [parsedJob],
          "benchmark-inclusion-conflict-snapshot",
        ),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(dialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    await user.click(groundTruthSwitch);

    expect(
      await screen.findByText("Parser datasets support at most 250 cases"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        window.sessionStorage.getItem("poker-training-processing-mutation-v1"),
      ).toBeNull(),
    );
    expect(groundTruthSwitch).toHaveAttribute("aria-checked", "false");
    expect(groundTruthSwitch).toBeEnabled();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${parsedJob.id}/benchmark`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("removes an import from processing after successful re-approval", async () => {
    const benchmarkJobId = "4".repeat(32);
    const mutatedImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "approval-success.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
      training_decision: {
        action: "call" as const,
        sizing: null,
        certainty: "medium" as const,
        recorded_at: "2026-07-20T12:05:00Z",
      },
    };
    const approvedState = canonicalState({ pot_size: 20 });
    const pristineImport = {
      ...mutatedImport,
      approved_state: approvedState,
      training_decision: null,
      updated_at: "2026-07-20T12:10:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([mutatedImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockResolvedValueOnce(
        processingQueueResponse([], "reapproved-import-success-snapshot"),
      );
    const firstRender = render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    await waitFor(() =>
      expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
        "[]",
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: approval-success.png",
      }),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: approval-success.png",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${benchmarkJobId}/approve`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it.each([
    { operation: "include" as const },
    { operation: "exclude" as const },
  ])(
    "reconciles a lost parser-backed benchmark $operation response",
    async ({ operation }) => {
      const jobId = "8".repeat(32);
      const initiallyIncluded = operation === "exclude";
      const includedAfterWrite = !initiallyIncluded;
      const parserBackedJob = {
        ...approvedJob(),
        id: jobId,
        original_filename: `parser-backed-${operation}.png`,
        image_filename: `${jobId}.png`,
        benchmark_included: initiallyIncluded,
      };
      const persistedJob = {
        ...parserBackedJob,
        benchmark_included: includedAfterWrite,
        updated_at: "2026-07-20T12:10:00Z",
      };
      const emptyOverview = {
        included_cases: 0,
        latest_report: null,
        recent_reports: [],
      };
      const includedOverview = benchmarkOverviewForJob(
        jobId,
        parserBackedJob.original_filename,
      );
      window.localStorage.setItem(
        "poker-training-processing-v1",
        JSON.stringify([parserBackedJob]),
      );
      window.localStorage.setItem("poker-training-processing-total-v1", "1");
      fetchMock()
        .mockResolvedValueOnce(
          jsonResponse(initiallyIncluded ? includedOverview : emptyOverview),
        )
        .mockRejectedValueOnce(
          new TypeError(`Connection lost after benchmark ${operation}`),
        )
        .mockResolvedValueOnce(
          processingQueueResponse(
            [persistedJob],
            `parser-backed-${operation}-snapshot`,
          ),
        )
        .mockResolvedValueOnce(
          jsonResponse(includedAfterWrite ? includedOverview : emptyOverview),
        );
      const firstRender = render(<App />);
      const user = userEvent.setup();

      await user.click(
        screen.getByRole("button", { name: "Parser benchmark" }),
      );
      const dialog = await screen.findByRole("dialog", {
        name: "Parser benchmark",
      });
      const groundTruthSwitch = within(dialog).getByRole("switch", {
        name: /Use current hand as ground truth/,
      });
      await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
      expect(groundTruthSwitch).toHaveAttribute(
        "aria-checked",
        String(initiallyIncluded),
      );
      await user.click(groundTruthSwitch);

      expect(
        await screen.findByText(`Connection lost after benchmark ${operation}`),
      ).toBeInTheDocument();
      await waitFor(() =>
        expect(groundTruthSwitch).toHaveAttribute(
          "aria-checked",
          String(includedAfterWrite),
        ),
      );
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        )[0].benchmark_included,
      ).toBe(includedAfterWrite);
      expect(
        window.sessionStorage.getItem("poker-training-processing-synced"),
      ).toBe("true");

      firstRender.unmount();
      render(<App />);
      await user.click(
        screen.getByRole("button", { name: "Parser benchmark" }),
      );
      const restoredDialog = await screen.findByRole("dialog", {
        name: "Parser benchmark",
      });
      expect(
        within(restoredDialog).getByRole("switch", {
          name: /Use current hand as ground truth/,
        }),
      ).toHaveAttribute("aria-checked", String(includedAfterWrite));
      expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
        "http://localhost:8000/api/benchmarks",
        `http://localhost:8000/api/jobs/${jobId}/benchmark`,
        "http://localhost:8000/api/jobs",
        "http://localhost:8000/api/benchmarks",
      ]);
    },
  );

  it("reconciles a lost benchmark inclusion response that removes an import from processing", async () => {
    const benchmarkJobId = "6".repeat(32);
    const processingImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "include-response-lost.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: false,
      parser_result: null,
    };
    const persistedInclusion: JobRecord = {
      ...processingImport,
      benchmark_included: true,
      updated_at: "2026-07-20T12:10:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([processingImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 0,
          latest_report: null,
          recent_reports: [],
        }),
      )
      .mockRejectedValueOnce(
        new TypeError("Connection lost after including hand"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([], "included-import-snapshot"),
      )
      .mockResolvedValueOnce(jsonResponse(persistedInclusion));
    const firstRender = render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(dialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    await user.click(groundTruthSwitch);

    expect(
      await screen.findByText("Connection lost after including hand"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
        "[]",
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: include-response-lost.png",
      }),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: include-response-lost.png",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}/benchmark`,
      "http://localhost:8000/api/jobs",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
    ]);
  });

  it("reconciles a lost benchmark exclusion response that returns an import to processing", async () => {
    const benchmarkJobId = "5".repeat(32);
    const pristineImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "exclude-response-lost.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
    };
    const processingImport = {
      ...pristineImport,
      benchmark_included: false,
      updated_at: "2026-07-20T12:10:00Z",
    };
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(benchmarkJobId, "exclude-response-lost.png"),
        ),
      )
      .mockResolvedValueOnce(jsonResponse(pristineImport))
      .mockResolvedValueOnce(
        jsonResponse(
          benchmarkOverviewForJob(benchmarkJobId, "exclude-response-lost.png"),
        ),
      )
      .mockRejectedValueOnce(
        new TypeError("Connection lost after excluding hand"),
      )
      .mockResolvedValueOnce(
        processingQueueResponse([processingImport], "excluded-import-snapshot"),
      );
    render(<App />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle exclude-response-lost.png benchmark details",
      }),
    );
    await user.click(
      within(dialog).getByRole("button", { name: "Review hand" }),
    );
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Parser benchmark" }),
      ).not.toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const reopenedDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const groundTruthSwitch = within(reopenedDialog).getByRole("switch", {
      name: /Use current hand as ground truth/,
    });
    await waitFor(() => expect(groundTruthSwitch).toBeEnabled());
    await user.click(groundTruthSwitch);

    expect(
      await screen.findByText("Connection lost after excluding hand"),
    ).toBeInTheDocument();
    const restoredQueueItem = await screen.findByRole("button", {
      name: "Open screenshot 1: exclude-response-lost.png",
    });
    expect(within(restoredQueueItem).getByText("approved")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        JSON.parse(
          String(window.localStorage.getItem("poker-training-processing-v1")),
        ),
      ).toEqual([processingImport]),
    );
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/jobs/${benchmarkJobId}/benchmark`,
      "http://localhost:8000/api/jobs",
    ]);
  });

  it("reconciles a lost re-approval response that makes a benchmark import pristine", async () => {
    const benchmarkJobId = "4".repeat(32);
    const mutatedImport = {
      ...approvedJob(),
      id: benchmarkJobId,
      original_filename: "approval-response-lost.png",
      image_filename: `${benchmarkJobId}.png`,
      benchmark_included: true,
      parser_result: null,
      training_decision: {
        action: "call" as const,
        sizing: null,
        certainty: "medium" as const,
        recorded_at: "2026-07-20T12:05:00Z",
      },
    };
    const persistedApproval: JobRecord = {
      ...mutatedImport,
      approved_state: canonicalState({ pot_size: 20 }),
      training_decision: null,
      updated_at: "2026-07-20T12:10:00Z",
    };
    window.localStorage.setItem(
      "poker-training-processing-v1",
      JSON.stringify([mutatedImport]),
    );
    window.localStorage.setItem("poker-training-processing-total-v1", "1");
    fetchMock()
      .mockRejectedValueOnce(new TypeError("Connection lost after approval"))
      .mockResolvedValueOnce(
        processingQueueResponse([], "reapproved-import-snapshot"),
      )
      .mockResolvedValueOnce(jsonResponse(persistedApproval));
    const firstRender = render(<App />);
    const user = userEvent.setup();

    const potInput = await screen.findByDisplayValue("12.5");
    await user.clear(potInput);
    await user.type(potInput, "20");
    await user.click(screen.getByRole("button", { name: "Approve state" }));

    expect(
      await screen.findByText("Connection lost after approval"),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(window.localStorage.getItem("poker-training-processing-v1")).toBe(
        "[]",
      ),
    );
    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: approval-response-lost.png",
      }),
    ).not.toBeInTheDocument();
    expect(
      window.sessionStorage.getItem("poker-training-processing-synced"),
    ).toBe("true");

    firstRender.unmount();
    render(<App />);

    expect(
      screen.queryByRole("button", {
        name: "Open screenshot 1: approval-response-lost.png",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      `http://localhost:8000/api/jobs/${benchmarkJobId}/approve`,
      "http://localhost:8000/api/jobs",
      `http://localhost:8000/api/jobs/${benchmarkJobId}`,
    ]);
  });

  it("ignores a stale benchmark overview after the parser pipeline changes", async () => {
    const firstOverview = deferredResponse();
    const secondOverview = deferredResponse();
    const fortunaOverview = benchmarkOverviewForJob(
      "a".repeat(32),
      "fortuna.png",
    );
    fortunaOverview.latest_report.id = "benchmark-fortuna";
    fortunaOverview.latest_report.layout_profile = "fortuna";
    fortunaOverview.latest_report.accuracy = 0.5;
    const genericOverview = benchmarkOverviewForJob(
      "b".repeat(32),
      "generic.png",
    );
    genericOverview.latest_report.id = "benchmark-generic";
    genericOverview.latest_report.layout_profile = "generic";
    genericOverview.latest_report.accuracy = 0.9;
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          defaults: {
            parser_provider: "mock",
            parser_layout_profile: "generic",
            recommendation_provider: "mock",
            recommendation_engine: null,
          },
          parser_providers: [
            {
              id: "mock",
              label: "Mock parser",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "ocr_cv",
              label: "Template OCR",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_profiles: [
            {
              id: "generic",
              label: "Generic",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "fortuna",
              label: "Fortuna",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_compatibility: {
            mock: ["generic", "fortuna"],
            ocr_cv: ["generic", "fortuna"],
          },
          recommendation_providers: [
            {
              id: "mock",
              label: "Mock recommendation",
              available: true,
              unavailable_reason: null,
            },
          ],
          recommendation_engines: [],
        }),
      )
      .mockReturnValueOnce(firstOverview.promise)
      .mockReturnValueOnce(secondOverview.promise);
    render(<App />);
    const user = userEvent.setup();

    await user.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    let pipelineDialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Recognition"),
      "ocr_cv",
    );
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Table layout"),
      "fortuna",
    );
    await user.click(
      within(pipelineDialog).getByRole("button", { name: "Done" }),
    );

    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    let benchmarkDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await user.click(
      within(benchmarkDialog).getByRole("button", {
        name: "Close parser benchmark",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    pipelineDialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Table layout"),
      "generic",
    );
    await user.click(
      within(pipelineDialog).getByRole("button", { name: "Done" }),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    benchmarkDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    firstOverview.resolve(jsonResponse(fortunaOverview));
    await waitFor(() =>
      expect(
        within(benchmarkDialog).getByText("Reading benchmark results..."),
      ).toBeInTheDocument(),
    );
    expect(
      within(benchmarkDialog).queryByLabelText("Benchmark summary"),
    ).not.toBeInTheDocument();

    secondOverview.resolve(jsonResponse(genericOverview));
    expect(
      await within(benchmarkDialog).findByLabelText("Benchmark summary"),
    ).toHaveTextContent("90%");
    expect(
      within(benchmarkDialog).getByText("Template OCR · generic"),
    ).toBeInTheDocument();

    await user.click(
      within(benchmarkDialog).getByRole("button", {
        name: "Close parser benchmark",
      }),
    );
    await user.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    pipelineDialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    await user.selectOptions(
      within(pipelineDialog).getByLabelText("Table layout"),
      "fortuna",
    );
    await user.click(
      within(pipelineDialog).getByRole("button", { name: "Done" }),
    );
    fetchMock().mockRejectedValueOnce(
      new TypeError("Fortuna benchmark unavailable"),
    );
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    benchmarkDialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    expect(
      await screen.findByText("Fortuna benchmark unavailable"),
    ).toBeInTheDocument();
    expect(
      within(benchmarkDialog).queryByLabelText("Benchmark summary"),
    ).not.toBeInTheDocument();
    expect(
      within(benchmarkDialog).getByText("No benchmark has been run yet."),
    ).toBeInTheDocument();
    expect(
      within(benchmarkDialog).queryByText("OCR + computer vision · generic"),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/pipeline",
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna",
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=generic",
      "http://localhost:8000/api/benchmarks?parser_provider=ocr_cv&parser_layout_profile=fortuna",
    ]);
  });

  it("loads historical benchmark reports and compares accuracy", async () => {
    const corpusFingerprint = "a".repeat(64);
    const earlierReport = {
      id: "benchmark-earlier",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      corpus_fingerprint: corpusFingerprint,
      created_at: "2026-07-19T12:00:00Z",
      total_cases: 2,
      successful_cases: 2,
      failed_cases: 0,
      correct_fields: 14,
      evaluated_fields: 20,
      accuracy: 0.7,
      field_metrics: [
        { field: "hero_cards", correct: 1, total: 2, accuracy: 0.5 },
        { field: "pot_size", correct: 2, total: 2, accuracy: 1 },
      ],
      cases: [],
    };
    const latestReport = {
      ...earlierReport,
      id: "benchmark-latest",
      created_at: "2026-07-20T12:00:00Z",
      correct_fields: 18,
      accuracy: 0.9,
      field_metrics: [
        { field: "hero_cards", correct: 2, total: 2, accuracy: 1 },
        { field: "pot_size", correct: 1, total: 2, accuracy: 0.5 },
        { field: "board_cards", correct: 2, total: 2, accuracy: 1 },
      ],
    };
    const summaries = [latestReport, earlierReport].map(
      ({
        id,
        parser_provider,
        layout_profile,
        corpus_fingerprint,
        created_at,
        total_cases,
        failed_cases,
        accuracy,
        field_metrics,
      }) => ({
        id,
        parser_provider,
        layout_profile,
        corpus_fingerprint,
        created_at,
        total_cases,
        failed_cases,
        accuracy,
        field_metrics,
      }),
    );
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 2,
          corpus_fingerprint: corpusFingerprint,
          latest_report: latestReport,
          recent_reports: summaries,
          parser_pipelines: [
            {
              parser: {
                id: "ocr_cv",
                label: "OCR + computer vision",
                available: true,
                unavailable_reason: null,
              },
              layout_profile: "fortuna",
              latest_report: summaries[0],
              previous_report: summaries[1],
            },
          ],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(earlierReport));
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    expect(
      await within(dialog).findByLabelText("Benchmark summary"),
    ).toHaveTextContent("90%");
    expect(within(dialog).getByText("+20 pts vs previous")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 90%",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("hero cards change +50 pts"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("pot size change -50 pts"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("board cards change New"),
    ).toBeInTheDocument();

    const reportSelect = within(dialog).getByRole("combobox", {
      name: "Benchmark report",
    });
    expect(reportSelect.parentElement).toHaveClass("select-control");
    expect(reportSelect.closest("label")?.firstElementChild).toHaveClass(
      "benchmark-report-label",
    );
    await user.selectOptions(reportSelect, "benchmark-earlier");

    await waitFor(() =>
      expect(
        within(dialog).getByLabelText("Benchmark summary"),
      ).toHaveTextContent("70%"),
    );
    expect(
      within(dialog).getByText("No comparable earlier run"),
    ).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/change/)).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      "http://localhost:8000/api/benchmarks/benchmark-earlier",
    ]);
  });

  it("uses a pipeline baseline outside the visible benchmark history", async () => {
    const corpusFingerprint = "a".repeat(64);
    const baseOverview = benchmarkOverviewForJob("4".repeat(32), "latest.png");
    const latestReport = {
      ...baseOverview.latest_report,
      corpus_fingerprint: corpusFingerprint,
      correct_fields: 18,
      evaluated_fields: 20,
      accuracy: 0.9,
      field_metrics: [
        { field: "hero_cards", correct: 2, total: 2, accuracy: 1 },
        { field: "pot_size", correct: 1, total: 2, accuracy: 0.5 },
      ],
    };
    const previousReport = {
      id: "benchmark-previous",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      corpus_fingerprint: corpusFingerprint,
      created_at: "2026-07-01T12:00:00Z",
      total_cases: 2,
      failed_cases: 0,
      accuracy: 0.7,
      field_metrics: [
        { field: "hero_cards", correct: 1, total: 2, accuracy: 0.5 },
        { field: "pot_size", correct: 2, total: 2, accuracy: 1 },
      ],
    };
    const unrelatedReports = Array.from({ length: 9 }, (_, index) => ({
      ...previousReport,
      id: `benchmark-unrelated-${index}`,
      corpus_fingerprint: "123456789".charAt(index).repeat(64),
      created_at: `2026-07-${String(index + 2).padStart(2, "0")}T12:00:00Z`,
    }));
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        included_cases: 2,
        included_cases_by_layout: { fortuna: 2 },
        corpus_fingerprint: corpusFingerprint,
        default_layout_profile: "fortuna",
        latest_report: latestReport,
        recent_reports: [latestReport, ...unrelatedReports],
        parser_pipelines: [
          {
            parser: {
              id: "ocr_cv",
              label: "OCR + computer vision",
              available: true,
              unavailable_reason: null,
            },
            layout_profile: "fortuna",
            latest_report: latestReport,
            previous_report: previousReport,
          },
        ],
      }),
    );
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    expect(
      await within(dialog).findByText("+20 pts vs previous"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("hero cards change +50 pts"),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByLabelText("pot size change -50 pts"),
    ).toBeInTheDocument();
    expect(within(dialog).getAllByRole("option")).toHaveLength(10);
  });

  it("filters regressed and recovered benchmark cases and reuses the baseline report", async () => {
    const corpusFingerprint = "b".repeat(64);
    const benchmarkCase = (
      jobId: string,
      originalFilename: string,
      heroCardsMatched: boolean,
      potSizeMatched = true,
    ) => ({
      job_id: jobId,
      original_filename: originalFilename,
      status: "completed",
      correct_fields: Number(heroCardsMatched) + Number(potSizeMatched),
      evaluated_fields: 2,
      accuracy: (Number(heroCardsMatched) + Number(potSizeMatched)) / 2,
      warnings: [],
      error: null,
      comparisons: [
        {
          field: "hero_cards",
          expected: ["Ah", "Kd"],
          detected: heroCardsMatched ? ["Ah", "Kd"] : ["As", "Kh"],
          matched: heroCardsMatched,
          confidence: 0.9,
        },
        {
          field: "pot_size",
          expected: 5,
          detected: potSizeMatched ? 5 : 4,
          matched: potSizeMatched,
          confidence: 0.9,
        },
      ],
    });
    const previousReport = {
      id: "benchmark-cases-previous",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      corpus_fingerprint: corpusFingerprint,
      created_at: "2026-07-19T12:00:00Z",
      total_cases: 4,
      successful_cases: 4,
      failed_cases: 0,
      correct_fields: 6,
      evaluated_fields: 8,
      accuracy: 0.75,
      field_metrics: [
        { field: "hero_cards", correct: 3, total: 4, accuracy: 0.75 },
        { field: "pot_size", correct: 3, total: 4, accuracy: 0.75 },
      ],
      cases: [
        benchmarkCase("1".repeat(32), "regressed.png", true),
        benchmarkCase("2".repeat(32), "recovered.png", false),
        benchmarkCase("3".repeat(32), "unchanged.png", true),
        benchmarkCase("4".repeat(32), "mixed.png", true, false),
      ],
    };
    const latestReport = {
      ...previousReport,
      id: "benchmark-cases-latest",
      created_at: "2026-07-20T12:00:00Z",
      field_metrics: [
        { field: "hero_cards", correct: 2, total: 4, accuracy: 0.5 },
        { field: "pot_size", correct: 4, total: 4, accuracy: 1 },
      ],
      cases: [
        benchmarkCase("1".repeat(32), "regressed.png", false),
        benchmarkCase("2".repeat(32), "recovered.png", true),
        benchmarkCase("3".repeat(32), "unchanged.png", true),
        benchmarkCase("4".repeat(32), "mixed.png", false, true),
      ],
    };
    const summaries = [latestReport, previousReport].map(
      ({
        cases: _cases,
        correct_fields: _correctFields,
        evaluated_fields: _evaluatedFields,
        successful_cases: _successfulCases,
        ...summary
      }) => summary,
    );
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 4,
          included_cases_by_layout: { fortuna: 4 },
          corpus_fingerprint: corpusFingerprint,
          default_layout_profile: "fortuna",
          latest_report: latestReport,
          recent_reports: summaries,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(previousReport));
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    const caseFilter = await within(dialog).findByRole("group", {
      name: "Benchmark case filter",
    });

    expect(
      within(caseFilter).getByRole("button", { name: "All 4" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(caseFilter).getByRole("button", { name: "Regressed 1" }),
    ).toBeInTheDocument();
    expect(
      within(caseFilter).getByRole("button", { name: "Recovered 1" }),
    ).toBeInTheDocument();
    expect(
      within(caseFilter).getByRole("button", { name: "Mixed 1" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Toggle regressed.png benchmark details, regressed",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Toggle recovered.png benchmark details, recovered",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", {
        name: "Toggle mixed.png benchmark details, mixed",
      }),
    ).toBeInTheDocument();

    await user.click(
      within(caseFilter).getByRole("button", { name: "Regressed 1" }),
    );
    expect(within(dialog).getByText("regressed.png")).toBeInTheDocument();
    expect(within(dialog).queryByText("recovered.png")).not.toBeInTheDocument();
    expect(within(dialog).queryByText("unchanged.png")).not.toBeInTheDocument();

    await user.click(
      within(caseFilter).getByRole("button", { name: "Recovered 1" }),
    );
    expect(within(dialog).getByText("recovered.png")).toBeInTheDocument();
    expect(within(dialog).queryByText("regressed.png")).not.toBeInTheDocument();

    await user.click(
      within(caseFilter).getByRole("button", { name: "Mixed 1" }),
    );
    expect(within(dialog).getByText("mixed.png")).toBeInTheDocument();
    expect(within(dialog).queryByText("recovered.png")).not.toBeInTheDocument();

    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle mixed.png benchmark details, mixed",
      }),
    );
    const changes = within(dialog).getByLabelText(
      "mixed.png changes since previous run",
    );
    const heroCardsChange = within(changes).getByLabelText(
      "hero cards regressed",
    );
    expect(within(heroCardsChange).getByText("Ah; Kd")).toBeInTheDocument();
    expect(within(heroCardsChange).getByText("As; Kh")).toBeInTheDocument();
    const potSizeChange = within(changes).getByLabelText("pot size recovered");
    expect(within(potSizeChange).getByText("4")).toBeInTheDocument();
    expect(within(potSizeChange).getByText("5")).toBeInTheDocument();

    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Benchmark report" }),
      previousReport.id,
    );

    expect(
      await within(dialog).findByText("No comparable earlier run"),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("group", {
        name: "Benchmark case filter",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/benchmarks/${previousReport.id}`,
    ]);
  });

  it("shows parser status regressions in benchmark case details", async () => {
    const jobId = "7".repeat(32);
    const corpusFingerprint = "d".repeat(64);
    const completedCase: BenchmarkCaseResult = {
      job_id: jobId,
      original_filename: "parser-failed.png",
      status: "completed",
      correct_fields: 1,
      evaluated_fields: 1,
      accuracy: 1,
      warnings: [],
      error: null,
      comparisons: [
        {
          field: "hero_cards",
          expected: ["Ah", "Kd"],
          detected: ["Ah", "Kd"],
          matched: true,
          confidence: 0.9,
        },
      ],
    };
    const previousReport: BenchmarkReport = {
      id: "benchmark-status-previous",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      corpus_fingerprint: corpusFingerprint,
      created_at: "2026-07-19T12:00:00Z",
      total_cases: 1,
      successful_cases: 1,
      failed_cases: 0,
      correct_fields: 1,
      evaluated_fields: 1,
      accuracy: 1,
      field_metrics: [
        { field: "hero_cards", correct: 1, total: 1, accuracy: 1 },
      ],
      cases: [completedCase],
    };
    const latestReport: BenchmarkReport = {
      ...previousReport,
      id: "benchmark-status-latest",
      created_at: "2026-07-20T12:00:00Z",
      successful_cases: 0,
      failed_cases: 1,
      correct_fields: 0,
      evaluated_fields: 1,
      accuracy: 0,
      field_metrics: [
        { field: "hero_cards", correct: 0, total: 1, accuracy: 0 },
      ],
      cases: [
        {
          ...completedCase,
          status: "error",
          correct_fields: 0,
          evaluated_fields: 1,
          accuracy: 0,
          error: "OCR process exited unexpectedly",
          comparisons: [
            {
              ...completedCase.comparisons[0],
              detected: null,
              matched: false,
              confidence: null,
            },
          ],
        },
      ],
    };
    const summary = (report: BenchmarkReport) => ({
      id: report.id,
      parser_provider: report.parser_provider,
      layout_profile: report.layout_profile,
      corpus_fingerprint: report.corpus_fingerprint,
      created_at: report.created_at,
      total_cases: report.total_cases,
      failed_cases: report.failed_cases,
      accuracy: report.accuracy,
      field_metrics: report.field_metrics,
    });
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { fortuna: 1 },
          corpus_fingerprint: corpusFingerprint,
          default_layout_profile: "fortuna",
          latest_report: latestReport,
          recent_reports: [summary(latestReport), summary(previousReport)],
        }),
      )
      .mockResolvedValueOnce(jsonResponse(previousReport));
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    await within(dialog).findByRole("group", { name: "Benchmark case filter" });
    await user.click(
      within(dialog).getByRole("button", {
        name: "Toggle parser-failed.png benchmark details, regressed",
      }),
    );

    const changes = within(dialog).getByLabelText(
      "parser-failed.png changes since previous run",
    );
    const statusChange = within(changes).getByLabelText(
      "Parser status regressed",
    );
    expect(
      within(statusChange).getByText("Completed at 100%"),
    ).toBeInTheDocument();
    expect(
      within(statusChange).getByText("OCR process exited unexpectedly"),
    ).toBeInTheDocument();
  });

  it("ignores a case comparison that finishes after the benchmark dialog closes", async () => {
    const corpusFingerprint = "c".repeat(64);
    const firstOverview = benchmarkOverviewForJob("5".repeat(32), "first.png");
    const currentReport = {
      ...firstOverview.latest_report,
      id: "benchmark-current-cases",
      corpus_fingerprint: corpusFingerprint,
    };
    const previousReport = {
      ...currentReport,
      id: "benchmark-previous-cases",
      created_at: "2026-07-19T12:00:00Z",
    };
    const summary = (report: typeof currentReport) => ({
      id: report.id,
      parser_provider: report.parser_provider,
      layout_profile: report.layout_profile,
      corpus_fingerprint: report.corpus_fingerprint,
      created_at: report.created_at,
      total_cases: report.total_cases,
      failed_cases: report.failed_cases,
      accuracy: report.accuracy,
      field_metrics: report.field_metrics,
    });
    const pendingComparison = deferredResponse();
    const nextOverview = benchmarkOverviewForJob("6".repeat(32), "second.png");
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          included_cases: 1,
          included_cases_by_layout: { fortuna: 1 },
          corpus_fingerprint: corpusFingerprint,
          default_layout_profile: "fortuna",
          latest_report: currentReport,
          recent_reports: [summary(currentReport), summary(previousReport)],
        }),
      )
      .mockReturnValueOnce(pendingComparison.promise)
      .mockResolvedValueOnce(jsonResponse(nextOverview));
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    let dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });
    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "Comparing cases",
    );

    await user.click(
      within(dialog).getByRole("button", {
        name: "Close parser benchmark",
      }),
    );
    pendingComparison.resolve(jsonResponse(previousReport));
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    dialog = await screen.findByRole("dialog", { name: "Parser benchmark" });

    expect(await within(dialog).findByText("second.png")).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("group", {
        name: "Benchmark case filter",
      }),
    ).not.toBeInTheDocument();
    expect(fetchMock().mock.calls.map(([url]) => url)).toEqual([
      "http://localhost:8000/api/benchmarks",
      `http://localhost:8000/api/benchmarks/${previousReport.id}`,
      "http://localhost:8000/api/benchmarks",
    ]);
  });

  it("requires a rerun for legacy benchmark reports without corpus fingerprints", async () => {
    const legacyReport = {
      id: "benchmark-legacy-latest",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      created_at: "2026-07-20T12:00:00Z",
      total_cases: 1,
      successful_cases: 1,
      failed_cases: 0,
      correct_fields: 1,
      evaluated_fields: 1,
      accuracy: 1,
      field_metrics: [
        { field: "hero_cards", correct: 1, total: 1, accuracy: 1 },
      ],
      cases: [],
    };
    const legacyEarlierSummary = {
      id: "benchmark-legacy-earlier",
      parser_provider: "ocr_cv",
      layout_profile: "fortuna",
      created_at: "2026-07-19T12:00:00Z",
      total_cases: 1,
      failed_cases: 0,
      accuracy: 0.5,
      field_metrics: [
        { field: "hero_cards", correct: 0, total: 1, accuracy: 0 },
      ],
    };
    fetchMock().mockResolvedValueOnce(
      jsonResponse({
        included_cases: 1,
        latest_report: legacyReport,
        recent_reports: [legacyReport, legacyEarlierSummary],
      }),
    );
    render(<App />);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Parser benchmark" }));
    const dialog = await screen.findByRole("dialog", {
      name: "Parser benchmark",
    });

    expect(await within(dialog).findByRole("status")).toHaveTextContent(
      "This run is not verified against the current ground truth",
    );
    expect(
      within(dialog).getByRole("option", {
        name: "Latest · OCR + computer vision · Fortuna · 100% · rerun needed",
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("No comparable earlier run"),
    ).toBeInTheDocument();
  });
});
