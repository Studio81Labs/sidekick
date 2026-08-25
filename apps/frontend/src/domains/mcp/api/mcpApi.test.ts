import { afterEach, describe, expect, it, vi } from "vitest";

import { jsonResponse, resetApiMocks } from "../../../test/api";
import { listMcpPrincipals } from "./mcpApi";

afterEach(resetApiMocks);

describe("MCP API adapter", () => {
  it("always sends the operator bearer to the same-origin Worker", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ principals: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await listMcpPrincipals("admin-secret");

    expect(fetchMock).toHaveBeenCalledWith("/api/mcp/principals", {
      headers: { Authorization: "Bearer admin-secret" },
      credentials: "include",
    });
  });
});
