import {
  HandReviewPanel,
  type HandReviewPanelProps,
} from "../../../features/hand-review/components/HandReviewPanel";

export interface HandReviewWorkspaceProps {
  panel: HandReviewPanelProps;
}

export function HandReviewWorkspace({ panel }: HandReviewWorkspaceProps) {
  return <HandReviewPanel {...panel} />;
}
