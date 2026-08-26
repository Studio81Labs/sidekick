import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getMcpAccessConfig,
  listMcpPrincipals,
} from "../../../domains/mcp/api/mcpApi";
import {
  createMcpPrincipalCommand,
  revokeMcpPrincipalCommand,
  rotateMcpPrincipalCommand,
} from "../services/mcpPrincipalCommands";
import { McpAccessPanel } from "./McpAccessPanel";
import type { McpPrincipal } from "../../../shared/types/mcp";

vi.mock("../../../domains/mcp/api/mcpApi", () => ({
  getMcpAccessConfig: vi.fn(),
  listMcpPrincipals: vi.fn(),
}));

vi.mock("../services/mcpPrincipalCommands", () => ({
  createMcpPrincipalCommand: vi.fn(),
  revokeMcpPrincipalCommand: vi.fn(),
  rotateMcpPrincipalCommand: vi.fn(),
}));

const principal: McpPrincipal = {
  id: "mcp_00000000000000000000000000000001",
  name: "Codex staging",
  environment: "staging",
  token_prefix: "abcdefghijkl",
  scopes: ["read"],
  status: "active",
  created_at: "2026-08-07T10:00:00Z",
  updated_at: "2026-08-07T10:00:00Z",
  expires_at: null,
  revoked_at: null,
  last_used_at: null,
};

describe("McpAccessPanel", () => {
  beforeEach(() => {
    vi.mocked(getMcpAccessConfig).mockResolvedValue({
      enabled: true,
      environment: "staging",
      endpoint: "https://poker-staging.example/mcp",
      writes_enabled: true,
    });
    vi.mocked(listMcpPrincipals).mockResolvedValue([principal]);
    vi.mocked(createMcpPrincipalCommand).mockResolvedValue({
      principal,
      token: "phmcp_first-token",
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("blocks token-producing actions until the one-time token is dismissed", async () => {
    const user = userEvent.setup();
    const onCloseBlockedChange = vi.fn();
    render(<McpAccessPanel onCloseBlockedChange={onCloseBlockedChange} />);

    await user.type(
      await screen.findByLabelText("Agent access admin token"),
      "admin-secret",
    );
    await user.click(
      screen.getByRole("button", { name: "Unlock credential management" }),
    );
    await user.type(
      await screen.findByLabelText("Credential name"),
      "Codex staging",
    );
    await user.click(screen.getByRole("button", { name: "Create credential" }));

    await waitFor(() =>
      expect(screen.getByText("phmcp_first-token")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: "Create credential" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "Rotate" })).toBeDisabled();
    expect(onCloseBlockedChange).toHaveBeenLastCalledWith(true);
    expect(rotateMcpPrincipalCommand).not.toHaveBeenCalled();
    expect(revokeMcpPrincipalCommand).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "I stored it" }));

    expect(
      screen.getByRole("button", { name: "Create credential" }),
    ).toBeEnabled();
    expect(screen.getByRole("button", { name: "Rotate" })).toBeEnabled();
    expect(onCloseBlockedChange).toHaveBeenLastCalledWith(false);
    expect(listMcpPrincipals).toHaveBeenCalledWith("admin-secret");
    expect(createMcpPrincipalCommand).toHaveBeenCalledWith({
      adminToken: "admin-secret",
      input: {
        name: "Codex staging",
        scopes: ["read"],
        expires_at: null,
      },
    });
  });

  it("blocks dialog close for the full revocation request", async () => {
    const user = userEvent.setup();
    const onCloseBlockedChange = vi.fn();
    let resolveRevocation: ((value: McpPrincipal) => void) | undefined;
    vi.mocked(revokeMcpPrincipalCommand).mockImplementation(
      () =>
        new Promise<McpPrincipal>((resolve) => {
          resolveRevocation = resolve;
        }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<McpAccessPanel onCloseBlockedChange={onCloseBlockedChange} />);

    await user.type(
      await screen.findByLabelText("Agent access admin token"),
      "admin-secret",
    );
    await user.click(
      screen.getByRole("button", { name: "Unlock credential management" }),
    );
    await user.click(await screen.findByRole("button", { name: "Revoke" }));

    await waitFor(() =>
      expect(onCloseBlockedChange).toHaveBeenLastCalledWith(true),
    );
    expect(screen.getByRole("button", { name: "Revoke" })).toBeDisabled();

    resolveRevocation?.({
      ...principal,
      revoked_at: "2026-08-26T17:00:00Z",
      status: "revoked",
    });

    await waitFor(() =>
      expect(onCloseBlockedChange).toHaveBeenLastCalledWith(false),
    );
    expect(revokeMcpPrincipalCommand).toHaveBeenCalledWith({
      adminToken: "admin-secret",
      principalId: principal.id,
    });
  });

  it("surfaces initial credential-loading failures", async () => {
    vi.mocked(getMcpAccessConfig).mockRejectedValue(
      new Error("Could not read staging MCP configuration"),
    );

    render(<McpAccessPanel />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not read staging MCP configuration",
    );
    expect(
      screen.queryByText(
        "Hosted agent access is available in staging and production deployments.",
      ),
    ).not.toBeInTheDocument();
    expect(listMcpPrincipals).not.toHaveBeenCalled();
  });

  it("keeps credential management locked when the admin token is rejected", async () => {
    const user = userEvent.setup();
    vi.mocked(listMcpPrincipals).mockRejectedValue(
      new Error("Agent access admin token is invalid"),
    );

    render(<McpAccessPanel />);

    await user.type(
      await screen.findByLabelText("Agent access admin token"),
      "wrong-secret",
    );
    await user.click(
      screen.getByRole("button", { name: "Unlock credential management" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Agent access admin token is invalid",
    );
    expect(screen.queryByLabelText("Credential name")).not.toBeInTheDocument();
  });
});
