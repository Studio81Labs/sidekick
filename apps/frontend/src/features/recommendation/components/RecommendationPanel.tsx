import { Check, Pencil, RefreshCcw, X } from "lucide-react";
import "./RecommendationPanel.css";

import {
  candidateMatchesRecommendation,
  formatEvidenceMetric,
  recommendationContextLabel,
  type RecommendationEvidence,
} from "../lib/recommendationPresentation";
import {
  MAX_TRAINING_REVIEW_NOTE_LENGTH,
  trainingCertaintyLabel,
  trainingDecisionComparison,
  trainingDecisionLabel,
} from "../../training/lib/trainingPresentation";
import {
  ButtonControl,
  TextAreaControl,
} from "../../../shared/components/FormControls";
import {
  formatCandidateValue,
  formatEvLossBb,
} from "../../../shared/lib/metricPresentation";
import type { JobRecord } from "../../../shared/types/jobs";
import type { RecommendationResult } from "../../../shared/types/recommendations";
import type { TrainingDecision } from "../../../shared/types/training";

export interface RecommendationPanelProps {
  busy: boolean;
  decision: TrainingDecision | null;
  decisionComparison: ReturnType<typeof trainingDecisionComparison> | null;
  evidence: RecommendationEvidence | null;
  job: JobRecord;
  note: string;
  noteEditing: boolean;
  onCancelNoteEdit: () => void;
  onCompleteReview: () => void | Promise<void>;
  onNoteChange: (note: string) => void;
  onReopenReview: () => void | Promise<void>;
  onSaveNote: () => void | Promise<void>;
  onStartNoteEdit: () => void;
  recommendation: RecommendationResult;
  reviewQueueJobId: string | null;
}

export function RecommendationPanel({
  busy,
  decision,
  decisionComparison,
  evidence,
  job,
  note,
  noteEditing,
  onCancelNoteEdit,
  onCompleteReview,
  onNoteChange,
  onReopenReview,
  onSaveNote,
  onStartNoteEdit,
  recommendation,
  reviewQueueJobId,
}: RecommendationPanelProps) {
  const needsReview = Boolean(
    decision && decisionComparison && decisionComparison.tone !== "match",
  );

  return (
    <section className="recommendation" aria-label="Recommendation">
      <div className="recommendation-head">
        <span>Recommended play</span>
        <strong>
          {Math.round(recommendation.confidence * 100)}% confidence
        </strong>
      </div>
      <div className="recommendation-main">
        <span className="recommendation-action">{recommendation.action}</span>
        {recommendation.sizing !== null ? (
          <span className="recommendation-sizing">{recommendation.sizing}</span>
        ) : null}
      </div>

      {decision && decisionComparison ? (
        <div
          className="training-comparison"
          aria-label="Training decision comparison"
        >
          <span>
            <small>Your answer</small>
            <strong>
              {trainingDecisionLabel(decision.action, decision.sizing)}
            </strong>
            {decision.certainty ? (
              <small className="training-comparison-certainty">
                {trainingCertaintyLabel(decision.certainty)} certainty
              </small>
            ) : null}
          </span>
          <div className="training-comparison-result">
            <em className={decisionComparison.tone}>
              {decisionComparison.label}
            </em>
            {decisionComparison.evLossBb !== null ? (
              <small className="training-comparison-ev">
                {formatEvLossBb(decisionComparison.evLossBb)} EV loss
              </small>
            ) : null}
            {decisionComparison.tone !== "match" ? (
              job.training_reviewed_at ? (
                <div className="training-review-complete">
                  <span>
                    <Check size={12} aria-hidden="true" />
                    Reviewed
                  </span>
                  <ButtonControl
                    variant="ghost"
                    onClick={() => void onReopenReview()}
                    disabled={busy || noteEditing}
                  >
                    <RefreshCcw size={11} aria-hidden="true" />
                    Reopen review
                  </ButtonControl>
                </div>
              ) : (
                <ButtonControl
                  variant="ghost"
                  onClick={() => void onCompleteReview()}
                  disabled={busy}
                >
                  <Check size={12} aria-hidden="true" />
                  {reviewQueueJobId === job.id
                    ? "Mark reviewed & next"
                    : "Mark reviewed"}
                </ButtonControl>
              )
            ) : null}
          </div>
        </div>
      ) : null}

      {needsReview ? (
        job.training_reviewed_at ? (
          noteEditing ? (
            <label className="training-review-note">
              <span>
                Lesson note
                <small>
                  {note.length}/{MAX_TRAINING_REVIEW_NOTE_LENGTH}
                </small>
              </span>
              <TextAreaControl
                appearance="inverse"
                aria-label="Edit training review note"
                value={note}
                onChange={(event) => onNoteChange(event.target.value)}
                maxLength={MAX_TRAINING_REVIEW_NOTE_LENGTH}
                rows={2}
                placeholder="What will you remember next time?"
                disabled={busy}
              />
              <span className="training-review-note-actions">
                <ButtonControl
                  variant="secondary"
                  onClick={onCancelNoteEdit}
                  disabled={busy}
                >
                  <X size={11} aria-hidden="true" />
                  Cancel
                </ButtonControl>
                <ButtonControl
                  variant="secondary"
                  onClick={() => void onSaveNote()}
                  disabled={
                    busy || (note.trim() || null) === job.training_review_note
                  }
                >
                  <Check size={11} aria-hidden="true" />
                  Save note
                </ButtonControl>
              </span>
            </label>
          ) : job.training_review_note ? (
            <div
              className="training-review-note-saved"
              aria-label="Saved training review note"
            >
              <div>
                <strong>Review note</strong>
                <ButtonControl
                  variant="secondary"
                  onClick={onStartNoteEdit}
                  disabled={busy}
                  aria-label="Edit training review note"
                  title="Edit lesson note"
                >
                  <Pencil size={11} aria-hidden="true" />
                </ButtonControl>
              </div>
              <span>{job.training_review_note}</span>
            </div>
          ) : (
            <ButtonControl
              variant="secondary"
              className="training-review-note-add"
              onClick={onStartNoteEdit}
              disabled={busy}
            >
              <Pencil size={11} aria-hidden="true" />
              Add lesson note
            </ButtonControl>
          )
        ) : (
          <label className="training-review-note">
            <span>
              Review note
              <small>
                {note.length}/{MAX_TRAINING_REVIEW_NOTE_LENGTH}
              </small>
            </span>
            <TextAreaControl
              appearance="inverse"
              aria-label="Training review note"
              value={note}
              onChange={(event) => onNoteChange(event.target.value)}
              maxLength={MAX_TRAINING_REVIEW_NOTE_LENGTH}
              rows={2}
              placeholder="What will you remember next time?"
              disabled={busy}
            />
          </label>
        )
      ) : null}

      <p>{recommendation.explanation}</p>
      {evidence ? (
        <div className="recommendation-evidence" aria-label="Decision evidence">
          <div className="recommendation-evidence-head">
            <span>Decision evidence</span>
            {evidence.engine ? <strong>{evidence.engine}</strong> : null}
          </div>
          {evidence.fallbackReason ? (
            <div className="recommendation-fallback">
              <strong>{recommendationContextLabel(evidence)}</strong>
              <span>{evidence.fallbackReason}</span>
            </div>
          ) : null}
          {evidence.metrics.length > 0 ? (
            <div className="recommendation-metrics">
              {evidence.metrics.map((metric) => (
                <div key={metric.label}>
                  <strong>{formatEvidenceMetric(metric)}</strong>
                  <span>{metric.label}</span>
                </div>
              ))}
            </div>
          ) : null}
          {evidence.details.length > 0 ? (
            <dl
              className="recommendation-context"
              aria-label="Decision context"
            >
              {evidence.details.map((detail) => (
                <div key={detail.label}>
                  <dt>{detail.label}</dt>
                  <dd>{detail.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
          {evidence.ranges.length > 0 ? (
            <details
              className="recommendation-ranges"
              aria-label="Modeled ranges"
            >
              <summary>Modeled ranges</summary>
              <dl>
                {evidence.ranges.map((range) => (
                  <div key={range.label}>
                    <dt>{range.label}</dt>
                    <dd>{range.value}</dd>
                  </div>
                ))}
              </dl>
            </details>
          ) : null}
          {evidence.candidates.length > 0 ? (
            <div
              className="recommendation-candidates"
              role="list"
              aria-label="Compared actions"
            >
              <div className="recommendation-candidates-head">
                <span>Compared actions</span>
                <span>EV / frequency</span>
              </div>
              {evidence.candidates.map((candidate, index) => {
                const selected = candidateMatchesRecommendation(
                  candidate,
                  recommendation,
                );
                return (
                  <div
                    key={`${candidate.action}-${candidate.sizing ?? "none"}-${index}`}
                    className={selected ? "selected" : undefined}
                    role="listitem"
                    aria-current={selected ? "true" : undefined}
                  >
                    <span className="recommendation-candidate-action">
                      <strong>{candidate.action}</strong>
                      {candidate.sizing !== null ? (
                        <small>
                          {formatCandidateValue(candidate.sizing)} BB
                        </small>
                      ) : null}
                      {selected ? <em>Chosen</em> : null}
                    </span>
                    <span className="recommendation-candidate-values">
                      {candidate.ev !== null ? (
                        <strong>
                          EV {formatCandidateValue(candidate.ev)} BB
                        </strong>
                      ) : null}
                      {candidate.frequency !== null ? (
                        <small>
                          {Math.round(candidate.frequency * 100)}% frequency
                        </small>
                      ) : null}
                      {candidate.foldEquity !== null ? (
                        <small>
                          Field folds {Math.round(candidate.foldEquity * 100)}%
                          {candidate.perOpponentFoldEquity !== null &&
                          candidate.perOpponentFoldEquity !==
                            candidate.foldEquity
                            ? ` · each ${Math.round(candidate.perOpponentFoldEquity * 100)}%`
                            : ""}
                        </small>
                      ) : null}
                    </span>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
