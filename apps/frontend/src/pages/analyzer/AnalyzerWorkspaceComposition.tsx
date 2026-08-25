import { AutomationDialog } from "../../features/automation/components/AutomationDialog";
import { BenchmarkDialog } from "../../features/benchmark/components/BenchmarkDialog";
import { InputSourcePanel } from "../../features/capture/components/InputSourcePanel";
import { TablePreview } from "../../features/capture/components/TablePreview";
import { HandReviewPanel } from "../../features/hand-review/components/HandReviewPanel";
import { HistoryPanel } from "../../features/history/components/HistoryPanel";
import { PipelineDialog } from "../../features/pipeline/components/PipelineDialog";
import { QueueProcessingDialog } from "../../features/queue/components/QueueProcessingDialog";
import { ScreenshotQueuePanel } from "../../features/queue/components/ScreenshotQueuePanel";
import { ScreenshotDetailsDialog } from "../../features/screenshots/components/ScreenshotDetailsDialog";
import { InfoDialog } from "../../features/system/components/InfoDialog";
import { UserGuideDialog } from "../../features/system/components/UserGuideDialog";
import { TrainingProgressDialog } from "../../features/training/components/TrainingProgressDialog";
import {
  AnalyzerControlRail,
  AnalyzerDialogHost,
  AnalyzerLayout,
  AnalyzerWorkspaceLayout,
} from "./AnalyzerLayout";
import { AnalyzerToolbar } from "./components/AnalyzerToolbar";
import {
  type AnalyzerWorkspaceControllerProps,
  useAnalyzerWorkspaceController,
} from "./useAnalyzerWorkspaceController";

export function AnalyzerWorkspaceComposition(
  props: AnalyzerWorkspaceControllerProps,
) {
  const view = useAnalyzerWorkspaceController(props);

  return (
    <AnalyzerLayout>
      <AnalyzerToolbar {...view.toolbar} />
      <AnalyzerWorkspaceLayout>
        <AnalyzerControlRail>
          <InputSourcePanel {...view.inputSource} />
          <ScreenshotQueuePanel {...view.queue} />
          <HistoryPanel {...view.history} />
        </AnalyzerControlRail>
        <TablePreview {...view.preview} />
        <HandReviewPanel {...view.handReview} />
      </AnalyzerWorkspaceLayout>
      <AnalyzerDialogHost>
        {view.dialogs.queueProcessing ? (
          <QueueProcessingDialog {...view.dialogs.queueProcessing} />
        ) : null}
        {view.dialogs.screenshotDetails ? (
          <ScreenshotDetailsDialog {...view.dialogs.screenshotDetails} />
        ) : null}
        {view.dialogs.automation ? (
          <AutomationDialog {...view.dialogs.automation} />
        ) : null}
        {view.dialogs.pipeline ? (
          <PipelineDialog {...view.dialogs.pipeline} />
        ) : null}
        {view.dialogs.help ? <UserGuideDialog {...view.dialogs.help} /> : null}
        {view.dialogs.info ? <InfoDialog {...view.dialogs.info} /> : null}
        {view.dialogs.training ? (
          <TrainingProgressDialog {...view.dialogs.training} />
        ) : null}
        {view.dialogs.benchmark ? (
          <BenchmarkDialog {...view.dialogs.benchmark} />
        ) : null}
      </AnalyzerDialogHost>
    </AnalyzerLayout>
  );
}
