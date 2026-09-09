import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../../test/api";
import { createMcpPrincipalCommand } from "./mcpPrincipalCommands";

afterEach(resetApiMocks);

describe("MCP principal commands", () => {
  it("creates a principal through the same-origin administration endpoint", async () => {
    const principal = { id: "mcp_1", name: "Codex staging" };
    const result = { principal, token: "phmcp_once" };
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(result));
    vi.stubGlobal("fetch", fetchMock);
    const input = {
      name: "Codex staging",
      expires_at: null,
    };

    await expect(
      createMcpPrincipalCommand({
        adminToken: "admin-secret",
        input,
      }),
    ).resolves.toEqual(result);
    expect(fetchMock).toHaveBeenCalledWith("/api/mcp/principals", {
      method: "POST",
      headers: {
        Authorization: "Bearer admin-secret",
        "Content-Type": "application/json",
      },
      body: JSON.stringify(input),
      credentials: "include",
    });
  });
});
