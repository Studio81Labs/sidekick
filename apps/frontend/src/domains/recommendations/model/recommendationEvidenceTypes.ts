export interface RecommendationEvidenceMetric {
  label: string;
  value: number;
  unit: "percent" | "bb";
}

export interface RecommendationEvidenceDetail {
  label: string;
  value: string;
}

export interface RecommendationEvidenceCandidate {
  action: string;
  sizing: number | null;
  ev: number | null;
  frequency: number | null;
  foldEquity: number | null;
  perOpponentFoldEquity: number | null;
}

export interface RecommendationEvidence {
  engine: string | null;
  fallbackFrom: string | null;
  fallbackReason: string | null;
  routed: boolean;
  metrics: RecommendationEvidenceMetric[];
  details: RecommendationEvidenceDetail[];
  ranges: RecommendationEvidenceDetail[];
  candidates: RecommendationEvidenceCandidate[];
}

export interface ParserRoutingEvidence {
  provider: string;
  selectedProvider: string;
  layoutProfile: string;
  fallbackFrom: string | null;
  fallbackReason: string | null;
}
