import type { components } from "@poker-hero/openapi-client";
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
  };
}

export function toPipelineCapabilities(
  response: PipelineCapabilitiesResponse,
): PipelineCapabilities {
  return {
    administrative_ocr_test: {
      enabled: response.administrative_ocr_test.enabled,
    },
    defaults: toPipelineSelection(response.defaults),
    parser_layout_compatibility: response.parser_layout_compatibility,
    parser_layout_profiles:
      response.parser_layout_profiles.map(toPipelineOption),
    parser_providers: response.parser_providers.map(toPipelineOption),
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
