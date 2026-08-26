import { describe, expect, it } from "vitest";

import { ApiResponseError, humanReadableMessage, readJson } from "./core";

describe("humanReadableMessage", () => {
  it("turns missing recommendation fields into table language", () => {
    expect(
      humanReadableMessage(
        {
          detail: {
            missing_fields: ["opponent_wager", "opponents_at_current_bet"],
          },
        },
        "Recommendation failed",
      ),
    ).toBe(
      "Complete the required table details before requesting a recommendation: Opponent wager total and opponents at the current wager. Edit the listed fields, then approve the state again.",
    );
  });

  it("turns FastAPI validation arrays into readable field messages", () => {
    expect(
      humanReadableMessage(
        [
          {
            type: "missing",
            loc: ["body", "file"],
            msg: "Field required",
            input: null,
          },
        ],
        "Upload failed",
      ),
    ).toBe("File is required");
  });

  it("decodes structured JSON strings instead of displaying raw payloads", () => {
    expect(
      humanReadableMessage(
        '{"missing_fields":["effective_stack"]}',
        "Recommendation failed",
      ),
    ).toBe(
      "Complete the required table details before requesting a recommendation: Effective stack. Edit the listed fields, then approve the state again.",
    );
  });

  it.each([
    "[low light] board cards unclear",
    "{solver unavailable until ranges load",
  ])("preserves bracket-prefixed plain diagnostics: %s", (message) => {
    expect(humanReadableMessage(message, "Request failed")).toBe(message);
  });
});

describe("readJson", () => {
  it("uses the human-readable message for structured errors", async () => {
    const response = new Response(
      JSON.stringify({ detail: { missing_fields: ["opponent_wager"] } }),
      { status: 422, headers: { "Content-Type": "application/json" } },
    );

    await expect(readJson(response)).rejects.toThrow(
      "Complete the required table details before requesting a recommendation: Opponent wager total. Edit the listed fields, then approve the state again.",
    );
  });

  it("uses the HTTP fallback instead of displaying an HTML error page", async () => {
    const response = new Response(
      "<!doctype html><html><body><h1>Bad gateway</h1></body></html>",
      {
        status: 502,
        statusText: "Bad Gateway",
        headers: { "Content-Type": "text/html; charset=utf-8" },
      },
    );

    await expect(readJson(response)).rejects.toThrow("Bad Gateway");
  });

  it("preserves concise plain-text API errors", async () => {
    const response = new Response("Solver is warming up", {
      status: 503,
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });

    await expect(readJson(response)).rejects.toThrow("Solver is warming up");
  });

  it("uses the HTTP fallback for oversized plain-text errors", async () => {
    const response = new Response("x".repeat(513), {
      status: 503,
      statusText: "Service Unavailable",
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });

    await expect(readJson(response)).rejects.toThrow("Service Unavailable");
  });

  it("preserves Retry-After metadata from rate-limit responses", async () => {
    const response = new Response(
      JSON.stringify({ detail: "Rate limit exceeded for data transfers" }),
      {
        status: 429,
        headers: {
          "Content-Type": "application/json",
          "Retry-After": "7",
          "X-Request-ID": "request-429",
        },
      },
    );

    await expect(readJson(response)).rejects.toEqual(
      expect.objectContaining({
        name: "ApiResponseError",
        requestId: "request-429",
        status: 429,
        retryAfterSeconds: 7,
      } satisfies Partial<ApiResponseError>),
    );
  });

  it("returns undefined for successful no-content responses", async () => {
    await expect(
      readJson<void>(new Response(null, { status: 204 })),
    ).resolves.toBeUndefined();
  });
});
