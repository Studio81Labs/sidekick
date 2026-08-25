import { Check, Play, RefreshCcw } from "lucide-react";
import "./HandReviewPanel.css";

import type { RecommendationEvidence } from "../../recommendation/lib/recommendationPresentation";
import type {
  TrainingActionOption,
  TrainingCertaintyOption,
} from "../../training/lib/trainingPresentation";
import { ButtonControl } from "../../../shared/components/FormControls";
import { HandStateEditor, type HandStateEditorProps } from "./HandStateEditor";
import { JobStatusBadge } from "../../../shared/components/JobStatusBadge";
import { RecommendationPanel } from "../../recommendation/components/RecommendationPanel";
import { TrainingDecisionPanel } from "../../training/components/TrainingDecisionPanel";
import { trainingDecisionComparison } from "../../training/lib/trainingPresentation";
import type { JobRecord } from "../../../shared/types/jobs";
import type { RecommendationResult } from "../../../shared/types/recommendations";
import type { TrainingDecision } from "../../../shared/types/training";

export interface HandReviewPanelProps {
  busy: boolean;
  canApprove: boolean;
  canRecommend: boolean;
  currentStateApproved: boolean;
  decisionComparison: ReturnType<typeof trainingDecisionComparison> | null;
  decisionEvidence: RecommendationEvidence | null;
  editor: HandStateEditorProps;
  job: JobRecord | null;
  onApprove: () => void | Promise<void>;
  onCancelTrainingReviewNoteEdit: () => void;
  onCompleteTrainingReview: () => void | Promise<void>;
  onRecommend: () => void | Promise<void>;
  onReopenTrainingReview: () => void | Promise<void>;
  onResetToParser: () => void;
  onSaveTrainingDecision: () => void | Promise<void>;
  onStartTrainingReviewNoteEdit: () => void;
  onTrainingActionChange: (action: TrainingActionOption) => void;
  onTrainingCertaintyChange: (certainty: TrainingCertaintyOption) => void;
  onTrainingReviewNoteChange: (note: string) => void;
  onTrainingSizingChange: (sizing: string) => void;
  onUpdateTrainingReviewNote: () => void | Promise<void>;
  recommendation: RecommendationResult | null;
  trainingAction: TrainingActionOption;
  trainingCertainty: TrainingCertaintyOption;
  trainingDecision: TrainingDecision | null;
  trainingReviewNote: string;
  trainingReviewNoteEditing: boolean;
  trainingReviewQueueJobId: string | null;
  trainingSizing: string;
}

export function HandReviewPanel({
  busy,
  canApprove,
  canRecommend,
  currentStateApproved,
  decisionComparison,
  decisionEvidence,
  editor,
  job,
  onApprove,
  onCancelTrainingReviewNoteEdit,
  onCompleteTrainingReview,
  onRecommend,
  onReopenTrainingReview,
  onResetToParser,
  onSaveTrainingDecision,
  onStartTrainingReviewNoteEdit,
  onTrainingActionChange,
  onTrainingCertaintyChange,
  onTrainingReviewNoteChange,
  onTrainingSizingChange,
  onUpdateTrainingReviewNote,
  recommendation,
  trainingAction,
  trainingCertainty,
  trainingDecision,
  trainingReviewNote,
  trainingReviewNoteEditing,
  trainingReviewQueueJobId,
  trainingSizing,
}: HandReviewPanelProps) {
  return (
    <section className="review-column" aria-label="Hand review">
      <div className="panel-header">
        <h2>Detected state</h2>
        {job ? <JobStatusBadge status={job.status} /> : null}
      </div>

      <div className="review-scroll">
        <HandStateEditor {...editor} />

        {currentStateApproved && !recommendation ? (
          <TrainingDecisionPanel
            action={trainingAction}
            busy={busy}
            certainty={trainingCertainty}
            decision={trainingDecision}
            onActionChange={onTrainingActionChange}
            onCertaintyChange={onTrainingCertaintyChange}
            onSave={onSaveTrainingDecision}
            onSizingChange={onTrainingSizingChange}
            sizing={trainingSizing}
          />
        ) : null}

        {job && recommendation ? (
          <RecommendationPanel
            busy={busy}
            decision={trainingDecision}
            decisionComparison={decisionComparison}
            evidence={decisionEvidence}
            job={job}
            note={trainingReviewNote}
            noteEditing={trainingReviewNoteEditing}
            onCancelNoteEdit={onCancelTrainingReviewNoteEdit}
            onCompleteReview={onCompleteTrainingReview}
            onNoteChange={onTrainingReviewNoteChange}
            onReopenReview={onReopenTrainingReview}
            onSaveNote={onUpdateTrainingReviewNote}
            onStartNoteEdit={onStartTrainingReviewNoteEdit}
            recommendation={recommendation}
            reviewQueueJobId={trainingReviewQueueJobId}
          />
        ) : null}
      </div>

      <div className="review-actions">
        <ButtonControl
          onClick={() => void onApprove()}
          disabled={!canApprove || busy}
          aria-label="Approve state"
        >
          <Check size={15} aria-hidden="true" />
          Approve
        </ButtonControl>
        <ButtonControl
          variant="secondary"
          onClick={() => void onRecommend()}
          disabled={!canRecommend || busy}
          aria-label="Request recommendation"
        >
          <Play size={14} aria-hidden="true" />
          Recommend
        </ButtonControl>
        <ButtonControl
          variant="ghost"
          iconOnly
          onClick={onResetToParser}
          disabled={!job?.parser_result || busy}
          title="Reset to parser"
          aria-label="Reset to parser"
        >
          <RefreshCcw size={14} aria-hidden="true" />
        </ButtonControl>
      </div>
    </section>
  );
}
