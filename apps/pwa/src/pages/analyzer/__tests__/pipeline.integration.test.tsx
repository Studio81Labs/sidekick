import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  AnalyzerTestApp as App,
  disableAutomation,
  fetchMock,
  jobRecord,
  jsonResponse,
  recommendation,
  switchToUploadMode,
} from "../../../test/analyzerHarness";

describe("Analyzer pipeline", () => {
  it("selects compatible fallbacks when configured pipeline defaults are unavailable", async () => {
    fetchMock()
      .mockResolvedValueOnce(
        jsonResponse({
          defaults: {
            parser_provider: "llm_vision",
            parser_layout_profile: "pokerstars",
            recommendation_provider: "external_solver",
            recommendation_engine: null,
          },
          parser_providers: [
            {
              id: "llm_vision",
              label: "External vision",
              available: false,
              unavailable_reason: "External parser URL is not configured",
            },
            {
              id: "mock",
              label: "Mock parser",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_profiles: [
            {
              id: "pokerstars",
              label: "PokerStars",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "generic",
              label: "Generic",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_compatibility: {
            llm_vision: ["pokerstars", "generic"],
            mock: ["pokerstars", "generic"],
          },
          recommendation_providers: [
            {
              id: "external_solver",
              label: "External solver",
              available: false,
              unavailable_reason: "External solver URL is not configured",
            },
            {
              id: "rule_based",
              label: "Rule-based training",
              available: true,
              unavailable_reason: null,
            },
          ],
          recommendation_engines: [],
        }),
      )
      .mockResolvedValue(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "pipeline-fallback-snapshot",
        }),
      );
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });

    const recognitionSelect = within(dialog).getByLabelText("Recognition");
    expect(recognitionSelect).toHaveValue("mock");
    expect(recognitionSelect.parentElement).toHaveClass("select-control");
    expect(recognitionSelect.closest("label")?.firstElementChild).toHaveClass(
      "pipeline-select-copy",
    );
    expect(within(dialog).getByLabelText("Table layout")).toHaveValue(
      "pokerstars",
    );
    expect(within(dialog).getByLabelText("Recommendation")).toHaveValue(
      "rule_based",
    );
  });

  it("selects installed analysis plugins for new uploads", async () => {
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
            {
              id: "llm_vision",
              label: "External vision",
              available: false,
              unavailable_reason: "External parser URL is not configured",
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
              id: "fortuna_nations",
              label: "Fortuna / Nations",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "pokerstars",
              label: "PokerStars",
              available: true,
              unavailable_reason: null,
            },
          ],
          parser_layout_compatibility: {
            mock: ["generic", "fortuna_nations", "pokerstars"],
            ocr_cv: ["generic", "fortuna_nations"],
            llm_vision: ["generic", "fortuna_nations", "pokerstars"],
          },
          recommendation_providers: [
            {
              id: "mock",
              label: "Mock recommendation",
              available: true,
              unavailable_reason: null,
            },
            {
              id: "local_solver",
              label: "Local solver",
              available: true,
              unavailable_reason: null,
            },
          ],
          recommendation_engines: [
            {
              id: "postflop_solver",
              label: "Postflop CFR",
              available: true,
              unavailable_reason: null,
            },
          ],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          jobRecord({
            id: "a".repeat(32),
            upload_request_id: null,
            parser_provider: "ocr_cv",
            parser_layout_profile: "fortuna_nations",
            recommendation_provider: "local_solver",
            recommendation_engine: "postflop_solver",
          }),
          201,
        ),
      )
      .mockResolvedValue(
        jsonResponse({
          total: 0,
          jobs: [],
          snapshot_version: "pipeline-test-snapshot",
        }),
      );
    const user = userEvent.setup();
    render(<App />);

    await user.click(
      screen.getByRole("button", { name: "Configure analysis plugins" }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: "Analysis plugins",
    });
    expect(
      within(dialog).getByText("External parser URL is not configured", {
        exact: false,
      }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("option", { name: "PokerStars" }),
    ).toBeInTheDocument();
    await user.selectOptions(
      within(dialog).getByLabelText("Recognition"),
      "ocr_cv",
    );
    expect(
      within(dialog).queryByRole("option", { name: "PokerStars" }),
    ).not.toBeInTheDocument();
    await user.selectOptions(
      within(dialog).getByLabelText("Table layout"),
      "fortuna_nations",
    );
    await user.selectOptions(
      within(dialog).getByLabelText("Recommendation"),
      "local_solver",
    );
    expect(within(dialog).getByLabelText("Solver engine")).toHaveValue(
      "postflop_solver",
    );
    await user.click(within(dialog).getByRole("button", { name: "Done" }));

    await disableAutomation(user);
    await switchToUploadMode(user);
    const file = new File(["image"], "poker-table.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Choose screenshots"), file);
    await user.click(screen.getByRole("button", { name: "Upload and parse" }));

    await waitFor(() =>
      expect(
        fetchMock().mock.calls.some(
          ([, request]) =>
            request?.method === "POST" && request.body instanceof FormData,
        ),
      ).toBe(true),
    );
    const uploadRequest = fetchMock().mock.calls.find(
      ([, request]) =>
        request?.method === "POST" && request.body instanceof FormData,
    )?.[1];
    const form = uploadRequest?.body as FormData;
    expect(form.get("parser_provider")).toBe("ocr_cv");
    expect(form.get("parser_layout_profile")).toBe("fortuna_nations");
    expect(form.get("recommendation_provider")).toBe("local_solver");
    expect(form.get("recommendation_engine")).toBe("postflop_solver");
  });
});
