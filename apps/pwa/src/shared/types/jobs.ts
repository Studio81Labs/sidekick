import type { CanonicalState, ParserResult } from "./poker";
import type { RecommendationResult } from "./recommendations";
import type { TrainingDecision } from "./training";

export interface JobRecord {
  id: string;
  status: "created" | "parsed" | "approved" | "recommended" | "error";
  upload_request_id?: string | null;
  original_filename: string;
  title?: string | null;
  notes?: string | null;
  tags?: string[];
  image_filename: string;
  parser_provider: string;
  parser_layout_profile?: string | null;
  recommendation_provider: string;
  recommendation_engine?: string | null;
  parser_result: ParserResult | null;
  parser_auto_approval_eligible?: boolean | null;
  approved_state: CanonicalState | null;
  training_decision: TrainingDecision | null;
  recommendation: RecommendationResult | null;
  recommendation_pending: boolean;
  recommendation_request_id?: string | null;
  training_reviewed_at: string | null;
  training_review_note: string | null;
  benchmark_included: boolean;
  archived_at: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobHistory {
  total: number;
  jobs: JobRecord[];
  snapshot_version?: string;
}

export interface JobQueue {
  total: number;
  jobs: JobRecord[];
  snapshot_version?: string;
}
