import { Download, Eye } from "lucide-react";
import "./TrainingProgressDialog.css";

import { trainingLessonsExportUrl } from "../../../domains/training/api/trainingApi";
import { providerLabel } from "../../pipeline/lib/pipelineSelection";
import {
  trainingCertaintyLabel,
  trainingDecisionLabel,
  type TrainingActionDifferenceFocus,
  type TrainingCertaintyFocus,
  type TrainingFocus,
  type TrainingPositionFocus,
  type TrainingProgressView,
} from "../lib/trainingPresentation";
import { DialogFooter } from "../../../shared/components/DialogFooter";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import {
  ButtonControl,
  DownloadLinkControl,
} from "../../../shared/components/FormControls";
import { StateMessage } from "../../../shared/components/StateMessage";
import { TrainingActionDifferences } from "./TrainingActionDifferences";
import { TrainingActiveFilters } from "./TrainingActiveFilters";
import { TrainingCertaintyCalibration } from "./TrainingCertaintyCalibration";
import { TrainingDecisionList } from "./TrainingDecisionList";
import { TrainingPositionSummary } from "./TrainingPositionSummary";
import { TrainingProgressControls } from "./TrainingProgressControls";
import { TrainingProgressOverview } from "./TrainingProgressOverview";
import { TrainingSolverCoverage } from "./TrainingSolverCoverage";
import { TrainingStreetSummary } from "./TrainingStreetSummary";
import type { Street } from "../../../shared/types/poker";
import type {
  TrainingCertaintyFilter,
  TrainingPositionFilter,
  TrainingProgress,
  TrainingRecentHand,
  TrainingReviewCertainty,
  TrainingReviewCertaintyFilter,
  TrainingReviewDifference,
  TrainingReviewOrder,
  TrainingReviewStreet,
  TrainingSolverFilter,
  TrainingStreetFilter,
} from "../../../shared/types/training";

export interface TrainingProgressDialogProps {
  actionDifferenceFocus: TrainingActionDifferenceFocus | null;
  busy: boolean;
  certaintyFilter: TrainingCertaintyFilter | null;
  certaintyFocus: TrainingCertaintyFocus | null;
  lessonOrder: TrainingReviewOrder;
  lessonQuery: string;
  lessonSearch: string;
  lessonStreet: TrainingReviewStreet;
  lessonsExportDisabled: boolean;
  nextReviewHand: TrainingRecentHand | null;
  onClose: () => void;
  onFocusActionDifference: (
    difference: TrainingReviewDifference,
  ) => void | Promise<void>;
  onFocusCertainty: (
    certainty: TrainingReviewCertainty,
  ) => void | Promise<void>;
  onFocusPosition: (position: TrainingPositionFilter) => void | Promise<void>;
  onFocusStreet: (street: Street) => void | Promise<void>;
  onLessonFiltersChange: (
    street: TrainingReviewStreet,
    search: string,
    order?: TrainingReviewOrder,
  ) => void | Promise<void>;
  onLessonSearchChange: (search: string) => void;
  onOpenHand: (
    jobId: string,
    continueReviewQueue?: boolean,
  ) => void | Promise<void>;
  onReopenHand: (jobId: string) => void | Promise<void>;
  onReviewQueueChange: (
    order: TrainingReviewOrder,
    street: TrainingReviewStreet,
    difference?: TrainingReviewDifference | null,
    certainty?: TrainingReviewCertaintyFilter,
    position?: TrainingPositionFilter | null,
  ) => void | Promise<void>;
  onSolverFilterChange: (
    filter: TrainingSolverFilter | null,
  ) => void | Promise<void>;
  onPositionFilterChange: (
    filter: TrainingPositionFilter | null,
  ) => void | Promise<void>;
  onStreetFilterChange: (
    filter: TrainingStreetFilter | null,
  ) => void | Promise<void>;
  onCertaintyFilterChange: (
    filter: TrainingCertaintyFilter | null,
  ) => void | Promise<void>;
  onViewChange: (view: TrainingProgressView) => void;
  positionFilter: TrainingPositionFilter | null;
  positionFocus: TrainingPositionFocus | null;
  progress: TrainingProgress | null;
  progressLoading: boolean;
  reviewCertainty: TrainingReviewCertaintyFilter;
  reviewDifference: TrainingReviewDifference | null;
  reviewJobId: string | null;
  reviewOrder: TrainingReviewOrder;
  reviewPosition: TrainingPositionFilter | null;
  reviewQueueStatus: string;
  reviewStreet: TrainingReviewStreet;
  solverFilter: TrainingSolverFilter | null;
  streetFilter: TrainingStreetFilter | null;
  streetFocus: TrainingFocus | null;
  view: TrainingProgressView;
  visibleHands: TrainingRecentHand[];
}

export function TrainingProgressDialog({
  actionDifferenceFocus,
  busy,
  certaintyFilter,
  certaintyFocus,
  lessonOrder,
  lessonQuery,
  lessonSearch,
  lessonStreet,
  lessonsExportDisabled,
  nextReviewHand,
  onCertaintyFilterChange,
  onClose,
  onFocusActionDifference,
  onFocusCertainty,
  onFocusPosition,
  onFocusStreet,
  onLessonFiltersChange,
  onLessonSearchChange,
  onOpenHand,
  onPositionFilterChange,
  onReopenHand,
  onReviewQueueChange,
  onSolverFilterChange,
  onStreetFilterChange,
  onViewChange,
  positionFilter,
  positionFocus,
  progress,
  progressLoading,
  reviewCertainty,
  reviewDifference,
  reviewJobId,
  reviewOrder,
  reviewPosition,
  reviewQueueStatus,
  reviewStreet,
  solverFilter,
  streetFilter,
  streetFocus,
  view,
  visibleHands,
}: TrainingProgressDialogProps) {
  const controlsDisabled = progressLoading || reviewJobId !== null || busy;

  return (
    <DialogFrame
      className="training-progress-dialog"
      titleId="training-progress-title"
    >
      <DialogHeader
        titleId="training-progress-title"
        title="Training progress"
        subtitle="Your locked answers compared with completed recommendations"
        closeLabel="Close training progress"
        closeDisabled={reviewJobId !== null}
        onClose={onClose}
      />

      <div className="training-progress-body">
        {progressLoading ? (
          <StateMessage centered className="training-progress-empty">
            Reading reviewed decisions...
          </StateMessage>
        ) : progress && progress.reviewed_hands > 0 ? (
          <>
            <TrainingProgressOverview progress={progress} />

            <TrainingSolverCoverage
              controlsDisabled={controlsDisabled}
              coverage={progress.solver_coverage}
              engineLabel={providerLabel}
              onFilterChange={onSolverFilterChange}
            />

            <TrainingCertaintyCalibration
              certaintyLabel={trainingCertaintyLabel}
              controlsDisabled={controlsDisabled}
              focus={certaintyFocus}
              onFilterChange={onCertaintyFilterChange}
              onReview={onFocusCertainty}
              progress={progress}
              showFocus={view === "recent"}
            />

            <TrainingActionDifferences
              actionLabel={(action) => trainingDecisionLabel(action, null)}
              controlsDisabled={controlsDisabled}
              differences={progress.action_differences}
              focus={actionDifferenceFocus}
              onReview={onFocusActionDifference}
              showFocus={view === "recent"}
            />

            <TrainingStreetSummary
              controlsDisabled={controlsDisabled}
              focus={streetFocus}
              onFilterChange={onStreetFilterChange}
              onReview={onFocusStreet}
              reviewCounts={progress.review_street_counts}
              showFocus={view === "recent"}
              summaries={progress.street_summaries}
            />

            <TrainingPositionSummary
              controlsDisabled={controlsDisabled}
              focus={positionFocus}
              onFilterChange={onPositionFilterChange}
              onReview={onFocusPosition}
              progress={progress}
              showFocus={view === "recent"}
            />

            <section
              className="training-progress-section recent-training-section"
              aria-labelledby="training-hands-title"
            >
              <TrainingProgressControls
                controlsDisabled={controlsDisabled}
                lessonCount={
                  progress.lesson_count ?? progress.lesson_hands?.length ?? 0
                }
                lessonOrder={lessonOrder}
                lessonQuery={lessonQuery}
                lessonSearch={lessonSearch}
                lessonStreet={lessonStreet}
                needsReviewHands={progress.needs_review_hands}
                onLessonOrderChange={(order) =>
                  onLessonFiltersChange(lessonStreet, lessonSearch, order)
                }
                onLessonSearchChange={onLessonSearchChange}
                onLessonSearchSubmit={() =>
                  onLessonFiltersChange(lessonStreet, lessonSearch)
                }
                onLessonStreetChange={(street) =>
                  onLessonFiltersChange(street, lessonSearch)
                }
                onReviewCertaintyChange={(certainty) =>
                  onReviewQueueChange(
                    reviewOrder,
                    reviewStreet,
                    reviewDifference,
                    certainty,
                  )
                }
                onReviewOrderChange={(order) =>
                  onReviewQueueChange(order, reviewStreet)
                }
                onReviewStreetChange={(street) =>
                  onReviewQueueChange(reviewOrder, street)
                }
                onViewChange={onViewChange}
                reviewCertainty={reviewCertainty}
                reviewOrder={reviewOrder}
                reviewStreet={reviewStreet}
                view={view}
              />
              <TrainingActiveFilters
                actionLabel={(action) => trainingDecisionLabel(action, null)}
                certaintyFilter={certaintyFilter}
                controlsDisabled={controlsDisabled}
                onClearCertainty={() => onCertaintyFilterChange(null)}
                onClearPosition={() => onPositionFilterChange(null)}
                onClearReviewDifference={() =>
                  onReviewQueueChange(reviewOrder, reviewStreet, null)
                }
                onClearReviewPosition={() =>
                  onReviewQueueChange(
                    reviewOrder,
                    reviewStreet,
                    reviewDifference,
                    reviewCertainty,
                    null,
                  )
                }
                onClearSolver={() => onSolverFilterChange(null)}
                onClearStreet={() => onStreetFilterChange(null)}
                positionFilter={positionFilter}
                reviewDifference={reviewDifference}
                reviewPosition={reviewPosition}
                solverFilter={solverFilter}
                streetFilter={streetFilter}
                view={view}
              />
              <TrainingDecisionList
                certaintyLabel={trainingCertaintyLabel}
                decisionLabel={trainingDecisionLabel}
                hands={visibleHands}
                lessonFiltersActive={
                  lessonStreet !== "all" || Boolean(lessonQuery)
                }
                onOpen={onOpenHand}
                onReopen={onReopenHand}
                openDisabled={controlsDisabled}
                positionFilter={positionFilter}
                reopenDisabled={reviewJobId !== null || busy}
                solverFilter={solverFilter}
                streetFilter={streetFilter}
                view={view}
              />
            </section>
          </>
        ) : (
          <StateMessage centered className="training-progress-empty">
            Lock an answer before revealing a recommendation to start tracking
            progress.
          </StateMessage>
        )}
      </div>

      <DialogFooter className="training-progress-footer">
        <span>{reviewQueueStatus}</span>
        {view === "lessons" ? (
          <DownloadLinkControl
            className="training-lessons-export"
            href={trainingLessonsExportUrl(
              lessonStreet,
              lessonQuery,
              lessonOrder,
            )}
            download="poker-hero-lessons.md"
            disabled={lessonsExportDisabled}
          >
            <Download size={14} aria-hidden="true" />
            Export lessons
          </DownloadLinkControl>
        ) : null}
        {nextReviewHand ? (
          <ButtonControl
            onClick={() => void onOpenHand(nextReviewHand.job_id, true)}
            disabled={controlsDisabled}
          >
            <Eye size={14} aria-hidden="true" />
            {reviewOrder === "ev_loss" &&
            typeof nextReviewHand.ev_loss_bb === "number"
              ? "Review highest loss"
              : "Review next"}
          </ButtonControl>
        ) : null}
        <ButtonControl
          variant="secondary"
          onClick={onClose}
          disabled={reviewJobId !== null}
        >
          Done
        </ButtonControl>
      </DialogFooter>
    </DialogFrame>
  );
}
