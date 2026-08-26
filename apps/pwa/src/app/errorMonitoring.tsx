import { RotateCw } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";

import { ButtonControl } from "../shared/components/FormControls";

type SentryModule = typeof import("@sentry/react");
type BrowserMonitoringOptions = Parameters<SentryModule["init"]>[0];

interface BrowserMonitoringEnvironment {
  VITE_SENTRY_DSN?: string;
  VITE_SENTRY_ENVIRONMENT?: string;
  VITE_SENTRY_RELEASE?: string;
}

let sentryModule: Promise<SentryModule | null> | null = null;
const allowedEventFields = new Set([
  "dist",
  "environment",
  "event_id",
  "exception",
  "level",
  "platform",
  "release",
  "tags",
  "timestamp",
]);
const allowedTags = new Set(["component", "source"]);
const allowedExceptionFields = new Set([
  "mechanism",
  "stacktrace",
  "type",
  "value",
]);
const allowedMechanismFields = new Set(["handled", "synthetic", "type"]);
const allowedStacktraceFields = new Set(["frames", "frames_omitted"]);
const allowedFrameFields = new Set([
  "colno",
  "filename",
  "function",
  "in_app",
  "instruction_addr",
  "lineno",
  "module",
  "symbol_addr",
]);

export function browserMonitoringOptions(
  environment: BrowserMonitoringEnvironment,
): BrowserMonitoringOptions | null {
  const dsn = environment.VITE_SENTRY_DSN?.trim();
  if (!dsn || !isCompleteHttpsDsn(dsn)) {
    return null;
  }
  return {
    dsn,
    environment: environment.VITE_SENTRY_ENVIRONMENT?.trim() || "production",
    release: environment.VITE_SENTRY_RELEASE?.trim() || undefined,
    sampleRate: 1,
    sendClientReports: false,
    integrations: exceptionOnlyIntegrations,
    tracesSampleRate: 0,
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate: 0,
    dataCollection: {
      userInfo: false,
      cookies: false,
      httpHeaders: {
        request: false,
        response: false,
      },
      httpBodies: [],
      urlQueryParams: false,
      graphQL: {
        document: false,
        variables: false,
      },
      genAI: {
        inputs: false,
        outputs: false,
      },
      databaseQueryData: false,
      stackFrameVariables: false,
      frameContextLines: 0,
    },
    beforeBreadcrumb: () => null,
    beforeSend: scrubBrowserEvent,
    initialScope: {
      tags: {
        component: "frontend",
      },
    },
  };
}

export function exceptionOnlyIntegrations<T extends { name: string }>(
  integrations: T[],
): T[] {
  return integrations.filter(({ name }) => name !== "BrowserSession");
}

function isCompleteHttpsDsn(value: string): boolean {
  try {
    const dsn = new URL(value);
    return (
      dsn.protocol === "https:" &&
      dsn.username.length > 0 &&
      dsn.pathname.replace(/\//g, "").length > 0 &&
      dsn.search === "" &&
      dsn.hash === ""
    );
  } catch {
    return false;
  }
}

export async function configureBrowserErrorMonitoring(
  environment: BrowserMonitoringEnvironment = import.meta
    .env as BrowserMonitoringEnvironment,
): Promise<boolean> {
  const options = browserMonitoringOptions(environment);
  if (options === null) {
    sentryModule = null;
    return false;
  }
  sentryModule = import("@sentry/react")
    .then((sentry) => {
      sentry.init(options);
      return sentry;
    })
    .catch(() => null);
  return (await sentryModule) !== null;
}

export function captureBrowserException(error: unknown, source: string) {
  const capture = sentryModule?.then((sentry) => {
    sentry?.captureException(error, { tags: { source } });
  });
  void capture?.catch(() => undefined);
}

export function scrubBrowserEvent(
  event: Parameters<NonNullable<BrowserMonitoringOptions["beforeSend"]>>[0],
) {
  retainFields(event, allowedEventFields);
  if (event.tags) {
    retainFields(event.tags, allowedTags);
  }

  for (const exception of event.exception?.values ?? []) {
    retainFields(exception, allowedExceptionFields);
    exception.value = "Exception details redacted";
    if (exception.mechanism) {
      retainFields(exception.mechanism, allowedMechanismFields);
    }
    if (exception.stacktrace) {
      retainFields(exception.stacktrace, allowedStacktraceFields);
    }
    for (const frame of exception.stacktrace?.frames ?? []) {
      retainFields(frame, allowedFrameFields);
      if (frame.filename) {
        frame.filename = stackFilename(frame.filename);
      }
    }
  }
  return event;
}

function retainFields(value: object, allowed: Set<string>) {
  const mutable = value as Record<string, unknown>;
  for (const key of Object.keys(mutable)) {
    if (!allowed.has(key)) {
      delete mutable[key];
    }
  }
}

function stackFilename(value: string): string {
  try {
    const url = new URL(value);
    return `${url.origin}${url.pathname}`;
  } catch {
    return value.split(/[?#]/, 1)[0];
  }
}

export function FatalError() {
  return (
    <main className="fatal-error" role="alert">
      <div className="brand-mark" aria-hidden="true">
        A
      </div>
      <h1>Poker Training Analyzer</h1>
      <p>The application stopped unexpectedly.</p>
      <ButtonControl onClick={() => window.location.reload()}>
        <RotateCw size={16} aria-hidden="true" />
        Reload
      </ButtonControl>
    </main>
  );
}

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  failed: boolean;
}

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(error: Error, _errorInfo: ErrorInfo) {
    captureBrowserException(error, "react_error_boundary");
  }

  render() {
    return this.state.failed ? <FatalError /> : this.props.children;
  }
}
