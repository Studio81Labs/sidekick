import type { Street } from "../../../shared/types/poker";
import type {
  TrainingPositionFilter,
  TrainingReviewCertainty,
  TrainingReviewDifference,
} from "../../../shared/types/training";

export type TrainingProgressView = "recent" | "review" | "lessons";

export type TrainingFocus = { street: Street; reason: string };

export type TrainingCertaintyFocus = {
  certainty: TrainingReviewCertainty;
  label: string;
  reason: string;
};

export type TrainingPositionFocus = {
  filter: TrainingPositionFilter;
  label: string;
  reason: string;
};

export type TrainingActionDifferenceFocus = {
  difference: TrainingReviewDifference;
  label: string;
  reason: string;
};
