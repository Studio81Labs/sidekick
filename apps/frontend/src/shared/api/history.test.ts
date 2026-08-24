import { afterEach, describe, expect, it, vi } from "vitest";

import {
  archiveJobs as archiveDomainJobs,
  getHistory as getDomainHistory,
} from "../../domains/history/api/historyApi";
import { jsonResponse, resetApiMocks } from "../../test/api";
import { archiveJobs, getHistory } from "./history";

afterEach(resetApiMocks);

describe("archiveJobs", () => {
  it("preserves the domain adapter export identity", () => {
    expect(archiveJobs).toBe(archiveDomainJobs);
  });

  it("archives queues larger than the backend request limit in bounded batches", async () => {
    const jobIds = Array.from({ length: 205 }, (_, index) => `job-${index}`);
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ total: 100, jobs: [] }))
      .mockResolvedValueOnce(jsonResponse({ total: 200, jobs: [] }))
      .mockResolvedValueOnce(jsonResponse({ total: 205, jobs: [] }));
    vi.stubGlobal("fetch", fetchMock);

    const history = await archiveJobs(jobIds);

    expect(history.total).toBe(205);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(
      fetchMock.mock.calls.map(
        (call) => JSON.parse(String(call[1]?.body)).job_ids,
      ),
    ).toEqual([
      jobIds.slice(0, 100),
      jobIds.slice(100, 200),
      jobIds.slice(200),
    ]);
  });
});

describe("getHistory", () => {
  it("preserves the domain adapter export identity", () => {
    expect(getHistory).toBe(getDomainHistory);
  });

  it("requests an older page from the current loaded offset", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ total: 31, jobs: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getHistory(24);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/history?offset=24",
      { credentials: "include" },
    );
  });

  it("encodes history search terms alongside the page offset", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ total: 2, jobs: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await getHistory(24, "turn bluff");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/history?offset=24&query=turn+bluff",
      { credentials: "include" },
    );
  });
});
