export type RecommendationAction = "fold" | "check" | "call" | "bet" | "raise";

export interface RecommendationResult {
  action: RecommendationAction;
  sizing: number | null;
  confidence: number;
  explanation: string;
  raw: Record<string, unknown>;
}
