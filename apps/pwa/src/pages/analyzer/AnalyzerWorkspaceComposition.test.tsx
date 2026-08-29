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
vi.mock("../../features/capture/components/AdministrativeTestBanner", () => ({
  AdministrativeTestBanner: () => <div>Administrative banner slot</div>,
}));
vi.mock("../../features/capture/components/ImportFirstNotice", () => ({
  ImportFirstNotice: () => <div>Import-first notice slot</div>,
}));
vi.mock(
  "../../features/admin-ocr-test/components/AdministrativeAccessDialog",
  () => ({
    AdministrativeAccessDialog: () => (
      <div role="dialog">Administrator tools slot</div>
    ),
  }),
);
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

const navigation: AnalyzerRouteNavigation = {
  closeSurface: vi.fn(),
  managed: true,
  openBenchmarks: vi.fn(),
  openJob: vi.fn(),
  openTraining: vi.fn(),
  openWorkspace: vi.fn(),
};

function mockView(
  overrides: Record<string, unknown> = {},
  dialogOverrides: Record<string, unknown> = {},
) {
  vi.mocked(useAnalyzerWorkspaceController).mockReturnValue({
    administrativeBanner: {},
    dialogs: {
      administrativeAccess: null,
      benchmark: null,
      help: { onClose: vi.fn() },
      info: null,
      pipeline: null,
      queueProcessing: null,
      screenshotDetails: null,
      training: null,
      ...dialogOverrides,
    },
    handReview: {},
    history: {},
    inputSource: null,
    preview: {},
    queue: {},
    toolbar: {},
    ...overrides,
  } as unknown as ReturnType<typeof useAnalyzerWorkspaceController>);
}

function renderComposition() {
  render(
    <AnalyzerWorkspaceComposition
      mutationOwnerId="test-owner"
      navigation={navigation}
      route={{ jobId: null, surface: "workspace" }}
    />,
  );
}

describe("AnalyzerWorkspaceComposition", () => {
  it("renders controller-owned feature props through the page layout", () => {
    mockView();
    renderComposition();

    expect(screen.getByText("Toolbar slot")).toBeInTheDocument();
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

  it("shows the import-first notice while no input source is unlocked", () => {
    mockView();
    renderComposition();

    expect(screen.getByText("Import-first notice slot")).toBeInTheDocument();
    expect(screen.queryByText("Input slot")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Administrative banner slot"),
    ).not.toBeInTheDocument();
  });

  it("shows the administrative banner and capture panel once unlocked", () => {
    mockView({ inputSource: {} });
    renderComposition();

    expect(screen.getByText("Administrative banner slot")).toBeInTheDocument();
    expect(screen.getByText("Input slot")).toBeInTheDocument();
    expect(
      screen.queryByText("Import-first notice slot"),
    ).not.toBeInTheDocument();
  });

  it("hosts the administrator tools dialog when the controller opens it", () => {
    mockView({}, { administrativeAccess: {}, help: null });
    renderComposition();

    expect(screen.getByRole("dialog")).toHaveTextContent(
      "Administrator tools slot",
    );
  });
});
