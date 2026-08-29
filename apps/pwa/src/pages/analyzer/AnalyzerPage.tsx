import "./AnalyzerPage.css";
import { AnalyzerWorkspaceComposition } from "./AnalyzerWorkspaceComposition";
import type {
  AnalyzerRouteNavigation,
  AnalyzerRouteState,
} from "./analyzerRouteState";
import { AnalyzerWorkflowProvider } from "../../features/workspace/hooks/useAnalyzerWorkflow";
import { useAnalyzerWorkflowOwnerId } from "../../features/workspace/hooks/useAnalyzerWorkflowOwnerId";

const DEFAULT_ANALYZER_ROUTE: AnalyzerRouteState = {
  jobId: null,
  surface: "workspace",
};
const ignoreRouteNavigation = () => undefined;
const DEFAULT_ANALYZER_NAVIGATION: AnalyzerRouteNavigation = {
  closeSurface: ignoreRouteNavigation,
  managed: false,
  openBenchmarks: ignoreRouteNavigation,
  openJob: ignoreRouteNavigation,
  openWorkspace: ignoreRouteNavigation,
};

export interface AnalyzerPageProps {
  navigation?: AnalyzerRouteNavigation;
  route?: AnalyzerRouteState;
}

export default function AnalyzerPage({
  navigation = DEFAULT_ANALYZER_NAVIGATION,
  route = DEFAULT_ANALYZER_ROUTE,
}: AnalyzerPageProps) {
  const mutationOwnerId = useAnalyzerWorkflowOwnerId();

  return (
    <AnalyzerWorkflowProvider mutationOwnerId={mutationOwnerId}>
      <AnalyzerWorkspaceComposition
        mutationOwnerId={mutationOwnerId}
        navigation={navigation}
        route={route}
      />
    </AnalyzerWorkflowProvider>
  );
}
