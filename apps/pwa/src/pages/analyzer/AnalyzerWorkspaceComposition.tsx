import { AdministrativeAccessDialog } from "../../features/admin-ocr-test/components/AdministrativeAccessDialog";
import { BenchmarkDialog } from "../../features/benchmark/components/BenchmarkDialog";
import { AdministrativeTestBanner } from "../../features/capture/components/AdministrativeTestBanner";
import { ImportFirstNotice } from "../../features/capture/components/ImportFirstNotice";
import { InputSourcePanel } from "../../features/capture/components/InputSourcePanel";
import { TablePreview } from "../../features/capture/components/TablePreview";
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
import { HandReviewWorkspace } from "./components/HandReviewWorkspace";
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
          {view.inputSource ? (
            <>
              <AdministrativeTestBanner {...view.administrativeBanner} />
              <InputSourcePanel {...view.inputSource} />
            </>
          ) : (
            <ImportFirstNotice />
          )}
          <ScreenshotQueuePanel {...view.queue} />
          <HistoryPanel {...view.history} />
        </AnalyzerControlRail>
        <TablePreview {...view.preview} />
        <HandReviewWorkspace {...view.handReview} />
      </AnalyzerWorkspaceLayout>
      <AnalyzerDialogHost>
        {view.dialogs.queueProcessing ? (
          <QueueProcessingDialog {...view.dialogs.queueProcessing} />
        ) : null}
        {view.dialogs.screenshotDetails ? (
          <ScreenshotDetailsDialog {...view.dialogs.screenshotDetails} />
        ) : null}
        {view.dialogs.administrativeAccess ? (
          <AdministrativeAccessDialog {...view.dialogs.administrativeAccess} />
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
