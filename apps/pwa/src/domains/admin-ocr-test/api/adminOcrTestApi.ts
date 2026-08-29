import type { components } from "@poker-hero/openapi-client";
import { requestJson } from "../../../shared/api/transport";

type AdminOcrTestSessionResponse = components["schemas"]["AdminOcrTestSession"];

export type AdministrativeSession = { enabled: boolean; authorized: boolean };

/**
 * Asks the server whether a candidate credential is the deployment's
 * administrative OCR test token, so the PWA never unlocks on client belief.
 */
export async function verifyAdministratorToken(
  token: string,
  signal?: AbortSignal,
): Promise<AdministrativeSession> {
  const response = await requestJson<AdminOcrTestSessionResponse>(
    "/api/admin/ocr-test/session",
    {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      ...(signal ? { signal } : {}),
    },
  );
  return { authorized: response.authorized, enabled: response.enabled };
}
