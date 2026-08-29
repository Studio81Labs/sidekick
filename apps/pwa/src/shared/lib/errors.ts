import { ApiResponseError, humanReadableMessage } from "../api/core";

export const ERROR_TOAST_ID = "poker-training-error";

export const VALIDATION_TOAST_ID = "poker-training-validation";

export function messageFromError(error: unknown, fallback: string): string {
  return humanReadableMessage(
    error instanceof Error ? error.message : error,
    fallback,
  );
}

export function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

export function mutationFailureMayHavePersistedSideEffect(
  error: unknown,
): boolean {
  return (
    error instanceof TypeError ||
    (error instanceof ApiResponseError &&
      (error.status === 408 || error.status >= 500))
  );
}
