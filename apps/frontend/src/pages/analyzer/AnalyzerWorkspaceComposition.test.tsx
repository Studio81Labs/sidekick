import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AnalyzerRouteNavigation } from "./analyzerRouteState";
import { AnalyzerWorkspaceComposition } from "./AnalyzerWorkspaceComposition";
import { useAnalyzerWorkspaceController } from "./useAnalyzerWorkspaceController";

vi.mock("./useAnalyzerWorkspaceController", () => ({
  useAnalyzerWorkspaceController: vi.fn(),
}));
vi.mock("./components/AnalyzerToolbar", () => ({
  AnalyzerToolbar: () => <div>Toolbar slot</div>,
}));
vi.mock("../../features/capture/components/InputSourcePanel", () => ({
  InputSourcePanel: () => <div>Input slot</div>,
}));
vi.mock("../../features/queue/components/ScreenshotQueuePanel", () => ({
  ScreenshotQueuePanel: () => <div>Queue slot</div>,
}));
vi.mock("../../features/history/components/HistoryPanel", () => ({
  HistoryPanel: () => <div>History slot</div>,
}));
vi.mock("../../features/capture/components/TablePreview", () => ({
  TablePreview: () => <div>Preview slot</div>,
}));
vi.mock("./components/HandReviewWorkspace", () => ({
  HandReviewWorkspace: () => <div>Review slot</div>,
}));
vi.mock("../../features/system/components/UserGuideDialog", () => ({
  UserGuideDialog: () => <div role="dialog">Help slot</div>,
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AnalyzerWorkspaceComposition", () => {
  it("renders controller-owned feature props through the page layout", () => {
    vi.mocked(useAnalyzerWorkspaceController).mockReturnValue({
      dialogs: {
        automation: null,
        benchmark: null,
        help: { onClose: vi.fn() },
        info: null,
        pipeline: null,
        queueProcessing: null,
        screenshotDetails: null,
        training: null,
      },
      handReview: {},
      history: {},
      inputSource: {},
      preview: {},
      queue: {},
      toolbar: {},
    } as unknown as ReturnType<typeof useAnalyzerWorkspaceController>);
    const navigation: AnalyzerRouteNavigation = {
      closeSurface: vi.fn(),
      managed: true,
      openBenchmarks: vi.fn(),
      openJob: vi.fn(),
      openTraining: vi.fn(),
      openWorkspace: vi.fn(),
    };

    render(
      <AnalyzerWorkspaceComposition
        mutationOwnerId="test-owner"
        navigation={navigation}
        route={{ jobId: null, surface: "workspace" }}
      />,
    );

    expect(screen.getByText("Toolbar slot")).toBeInTheDocument();
    expect(screen.getByText("Input slot")).toBeInTheDocument();
    expect(screen.getByText("Queue slot")).toBeInTheDocument();
    expect(screen.getByText("History slot")).toBeInTheDocument();
    expect(screen.getByText("Preview slot")).toBeInTheDocument();
    expect(screen.getByText("Review slot")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toHaveTextContent("Help slot");
    expect(useAnalyzerWorkspaceController).toHaveBeenCalledWith({
      mutationOwnerId: "test-owner",
      navigation,
      route: { jobId: null, surface: "workspace" },
    });
  });
});
