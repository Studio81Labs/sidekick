import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "../../../shared/api/generated/openapi";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { getHistory, toJobHistory } from "./historyApi";

type JobHistoryResponse = components["schemas"]["JobHistory"];

const historyResponse = {
  total: 2,
  jobs: [],
  snapshot_version: "history-snapshot",
} satisfies JobHistoryResponse;

afterEach(resetApiMocks);

describe("history API adapter", () => {
  it("preserves the generated response object and JSON shape", () => {
    expect(toJobHistory(historyResponse)).toBe(historyResponse);
  });

  it("reads the default history page through the shared transport", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(historyResponse));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getHistory()).resolves.toEqual(historyResponse);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/history",
      { credentials: "include" },
    );
  });

  it("encodes pagination, normalized search, and explicit limits", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(historyResponse));
    vi.stubGlobal("fetch", fetchMock);

    await getHistory(24, "  turn bluff  ", 48);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/history?offset=24&query=turn+bluff&limit=48",
      { credentials: "include" },
    );
  });
});
