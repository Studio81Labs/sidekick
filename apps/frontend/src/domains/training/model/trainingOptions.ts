import type { Street } from "../../../shared/types/poker";
import type { RecommendationAction } from "../../../shared/types/recommendations";
import type { TrainingCertainty } from "../../../shared/types/training";

export const TRAINING_ACTIONS: readonly RecommendationAction[] = [
  "fold",
  "check",
  "call",
  "bet",
  "raise",
];

export const TRAINING_CERTAINTIES: readonly TrainingCertainty[] = [
  "low",
  "medium",
  "high",
];

export const TRAINING_ACTION_OPTIONS = TRAINING_ACTIONS.map((value) => ({
  value,
  label: value,
}));

export const TRAINING_CERTAINTY_OPTIONS = TRAINING_CERTAINTIES.map((value) => ({
  value,
  label: value,
}));

export const MIN_SUPPORTED_FREQUENCY = 0.05;

export const SIZING_MATCH_TOLERANCE = 0.01;

export const MAX_TRAINING_REVIEW_NOTE_LENGTH = 1000;

export const TRAINING_STREET_ORDER: readonly Street[] = [
  "preflop",
  "flop",
  "turn",
  "river",
];

export const TRAINING_CERTAINTY_FOCUS_ORDER: readonly TrainingCertainty[] = [
  "high",
  "medium",
  "low",
];

export const TRAINING_POSITION_FOCUS_ORDER: readonly string[] = [
  "UTG",
  "HJ",
  "CO",
  "BTN",
  "SB",
  "BB",
  "IP",
  "OOP",
];
