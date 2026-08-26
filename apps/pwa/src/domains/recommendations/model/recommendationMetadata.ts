export function metadataRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function metadataNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function metadataRatio(value: unknown): number | null {
  const number = metadataNumber(value);
  return number !== null && number >= 0 && number <= 1 ? number : null;
}

export function metadataString(value: unknown, maxLength = 320): string | null {
  if (typeof value !== "string" || value.trim() === "") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length <= maxLength
    ? normalized
    : `${normalized.slice(0, maxLength - 3)}...`;
}

export function metadataExactString(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized === "" ? null : normalized;
}

export function metadataLabel(value: unknown): string | null {
  const normalized = metadataString(value, 40)
    ?.replace(/_/g, " ")
    .toLowerCase();
  if (!normalized) {
    return null;
  }
  if (["ip", "oop", "utg"].includes(normalized)) {
    return normalized.toUpperCase();
  }
  return `${normalized.slice(0, 1).toUpperCase()}${normalized.slice(1)}`;
}

export function metadataStringList(
  value: unknown,
  maxItems = 3,
  maxLength = 80,
): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.slice(0, maxItems).flatMap((item) => {
    const normalized = metadataString(item, maxLength);
    return normalized ? [normalized] : [];
  });
}
