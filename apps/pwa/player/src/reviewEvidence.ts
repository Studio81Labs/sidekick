import type { ImportedHandSourceEvidence, PlayerHandDetail } from "./playerApi";

/**
 * The server treats a source locator as this exact typed tuple. Keep browser
 * option identity just as exact: delimiter joining would conflate valid marker
 * or source identifiers that contain the delimiter.
 */
export function sourceEvidenceKey(
  evidence: ImportedHandSourceEvidence,
): string {
  return JSON.stringify([
    evidence.raw_source_id,
    evidence.line_start,
    evidence.line_end,
    evidence.marker,
  ]);
}

export function uniqueSourceEvidence(
  evidence: readonly ImportedHandSourceEvidence[],
): ImportedHandSourceEvidence[] {
  const seen = new Set<string>();
  return evidence.filter((item) => {
    const key = sourceEvidenceKey(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Only the selected immutable detection may offer parser-linked evidence to a
 * review draft. This intentionally excludes any locator already copied into
 * the editable draft.
 */
export function selectedDetectionEvidence(
  detection: PlayerHandDetail["detections"][number],
): ImportedHandSourceEvidence[] {
  return uniqueSourceEvidence([
    ...Object.values(detection.field_evidence).flatMap(
      (field) => field.evidence,
    ),
    ...detection.state.streets.flatMap((street) =>
      street.actions.flatMap((action) => [
        ...action.evidence,
        ...action.origin.evidence,
      ]),
    ),
    ...(detection.state.results?.showdown.flatMap((entry) => entry.evidence) ??
      []),
    ...(detection.state.results?.awards.flatMap((award) => award.evidence) ??
      []),
  ]);
}
