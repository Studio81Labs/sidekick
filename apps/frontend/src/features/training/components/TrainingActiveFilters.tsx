import { AlertTriangle, ArrowRight, Info, Target, X } from "lucide-react";
import type { ReactNode } from "react";

import "./TrainingActiveFilters.css";
import { ButtonControl } from "../../../shared/components/FormControls";
import type { TrainingDecisionListView } from "./TrainingDecisionList";
import type { RecommendationAction } from "../../../shared/types/recommendations";
import type {
  TrainingCertaintyFilter,
  TrainingPositionFilter,
  TrainingReviewDifference,
  TrainingSolverFilter,
  TrainingStreetFilter,
} from "../../../shared/types/training";

export interface TrainingActiveFiltersProps {
  actionLabel: (action: RecommendationAction) => string;
  certaintyFilter: TrainingCertaintyFilter | null;
  controlsDisabled: boolean;
  onClearCertainty: () => void | Promise<void>;
  onClearPosition: () => void | Promise<void>;
  onClearReviewDifference: () => void | Promise<void>;
  onClearReviewPosition: () => void | Promise<void>;
  onClearSolver: () => void | Promise<void>;
  onClearStreet: () => void | Promise<void>;
  positionFilter: TrainingPositionFilter | null;
  reviewDifference: TrainingReviewDifference | null;
  reviewPosition: TrainingPositionFilter | null;
  solverFilter: TrainingSolverFilter | null;
  streetFilter: TrainingStreetFilter | null;
  view: TrainingDecisionListView;
}

interface ActiveFilterProps {
  ariaLabel: string;
  children: ReactNode;
  className?: string;
  clearLabel: string;
  controlsDisabled: boolean;
  onClear: () => void | Promise<void>;
}

function ActiveFilter({
  ariaLabel,
  children,
  className,
  clearLabel,
  controlsDisabled,
  onClear,
}: ActiveFilterProps) {
  return (
    <div
      className={["training-active-difference", className]
        .filter(Boolean)
        .join(" ")}
      aria-label={ariaLabel}
    >
      <span>{children}</span>
      <ButtonControl
        variant="ghost"
        iconOnly
        onClick={() => void onClear()}
        disabled={controlsDisabled}
        aria-label={clearLabel}
        title={clearLabel}
      >
        <X size={12} aria-hidden="true" />
      </ButtonControl>
    </div>
  );
}

function solverFilterIcon(filter: TrainingSolverFilter) {
  if (filter.kind === "fallback") {
    return <AlertTriangle size={12} aria-hidden="true" />;
  }
  if (filter.kind === "unattributed") {
    return <Info size={12} aria-hidden="true" />;
  }
  return <Target size={12} aria-hidden="true" />;
}

export function TrainingActiveFilters({
  actionLabel,
  certaintyFilter,
  controlsDisabled,
  onClearCertainty,
  onClearPosition,
  onClearReviewDifference,
  onClearReviewPosition,
  onClearSolver,
  onClearStreet,
  positionFilter,
  reviewDifference,
  reviewPosition,
  solverFilter,
  streetFilter,
  view,
}: TrainingActiveFiltersProps) {
  if (view === "review") {
    return (
      <>
        {reviewDifference ? (
          <ActiveFilter
            ariaLabel="Active action-difference filter"
            clearLabel="Clear action-difference filter"
            controlsDisabled={controlsDisabled}
            onClear={onClearReviewDifference}
          >
            {actionLabel(reviewDifference.decision_action)}
            <ArrowRight size={12} aria-hidden="true" />
            {actionLabel(reviewDifference.recommended_action)}
          </ActiveFilter>
        ) : null}
        {reviewPosition ? (
          <ActiveFilter
            ariaLabel="Active review position filter"
            className="training-active-position"
            clearLabel="Clear review position filter"
            controlsDisabled={controlsDisabled}
            onClear={onClearReviewPosition}
          >
            <Target size={12} aria-hidden="true" />
            {reviewPosition.label}
          </ActiveFilter>
        ) : null}
      </>
    );
  }

  if (view !== "recent") {
    return null;
  }

  return (
    <>
      {solverFilter ? (
        <ActiveFilter
          ariaLabel="Active solver filter"
          className="training-active-solver"
          clearLabel="Clear solver filter"
          controlsDisabled={controlsDisabled}
          onClear={onClearSolver}
        >
          {solverFilterIcon(solverFilter)}
          {solverFilter.label}
        </ActiveFilter>
      ) : null}
      {positionFilter ? (
        <ActiveFilter
          ariaLabel="Active position filter"
          className="training-active-position"
          clearLabel="Clear position filter"
          controlsDisabled={controlsDisabled}
          onClear={onClearPosition}
        >
          <Target size={12} aria-hidden="true" />
          {positionFilter.label}
        </ActiveFilter>
      ) : null}
      {streetFilter ? (
        <ActiveFilter
          ariaLabel="Active street filter"
          className="training-active-street"
          clearLabel="Clear street filter"
          controlsDisabled={controlsDisabled}
          onClear={onClearStreet}
        >
          <Target size={12} aria-hidden="true" />
          {streetFilter.label}
        </ActiveFilter>
      ) : null}
      {certaintyFilter ? (
        <ActiveFilter
          ariaLabel="Active certainty filter"
          className="training-active-certainty"
          clearLabel="Clear certainty filter"
          controlsDisabled={controlsDisabled}
          onClear={onClearCertainty}
        >
          <Target size={12} aria-hidden="true" />
          {certaintyFilter.label}
        </ActiveFilter>
      ) : null}
    </>
  );
}
