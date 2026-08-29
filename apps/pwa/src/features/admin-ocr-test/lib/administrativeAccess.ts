export type AdministrativeAccessDenial = "disabled" | "unauthorized";

/** Every way the server-verified unlock can end without a usable token. */
export type AdministrativeUnlockFailure =
  | AdministrativeAccessDenial
  | "blank"
  | "unavailable";

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

export function unlockFailureMessage(
  failure: AdministrativeUnlockFailure,
): string {
  if (failure === "blank") {
    return "Enter the administrative OCR test token.";
  }
  if (failure === "unavailable") {
    return "Could not verify the administrative OCR test token. Check the connection and try again.";
  }
  return administrativeAccessDenialMessage(failure);
}
