export interface ParserRoutingEvidence {
  provider: string;
  selectedProvider: string;
  layoutProfile: string;
  fallbackFrom: string | null;
  fallbackReason: string | null;
}

function routingRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function routingString(value: unknown, maxLength: number): string | null {
  if (typeof value !== "string" || value.trim() === "") {
    return null;
  }
  const normalized = value.trim();
  return normalized.length <= maxLength
    ? normalized
    : `${normalized.slice(0, maxLength - 3)}...`;
}

export function parserRoutingEvidence(
  value: unknown,
): ParserRoutingEvidence | null {
  const routing = routingRecord(value);
  const provider = routingString(routing?.provider, 64);
  const selectedProvider = routingString(routing?.selected_provider, 64);
  const layoutProfile = routingString(routing?.layout_profile, 64);
  if (!routing || !provider || !selectedProvider || !layoutProfile) {
    return null;
  }
  const fallbackFrom = routingString(routing.fallback_from, 64);
  const fallbackReason = routingString(routing.fallback_reason, 320);
  return {
    provider,
    selectedProvider,
    layoutProfile,
    fallbackFrom: fallbackFrom && fallbackReason ? fallbackFrom : null,
    fallbackReason: fallbackFrom && fallbackReason ? fallbackReason : null,
  };
}

export function parserRoutingFromRaw(
  value: unknown,
): ParserRoutingEvidence | null {
  return parserRoutingEvidence(routingRecord(value)?.parser_routing);
}
