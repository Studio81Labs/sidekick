import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const sentryMocks = vi.hoisted(() => ({
  captureException: vi.fn(),
  init: vi.fn(),
}));

vi.mock("@sentry/react", () => sentryMocks);

import {
  AppErrorBoundary,
  browserMonitoringOptions,
  captureBrowserException,
  configureBrowserErrorMonitoring,
  exceptionOnlyIntegrations,
  scrubBrowserEvent,
} from "./errorMonitoring";

afterEach(async () => {
  await configureBrowserErrorMonitoring({});
  vi.clearAllMocks();
  vi.restoreAllMocks();
});

describe("browser error monitoring", () => {
  it("stays disabled without a DSN", () => {
    expect(browserMonitoringOptions({})).toBeNull();
    expect(browserMonitoringOptions({ VITE_SENTRY_DSN: "  " })).toBeNull();
    expect(
      browserMonitoringOptions({
        VITE_SENTRY_DSN: "http://public@example.ingest.sentry.io/123",
      }),
    ).toBeNull();
    expect(
      browserMonitoringOptions({
        VITE_SENTRY_DSN: "https://example.ingest.sentry.io/123",
      }),
    ).toBeNull();
  });

  it("builds privacy-safe reporting options", () => {
    const options = browserMonitoringOptions({
      VITE_SENTRY_DSN: " https://public@example.ingest.sentry.io/123 ",
      VITE_SENTRY_ENVIRONMENT: " testing ",
      VITE_SENTRY_RELEASE: " abc123 ",
    });

    expect(options).toMatchObject({
      dsn: "https://public@example.ingest.sentry.io/123",
      environment: "testing",
      release: "abc123",
      sampleRate: 1,
      sendClientReports: false,
      tracesSampleRate: 0,
      replaysSessionSampleRate: 0,
      replaysOnErrorSampleRate: 0,
      dataCollection: {
        userInfo: false,
        cookies: false,
        httpHeaders: { request: false, response: false },
        httpBodies: [],
        urlQueryParams: false,
        stackFrameVariables: false,
        frameContextLines: 0,
      },
    });
    expect(options?.beforeBreadcrumb?.({})).toBeNull();
    expect(options?.beforeSend).toBe(scrubBrowserEvent);
    expect(options?.integrations).toBe(exceptionOnlyIntegrations);
    expect(
      exceptionOnlyIntegrations([
        { name: "GlobalHandlers" },
        { name: "BrowserSession" },
      ]),
    ).toEqual([{ name: "GlobalHandlers" }]);
  });

  it("initializes monitoring before reporting startup failures", async () => {
    const configured = await configureBrowserErrorMonitoring({
      VITE_SENTRY_DSN: "https://public@example.ingest.sentry.io/123",
    });
    const error = new Error("startup failed");

    captureBrowserException(error, "application_bootstrap");
    await vi.waitFor(() =>
      expect(sentryMocks.captureException).toHaveBeenCalled(),
    );

    expect(configured).toBe(true);
    expect(sentryMocks.init).toHaveBeenCalledOnce();
    expect(sentryMocks.captureException).toHaveBeenCalledWith(error, {
      tags: { source: "application_bootstrap" },
    });
    expect(sentryMocks.init.mock.invocationCallOrder[0]).toBeLessThan(
      sentryMocks.captureException.mock.invocationCallOrder[0],
    );
  });

  it("removes poker and request data while retaining stack locations", () => {
    const event = {
      type: undefined,
      breadcrumbs: [{ message: "Uploaded AhKd" }],
      contexts: { player: { cards: "AhKd" } },
      culprit: "https://poker.example.com/?player=name",
      extra: { approvedState: { heroCards: ["Ah", "Kd"] } },
      logentry: { message: "private provider output" },
      message: "private provider output",
      request: { url: "https://poker.example.com/?player=name" },
      server_name: "private-browser",
      transaction: "/?player=name",
      user: { email: "player@example.com" },
      future_sdk_field: { cards: ["Ah", "Kd"] },
      exception: {
        values: [
          {
            type: "Error",
            value: "solver failed for AhKd",
            future_exception_field: "private provider output",
            mechanism: { type: "generic", data: { private: true } },
            stacktrace: {
              frames: [
                {
                  filename:
                    "https://poker.example.com/assets/index.js?player=name#fragment",
                  abs_path:
                    "https://poker.example.com/assets/index.js?player=name",
                  lineno: 10,
                  vars: { heroCards: ["Ah", "Kd"] },
                  context_line: "throw new Error(heroCards)",
                },
              ],
            },
          },
        ],
      },
      tags: { component: "frontend", future_private_tag: "player-name" },
    };

    const sanitized = scrubBrowserEvent(event);

    expect(sanitized).not.toHaveProperty("breadcrumbs");
    expect(sanitized).not.toHaveProperty("contexts");
    expect(sanitized).not.toHaveProperty("culprit");
    expect(sanitized).not.toHaveProperty("extra");
    expect(sanitized).not.toHaveProperty("logentry");
    expect(sanitized).not.toHaveProperty("message");
    expect(sanitized).not.toHaveProperty("request");
    expect(sanitized).not.toHaveProperty("server_name");
    expect(sanitized).not.toHaveProperty("transaction");
    expect(sanitized).not.toHaveProperty("user");
    expect(sanitized).not.toHaveProperty("future_sdk_field");
    expect(sanitized.exception?.values?.[0]?.value).toBe(
      "Exception details redacted",
    );
    expect(sanitized.exception?.values?.[0]).not.toHaveProperty(
      "future_exception_field",
    );
    expect(sanitized.exception?.values?.[0]?.mechanism).not.toHaveProperty(
      "data",
    );
    expect(sanitized.exception?.values?.[0]?.stacktrace?.frames?.[0]).toEqual({
      filename: "https://poker.example.com/assets/index.js",
      lineno: 10,
    });
    expect(sanitized.tags).toEqual({ component: "frontend" });
  });

  it("renders a recovery surface when React crashes", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const suppressExpectedError = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", suppressExpectedError);

    function BrokenView(): never {
      throw new Error("render failed");
    }

    try {
      render(
        <AppErrorBoundary>
          <BrokenView />
        </AppErrorBoundary>,
      );
    } finally {
      window.removeEventListener("error", suppressExpectedError);
    }

    expect(screen.getByRole("alert")).toHaveTextContent(
      "The application stopped unexpectedly.",
    );
    expect(screen.getByRole("button", { name: "Reload" })).toBeInTheDocument();
  });
});
