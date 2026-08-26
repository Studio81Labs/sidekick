import { Download, Upload } from "lucide-react";
import { useRef } from "react";

import "./InfoDialog.css";
import { DialogFooter } from "../../../shared/components/DialogFooter";
import { DialogFrame } from "../../../shared/components/DialogFrame";
import { DialogHeader } from "../../../shared/components/DialogHeader";
import {
  ButtonControl,
  DownloadLinkControl,
  FileInputControl,
} from "../../../shared/components/FormControls";
import { McpAccessPanel } from "./McpAccessPanel";

export interface InfoProviderSummary {
  recognition: string;
  recognitionFallbackFrom: string | null;
  recognitionRoute: string | null;
  recommendation: string;
}

export interface InfoDialogProps {
  backupDownloadUrl: string;
  backupRestoring: boolean;
  busy: boolean;
  mcpTokenPending: boolean;
  onClose: () => void;
  onMcpTokenPendingChange: (pending: boolean) => void;
  onRestoreBackup: (file: File) => void;
  providers: InfoProviderSummary | null;
  systemInfoLoading: boolean;
}

export function InfoDialog({
  backupDownloadUrl,
  backupRestoring,
  busy,
  mcpTokenPending,
  onClose,
  onMcpTokenPendingChange,
  onRestoreBackup,
  providers,
  systemInfoLoading,
}: InfoDialogProps) {
  const backupInputRef = useRef<HTMLInputElement | null>(null);
  const closeDisabled = backupRestoring || mcpTokenPending;
  const backupControlsDisabled = busy || backupRestoring;

  return (
    <DialogFrame className="info-dialog" titleId="info-dialog-title">
      <DialogHeader
        titleId="info-dialog-title"
        title="About Poker Training Analyzer"
        subtitle="Post-hand Texas Hold'em review and training"
        closeLabel="Close app information"
        closeDisabled={closeDisabled}
        onClose={onClose}
      />

      <div className="info-dialog-body">
        <section className="info-dialog-section active-engines">
          <h3>Currently active</h3>
          {providers ? (
            <div className="info-provider-grid">
              <div>
                <small>Recognition</small>
                <strong>{providers.recognition}</strong>
                {providers.recognitionRoute ? (
                  <span className="info-provider-route">
                    via {providers.recognitionRoute}
                    {providers.recognitionFallbackFrom
                      ? ` · fallback from ${providers.recognitionFallbackFrom}`
                      : ""}
                  </span>
                ) : null}
              </div>
              <div>
                <small>Recommendation</small>
                <strong>{providers.recommendation}</strong>
              </div>
            </div>
          ) : (
            <p>
              {systemInfoLoading
                ? "Reading backend configuration..."
                : "Active engine details are unavailable."}
            </p>
          )}
        </section>
        <section className="info-dialog-section">
          <h3>Recognition</h3>
          <p>
            OCR and computer vision read the cards, board, pot, bets, stacks,
            and table state from each screenshot. Confidence scores identify
            fields that need review.
          </p>
        </section>
        <section className="info-dialog-section">
          <h3>Recommendations</h3>
          <p>
            The configured engine analyzes approved hand state and compares
            available actions. Preflop uses a position-aware training chart, the
            postflop engine solves supported heads-up game trees, and ambiguous
            spots use the range/EV fallback.
          </p>
        </section>
        <section className="info-dialog-section">
          <h3>Training scope</h3>
          <p>
            Designed for post-hand study. It does not place bets or interact
            directly with a poker client.
          </p>
        </section>
        <section className="info-dialog-section">
          <h3>Agent access</h3>
          <p>
            Create environment-bound bearer credentials for trusted developer
            agents. Store each token when it is shown; only its hash remains on
            the server.
          </p>
          <McpAccessPanel onPendingTokenChange={onMcpTokenPendingChange} />
        </section>
        <section className="info-dialog-section data-recovery-section">
          <h3>Data and recovery</h3>
          <p>
            Back up screenshots, reviewed hands, lesson notes, training
            decisions, recommendations, and benchmark reports in one portable
            ZIP.
          </p>
          <div className="data-recovery-actions">
            <DownloadLinkControl
              className="secondary-button"
              href={backupDownloadUrl}
              download
              aria-label="Download application backup"
              disabled={busy}
            >
              <Download size={14} aria-hidden="true" />
              Download backup
            </DownloadLinkControl>
            <ButtonControl
              variant="secondary"
              onClick={() => backupInputRef.current?.click()}
              disabled={backupControlsDisabled}
              aria-label="Restore application backup"
            >
              <Upload size={14} aria-hidden="true" />
              {backupRestoring ? "Restoring..." : "Restore backup"}
            </ButtonControl>
            <FileInputControl
              ref={backupInputRef}
              accept=".zip,application/zip"
              aria-label="Application backup ZIP"
              disabled={backupControlsDisabled}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0] ?? null;
                event.currentTarget.value = "";
                if (file) {
                  onRestoreBackup(file);
                }
              }}
            />
          </div>
        </section>
      </div>

      <DialogFooter className="info-dialog-footer">
        <ButtonControl
          variant="secondary"
          onClick={onClose}
          disabled={closeDisabled}
        >
          Done
        </ButtonControl>
      </DialogFooter>
    </DialogFrame>
  );
}
