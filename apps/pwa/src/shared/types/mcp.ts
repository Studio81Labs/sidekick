export type McpScope = "read" | "write";

export interface McpAccessConfig {
  enabled: boolean;
  environment: "local" | "staging" | "production";
  endpoint: string | null;
  writes_enabled: boolean;
}

export interface McpPrincipal {
  id: string;
  name: string;
  environment: "staging" | "production";
  token_prefix: string;
  scopes: McpScope[];
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
