import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../../test/api";
import type { components } from "@poker-hero/openapi-client";
import { getSystemInfo, toSystemInfo } from "./systemApi";

afterEach(resetApiMocks);

const response = {
  environment: "local",
  parser_provider: "ocr_cv",
  status: "ok",
} satisfies components["schemas"]["HealthResponse"];

const systemInfo = {
  environment: "local",
  parser_provider: "ocr_cv",
  status: "ok",
};

describe("system API adapter", () => {
  it("maps the generated health response into the stable system domain value", () => {
    expect(toSystemInfo(response)).toEqual(systemInfo);
  });

  it("reads system information through the shared transport", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(response));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getSystemInfo()).resolves.toEqual(systemInfo);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/health", {
      credentials: "include",
      signal: undefined,
    });
  });
});
