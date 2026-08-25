import {
  benchmarkPercent,
  formatEvLossBb,
} from "../../../shared/lib/metricPresentation";
import type { TrainingProgress } from "../../../shared/types/training";
import {
  TRAINING_ACTIONS,
  TRAINING_CERTAINTY_FOCUS_ORDER,
  TRAINING_POSITION_FOCUS_ORDER,
  TRAINING_STREET_ORDER,
} from "../../../domains/training/model/trainingOptions";
import {
  trainingCertaintyLabel,
  trainingDecisionLabel,
} from "../../../domains/training/model/trainingDecision";
import type {
  TrainingActionDifferenceFocus,
  TrainingCertaintyFocus,
  TrainingFocus,
  TrainingPositionFocus,
} from "./trainingPresentationTypes";

export function suggestedTrainingFocus(
  progress: TrainingProgress,
): TrainingFocus | null {
  const counts = progress.review_street_counts ?? {};
  const candidates = progress.street_summaries.filter(
    (summary) => (counts[summary.street] ?? 0) > 0,
  );
  if (candidates.length === 0) {
    return null;
  }

  const evCandidates = candidates.filter(
    (summary) =>
      summary.ev_compared_hands > 0 && summary.average_ev_loss_bb !== null,
  );
  const usesEvLoss = evCandidates.length > 0;
  const ranked = [...(usesEvLoss ? evCandidates : candidates)].sort(
    (left, right) => {
      if (usesEvLoss) {
        const evDifference =
          (right.average_ev_loss_bb ?? 0) - (left.average_ev_loss_bb ?? 0);
        if (evDifference !== 0) {
          return evDifference;
        }
      } else {
        const accuracyDifference = left.action_accuracy - right.action_accuracy;
        if (accuracyDifference !== 0) {
          return accuracyDifference;
        }
      }

      const pendingDifference =
        (counts[right.street] ?? 0) - (counts[left.street] ?? 0);
      if (pendingDifference !== 0) {
        return pendingDifference;
      }
      return (
        TRAINING_STREET_ORDER.indexOf(left.street) -
        TRAINING_STREET_ORDER.indexOf(right.street)
      );
    },
  );
  const focus = ranked[0];
  if (!focus) {
    return null;
  }
  return {
    street: focus.street,
    reason:
      usesEvLoss && focus.average_ev_loss_bb !== null
        ? `Highest average EV loss: ${formatEvLossBb(focus.average_ev_loss_bb)}`
        : `Lowest action match: ${benchmarkPercent(focus.action_accuracy)}`,
  };
}

export function suggestedCertaintyFocus(
  progress: TrainingProgress,
): TrainingCertaintyFocus | null {
  const candidates = (progress.certainty_summaries ?? []).filter(
    (summary) => (summary.needs_review_hands ?? 0) > 0,
  );
  if (candidates.length === 0) {
    const unratedPending = progress.unrated_needs_review_hands ?? 0;
    return unratedPending > 0
      ? {
          certainty: "unrated",
          label: "Unrated",
          reason: `${unratedPending} legacy ${unratedPending === 1 ? "hand needs" : "hands need"} review`,
        }
      : null;
  }

  const evCandidates = candidates.filter(
    (summary) =>
      summary.ev_compared_hands > 0 && summary.average_ev_loss_bb !== null,
  );
  const usesEvLoss = evCandidates.length > 0;
  const ranked = [...(usesEvLoss ? evCandidates : candidates)].sort(
    (left, right) => {
      if (usesEvLoss) {
        const evDifference =
          (right.average_ev_loss_bb ?? 0) - (left.average_ev_loss_bb ?? 0);
        if (evDifference !== 0) {
          return evDifference;
        }
      } else {
        const accuracyDifference = left.action_accuracy - right.action_accuracy;
        if (accuracyDifference !== 0) {
          return accuracyDifference;
        }
      }

      const pendingDifference =
        (right.needs_review_hands ?? 0) - (left.needs_review_hands ?? 0);
      if (pendingDifference !== 0) {
        return pendingDifference;
      }
      return (
        TRAINING_CERTAINTY_FOCUS_ORDER.indexOf(left.certainty) -
        TRAINING_CERTAINTY_FOCUS_ORDER.indexOf(right.certainty)
      );
    },
  );
  const focus = ranked[0];
  if (!focus) {
    return null;
  }
  return {
    certainty: focus.certainty,
    label: trainingCertaintyLabel(focus.certainty),
    reason:
      usesEvLoss && focus.average_ev_loss_bb !== null
        ? `Highest average EV loss: ${formatEvLossBb(focus.average_ev_loss_bb)}`
        : `Lowest action match: ${benchmarkPercent(focus.action_accuracy)}`,
  };
}

export function suggestedPositionFocus(
  progress: TrainingProgress,
): TrainingPositionFocus | null {
  const candidates = (progress.position_summaries ?? []).filter(
    (summary) => (summary.needs_review_hands ?? 0) > 0,
  );
  if (candidates.length === 0) {
    const unpositionedPending = progress.unpositioned_needs_review_hands ?? 0;
    return unpositionedPending > 0
      ? {
          filter: {
            kind: "unpositioned",
            label: "Unpositioned",
          },
          label: "Unpositioned",
          reason: `${unpositionedPending} unpositioned ${unpositionedPending === 1 ? "hand needs" : "hands need"} review`,
        }
      : null;
  }

  const evCandidates = candidates.filter(
    (summary) =>
      summary.ev_compared_hands > 0 && summary.average_ev_loss_bb !== null,
  );
  const usesEvLoss = evCandidates.length > 0;
  const ranked = [...(usesEvLoss ? evCandidates : candidates)].sort(
    (left, right) => {
      if (usesEvLoss) {
        const evDifference =
          (right.average_ev_loss_bb ?? 0) - (left.average_ev_loss_bb ?? 0);
        if (evDifference !== 0) {
          return evDifference;
        }
      } else {
        const accuracyDifference = left.action_accuracy - right.action_accuracy;
        if (accuracyDifference !== 0) {
          return accuracyDifference;
        }
      }

      const pendingDifference =
        (right.needs_review_hands ?? 0) - (left.needs_review_hands ?? 0);
      if (pendingDifference !== 0) {
        return pendingDifference;
      }
      const leftOrder = TRAINING_POSITION_FOCUS_ORDER.indexOf(left.position);
      const rightOrder = TRAINING_POSITION_FOCUS_ORDER.indexOf(right.position);
      return (
        (leftOrder < 0 ? TRAINING_POSITION_FOCUS_ORDER.length : leftOrder) -
          (rightOrder < 0
            ? TRAINING_POSITION_FOCUS_ORDER.length
            : rightOrder) || left.position.localeCompare(right.position)
      );
    },
  );
  const focus = ranked[0];
  if (!focus) {
    return null;
  }
  return {
    filter: {
      kind: "position",
      position: focus.position,
      label: focus.position,
    },
    label: focus.position,
    reason:
      usesEvLoss && focus.average_ev_loss_bb !== null
        ? `Highest average EV loss: ${formatEvLossBb(focus.average_ev_loss_bb)}`
        : `Lowest action match: ${benchmarkPercent(focus.action_accuracy)}`,
  };
}

export function suggestedActionDifferenceFocus(
  progress: TrainingProgress,
): TrainingActionDifferenceFocus | null {
  const candidates = (progress.action_differences ?? []).filter(
    (difference) => difference.needs_review_hands > 0,
  );
  if (candidates.length === 0) {
    return null;
  }

  const evCandidates = candidates.filter(
    (difference) =>
      difference.ev_compared_hands > 0 &&
      difference.average_ev_loss_bb !== null,
  );
  const usesEvLoss = evCandidates.length > 0;
  const ranked = [...(usesEvLoss ? evCandidates : candidates)].sort(
    (left, right) => {
      if (usesEvLoss) {
        const evDifference =
          (right.average_ev_loss_bb ?? 0) - (left.average_ev_loss_bb ?? 0);
        if (evDifference !== 0) {
          return evDifference;
        }
      }

      const pendingDifference =
        right.needs_review_hands - left.needs_review_hands;
      if (pendingDifference !== 0) {
        return pendingDifference;
      }
      const handDifference = right.hands - left.hands;
      if (handDifference !== 0) {
        return handDifference;
      }
      const decisionDifference =
        TRAINING_ACTIONS.indexOf(left.decision_action) -
        TRAINING_ACTIONS.indexOf(right.decision_action);
      return decisionDifference !== 0
        ? decisionDifference
        : TRAINING_ACTIONS.indexOf(left.recommended_action) -
            TRAINING_ACTIONS.indexOf(right.recommended_action);
    },
  );
  const focus = ranked[0];
  if (!focus) {
    return null;
  }
  return {
    difference: {
      decision_action: focus.decision_action,
      recommended_action: focus.recommended_action,
    },
    label: `${trainingDecisionLabel(focus.decision_action, null)} to ${trainingDecisionLabel(focus.recommended_action, null)}`,
    reason:
      usesEvLoss && focus.average_ev_loss_bb !== null
        ? `Highest average EV loss: ${formatEvLossBb(focus.average_ev_loss_bb)}`
        : `Largest backlog: ${focus.needs_review_hands} ${focus.needs_review_hands === 1 ? "hand needs" : "hands need"} review`,
  };
}
