import type {
  PipelineCapabilities,
  PipelineOption,
  PipelineSelection,
} from "../../../shared/types/pipeline";

export const PROVIDER_LABELS: Record<string, string> = {
  auto: "Automatic recognition",
  custom_local: "Custom local solver",
  external_solver: "External solver",
  llm_advice: "LLM adviser",
  llm_vision: "External vision model",
  local_ev: "Local EV solver",
  local_ev_solver_v1: "Local EV solver",
  local_solver: "Local solver",
  mock: "Demo engine",
  ocr_cv: "OCR + computer vision",
  preflop_chart_v1: "Preflop chart",
  postflop_solver: "Postflop solver",
  rule_based: "Rule-based trainer",
  rule_based_training_v2: "Rule-based trainer",
};

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider.replace(/_/g, " ");
}

export function availablePipelineOption(
  options: PipelineOption[],
  optionId: string | null | undefined,
): PipelineOption | undefined {
  return options.find((option) => option.available && option.id === optionId);
}

export function compatiblePipelineLayouts(
  capabilities: PipelineCapabilities,
  parserProvider: string,
): PipelineOption[] {
  const compatibleIds =
    capabilities.parser_layout_compatibility?.[parserProvider];
  if (!compatibleIds) {
    return capabilities.parser_layout_profiles;
  }
  const compatible = new Set(compatibleIds);
  return capabilities.parser_layout_profiles.filter((option) =>
    compatible.has(option.id),
  );
}

export function reconcilePipelineSelection(
  capabilities: PipelineCapabilities,
  candidate: PipelineSelection,
): PipelineSelection {
  const parserProvider =
    availablePipelineOption(
      capabilities.parser_providers,
      candidate.parser_provider,
    )?.id ??
    capabilities.parser_providers.find((option) => option.available)?.id ??
    capabilities.defaults.parser_provider;
  const layouts = compatiblePipelineLayouts(capabilities, parserProvider);
  const parserLayoutProfile =
    availablePipelineOption(layouts, candidate.parser_layout_profile)?.id ??
    availablePipelineOption(
      layouts,
      capabilities.defaults.parser_layout_profile,
    )?.id ??
    layouts.find((option) => option.available)?.id ??
    capabilities.defaults.parser_layout_profile;
  const recommendationProvider =
    availablePipelineOption(
      capabilities.recommendation_providers,
      candidate.recommendation_provider,
    )?.id ??
    capabilities.recommendation_providers.find((option) => option.available)
      ?.id ??
    capabilities.defaults.recommendation_provider;
  const recommendationEngine =
    recommendationProvider === "local_solver"
      ? (availablePipelineOption(
          capabilities.recommendation_engines,
          candidate.recommendation_engine,
        )?.id ??
        availablePipelineOption(
          capabilities.recommendation_engines,
          capabilities.defaults.recommendation_engine,
        )?.id ??
        capabilities.recommendation_engines.find((option) => option.available)
          ?.id ??
        null)
      : null;
  return {
    parser_provider: parserProvider,
    parser_layout_profile: parserLayoutProfile,
    recommendation_provider: recommendationProvider,
    recommendation_engine: recommendationEngine,
  };
}
