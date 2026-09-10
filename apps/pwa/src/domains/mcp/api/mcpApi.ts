import { apiUrl, readJson } from "../../../shared/api/core";
import type {
  McpAccessConfig,
  McpIssuedPrincipal,
  McpPrincipal,
} from "../../../shared/types/mcp";

export type CreateMcpPrincipalInput = {
  name: string;
  expires_at: string | null;
};

export async function getMcpAccessConfig(): Promise<McpAccessConfig> {
  const response = await fetch(apiUrl("/api/mcp/config"), {
    credentials: "include",
  });
  return readJson<McpAccessConfig>(response);
}

function mcpAdminHeaders(adminToken: string): HeadersInit {
  return { Authorization: `Bearer ${adminToken}` };
}

export async function listMcpPrincipals(
  adminToken: string,
): Promise<McpPrincipal[]> {
  const response = await fetch("/api/mcp/principals", {
    headers: mcpAdminHeaders(adminToken),
    credentials: "include",
  });
  const payload = await readJson<{ principals: McpPrincipal[] }>(response);
  return payload.principals;
}

export async function createMcpPrincipal(
  adminToken: string,
  input: CreateMcpPrincipalInput,
): Promise<McpIssuedPrincipal> {
  const response = await fetch("/api/mcp/principals", {
    method: "POST",
    headers: {
      ...mcpAdminHeaders(adminToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(input),
    credentials: "include",
  });
  return readJson<McpIssuedPrincipal>(response);
}

export async function rotateMcpPrincipal(
  adminToken: string,
  principalId: string,
): Promise<McpIssuedPrincipal> {
  const response = await fetch(
    `/api/mcp/principals/${encodeURIComponent(principalId)}/rotate`,
    {
      method: "POST",
      headers: mcpAdminHeaders(adminToken),
      credentials: "include",
    },
  );
  return readJson<McpIssuedPrincipal>(response);
}

export async function revokeMcpPrincipal(
  adminToken: string,
  principalId: string,
): Promise<McpPrincipal> {
  const response = await fetch(
    `/api/mcp/principals/${encodeURIComponent(principalId)}`,
    {
      method: "DELETE",
      headers: mcpAdminHeaders(adminToken),
      credentials: "include",
    },
  );
  return readJson<McpPrincipal>(response);
}
