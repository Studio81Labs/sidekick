import type { components } from "../../../shared/api/generated/openapi";
import { requestJson } from "../../../shared/api/transport";
import type { SystemInfo } from "../../../shared/types/system";

type HealthResponse = components["schemas"]["HealthResponse"];

export function toSystemInfo(response: HealthResponse): SystemInfo {
  return {
    environment: response.environment,
    parser_provider: response.parser_provider,
    recommendation_engine: response.recommendation_engine,
    recommendation_provider: response.recommendation_provider,
    status: response.status,
  };
}

export async function getSystemInfo(signal?: AbortSignal): Promise<SystemInfo> {
  const response = await requestJson<HealthResponse>("/api/health", {
    signal,
  });
  return toSystemInfo(response);
}
