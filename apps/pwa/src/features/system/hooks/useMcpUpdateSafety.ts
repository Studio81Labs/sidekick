import { useUpdateSafetyRegistration } from "../../../shared/pwa/updateSafety";

export interface McpUpdateSafetyInput {
  administratorSession: boolean;
  credentialDraft: boolean;
  operation: boolean;
  unacknowledgedCredential: boolean;
}

export function mcpUpdateSafetyReasons({
  administratorSession,
  credentialDraft,
  operation,
  unacknowledgedCredential,
}: McpUpdateSafetyInput) {
  return {
    busy: operation ? ["agent access operation"] : [],
    dirty: [
      administratorSession ? "agent access administrator session" : null,
      credentialDraft ? "agent access credential draft" : null,
      unacknowledgedCredential
        ? "unacknowledged one-time agent credential"
        : null,
    ].filter((reason): reason is string => reason !== null),
  };
}

export function useMcpUpdateSafety(
  input: McpUpdateSafetyInput,
  dirtyVersion: unknown,
) {
  useUpdateSafetyRegistration(
    "mcp-access",
    mcpUpdateSafetyReasons(input),
    dirtyVersion,
  );
}
