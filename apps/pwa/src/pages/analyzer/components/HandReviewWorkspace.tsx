import type { ComponentProps } from "react";

import {
  HandReviewPanel,
  type HandReviewPanelProps,
} from "../../../features/hand-review/components/HandReviewPanel";
import { RecommendationPanel } from "../../../features/recommendation/components/RecommendationPanel";
import { TrainingDecisionPanel } from "../../../features/training/components/TrainingDecisionPanel";

export interface HandReviewWorkspaceProps {
  panel: HandReviewPanelProps;
  recommendation: ComponentProps<typeof RecommendationPanel> | null;
  trainingDecision: ComponentProps<typeof TrainingDecisionPanel> | null;
}

export function HandReviewWorkspace({
  panel,
  recommendation,
  trainingDecision,
}: HandReviewWorkspaceProps) {
  return (
    <HandReviewPanel {...panel}>
      {trainingDecision ? (
        <TrainingDecisionPanel {...trainingDecision} />
      ) : null}
      {recommendation ? <RecommendationPanel {...recommendation} /> : null}
    </HandReviewPanel>
  );
}
