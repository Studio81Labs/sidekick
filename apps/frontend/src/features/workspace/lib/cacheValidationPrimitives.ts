export const PROCESSING_CACHE_FUTURE_SKEW_MS = 5 * 60 * 1000;

export function isNullableCachedNumber(
  value: unknown,
  minimum: number,
  minimumInclusive = true,
): value is number | null {
  return (
    value === null ||
    (typeof value === "number" &&
      Number.isFinite(value) &&
      (minimumInclusive ? value >= minimum : value > minimum))
  );
}

export function isNullableCachedString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function isSafeProcessingCacheTimestamp(
  value: unknown,
): value is string {
  if (typeof value !== "string") {
    return false;
  }
  const timestamp = Date.parse(value);
  return (
    Number.isFinite(timestamp) &&
    timestamp <= Date.now() + PROCESSING_CACHE_FUTURE_SKEW_MS
  );
}
