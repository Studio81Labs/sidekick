import { useCallback, useEffect, useState } from "react";

import { usePipelineCapabilitiesQuery } from "../../../domains/pipeline/api/pipelineQueries";
import {
  compatiblePipelineLayouts,
  providerLabel,
  reconcilePipelineSelection,
} from "../../../domains/pipeline/model/pipelineSelection";
import { messageFromError } from "../../../shared/lib/errors";
import type {
  PipelineCapabilities,
  PipelineSelection,
} from "../../../shared/types/pipeline";

interface UsePipelineSelectionOptions {
  onError: (message: string | null) => void;
}

export function usePipelineSelection({ onError }: UsePipelineSelectionOptions) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [selection, setSelection] = useState<PipelineSelection | null>(null);
  const { data, isFetching, refetch } = usePipelineCapabilitiesQuery(false);
  const capabilities = data ?? null;
  const compatibleLayouts =
    capabilities && selection
      ? compatiblePipelineLayouts(capabilities, selection.parser_provider)
      : [];

  useEffect(() => {
    if (!capabilities) return;
    setSelection((current) =>
      reconcilePipelineSelection(
        capabilities,
        current ?? capabilities.defaults,
      ),
    );
  }, [capabilities]);

  const loadCapabilities = useCallback(async () => {
    if (capabilities) return capabilities;
    const result = await refetch();
    if (result.error) {
      onError(
        messageFromError(result.error, "Could not read analysis plugins"),
      );
      return null;
    }
    return result.data ?? null;
  }, [capabilities, onError, refetch]);

  function openDialog() {
    setDialogOpen(true);
    void loadCapabilities();
  }

  function updateSelection<K extends keyof PipelineSelection>(
    key: K,
    value: PipelineSelection[K],
  ) {
    setSelection((current) =>
      current ? { ...current, [key]: value } : current,
    );
  }

  function updateParserProvider(value: string) {
    setSelection((current) =>
      current && capabilities
        ? reconcilePipelineSelection(capabilities, {
            ...current,
            parser_provider: value,
          })
        : current,
    );
  }

  return {
    capabilities,
    compatibleLayouts,
    dialogOpen,
    loadCapabilities,
    loading: isFetching,
    openDialog,
    providerLabel,
    selection,
    setDialogOpen,
    setSelection,
    updateParserProvider,
    updateSelection,
  };
}
