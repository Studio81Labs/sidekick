import { useEffect, useState } from "react";
import "./McpAccessPanel.css";

import {
  ButtonControl,
  FormField,
  SelectControl,
  TextInput,
} from "../../../shared/components/FormControls";
import {
  getMcpAccessConfig,
  listMcpPrincipals,
} from "../../../domains/mcp/api/mcpApi";
import {
  createMcpPrincipalCommand,
  revokeMcpPrincipalCommand,
  rotateMcpPrincipalCommand,
} from "../services/mcpPrincipalCommands";
import type {
  McpAccessConfig,
  McpIssuedPrincipal,
  McpPrincipal,
  McpScope,
} from "../../../shared/types/mcp";
import { useMcpUpdateSafety } from "../hooks/useMcpUpdateSafety";

export function McpAccessPanel({
  onPendingTokenChange,
}: {
  onPendingTokenChange?: (pending: boolean) => void;
}) {
  const [config, setConfig] = useState<McpAccessConfig | null>(null);
  const [principals, setPrincipals] = useState<McpPrincipal[]>([]);
  const [adminToken, setAdminToken] = useState("");
  const [adminUnlocked, setAdminUnlocked] = useState(false);
  const [name, setName] = useState("");
  const [access, setAccess] = useState<"read" | "write">("read");
  const [expiry, setExpiry] = useState("");
  const [issued, setIssued] = useState<McpIssuedPrincipal | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [tokenRequestPending, setTokenRequestPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tokenPending = issued !== null || tokenRequestPending;
  useMcpUpdateSafety({
    administratorSession: adminToken !== "",
    credentialDraft: name !== "" || access !== "read" || expiry !== "",
    operation: busyId !== null || tokenRequestPending,
    unacknowledgedCredential: issued !== null,
  });

  useEffect(() => {
    onPendingTokenChange?.(tokenPending);
  }, [onPendingTokenChange, tokenPending]);

  useEffect(() => {
    let active = true;
    void getMcpAccessConfig()
      .then((nextConfig) => {
        if (!active) return;
        setConfig(nextConfig);
      })
      .catch((reason: unknown) => {
        if (active) setError(messageFrom(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function unlockAdmin() {
    const normalizedToken = adminToken.trim();
    if (!normalizedToken) {
      setError("Enter the agent access admin token.");
      return;
    }
    setBusyId("unlock");
    setError(null);
    try {
      setPrincipals(await listMcpPrincipals(normalizedToken));
      setAdminToken(normalizedToken);
      setAdminUnlocked(true);
    } catch (reason) {
      setAdminUnlocked(false);
      setPrincipals([]);
      setError(messageFrom(reason));
    } finally {
      setBusyId(null);
    }
  }

  function lockAdmin() {
    if (tokenPending) return;
    setAdminToken("");
    setAdminUnlocked(false);
    setPrincipals([]);
    setError(null);
  }

  async function createPrincipal() {
    const normalizedName = name.trim();
    if (normalizedName.length < 3) {
      setError("Use a name of at least 3 characters.");
      return;
    }
    setTokenRequestPending(true);
    setBusyId("create");
    setError(null);
    try {
      const scopes: McpScope[] =
        access === "write" ? ["read", "write"] : ["read"];
      const result = await createMcpPrincipalCommand({
        adminToken,
        input: {
          name: normalizedName,
          scopes,
          expires_at: expiry ? new Date(expiry).toISOString() : null,
        },
      });
      setIssued(result);
      setPrincipals((current) => [
        result.principal,
        ...current.filter((candidate) => candidate.id !== result.principal.id),
      ]);
      setName("");
      setExpiry("");
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusyId(null);
      setTokenRequestPending(false);
    }
  }

  async function rotate(principal: McpPrincipal) {
    if (
      !window.confirm(
        `Rotate ${principal.name}? The current token will stop working immediately.`,
      )
    ) {
      return;
    }
    setTokenRequestPending(true);
    setBusyId(principal.id);
    setError(null);
    try {
      const result = await rotateMcpPrincipalCommand({
        adminToken,
        principalId: principal.id,
      });
      setIssued(result);
      replacePrincipal(result.principal);
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusyId(null);
      setTokenRequestPending(false);
    }
  }

  async function revoke(principal: McpPrincipal) {
    if (!window.confirm(`Revoke ${principal.name}? This cannot be undone.`)) {
      return;
    }
    setBusyId(principal.id);
    setError(null);
    try {
      replacePrincipal(
        await revokeMcpPrincipalCommand({
          adminToken,
          principalId: principal.id,
        }),
      );
    } catch (reason) {
      setError(messageFrom(reason));
    } finally {
      setBusyId(null);
    }
  }

  function replacePrincipal(principal: McpPrincipal) {
    setPrincipals((current) =>
      current.map((candidate) =>
        candidate.id === principal.id ? principal : candidate,
      ),
    );
  }

  if (loading) {
    return <p>Reading agent access configuration...</p>;
  }
  if (error && !config) {
    return (
      <p className="mcp-access-error" role="alert">
        {error}
      </p>
    );
  }
  if (!config || config.environment === "local") {
    return (
      <p>
        Hosted agent access is available in staging and production deployments.
      </p>
    );
  }

  return (
    <div className="mcp-access-panel">
      <p>
        <strong>{config.environment}</strong>
        {" · "}
        {config.enabled ? config.endpoint : "Endpoint disabled"}
        {" · "}
        {config.writes_enabled ? "staging writes enabled" : "read-only server"}
      </p>

      {!config.enabled ? (
        <p>
          Credential management is unavailable while the MCP endpoint is
          disabled.
        </p>
      ) : !adminUnlocked ? (
        <div className="mcp-unlock-row">
          <FormField label="Agent access admin token">
            <TextInput
              type="password"
              autoComplete="off"
              value={adminToken}
              onChange={(event) => setAdminToken(event.target.value)}
            />
          </FormField>
          <ButtonControl
            variant="secondary"
            disabled={busyId !== null}
            onClick={() => void unlockAdmin()}
          >
            {busyId === "unlock"
              ? "Unlocking..."
              : "Unlock credential management"}
          </ButtonControl>
        </div>
      ) : (
        <div className="mcp-session-row">
          <span>Credential management unlocked for this browser session.</span>
          <ButtonControl
            variant="secondary"
            disabled={busyId !== null || tokenPending}
            onClick={lockAdmin}
          >
            Lock
          </ButtonControl>
        </div>
      )}

      {error ? (
        <p className="mcp-access-error" role="alert">
          {error}
        </p>
      ) : null}

      {!adminUnlocked ? null : (
        <>
          {issued ? (
            <div className="mcp-issued-token" role="status">
              <strong>Copy this token now</strong>
              <p>It is shown once and cannot be retrieved later.</p>
              <code>{issued.token}</code>
              <div className="mcp-inline-actions">
                <ButtonControl
                  variant="secondary"
                  onClick={() =>
                    void navigator.clipboard.writeText(issued.token)
                  }
                >
                  Copy token
                </ButtonControl>
                <ButtonControl
                  variant="secondary"
                  onClick={() => setIssued(null)}
                >
                  I stored it
                </ButtonControl>
              </div>
            </div>
          ) : null}

          <div className="mcp-create-grid">
            <FormField label="Credential name">
              <TextInput
                value={name}
                maxLength={100}
                onChange={(event) => setName(event.target.value)}
                placeholder="Developer or agent purpose"
              />
            </FormField>
            <FormField label="Access">
              <SelectControl
                value={access}
                onChange={(event) =>
                  setAccess(event.target.value as "read" | "write")
                }
              >
                <option value="read">Read only</option>
                <option value="write" disabled={!config.writes_enabled}>
                  Read and write
                </option>
              </SelectControl>
            </FormField>
            <FormField label="Expires (optional)">
              <TextInput
                type="datetime-local"
                value={expiry}
                onChange={(event) => setExpiry(event.target.value)}
              />
            </FormField>
            <ButtonControl
              variant="secondary"
              disabled={busyId !== null || tokenPending}
              onClick={() => void createPrincipal()}
            >
              {busyId === "create" ? "Creating..." : "Create credential"}
            </ButtonControl>
          </div>

          <div className="mcp-principal-list">
            {principals.length === 0 ? (
              <p>No credentials have been created for this environment.</p>
            ) : (
              principals.map((principal) => (
                <div className="mcp-principal-row" key={principal.id}>
                  <div>
                    <strong>{principal.name}</strong>
                    <small>
                      {principal.status} · {principal.scopes.join(" + ")} ·
                      phmcp_
                      {principal.token_prefix}…
                      {principal.last_used_at
                        ? ` · used ${formatDate(principal.last_used_at)}`
                        : " · unused"}
                    </small>
                  </div>
                  {principal.status === "active" ? (
                    <div className="mcp-inline-actions">
                      <ButtonControl
                        variant="secondary"
                        disabled={busyId !== null || tokenPending}
                        onClick={() => void rotate(principal)}
                      >
                        Rotate
                      </ButtonControl>
                      <ButtonControl
                        variant="secondary"
                        disabled={busyId !== null}
                        onClick={() => void revoke(principal)}
                      >
                        Revoke
                      </ButtonControl>
                    </div>
                  ) : null}
                </div>
              ))
            )}
          </div>
        </>
      )}
    </div>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
    new Date(value),
  );
}

function messageFrom(reason: unknown): string {
  return reason instanceof Error
    ? reason.message
    : "Could not update agent access.";
}
