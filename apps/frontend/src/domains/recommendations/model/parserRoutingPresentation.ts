import type { ParserRoutingEvidence } from "./recommendationEvidenceTypes";
import { metadataRecord, metadataString } from "./recommendationMetadata";

export function parserRoutingEvidence(
  value: unknown,
): ParserRoutingEvidence | null {
  const routing = metadataRecord(value);
  const provider = metadataString(routing?.provider, 64);
  const selectedProvider = metadataString(routing?.selected_provider, 64);
  const layoutProfile = metadataString(routing?.layout_profile, 64);
  if (!routing || !provider || !selectedProvider || !layoutProfile) {
    return null;
  }
  const fallbackFrom = metadataString(routing.fallback_from, 64);
  const fallbackReason = metadataString(routing.fallback_reason, 320);
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
  return parserRoutingEvidence(metadataRecord(value)?.parser_routing);
}
