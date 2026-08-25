import type { BenchmarkFieldComparison } from "../../../shared/types/benchmarks";
import { PREFLOP_POSITIONS } from "../../hand-review/lib/preflopPosition";

export function benchmarkComparisonValue(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "Not detected";
  }
  if (Array.isArray(value)) {
    return value.length > 0
      ? value
          .map((item) => benchmarkActionValue(item) ?? String(item))
          .join("; ")
      : "None";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

export function benchmarkActionValue(value: unknown): string | null {
  return (
    benchmarkPreflopActionValue(value) ?? benchmarkPostflopActionValue(value)
  );
}

export function benchmarkPreflopActionValue(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const item = value as Record<string, unknown>;
  if (
    !PREFLOP_POSITIONS.some((position) => position.value === item.actor) ||
    (item.action !== "call" && item.action !== "raise") ||
    typeof item.amount !== "number" ||
    !Number.isFinite(item.amount)
  ) {
    return null;
  }
  const actor = PREFLOP_POSITIONS.find(
    (position) => position.value === item.actor,
  )?.label;
  const action = item.action === "raise" ? "raise to" : "call";
  return `${actor} ${action} ${item.amount} BB`;
}

export function benchmarkPostflopActionValue(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  const item = value as Record<string, unknown>;
  if (
    (item.actor !== "oop" && item.actor !== "ip") ||
    (item.action !== "check" &&
      item.action !== "bet" &&
      item.action !== "raise")
  ) {
    return null;
  }
  const actor = item.actor.toUpperCase();
  if (item.action === "check") {
    return `${actor} check`;
  }
  if (typeof item.amount !== "number" || !Number.isFinite(item.amount)) {
    return null;
  }
  const action = item.action === "raise" ? "raise to" : "bet";
  return `${actor} ${action} ${item.amount} BB`;
}

export function benchmarkMismatchLabel(
  comparisons: BenchmarkFieldComparison[],
): string {
  const mismatchCount = comparisons.filter(
    (comparison) => !comparison.matched,
  ).length;
  if (mismatchCount === 0) {
    return "All labeled fields matched";
  }
  return `${mismatchCount} ${mismatchCount === 1 ? "mismatch" : "mismatches"}`;
}
