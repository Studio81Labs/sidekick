export const ADMINISTRATIVE_TEST_LABEL = "Administrative OCR test";

export type AdministrativeAccessDenial = "disabled" | "unauthorized";

export function normalizeAdministratorToken(value: string): string {
  return value.trim();
}

export function administrativeAccessDenial(
  status: number,
): AdministrativeAccessDenial | null {
  if (status === 401) return "unauthorized";
  if (status === 403) return "disabled";
  return null;
}

export function administrativeAccessDenialMessage(
  denial: AdministrativeAccessDenial,
): string {
  return denial === "disabled"
    ? "Administrative OCR test mode is disabled on this deployment."
    : "The administrative OCR test token was rejected. Unlock administrator tools again with the deployment's token.";
}
