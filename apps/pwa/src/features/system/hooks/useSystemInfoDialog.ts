import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  systemInfoQueryOptions,
  useSystemInfoQuery,
} from "../../../domains/system/api/systemQueries";

export function useSystemInfoDialog() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [mcpTokenPending, setMcpTokenPending] = useState(false);
  const queryClient = useQueryClient();
  const { data, isFetching } = useSystemInfoQuery(false);

  function openDialog() {
    setDialogOpen(true);
    void queryClient
      .fetchQuery(systemInfoQueryOptions())
      .catch(() => undefined);
  }

  function closeDialog(blocked = false) {
    if (blocked || mcpTokenPending) {
      return;
    }
    setDialogOpen(false);
  }

  return {
    closeDialog,
    dialogOpen,
    loading: isFetching,
    mcpTokenPending,
    openDialog,
    setMcpTokenPending,
    systemInfo: data ?? null,
  };
}
