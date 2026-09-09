import "./AnalyzerPage.css";
import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AnalyzerWorkspaceComposition } from "./AnalyzerWorkspaceComposition";
import type {
  AnalyzerRouteNavigation,
  AnalyzerRouteState,
} from "./analyzerRouteState";
import { AnalyzerWorkflowProvider } from "../../features/workspace/hooks/useAnalyzerWorkflow";
import { useAnalyzerWorkflowOwnerId } from "../../features/workspace/hooks/useAnalyzerWorkflowOwnerId";
import { AdministrativeAccessDialog } from "../../features/admin-ocr-test/components/AdministrativeAccessDialog";
import { useAdministrativeAccess } from "../../features/admin-ocr-test/hooks/useAdministrativeAccess";

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
  const queryClient = useQueryClient();
  const administrativeAccess = useAdministrativeAccess({});
  const [accessError, setAccessError] = useState<string | null>(null);
  const lockAdministrator = useCallback(
    (reason?: string) => {
      setAccessError(typeof reason === "string" ? reason : null);
      queryClient.clear();
      administrativeAccess.lock();
    },
    [administrativeAccess, queryClient],
  );
  const unlockAdministrator = useCallback(
    async (token: string) => {
      const result = await administrativeAccess.unlock(token);
      if (result === "unlocked") setAccessError(null);
      return result;
    },
    [administrativeAccess],
  );

  if (administrativeAccess.token === null) {
    return (
      <main className="analyzer-access-gate">
        <AdministrativeAccessDialog
          busy={false}
          externalValidation={accessError}
          onClose={() => undefined}
          onLock={lockAdministrator}
          onUnlock={unlockAdministrator}
          unlocked={false}
          verifying={administrativeAccess.verifying}
        />
      </main>
    );
  }

  return (
    <AnalyzerWorkflowProvider mutationOwnerId={mutationOwnerId}>
      <AnalyzerWorkspaceComposition
        administratorToken={administrativeAccess.token}
        mutationOwnerId={mutationOwnerId}
        navigation={navigation}
        onLockAdministrator={lockAdministrator}
        route={route}
      />
    </AnalyzerWorkflowProvider>
  );
}
