import { useCallback, useEffect, useState } from "react";

import { usePipelineCapabilitiesQuery } from "../../../domains/pipeline/api/pipelineQueries";
import { reconcilePipelineSelection } from "../lib/pipelineSelection";
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

  function updateRecommendationProvider(value: string) {
    setSelection((current) => {
      if (!current) return current;
      if (value !== "local_solver") {
        return {
          ...current,
          recommendation_provider: value,
          recommendation_engine: null,
        };
      }
      const selectedEngineAvailable =
        capabilities?.recommendation_engines.some(
          (option) =>
            option.available && option.id === current.recommendation_engine,
        ) ?? false;
      return {
        ...current,
        recommendation_provider: value,
        recommendation_engine: selectedEngineAvailable
          ? current.recommendation_engine
          : (capabilities?.recommendation_engines.find(
              (option) => option.available,
            )?.id ?? null),
      };
    });
  }

  return {
    capabilities,
    dialogOpen,
    loadCapabilities,
    loading: isFetching,
    openDialog,
    selection,
    setDialogOpen,
    setSelection,
    updateParserProvider,
    updateRecommendationProvider,
    updateSelection,
  };
}
