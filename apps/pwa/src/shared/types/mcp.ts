export interface McpAccessConfig {
  enabled: boolean;
  environment: "local" | "staging" | "production";
  endpoint: string | null;
}

export interface McpPrincipal {
  id: string;
  name: string;
  environment: "staging" | "production";
  token_prefix: string;
  status: "active" | "expired" | "revoked";
  created_at: string;
  updated_at: string;
  expires_at: string | null;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface McpIssuedPrincipal {
  principal: McpPrincipal;
  token: string;
}
