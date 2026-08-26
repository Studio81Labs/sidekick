import type { components } from "../../../shared/api/generated/openapi";
import { requestJson } from "../../../shared/api/transport";
import type {
  PipelineCapabilities,
  PipelineOption,
  PipelineSelection,
} from "../../../shared/types/pipeline";

type PipelineCapabilitiesResponse =
  components["schemas"]["PipelineCapabilities"];
type PipelineOptionResponse = components["schemas"]["PipelineOption"];
type PipelineSelectionResponse = components["schemas"]["PipelineSelection"];

function toPipelineOption(option: PipelineOptionResponse): PipelineOption {
  return {
    available: option.available,
    id: option.id,
    label: option.label,
    unavailable_reason: option.unavailable_reason ?? null,
  };
}

function toPipelineSelection(
  selection: PipelineSelectionResponse,
): PipelineSelection {
  return {
    parser_layout_profile: selection.parser_layout_profile,
    parser_provider: selection.parser_provider,
    recommendation_engine: selection.recommendation_engine ?? null,
    recommendation_provider: selection.recommendation_provider,
  };
}

export function toPipelineCapabilities(
  response: PipelineCapabilitiesResponse,
): PipelineCapabilities {
  return {
    defaults: toPipelineSelection(response.defaults),
    parser_layout_compatibility: response.parser_layout_compatibility,
    parser_layout_profiles:
      response.parser_layout_profiles.map(toPipelineOption),
    parser_providers: response.parser_providers.map(toPipelineOption),
    recommendation_engines:
      response.recommendation_engines.map(toPipelineOption),
    recommendation_providers:
      response.recommendation_providers.map(toPipelineOption),
  };
}

export async function getPipelineCapabilities(
  signal?: AbortSignal,
): Promise<PipelineCapabilities> {
  const response = await requestJson<PipelineCapabilitiesResponse>(
    "/api/pipeline",
    { signal },
  );
  return toPipelineCapabilities(response);
}
