import { afterEach, describe, expect, it, vi } from "vitest";

import type { components } from "@poker-hero/openapi-client";
import { ApiResponseError } from "../../../shared/api/core";
import { jsonResponse, resetApiMocks } from "../../../test/api";
import { verifyAdministratorToken } from "./adminOcrTestApi";

type AdminOcrTestSessionResponse = components["schemas"]["AdminOcrTestSession"];

const sessionResponse = {
  enabled: true,
  authorized: true,
} satisfies AdminOcrTestSessionResponse;

afterEach(resetApiMocks);

describe("administrative OCR test API adapter", () => {
  it("presents the candidate token as a bearer credential without caching", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(sessionResponse));
    vi.stubGlobal("fetch", fetchMock);

    await expect(verifyAdministratorToken("secret-token")).resolves.toEqual({
      authorized: true,
      enabled: true,
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/admin/ocr/session",
      expect.objectContaining({
        cache: "no-store",
        credentials: "include",
        headers: { Authorization: "Bearer secret-token" },
      }),
    );
  });

  it("forwards an abort signal for a superseded verification", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(sessionResponse));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await verifyAdministratorToken("secret-token", controller.signal);

    expect(fetchMock.mock.calls[0]?.[1]?.signal).toBe(controller.signal);
  });

  it.each([401, 403])(
    "surfaces HTTP %i as an API response error carrying the status",
    async (status) => {
      const fetchMock = vi.fn().mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "denied" }), {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      );
      vi.stubGlobal("fetch", fetchMock);

      const denial = await verifyAdministratorToken("wrong-token").catch(
        (error: unknown) => error,
      );

      expect(denial).toBeInstanceOf(ApiResponseError);
      expect((denial as ApiResponseError).status).toBe(status);
    },
  );
});
