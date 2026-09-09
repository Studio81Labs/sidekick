import "./McpAdministrationPage.css";

import { McpAccessPanel } from "../../features/system/components/McpAccessPanel";

/**
 * Credential administration is intentionally independent of OCR test mode.
 * Its own MCP-admin token remains the only authority for this surface.
 */
export default function McpAdministrationPage() {
  return (
    <main className="mcp-administration-page">
      <section className="mcp-administration-card" aria-labelledby="mcp-title">
        <p className="mcp-administration-eyebrow">Poker Hero administrator</p>
        <h1 id="mcp-title">Agent access</h1>
        <p>
          Create, rotate, or revoke the read-only credentials used to inspect
          this deployment&apos;s environment status. This capability is separate
          from administrative OCR test mode.
        </p>
        <McpAccessPanel />
      </section>
    </main>
  );
}
