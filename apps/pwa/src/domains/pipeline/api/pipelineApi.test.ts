import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../../test/api";
import { getPipelineCapabilities, toPipelineCapabilities } from "./pipelineApi";

afterEach(resetApiMocks);

const response = {
  defaults: {
    parser_layout_profile: "fortuna_nations",
    parser_provider: "ocr_cv",
    recommendation_engine: "postflop_solver",
    recommendation_provider: "local_solver",
  },
  parser_layout_compatibility: { ocr_cv: ["fortuna_nations"] },
  parser_layout_profiles: [],
  parser_providers: [],
  recommendation_engines: [],
  recommendation_providers: [],
};

describe("pipeline API adapter", () => {
  it("normalizes optional generated fields for the stable domain value", () => {
    expect(toPipelineCapabilities(response)).toEqual(response);
  });

  it("reads capabilities through the shared transport", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(response));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getPipelineCapabilities()).resolves.toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/pipeline",
      {
        credentials: "include",
        signal: undefined,
      },
    );
  });
});
