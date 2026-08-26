import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../test/api";
import { ApiResponseError } from "./core";
import { requestJson } from "./transport";

afterEach(resetApiMocks);

describe("requestJson", () => {
  it("keeps credential and abort behavior for domain adapters", async () => {
    const controller = new AbortController();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      requestJson<{ status: string }>("/api/health", {
        signal: controller.signal,
      }),
    ).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/health", {
      credentials: "include",
      signal: controller.signal,
    });
  });

  it("forwards caller headers and multipart bodies without assigning a content type", async () => {
    const form = new FormData();
    form.append(
      "file",
      new Blob(["table"], { type: "image/png" }),
      "table.png",
    );
    const headers = new Headers({
      "Idempotency-Key": "upload-42",
      "X-Request-ID": "request-42",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ status: "ok" }));
    vi.stubGlobal("fetch", fetchMock);

    await requestJson<{ status: string }>("/api/jobs", {
      body: form,
      headers,
      method: "POST",
    });

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/jobs", {
      body: form,
      credentials: "include",
      headers,
      method: "POST",
    });
    expect(headers.has("Content-Type")).toBe(false);
  });

  it("returns undefined for successful no-content responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(new Response(null, { status: 204 })),
    );

    await expect(
      requestJson<void>("/api/jobs/job-42", { method: "DELETE" }),
    ).resolves.toBeUndefined();
  });

  it("preserves the shared human-readable API errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ missing_fields: ["opponent_wager"] }), {
          headers: { "Content-Type": "application/json" },
          status: 422,
        }),
      ),
    );

    await expect(requestJson("/api/health")).rejects.toEqual(
      expect.objectContaining({
        message:
          "Complete the required table details before requesting a recommendation: Opponent wager total. Edit the listed fields, then approve the state again.",
        status: 422,
      }),
    );
  });

  it("adds human-readable retry guidance and response request metadata", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Rate limit exceeded" }), {
          headers: {
            "Content-Type": "application/json",
            "Retry-After": "7",
            "X-Request-ID": "request-429",
          },
          status: 429,
        }),
      ),
    );

    await expect(requestJson("/api/health")).rejects.toEqual(
      expect.objectContaining({
        message: "Rate limit exceeded Try again in 7 seconds.",
        requestId: "request-429",
        retryAfterSeconds: 7,
        status: 429,
      } satisfies Partial<ApiResponseError>),
    );
  });
});
